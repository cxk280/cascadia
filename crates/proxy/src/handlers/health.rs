//! Health endpoints.
//!
//! - `GET /livez` — process liveness. Always 200 as long as the handler runs.
//!   Cheap. Use for Kubernetes `livenessProbe`.
//! - `GET /readyz` — readiness. 200 iff (a) at least one upstream provider is
//!   configured AND (b) Postgres is reachable (when configured) AND (c) the
//!   policy table has at least the default cluster. 503 otherwise with a JSON
//!   body naming the failed check. Use for `readinessProbe`.
//! - `GET /health` — backwards-compatible alias for `/readyz`. Pre-Phase-7
//!   deployments used this; existing probes still work.

use std::time::Duration;

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::Json;
use serde::Serialize;

use crate::state::AppState;

#[derive(Serialize)]
pub struct HealthResponse {
    pub status: &'static str,
    pub service: &'static str,
    pub version: &'static str,
    /// Names of every readiness check that passed in this evaluation. Empty
    /// on `/livez` (no checks run). On `/readyz`, this lets a probe verify
    /// what was actually validated — e.g. an operator can tell at a glance
    /// that the proxy ran the Postgres probe vs. skipped it (no DB configured).
    /// Always emitted (possibly empty `[]`) so consumers can rely on the field.
    pub passed_checks: Vec<&'static str>,
    /// Names of readiness checks that failed. Always emitted (possibly empty
    /// `[]`) so consumers can rely on the field.
    pub failed_checks: Vec<&'static str>,
    /// Seconds remaining in the graceful-shutdown drain window. Only set
    /// when `status == "shutting_down"`. The dashboard surfaces this as a
    /// countdown in its amber banner so an operator can see when the drain
    /// will complete without reading proxy logs.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub shutdown_remaining_secs: Option<u64>,
    /// The configured drain timeout (`CASCADIA_SHUTDOWN_TIMEOUT_SECS`). The
    /// dashboard pairs this with `shutdown_remaining_secs` so the operator
    /// sees "10s timeout, 3s left" rather than just "3s left" — context
    /// for whether the drain is mid-window or nearly done.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub shutdown_timeout_secs: Option<u64>,
}

/// Process liveness — minimal-cost handler that just confirms the proxy
/// hasn't deadlocked. Does NOT check Postgres or upstreams. K8s liveness
/// probes only need to know whether to restart the container.
pub async fn livez() -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok",
        service: "cascadia-proxy",
        version: env!("CARGO_PKG_VERSION"),
        passed_checks: Vec::new(),
        failed_checks: Vec::new(),
        shutdown_remaining_secs: None,
        shutdown_timeout_secs: None,
    })
}

/// Readiness — true iff this instance can serve traffic right now. K8s
/// readiness probes use this to gate traffic during startup and drain on
/// downstream-dependency failures. The response body lists every check
/// run, on both pass and fail paths, so operators can verify *what was
/// actually validated*.
pub async fn readyz(State(state): State<AppState>) -> impl IntoResponse {
    let mut passed: Vec<&'static str> = Vec::new();
    let mut failed: Vec<&'static str> = Vec::new();

    // 0. Shutdown short-circuit. As soon as SIGTERM/SIGINT fires, /readyz
    //    returns 503. K8s pulls us out of LB rotation immediately rather
    //    than waiting the full drain window (graceful shutdown still drains
    //    in-flight requests; this just stops new ones).
    if state.is_shutting_down() {
        failed.push("shutting_down");
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(HealthResponse {
                status: "shutting_down",
                service: "cascadia-proxy",
                version: env!("CARGO_PKG_VERSION"),
                passed_checks: Vec::new(),
                failed_checks: failed,
                shutdown_remaining_secs: state.shutdown_remaining_secs(),
                shutdown_timeout_secs: Some(state.shutdown_timeout_secs()),
            }),
        );
    }

    // 1. At least one provider must be credentialed.
    let config = state.config();
    let any_provider = config.openai_api_key.is_some()
        || config.anthropic_api_key.is_some()
        || config.groq_api_key.is_some()
        || config.xai_api_key.is_some();
    if any_provider {
        passed.push("upstream_provider_configured");
    } else {
        failed.push("no_upstream_provider_configured");
    }

    // 2. Default cluster must exist in the policy table.
    let policy = state.policy();
    if policy.clusters.contains_key(&policy.default_cluster) {
        passed.push("policy_default_cluster_present");
    } else {
        failed.push("policy_default_cluster_missing");
    }

    // 3. Postgres (when configured) must be reachable. 500ms hard timeout so
    //    a slow DB doesn't turn readiness probes into a slow leak.
    if let Some(pool) = state.db_pool() {
        let probe = tokio::time::timeout(
            Duration::from_millis(500),
            sqlx::query_scalar::<_, i32>("SELECT 1").fetch_one(pool),
        )
        .await;
        match probe {
            Ok(Ok(_)) => passed.push("postgres_reachable"),
            _ => failed.push("postgres_unreachable"),
        }
    } else {
        passed.push("postgres_not_configured");
    }

    let status = if failed.is_empty() {
        StatusCode::OK
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    };
    (
        status,
        Json(HealthResponse {
            status: if failed.is_empty() {
                "ok"
            } else {
                "unavailable"
            },
            service: "cascadia-proxy",
            version: env!("CARGO_PKG_VERSION"),
            passed_checks: passed,
            failed_checks: failed,
            shutdown_remaining_secs: None,
            shutdown_timeout_secs: None,
        }),
    )
}

/// Backwards-compatible alias for `readyz`. Pre-Phase-7 docs and probes
/// referenced `/health`; keeping it pointed at readyz preserves the contract
/// while giving operators the more precise livez/readyz split.
pub async fn health(state: State<AppState>) -> impl IntoResponse {
    readyz(state).await
}
