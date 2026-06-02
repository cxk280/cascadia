//! Event log: persist one row per request (and one per shadow pair) to Postgres.
//!
//! Writes happen on a background task fed by a bounded `tokio::mpsc` channel
//! so the hot path never blocks on the database. If the channel is full
//! (database is slow or down), `try_send` drops the entry and emits a warn
//! log — better to lose an event than to slow the proxy.
//!
//! Two kinds of log entries share one channel:
//! - `Event`: one per request (events table).
//! - `ShadowPair`: one per counterfactual pair (shadow_pairs table).
//!
//! Single-channel/single-writer keeps the database connection footprint small
//! and the order observed (events before their shadow_pairs, since the chat
//! handler always emits the event row before the cascade emits its pair).

use std::time::Duration;

use chrono::{DateTime, Utc};
use serde_json::Value;
use sqlx::postgres::{PgPool, PgPoolOptions};
use tokio::sync::mpsc;
use uuid::Uuid;

/// One row in the `events` table.
#[derive(Debug, Clone)]
pub struct Event {
    pub request_id: Uuid,
    pub occurred_at: DateTime<Utc>,
    pub route: &'static str,
    pub provider: &'static str,
    pub model: String,
    pub upstream_status: Option<i16>,
    pub elapsed_ms: i32,
    pub prompt_tokens: Option<i32>,
    pub completion_tokens: Option<i32>,
    pub request_body: Option<Value>,
    pub response_body: Option<Value>,
    pub error_code: Option<&'static str>,
    /// Phase 2: cluster the classifier assigned this request to.
    pub cluster_id: Option<String>,
    /// Phase 2: true iff the cheap tier was rejected and we escalated.
    pub escalated: Option<bool>,
    /// Phase 7.1: true iff the inbound request carried non-empty `tools=[]`,
    /// which causes the cascade to bypass escalation (cheap-tier only,
    /// no shadow pair logged). Lets the dashboard distinguish "0% escalation
    /// because tool-use traffic" from "0% escalation because misconfigured."
    pub tools_present: Option<bool>,
}

/// One row in the `shadow_pairs` table. The judge worker reads these and
/// writes one or more `judge_scores` rows per pair.
#[derive(Debug, Clone)]
pub struct ShadowPair {
    pub pair_id: Uuid,
    pub request_id: Uuid,
    pub occurred_at: DateTime<Utc>,
    pub cluster_id: String,
    pub prompt: String,
    pub cheap_model: String,
    pub cheap_response: String,
    pub expensive_model: String,
    pub expensive_response: String,
}

/// Internal channel variants. Both go through the same writer task.
#[derive(Debug)]
enum LogEntry {
    Event(Box<Event>),
    Shadow(Box<ShadowPair>),
}

/// Cheaply-clonable handle that handlers use to enqueue log entries.
#[derive(Clone)]
pub struct EventSender {
    tx: mpsc::Sender<LogEntry>,
}

impl EventSender {
    /// Try to enqueue an event. Drops the event (with a warn log) if the
    /// channel is full — the hot path must never block on event persistence.
    pub fn try_send(&self, event: Event) {
        self.send(LogEntry::Event(Box::new(event)), "event");
    }

    /// Try to enqueue a shadow pair. Same fail-open semantics as `try_send`.
    pub fn send_shadow_pair(&self, pair: ShadowPair) {
        self.send(LogEntry::Shadow(Box::new(pair)), "shadow_pair");
    }

    fn send(&self, entry: LogEntry, label: &'static str) {
        if let Err(err) = self.tx.try_send(entry) {
            tracing::warn!(?err, kind = label, "event channel full; entry dropped");
        }
    }
}

