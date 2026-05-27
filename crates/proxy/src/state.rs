//! Shared application state.

use std::sync::atomic::{AtomicBool, AtomicI64, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::Context;
use arc_swap::ArcSwap;
use reqwest::Client;
use sqlx::PgPool;

use crate::config::Config;
use crate::events::EventSender;
use crate::metrics::Metrics;
use crate::policy::PolicyTable;

/// State shared across all request handlers. Cheaply clonable.
#[derive(Clone)]
pub struct AppState {
    inner: Arc<Inner>,
}

struct Inner {
    config: Config,
    http: Client,
    metrics: Metrics,
    events: Option<EventSender>,
    db_pool: Option<PgPool>,
    policy: Arc<ArcSwap<PolicyTable>>,
    shutting_down: AtomicBool,
    /// Unix-seconds timestamp when shutdown began. `i64::MIN` = not started.
    shutdown_started_at: AtomicI64,
    /// Configured drain timeout (CASCADIA_SHUTDOWN_TIMEOUT_SECS); used by
    /// /readyz to report drain-remaining for the dashboard to display.
    shutdown_timeout_secs: u64,
}

impl AppState {
    pub fn new(
        config: Config,
        events: Option<EventSender>,
        db_pool: Option<PgPool>,
        policy: Arc<ArcSwap<PolicyTable>>,
        shutdown_timeout_secs: u64,
    ) -> anyhow::Result<Self> {
        let http = Client::builder()
            .user_agent(concat!("cascadia-proxy/", env!("CARGO_PKG_VERSION")))
            .timeout(Duration::from_secs(120))
            .build()
            .context("building reqwest client")?;
        let metrics = Metrics::new()?;
        Ok(Self {
            inner: Arc::new(Inner {
                config,
                http,
                metrics,
                events,
                db_pool,
                policy,
                shutting_down: AtomicBool::new(false),
                shutdown_started_at: AtomicI64::new(i64::MIN),
                shutdown_timeout_secs,
            }),
        })
    }

    /// Mark the proxy as draining. Called by the SIGINT/SIGTERM handler.
    /// `/readyz` returns 503 with `failed_checks: ["shutting_down"]` once
    /// this flag is set — Kubernetes will pull the instance out of the
    /// load balancer's rotation immediately rather than waiting for the
    /// drain window to expire.
    pub fn begin_shutdown(&self) {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs() as i64)
            .unwrap_or(0);
        self.inner.shutdown_started_at.store(now, Ordering::Release);
        self.inner.shutting_down.store(true, Ordering::Release);
    }

    pub fn is_shutting_down(&self) -> bool {
        self.inner.shutting_down.load(Ordering::Acquire)
    }

    pub fn shutdown_timeout_secs(&self) -> u64 {
        self.inner.shutdown_timeout_secs
    }

    /// Seconds remaining in the drain window. `None` if not shutting down or
    /// the window has already expired. Used by /readyz to feed a countdown
    /// into the dashboard banner.
    pub fn shutdown_remaining_secs(&self) -> Option<u64> {
        if !self.is_shutting_down() {
            return None;
        }
        let started = self.inner.shutdown_started_at.load(Ordering::Acquire);
        if started == i64::MIN {
            return Some(self.inner.shutdown_timeout_secs);
        }
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs() as i64)
            .unwrap_or(0);
        let elapsed = (now - started).max(0) as u64;
        self.inner.shutdown_timeout_secs.checked_sub(elapsed)
    }

    pub fn config(&self) -> &Config {
        &self.inner.config
    }

    pub fn http(&self) -> &Client {
        &self.inner.http
    }

    pub fn metrics(&self) -> &Metrics {
        &self.inner.metrics
    }

    pub fn events(&self) -> Option<&EventSender> {
        self.inner.events.as_ref()
    }

    /// Postgres pool for readiness probes and future read-side handlers.
    /// `None` when `CASCADIA_DATABASE_URL` was unset (event log is tracing-only).
    pub fn db_pool(&self) -> Option<&PgPool> {
        self.inner.db_pool.as_ref()
    }

    /// Snapshot the current policy. Returns an `Arc<PolicyTable>` so callers
    /// don't have to hold the swap across awaits.
    pub fn policy(&self) -> Arc<PolicyTable> {
        self.inner.policy.load_full()
    }
}
