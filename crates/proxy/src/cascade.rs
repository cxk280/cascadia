//! Phase-2 two-tier cascade routing, Phase-7 cross-provider extension.
//!
//! Flow:
//! 1. Classify request into a cluster.
//! 2. Look up that cluster's policy (cheap model, expensive model, threshold,
//!    shadow rate). Each model is a `provider/model` string parsed at boot
//!    by `policy.rs` (Phase-7 hard-fail on unprefixed).
//! 3. Call the cheap tier with the cluster's cheap model on its provider.
//! 4. Extract the assistant's text and compute a confidence signal.
//! 5. If confidence ≥ threshold → return cheap, optionally fire a background
//!    shadow request to the expensive tier (rate-controlled by policy.shadow_rate).
//!    A `ShadowPair` row is logged so the judge worker can score the pair.
//! 6. If confidence < threshold → call the expensive tier synchronously and
//!    return that. We still log a `ShadowPair` since we now have both responses.
//!
//! Phase 7.1: requests carrying `tools` bypass escalation. Tool loops are
//! stateful — escalating mid-loop to a different model mid-tool-call would
//! produce incoherent state. We log no shadow pair on the tool-use path
//! either (the judge can't compare two responses that diverge into different
//! tool-call sequences).
//!
//! Counterfactual shadow eval is the load-bearing claim — we ALWAYS log the
//! pair if we have it, whether we got it via escalation or via background
//! sampling, except on the tool-use path described above. The judge worker
//! doesn't care which path produced the pair.
//!
//! Cost accounting: the chat handler reads `outcome.escalated` and the
//! `final_response.usage` to compute proper tokens-per-tier metrics.

use std::sync::Arc;

use rand::Rng;
use serde_json::Value;
use uuid::Uuid;

use crate::cluster;
use crate::config::{Config, Provider};
use crate::error::AppError;
use crate::events::{EventSender, ShadowPair};
use crate::model_id::{parse_model_id, ModelId};
use crate::policy::{ClusterPolicy, PolicyTable};
use crate::upstream::{self, UpstreamResponse, UpstreamStreamResponse};

/// What the cascade did for one request.
pub struct CascadeOutcome {
    /// Cluster id chosen by the classifier.
    pub cluster_id: String,
    /// Model that produced `final_response`. Either cheap or expensive.
    /// Full `provider/model` string as it appeared in the policy.
    pub final_model: String,
    /// Provider that served `final_response`. Derived from `final_model`'s prefix.
    pub final_provider: Provider,
    /// Response we return to the client.
    pub final_response: UpstreamResponse,
    /// True if the cheap tier was rejected and we escalated.
    pub escalated: bool,
    /// True if a shadow eval was either dispatched (background) or completed
    /// synchronously (via escalation). i.e. true iff a shadow_pair was logged.
    pub shadow_logged: bool,
}

