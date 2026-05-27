//! Read-only `/policy` endpoint.
//!
//! Returns the in-memory `PolicyTable` as JSON so the dashboard-api can show
//! operators the threshold + shadow_rate that's actually running on each
//! cluster (without forcing every operator to grep the file system or
//! redeploy to check). The endpoint is NOT auth-gated by the bearer-token
//! middleware because it lives under `/policy`, not `/v1/*`, but it also
//! returns no secrets — the policy table is configuration, not credentials.

use axum::extract::State;
use axum::Json;
use serde_json::Value;

use crate::state::AppState;

pub async fn get_policy(State(state): State<AppState>) -> Json<Value> {
    let table = state.policy();
    // PolicyTable derives Serialize; round-trip through serde_json for a
    // stable shape that survives any future struct changes (we'd rather
    // emit slightly fewer fields than 500 on a serialization edge case).
    let v = serde_json::to_value(table.as_ref()).unwrap_or(Value::Null);
    Json(v)
}
