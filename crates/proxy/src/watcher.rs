//! Background task that watches a policy file and hot-reloads on change.
//!
//! The policy controller writes new versions via atomic `rename(2)` (see
//! `services/policy-controller/cascadia_policy/writer.py`). Filesystem-event
//! APIs handle that rename inconsistently across platforms: watching the
//! destination file directly binds to a vanished inode on most kernels, and
//! watching the parent directory works on inotify but not reliably on macOS
//! kqueue. Rather than litigate the platform-specific failure modes of every
//! API, we poll the file's modification time once a second. It's a fraction
//! of a syscall per second, robust through any number of atomic-replace
//! cycles, and trivially testable.
//!
//! Phase 5 acceptance criterion: "auto-tunes from cold start without manual
//! intervention." The policy-controller Python service is the one doing the
//! tuning; this module is the receiver that makes the proxy honor the new
//! policy without a restart.

use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use arc_swap::ArcSwap;
use sqlx::postgres::PgPool;
use tokio::time::{interval, MissedTickBehavior};

use crate::policy::PolicyTable;

const POLL_INTERVAL: Duration = Duration::from_secs(1);
const PG_POLL_INTERVAL_DEFAULT_SECS: u64 = 5;

/// Spawn the hot-reload watcher. Loads the file once synchronously (so a
/// malformed startup policy fails the boot), then polls for mtime changes
/// from a background task.
pub fn spawn(
    path: PathBuf,
    current: Arc<ArcSwap<PolicyTable>>,
    known_providers: Arc<HashSet<String>>,
) -> anyhow::Result<()> {
    let initial = PolicyTable::from_json_file(&path)?;
    initial
        .validate_providers(&known_providers)
        .with_context(|| format!("policy file {}", path.display()))?;
    current.store(Arc::new(initial));

    let last_mtime = std::fs::metadata(&path)
        .ok()
        .and_then(|m| m.modified().ok());

    tokio::spawn(poll_loop(path, current, last_mtime, known_providers));
    Ok(())
}

async fn poll_loop(
    path: PathBuf,
    current: Arc<ArcSwap<PolicyTable>>,
    mut last_mtime: Option<std::time::SystemTime>,
    known_providers: Arc<HashSet<String>>,
) {
    let mut ticker = interval(POLL_INTERVAL);
    // Don't burst-reload if the proxy was paused (laptop sleep, CI freeze).
    ticker.set_missed_tick_behavior(MissedTickBehavior::Skip);
    loop {
        ticker.tick().await;
        let next_mtime = match std::fs::metadata(&path).and_then(|m| m.modified()) {
            Ok(t) => Some(t),
            Err(err) => {
                // File transiently missing during atomic rename is expected;
                // we'll pick it up on the next tick.
                tracing::debug!(?err, "policy file metadata read failed");
                continue;
            }
        };

        if next_mtime == last_mtime {
            continue;
        }
        last_mtime = next_mtime;

        match PolicyTable::from_json_file(&path) {
            Ok(new) => match new.validate_providers(&known_providers) {
                Ok(()) => {
                    let version = new.version.clone();
                    current.store(Arc::new(new));
                    tracing::info!(?version, "policy hot-reloaded");
                }
                Err(err) => {
                    tracing::warn!(
                        ?err,
                        "policy hot-reload rejected (unknown provider); keeping previous policy"
                    );
                }
            },
            Err(err) => {
                tracing::warn!(?err, "policy hot-reload failed; keeping previous policy");
            }
        }
    }
}