/// Run the Phase-2 cascade with Phase-7 cross-provider dispatch. Returns the
/// final response plus diagnostics the handler will record in metrics + the
/// event log.
pub async fn route(
    http: &reqwest::Client,
    config: &Config,
    policy: Arc<PolicyTable>,
    events: Option<&EventSender>,
    request_id: Uuid,
    request: &Value,
) -> Result<CascadeOutcome, AppError> {
    let cluster_id = cluster::classify(policy.cluster_buckets, request);
    let cluster_policy = policy.lookup(&cluster_id).clone();

    // Parse provider/model for each tier. Policy validation in policy.rs
    // already guarantees this can't fail, but we plumb the error rather
    // than panic — defense in depth.
    let cheap_id = parse_model_id(&cluster_policy.cheap_model)
        .map_err(|e| AppError::Internal(e.context("cheap_model parse")))?;
    let expensive_id = parse_model_id(&cluster_policy.expensive_model)
        .map_err(|e| AppError::Internal(e.context("expensive_model parse")))?;

    // Tool-use bypass (Phase 7.1): if the caller sent `tools`, don't cascade.
    // Route to the cheap tier and return whatever it gives; no shadow logging.
    if has_tools(request) {
        let cheap_request = upstream::rewrite_model(request, &cheap_id.model);
        let cheap_response =
            upstream::forward_chat(http, config, cheap_id.provider, &cheap_request).await?;
        if !is_success(cheap_response.status) {
            return Err(AppError::UpstreamStatus {
                status: cheap_response.status,
                body: cheap_response.body.to_string(),
            });
        }
        return Ok(CascadeOutcome {
            cluster_id,
            final_model: cluster_policy.cheap_model.clone(),
            final_provider: cheap_id.provider,
            final_response: cheap_response,
            escalated: false,
            shadow_logged: false,
        });
    }

    // 1. Cheap-tier call.
    let cheap_request = upstream::rewrite_model(request, &cheap_id.model);
    let cheap_response =
        upstream::forward_chat(http, config, cheap_id.provider, &cheap_request).await?;
    if !is_success(cheap_response.status) {
        return Err(AppError::UpstreamStatus {
            status: cheap_response.status,
            body: cheap_response.body.to_string(),
        });
    }

    let cheap_text = extract_assistant_text(&cheap_response.body).unwrap_or_default();
    let conf = crate::confidence::confidence(&cheap_text);

    if conf >= cluster_policy.threshold {
        // Accept cheap. Maybe shadow-eval in the background.
        let dispatch_shadow = rand::thread_rng().gen::<f32>() < cluster_policy.shadow_rate;
        let mut shadow_logged = false;
        if dispatch_shadow {
            shadow_logged = true;
            spawn_shadow(
                http.clone(),
                config.clone(),
                events.cloned(),
                request_id,
                cluster_policy.clone(),
                expensive_id.clone(),
                request.clone(),
                cheap_text,
            );
        }
        return Ok(CascadeOutcome {
            cluster_id: cluster_id.clone(),
            final_model: cluster_policy.cheap_model.clone(),
            final_provider: cheap_id.provider,
            final_response: cheap_response,
            escalated: false,
            shadow_logged,
        });
    }

    // 2. Escalate. Call expensive synchronously.
    let exp_request = upstream::rewrite_model(request, &expensive_id.model);
    let exp_response =
        upstream::forward_chat(http, config, expensive_id.provider, &exp_request).await?;
    if !is_success(exp_response.status) {
        return Err(AppError::UpstreamStatus {
            status: exp_response.status,
            body: exp_response.body.to_string(),
        });
    }
    let exp_text = extract_assistant_text(&exp_response.body).unwrap_or_default();

    // Always log the pair when we've spent the tokens on both tiers.
    if let Some(sender) = events {
        let redact = config.redact_shadow_bodies;
        sender.send_shadow_pair(ShadowPair {
            pair_id: Uuid::new_v4(),
            request_id,
            occurred_at: chrono::Utc::now(),
            cluster_id: cluster_id.clone(),
            prompt: maybe_redact(extract_prompt(request), redact),
            cheap_model: cluster_policy.cheap_model.clone(),
            cheap_response: maybe_redact(cheap_text, redact),
            expensive_model: cluster_policy.expensive_model.clone(),
            expensive_response: maybe_redact(exp_text, redact),
        });
    }

    Ok(CascadeOutcome {
        cluster_id,
        final_model: cluster_policy.expensive_model.clone(),
        final_provider: expensive_id.provider,
        final_response: exp_response,
        escalated: true,
        shadow_logged: true,
    })
}

/// Outcome of the streaming-path cascade. The proxy hot-path for streaming
/// requests is "cheap-tier only, no escalation, no shadow"; this struct just
/// carries enough metadata for the handler to log an event row once the
/// stream completes.
pub struct StreamingCascadeOutcome {
    pub cluster_id: String,
    pub final_model: String,
    pub final_provider: Provider,
    pub stream: UpstreamStreamResponse,
}