/// Connect to Postgres, run migrations, and spawn the writer task.
/// Returns an `EventSender` for handlers and the pool for future readers
/// (admin endpoints, future API).
pub async fn init(database_url: &str) -> anyhow::Result<(EventSender, PgPool)> {
    let pool = PgPoolOptions::new()
        .max_connections(8)
        .acquire_timeout(Duration::from_secs(5))
        .connect(database_url)
        .await?;

    sqlx::migrate!("./migrations")
        .run(&pool)
        .await
        .map_err(|e| {
            // Common operational failure: someone dropped `_sqlx_migrations`
            // to "reset state" but left the data tables. Sqlx then re-runs
            // every migration and fails on the first CREATE TABLE because the
            // table already exists. The raw error is "relation X already
            // exists" which doesn't hint at the fix. Detect the pattern and
            // emit a recovery hint.
            let raw = e.to_string();
            if raw.contains("already exists") || raw.contains("relation") {
                anyhow::anyhow!(
                    "migration drift detected: {raw}.\n\
                 Likely cause: the `_sqlx_migrations` tracking table was \
                 dropped but data tables remain. Recovery options:\n\
                 1. Wipe the DB entirely and let sqlx re-run all migrations.\n\
                 2. Manually re-populate `_sqlx_migrations` with the \
                    versions you've already applied (see crates/proxy/migrations/)."
                )
            } else {
                anyhow::Error::from(e).context("running sqlx migrations")
            }
        })?;
    // Log the highest applied migration version. This makes a stale/cached
    // deploy *loud*: if a build didn't actually rebuild after a migration was
    // added (e.g. a platform served a cached image), this number lags the
    // migrations/ dir and the mismatch is obvious in the boot logs instead of
    // silently missing a table. See PLAN.md §9 (2026-06-01, postgres policy).
    let latest_applied: Option<i64> =
        sqlx::query_scalar("SELECT MAX(version) FROM _sqlx_migrations")
            .fetch_one(&pool)
            .await
            .unwrap_or(None);
    tracing::info!(latest_applied_migration = ?latest_applied, "postgres migrations applied");

    let (tx, rx) = mpsc::channel::<LogEntry>(2048);
    let writer_pool = pool.clone();
    tokio::spawn(writer_task(rx, writer_pool));

    Ok((EventSender { tx }, pool))
}

/// Background task: drain entries from the channel and INSERT them. Errors
/// are logged but never propagated — the proxy keeps serving.
async fn writer_task(mut rx: mpsc::Receiver<LogEntry>, pool: PgPool) {
    while let Some(entry) = rx.recv().await {
        let result = match &entry {
            LogEntry::Event(e) => insert_event(&pool, e).await,
            LogEntry::Shadow(p) => insert_shadow_pair(&pool, p).await,
        };
        if let Err(err) = result {
            tracing::warn!(?err, ?entry, "failed to persist log entry");
        }
    }
    tracing::info!("event writer task exited (channel closed)");
}

async fn insert_event(pool: &PgPool, e: &Event) -> Result<(), sqlx::Error> {
    sqlx::query(
        r#"
        INSERT INTO events (
            request_id, occurred_at, route, provider, model,
            upstream_status, elapsed_ms, prompt_tokens, completion_tokens,
            request_body, response_body, error_code, cluster_id, escalated,
            tools_present
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
        ON CONFLICT (request_id) DO NOTHING
        "#,
    )
    .bind(e.request_id)
    .bind(e.occurred_at)
    .bind(e.route)
    .bind(e.provider)
    .bind(&e.model)
    .bind(e.upstream_status)
    .bind(e.elapsed_ms)
    .bind(e.prompt_tokens)
    .bind(e.completion_tokens)
    .bind(e.request_body.as_ref())
    .bind(e.response_body.as_ref())
    .bind(e.error_code)
    .bind(e.cluster_id.as_ref())
    .bind(e.escalated)
    .bind(e.tools_present)
    .execute(pool)
    .await?;
    Ok(())
}

async fn insert_shadow_pair(pool: &PgPool, p: &ShadowPair) -> Result<(), sqlx::Error> {
    sqlx::query(
        r#"
        INSERT INTO shadow_pairs (
            pair_id, request_id, occurred_at, cluster_id, prompt,
            cheap_model, cheap_response, expensive_model, expensive_response
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (pair_id) DO NOTHING
        "#,
    )
    .bind(p.pair_id)
    .bind(p.request_id)
    .bind(p.occurred_at)
    .bind(&p.cluster_id)
    .bind(&p.prompt)
    .bind(&p.cheap_model)
    .bind(&p.cheap_response)
    .bind(&p.expensive_model)
    .bind(&p.expensive_response)
    .execute(pool)
    .await?;
    Ok(())
}
