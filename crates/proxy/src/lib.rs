//! Cascadia proxy library root.
//!
//! Public entry point is [`run`], which loads configuration, sets up tracing
//! and metrics, builds the HTTP router, and serves it until shutdown.

pub mod cascade;
pub mod cluster;
pub mod confidence;
pub mod config;
pub mod error;
pub mod events;
pub mod handlers;
pub mod metrics;
pub mod model_id;
pub mod openai;
pub mod policy;
pub mod state;
pub mod telemetry;
pub mod upstream;
pub mod watcher;

use std::env;
use std::net::SocketAddr;
use std::time::Duration;

use anyhow::Context;
use axum::Router;
use tokio::net::TcpListener;
use tokio::signal::unix::{signal, SignalKind};

use crate::config::Config;
use crate::policy::PolicyTable;
use crate::state::AppState;

/// Entry point used by the binary. Loads config, initializes telemetry, and
/// runs the server until shutdown.
pub async fn run() -> anyhow::Result<()> {
    let config = Config::from_env().context("loading configuration")?;
    telemetry::init(&config).context("initializing telemetry")?;

    log_recognized_env_vars();

    let addr: SocketAddr = config.listen_addr.parse().context("parsing listen addr")?;

    let (events, db_pool) = match &config.database_url {
        Some(url) => {
            let (sender, pool) = events::init(url).await.context("initializing event log")?;
            (Some(sender), Some(pool))
        }
        None => {
            tracing::warn!(
                "CASCADIA_DATABASE_URL unset; events will be logged via tracing but not persisted"
            );
            (None, None)
        }
    };

    let policy = PolicyTable::from_env().context("loading policy table")?;
    let policy_swap = std::sync::Arc::new(arc_swap::ArcSwap::from_pointee(policy));
    // Policy source: `postgres` polls the shared `policy_store` table (the
    // controller writes it) — for deploys without a cross-service volume.
    // Otherwise fall back to the file watcher when CASCADIA_POLICY_FILE is set.
    // The `from_env` policy above is the initial value either way (and the
    // postgres seed when the table is empty).
    let policy_source = env::var("CASCADIA_POLICY_SOURCE")
        .unwrap_or_default()
        .to_lowercase();
    if policy_source == "postgres" {
        match &db_pool {
            Some(pool) => watcher::spawn_pg(pool.clone(), policy_swap.clone())
                .await
                .context("initializing postgres policy source")?,
            None => anyhow::bail!(
                "CASCADIA_POLICY_SOURCE=postgres requires CASCADIA_DATABASE_URL to be set"
            ),
        }
    } else if let Some(path) = config.policy_file.clone() {
        watcher::spawn(path, policy_swap.clone()).context("spawning policy watcher")?;
    }
    let shutdown_timeout = env::var("CASCADIA_SHUTDOWN_TIMEOUT_SECS")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(30);

    let state = AppState::new(config, events, db_pool, policy_swap, shutdown_timeout)?;
    let app = router(state.clone());

    tracing::info!(%addr, version = env!("CARGO_PKG_VERSION"), "cascadia-proxy listening");
    let listener = TcpListener::bind(addr).await.context("binding listener")?;

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal(state.clone(), shutdown_timeout))
        .await
        .context("serving")?;

    tracing::info!("cascadia-proxy shut down cleanly");
    Ok(())
}