/// Streaming variant of `route`. Like the tool-use path, streaming bypasses
/// escalation — the cheap-tier response is committed to the wire chunk by
/// chunk and cannot be retroactively replaced with an expensive response
/// without breaking the client's stream contract. No shadow pair is logged
/// for the same reason: the judge needs both cheap and expensive completions
/// to score, and we have only the cheap one.
pub async fn route_streaming(
    http: &reqwest::Client,
    config: &Config,
    policy: Arc<PolicyTable>,
    request: &Value,
) -> Result<StreamingCascadeOutcome, AppError> {
    let cluster_id = cluster::classify(policy.cluster_buckets, request);
    let cluster_policy = policy.lookup(&cluster_id).clone();
    let cheap_id = parse_model_id(&cluster_policy.cheap_model)
        .map_err(|e| AppError::Internal(e.context("cheap_model parse")))?;

    let upstream_request =
        upstream::force_stream(&upstream::rewrite_model(request, &cheap_id.model));
    let stream =
        upstream::forward_chat_stream(http, config, cheap_id.provider, &upstream_request).await?;

    Ok(StreamingCascadeOutcome {
        cluster_id,
        final_model: cluster_policy.cheap_model.clone(),
        final_provider: cheap_id.provider,
        stream,
    })
}

/// Spawn a background task that calls the expensive tier and logs the pair.
/// Errors are swallowed (with a warn log) — the foreground request has
/// already returned successfully to the caller.
///
/// The 8 parameters are intentional: each is a distinct piece of state the
/// background task needs to own (owned clones, not borrows, because the task
/// outlives the handler frame). Bundling them into a struct would just
/// rename the same 8 fields — `BackgroundShadowJob { http, config, ... }` —
/// without reducing complexity. Keeping the signature flat means the
/// call-site in `route()` doesn't need an extra constructor invocation.
#[allow(clippy::too_many_arguments)]
fn spawn_shadow(
    http: reqwest::Client,
    config: Config,
    events: Option<EventSender>,
    request_id: Uuid,
    cluster_policy: ClusterPolicy,
    expensive_id: ModelId,
    original_request: Value,
    cheap_text: String,
) {
    tokio::spawn(async move {
        let exp_request = upstream::rewrite_model(&original_request, &expensive_id.model);
        let result =
            upstream::forward_chat(&http, &config, expensive_id.provider, &exp_request).await;
        match result {
            Ok(resp) if is_success(resp.status) => {
                let exp_text = extract_assistant_text(&resp.body).unwrap_or_default();
                if let Some(sender) = events {
                    let redact = config.redact_shadow_bodies;
                    sender.send_shadow_pair(ShadowPair {
                        pair_id: Uuid::new_v4(),
                        request_id,
                        occurred_at: chrono::Utc::now(),
                        cluster_id: cluster_policy.cluster_id.clone(),
                        prompt: maybe_redact(extract_prompt(&original_request), redact),
                        cheap_model: cluster_policy.cheap_model.clone(),
                        cheap_response: maybe_redact(cheap_text, redact),
                        expensive_model: cluster_policy.expensive_model.clone(),
                        expensive_response: maybe_redact(exp_text, redact),
                    });
                }
            }
            Ok(resp) => {
                tracing::warn!(
                    request_id = %request_id,
                    status = resp.status,
                    "shadow eval upstream returned non-success"
                );
            }
            Err(err) => {
                tracing::warn!(request_id = %request_id, ?err, "shadow eval upstream failed");
            }
        }
    });
}

/// Conditionally replace a user-data string with its SHA-256 digest. Used
/// by the shadow_pair logging path when `CASCADIA_REDACT_SHADOW_BODIES=true`
/// so regulated deployments can keep cascade telemetry without storing
/// verbatim prompts/responses. See SECURITY.md for the trade-off.
pub(crate) fn maybe_redact(text: String, redact: bool) -> String {
    if !redact {
        return text;
    }
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(text.as_bytes());
    format!("sha256:{:x}", hasher.finalize())
}