/// Spawn the Postgres-backed policy source (`CASCADIA_POLICY_SOURCE=postgres`).
///
/// Used where a shared filesystem volume can't be mounted into both the proxy
/// and the policy-controller (e.g. Railway, whose volumes are single-service).
/// The controller appends rows to `policy_store`; we poll the latest and
/// hot-swap via the same `ArcSwap` the file watcher uses.
///
/// On boot: load the latest row as the initial policy. If the table is empty,
/// *seed* it from the current in-memory policy (the `CASCADIA_POLICY_JSON` /
/// env-derived table) so a deploy migrating off inline JSON comes up cleanly —
/// that seed becomes row 1 and the controller refits from there.
///
/// Hot-path safety: routing reads policy lock-free from `ArcSwap`; this poll
/// runs in a background task. A DB outage just means we keep serving the last
/// good policy (mirrors the file watcher's keep-previous-on-error behavior),
/// honoring the "hot path must not block on Postgres" invariant.
pub async fn spawn_pg(
    pool: PgPool,
    current: Arc<ArcSwap<PolicyTable>>,
    known_providers: Arc<HashSet<String>>,
) -> anyhow::Result<()> {
    let last_id = match fetch_latest(&pool).await? {
        Some((id, body)) => {
            let table = PolicyTable::from_json_str(&body)
                .map_err(|e| anyhow::anyhow!("policy_store row {id}: {e}"))?;
            table
                .validate_providers(&known_providers)
                .map_err(|e| anyhow::anyhow!("policy_store row {id}: {e}"))?;
            let version = table.version.clone();
            current.store(Arc::new(table));
            tracing::info!(row_id = id, ?version, "loaded policy from postgres");
            id
        }
        None => {
            let seed = current.load();
            let body = serde_json::to_string(&**seed).context("serializing seed policy")?;
            let version = seed.version.clone().unwrap_or_else(|| "seed".to_string());
            let id = insert_policy(&pool, &version, &body).await?;
            tracing::info!(row_id = id, %version, "seeded policy_store from env policy");
            id
        }
    };

    let interval_secs = std::env::var("CASCADIA_POLICY_POLL_SECS")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .filter(|&s| s > 0)
        .unwrap_or(PG_POLL_INTERVAL_DEFAULT_SECS);

    tokio::spawn(pg_poll_loop(
        pool,
        current,
        last_id,
        Duration::from_secs(interval_secs),
        known_providers,
    ));
    Ok(())
}

/// Latest `(id, body-as-text)` from `policy_store`, or `None` if empty.
async fn fetch_latest(pool: &PgPool) -> anyhow::Result<Option<(i64, String)>> {
    sqlx::query_as::<_, (i64, String)>(
        "SELECT id, body::text FROM policy_store ORDER BY id DESC LIMIT 1",
    )
    .fetch_optional(pool)
    .await
    .context("querying policy_store")
}

/// Insert a policy row (seed path), returning its id.
async fn insert_policy(pool: &PgPool, version: &str, body: &str) -> anyhow::Result<i64> {
    sqlx::query_scalar::<_, i64>(
        "INSERT INTO policy_store (version, body) VALUES ($1, $2::jsonb) RETURNING id",
    )
    .bind(version)
    .bind(body)
    .fetch_one(pool)
    .await
    .context("seeding policy_store")
}

async fn pg_poll_loop(
    pool: PgPool,
    current: Arc<ArcSwap<PolicyTable>>,
    mut last_id: i64,
    poll: Duration,
    known_providers: Arc<HashSet<String>>,
) {
    let mut ticker = interval(poll);
    ticker.set_missed_tick_behavior(MissedTickBehavior::Skip);
    loop {
        ticker.tick().await;
        match fetch_latest(&pool).await {
            Ok(Some((id, body))) if id != last_id => match PolicyTable::from_json_str(&body)
                .and_then(|new| new.validate_providers(&known_providers).map(|()| new))
            {
                Ok(new) => {
                    let version = new.version.clone();
                    current.store(Arc::new(new));
                    last_id = id;
                    tracing::info!(row_id = id, ?version, "policy hot-reloaded from postgres");
                }
                Err(err) => {
                    // Advance past the bad row so we don't re-log it every tick;
                    // keep serving the previous good policy.
                    last_id = id;
                    tracing::warn!(
                        ?err,
                        row_id = id,
                        "postgres policy rejected (parse or unknown provider); keeping previous policy"
                    );
                }
            },
            Ok(_) => {} // no newer row
            Err(err) => {
                tracing::warn!(?err, "policy_store poll failed; keeping previous policy");
            }
        }
    }
}
