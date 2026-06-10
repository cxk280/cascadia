//! Read-only `/providers` endpoint.
//!
//! Returns the configured upstream provider registry — the set of `provider/`
//! prefixes that policy model strings may use, each with its wire format and
//! base URL. Returns NO secrets: API keys are reported only as a `configured`
//! boolean, never the key value. Lives alongside `/policy` and `/config` (all
//! public by design — they expose configuration, not credentials).
//!
//! The dashboard's model-picker reads this so an operator can see which
//! providers are available before choosing a model for a cluster.

use axum::extract::State;
use axum::Json;
use serde_json::{json, Value};

use crate::state::AppState;

pub async fn get_providers(State(state): State<AppState>) -> Json<Value> {
    let cfg = state.config();
    // Sorted for stable output (the registry is a HashMap).
    let mut providers: Vec<Value> = cfg
        .providers
        .values()
        .map(|p| {
            json!({
                "name": p.name,
                "wire": p.wire.label(),
                "base_url": p.base_url,
                // Whether a credential is set — NOT the credential itself.
                "configured": p.api_key.is_some(),
            })
        })
        .collect();
    providers.sort_by(|a, b| a["name"].as_str().cmp(&b["name"].as_str()));

    Json(json!({ "providers": providers }))
}