/// Wait for SIGINT or SIGTERM, then begin the graceful-shutdown grace
/// period. Axum drains in-flight requests up to `timeout_secs`; after that
/// the runtime stops regardless. Kubernetes' default `terminationGracePeriodSeconds`
/// is 30s — matching this default keeps the contract predictable.
///
/// The state's shutdown flag is flipped immediately on signal so that
/// `/readyz` returns 503 the moment SIGTERM lands. K8s sees the readiness
/// flip and stops sending new traffic right away rather than waiting the
/// full drain window — at which point existing requests can finish in peace.
/// Enumerate every `CASCADIA_*` env var set in this process, classifying
/// each as "honored" (recognized by config.rs / policy.rs) or "unknown"
/// (set but never read — almost certainly a typo or hallucinated var name).
/// Logged once at startup so an operator (or a Claude Code agent that
/// hallucinated an env-var name) sees the warning instead of silently
/// shipping a broken config.
fn log_recognized_env_vars() {
    const RECOGNIZED: &[&str] = &[
        "CASCADIA_LISTEN_ADDR",
        "PORT", // 12-factor fallback for listen addr
        "CASCADIA_OPENAI_API_KEY",
        "CASCADIA_OPENAI_BASE_URL",
        "CASCADIA_ANTHROPIC_API_KEY",
        "CASCADIA_ANTHROPIC_BASE_URL",
        "CASCADIA_GROQ_API_KEY",
        "CASCADIA_GROQ_BASE_URL",
        "CASCADIA_XAI_API_KEY",
        "CASCADIA_XAI_BASE_URL",
        "CASCADIA_LOG_LEVEL",
        "CASCADIA_LOG_JSON",
        "CASCADIA_DATABASE_URL",
        "CASCADIA_PERSIST_BODIES",
        "CASCADIA_REDACT_SHADOW_BODIES",
        "CASCADIA_OTLP_ENDPOINT",
        "CASCADIA_POLICY_FILE",
        "CASCADIA_POLICY_JSON",
        "CASCADIA_POLICY_SOURCE",
        "CASCADIA_POLICY_POLL_SECS",
        "CASCADIA_PROXY_BEARER_TOKEN",
        "CASCADIA_CHEAP_MODEL",
        "CASCADIA_EXPENSIVE_MODEL",
        "CASCADIA_CASCADE_THRESHOLD",
        "CASCADIA_SHADOW_RATE",
        "CASCADIA_CLUSTER_BUCKETS",
        "CASCADIA_SHUTDOWN_TIMEOUT_SECS",
        "RUST_LOG", // tracing-subscriber EnvFilter
    ];

    let mut honored = Vec::new();
    let mut unknown = Vec::new();
    for (key, _) in env::vars() {
        if !key.starts_with("CASCADIA_") {
            continue;
        }
        if RECOGNIZED.contains(&key.as_str()) {
            honored.push(key);
        } else {
            unknown.push(key);
        }
    }
    honored.sort();
    unknown.sort();
    if !honored.is_empty() {
        tracing::info!(?honored, "CASCADIA_* env vars honored by this build");
    }
    if !unknown.is_empty() {
        tracing::warn!(
            ?unknown,
            "CASCADIA_* env vars set but NOT recognized by this build — probable typo or stale config. \
             See crates/proxy/src/lib.rs::log_recognized_env_vars for the canonical list."
        );
    }
}

async fn shutdown_signal(state: AppState, timeout_secs: u64) {
    let ctrl_c = async {
        tokio::signal::ctrl_c()
            .await
            .expect("failed to install Ctrl+C handler");
    };

    let terminate = async {
        match signal(SignalKind::terminate()) {
            Ok(mut s) => {
                s.recv().await;
            }
            Err(err) => {
                tracing::warn!(?err, "could not install SIGTERM handler");
                std::future::pending::<()>().await;
            }
        }
    };

    tokio::select! {
        _ = ctrl_c => {
            tracing::info!("received SIGINT, draining for up to {timeout_secs}s");
        }
        _ = terminate => {
            tracing::info!("received SIGTERM, draining for up to {timeout_secs}s");
        }
    }

    state.begin_shutdown();

    // Hard ceiling on the drain. Beyond this, axum's task is dropped and
    // any in-flight requests are aborted — kept short so K8s doesn't SIGKILL us.
    tokio::time::sleep(Duration::from_secs(timeout_secs)).await;
}

fn router(state: AppState) -> Router {
    use axum::middleware;
    use axum::routing::{get, post};
    use tower_http::trace::TraceLayer;

    // `/v1/*` routes are auth-gated via the optional bearer token; everything
    // else (probes, metrics) is unauthenticated by design — Kubernetes' probes
    // and Prometheus scrapers don't carry a bearer.
    //
    // Layer order matters: middleware MUST be attached BEFORE with_state so
    // the from_fn_with_state state extraction wires up correctly.
    let v1 = Router::new()
        .route(
            "/v1/chat/completions",
            // Method-not-allowed fallback: a GET / DELETE / PUT against
            // /v1/chat/completions should return an OpenAI-shape error
            // envelope, not axum's default empty 405 body.
            post(handlers::chat::chat_completions)
                .fallback(handlers::not_found::method_not_allowed_chat),
        )
        .route_layer(middleware::from_fn_with_state(
            state.clone(),
            handlers::auth::require_bearer,
        ));

    Router::new()
        .route("/livez", get(handlers::health::livez))
        .route("/readyz", get(handlers::health::readyz))
        .route("/health", get(handlers::health::health))
        .route("/metrics", get(handlers::metrics::metrics))
        // Read-only policy snapshot. Not auth-gated — the policy is config
        // (cluster names + thresholds + model strings), not credentials. The
        // dashboard-api fetches this so operators can see threshold +
        // shadow_rate without grepping the file system.
        .route("/policy", get(handlers::policy::get_policy))
        // Read-only deployment-config snapshot. Surfaces the data-residency
        // posture (persist_bodies / redact_shadow_bodies / all-shadow-off
        // detection) so an operator answering a GDPR DSAR can see at a
        // glance what the deploy persists. No secrets — explicitly NO
        // API keys, DB URLs, or bearer tokens.
        .route("/config", get(handlers::config::get_config))
        .merge(v1)
        .fallback(handlers::not_found::not_found)
        .with_state(state)
        .layer(TraceLayer::new_for_http())
}
