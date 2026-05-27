//! Read-only `/config` endpoint.
//!
//! Returns the deployment's *non-secret* configuration so an operator
//! answering a GDPR / DSAR ticket can see what posture they're running in
//! without SSHing into the container or grepping env vars. Returns NO
//! secrets — no API keys, no DB URLs, no bearer tokens — only the policy
//! / persistence / redaction flags. Lives at `/config`, alongside `/policy`.

use axum::extract::State;
use axum::Json;
use serde_json::{json, Value};

use crate::state::AppState;

pub async fn get_config(State(state): State<AppState>) -> Json<Value> {
    let cfg = state.config();
    let policy = state.policy();
    // Three-posture data-residency classification (matches SECURITY.md's
    // table). Computed here so the dashboard doesn't have to duplicate the
    // logic.
    let all_shadow_off = policy.clusters.values().all(|c| c.shadow_rate <= 0.0);
    let residency_posture = if all_shadow_off {
        "shadow_disabled"
    } else if cfg.redact_shadow_bodies {
        "redacted"
    } else {
        "full_persistence"
    };

    let auth_enabled = cfg.proxy_bearer_token.is_some();
    Json(json!({
        "version": env!("CARGO_PKG_VERSION"),
        "data_residency": {
            "posture": residency_posture,
            "persist_bodies": cfg.persist_bodies,
            "redact_shadow_bodies": cfg.redact_shadow_bodies,
            "any_shadow_rate_active": !all_shadow_off,
        },
        "auth": {
            "bearer_required": auth_enabled,
        },
        "policy_version": policy.version.clone(),
        "policy_cluster_count": policy.clusters.len(),
    }))
}