/// Whether the caller sent a non-empty `tools: [...]` array. The cascade
/// uses this to short-circuit to the cheap tier (escalation bypass — see
/// PLAN.md §9 2026-05-20 Phase 7.1); the chat handler also reads it to
/// stamp `events.tools_present` so the dashboard can distinguish "all my
/// traffic was tool-use" from "cluster is misconfigured."
pub fn has_tools(request: &Value) -> bool {
    request
        .get("tools")
        .and_then(Value::as_array)
        .map(|a| !a.is_empty())
        .unwrap_or(false)
}

fn is_success(status: u16) -> bool {
    (200..300).contains(&status)
}

/// Pull the assistant's text from a ChatCompletion response body. Returns
/// `None` if the shape is unrecognized — the cascade then treats the
/// response as low-confidence and may escalate. Robust to absent or odd
/// content; we don't want a JSON quirk to crash the proxy.
fn extract_assistant_text(body: &Value) -> Option<String> {
    let first_choice = body.get("choices")?.get(0)?;
    let message = first_choice.get("message")?;
    let content = message.get("content")?;
    if let Some(s) = content.as_str() {
        return Some(s.to_string());
    }
    // Multi-part content (vision-style); flatten to text bits we can find.
    if let Some(arr) = content.as_array() {
        let joined: String = arr
            .iter()
            .filter_map(|p| p.get("text").and_then(Value::as_str))
            .collect::<Vec<_>>()
            .join("\n");
        if !joined.is_empty() {
            return Some(joined);
        }
    }
    None
}

/// Best-effort "prompt" extraction: the last user message's text content.
/// For the judge's purposes this is the canonical thing to score the
/// responses against. System prompts are excluded.
fn extract_prompt(request: &Value) -> String {
    let Some(messages) = request.get("messages").and_then(Value::as_array) else {
        return String::new();
    };
    for message in messages.iter().rev() {
        let role = message.get("role").and_then(Value::as_str).unwrap_or("");
        if role != "user" {
            continue;
        }
        let content = message.get("content");
        if let Some(text) = content.and_then(Value::as_str) {
            return text.to_string();
        }
        if let Some(arr) = content.and_then(Value::as_array) {
            let joined: String = arr
                .iter()
                .filter_map(|p| p.get("text").and_then(Value::as_str))
                .collect::<Vec<_>>()
                .join("\n");
            if !joined.is_empty() {
                return joined;
            }
        }
    }
    String::new()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn extract_text_handles_string_content() {
        let body = json!({
            "choices": [{
                "message": { "role": "assistant", "content": "hello" }
            }]
        });
        assert_eq!(extract_assistant_text(&body).as_deref(), Some("hello"));
    }

    #[test]
    fn extract_text_handles_multipart_content() {
        let body = json!({
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "part one"},
                        {"type": "text", "text": "part two"},
                    ]
                }
            }]
        });
        assert_eq!(
            extract_assistant_text(&body).as_deref(),
            Some("part one\npart two")
        );
    }

    #[test]
    fn extract_text_returns_none_on_unknown_shape() {
        let body = json!({"choices": []});
        assert!(extract_assistant_text(&body).is_none());
    }

    #[test]
    fn extract_prompt_uses_last_user_message() {
        let req = json!({
            "messages": [
                {"role": "system", "content": "you are helpful"},
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "response"},
                {"role": "user", "content": "second"}
            ]
        });
        assert_eq!(extract_prompt(&req), "second");
    }

    #[test]
    fn extract_prompt_empty_when_no_user_message() {
        let req = json!({"messages": [{"role": "system", "content": "hi"}]});
        assert_eq!(extract_prompt(&req), "");
    }

    #[test]
    fn has_tools_detects_non_empty_array() {
        assert!(!has_tools(&json!({})));
        assert!(!has_tools(&json!({"tools": []})));
        assert!(has_tools(&json!({"tools": [{"type": "function"}]})));
    }
}
