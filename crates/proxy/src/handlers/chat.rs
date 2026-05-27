//! `POST /v1/chat/completions` — OpenAI-compatible chat-completions handler.
//!
//! Phase 7: each cluster's policy carries `provider/model` strings; the
//! cascade picks per-tier providers and the event row records the provider
//! that served the final response (which may differ from the cheap tier on
//! escalation, and may be a different provider entirely on mixed-provider
//! clusters).

use std::time::Instant;

use axum::body::Body;
use axum::extract::State;
use axum::http::header::CONTENT_TYPE;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use bytes::Bytes;
use chrono::Utc;
use futures_util::StreamExt;
use serde_json::Value;
use uuid::Uuid;

use crate::cascade::{self, CascadeOutcome};
use crate::config::Provider;
use crate::error::AppError;
use crate::events::Event;
use crate::model_id::parse_model_id;
use crate::openai::Usage;
use crate::state::AppState;

pub async fn chat_completions(
    State(state): State<AppState>,
    body: Bytes,
) -> Result<Response, AppError> {
    let started = Instant::now();
    let request_id = Uuid::new_v4();
    let cluster_for_error = state.policy().default_cluster.clone();

    // Custom JSON parse — axum's `Json` extractor returns a raw `String`
    // body on parse failure, not an OpenAI-shape envelope. Catch the
    // failure here and bounce it back as an AppError::BadRequest so SDK
    // consumers always see a parseable JSON error.
    if body.is_empty() {
        return Err(AppError::BadRequest(
            "request body is empty; expected a JSON object with at least `model` \
             and `messages` fields"
                .into(),
        ));
    }
    let request: Value = serde_json::from_slice(&body).map_err(|e| {
        AppError::BadRequest(format!(
            "request body is not valid JSON: {e}. Expected an OpenAI \
             chat-completion request: {{\"model\":..., \"messages\":[...]}}"
        ))
    })?;

    let stream_requested = request
        .get("stream")
        .and_then(Value::as_bool)
        .unwrap_or(false);

    // Validate model field is present even if we'll override it.
    if request
        .get("model")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .is_none()
    {
        return Err(AppError::BadRequest(
            "missing required field `model`".into(),
        ));
    }

    // Validate `messages` is a non-empty array. OpenAI's contract requires
    // it; the mock upstream is permissive enough to silently succeed on
    // garbage, which surfaces nonsense at the client. Reject at the proxy
    // boundary so downstream code never has to second-guess request shape.
    //
    // Hint at the legacy completions API confusion: a 2023-vintage codebase
    // that sends `prompt: "..."` (the legacy /v1/completions shape) instead
    // of `messages: [...]` is the single most common failure mode for
    // "OpenAI-compatible" gateways. Naming it inline saves the operator an
    // hour of grepping.
    let messages_ok = request
        .get("messages")
        .and_then(Value::as_array)
        .map(|a| !a.is_empty())
        .unwrap_or(false);
    if !messages_ok {
        let mut msg = String::from("field `messages` is required and must be a non-empty array");
        if request.get("prompt").is_some() {
            msg.push_str(
                "; the request carries `prompt`, which is the legacy /v1/completions \
                 API shape. Cascadia only implements /v1/chat/completions — migrate to \
                 `messages=[{\"role\": \"user\", \"content\": ...}]`.",
            );
        }
        return Err(AppError::BadRequest(msg));
    }

    tracing::info!(
        request_id = %request_id,
        stream = stream_requested,
        "starting cascade route"
    );

    if stream_requested {
        return stream_chat_completions(state, started, request_id, request).await;
    }

    let outcome = cascade::route(
        state.http(),
        state.config(),
        state.policy(),
        state.events(),
        request_id,
        &request,
    )
    .await;
    let elapsed = started.elapsed();

    let (status_label, provider_label) = match &outcome {
        Ok(o) => {
            let label = if is_success(o.final_response.status) {
                "ok"
            } else {
                "upstream_error"
            };
            (label, o.final_provider.label())
        }
        Err(_) => ("error", "unknown"),
    };
    state
        .metrics()
        .requests_total
        .with_label_values(&["chat_completions", provider_label, status_label])
        .inc();
    state
        .metrics()
        .request_duration_seconds
        .with_label_values(&["chat_completions", provider_label])
        .observe(elapsed.as_secs_f64());

    match outcome {
        Ok(o) => {
            let CascadeOutcome {
                cluster_id,
                final_model,
                final_provider,
                final_response,
                escalated,
                shadow_logged,
            } = o;

            let usage = parse_usage(&final_response.body);
            let error_code = if is_success(final_response.status) {
                None
            } else {
                Some("upstream_status")
            };

            tracing::info!(
                request_id = %request_id,
                cluster_id,
                escalated,
                shadow_logged,
                final_model = %final_model,
                provider = final_provider.label(),
                status = final_response.status,
                elapsed_ms = elapsed.as_millis() as u64,
                prompt_tokens = usage.map(|u| u.prompt_tokens),
                completion_tokens = usage.map(|u| u.completion_tokens),
                "cascade completed"
            );

            // Always emit the request-level event row (success or upstream-failure).
            if let Some(sender) = state.events() {
                let persist_bodies = state.config().persist_bodies;
                sender.try_send(Event {
                    request_id,
                    occurred_at: Utc::now(),
                    route: "chat_completions",
                    provider: final_provider.label(),
                    model: final_model.clone(),
                    upstream_status: Some(final_response.status as i16),
                    elapsed_ms: elapsed.as_millis() as i32,
                    // `u32 as i32` wraps to a negative count for values above
                    // i32::MAX, corrupting usage analytics. Clamp instead.
                    prompt_tokens: usage
                        .map(|u| i32::try_from(u.prompt_tokens).unwrap_or(i32::MAX)),
                    completion_tokens: usage
                        .map(|u| i32::try_from(u.completion_tokens).unwrap_or(i32::MAX)),
                    request_body: persist_bodies.then(|| request.clone()),
                    response_body: persist_bodies.then(|| final_response.body.clone()),
                    error_code,
                    cluster_id: Some(cluster_id.clone()),
                    escalated: Some(escalated),
                    tools_present: Some(cascade::has_tools(&request)),
                });
            }

            if !is_success(final_response.status) {
                return Err(AppError::UpstreamStatus {
                    status: final_response.status,
                    body: final_response.body.to_string(),
                });
            }

            // Echo the caller's inbound `model` string in the response body
            // so OpenAI-SDK consumers' logging/billing-reconciliation code
            // (which inspects `response.model`) sees what they asked for, not
            // the policy's per-tier model. The actually-served model is
            // surfaced via the `x-cascadia-served-model` and
            // `x-cascadia-served-provider` headers and persisted in
            // `events.model` so observability isn't lost.
            let inbound_model = request
                .get("model")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            let mut final_body = final_response.body;
            rewrite_response_model(&mut final_body, &inbound_model);
            let mut response = Json(final_body).into_response();
            if let Ok(hv) = axum::http::HeaderValue::from_str(&final_model) {
                response.headers_mut().insert("x-cascadia-served-model", hv);
            }
            response.headers_mut().insert(
                "x-cascadia-served-provider",
                axum::http::HeaderValue::from_static(final_provider.label()),
            );
            response.headers_mut().insert(
                "x-cascadia-escalated",
                axum::http::HeaderValue::from_static(if escalated { "true" } else { "false" }),
            );
            // request_id closes the GDPR correlation loop: the application
            // layer can log this header value alongside the user's session
            // to later run the deletion recipe in SECURITY.md.
            if let Ok(hv) = axum::http::HeaderValue::from_str(&request_id.to_string()) {
                response.headers_mut().insert("x-cascadia-request-id", hv);
            }
            Ok(response)
        }
        Err(err) => {
            let error_code = error_code_for(&err);
            // Try to attribute the failure to whichever provider would have
            // served the cluster's cheap tier, falling back to "unknown".
            let provider =
                provider_for_cluster(state.policy(), &cluster_for_error).unwrap_or("unknown");
            emit_event_failure(
                &state,
                request_id,
                &request,
                None,
                provider,
                None,
                started,
                error_code,
                cluster_for_error,
            );
            Err(err)
        }
    }
}

fn is_success(status: u16) -> bool {
    (200..300).contains(&status)
}

/// Streaming chat-completions path. Cascade picks the cheap tier only — no
/// escalation, no shadow pair logged (see `cascade::route_streaming` for why)
/// — and we pipe the upstream's SSE chunks back to the client through an
/// axum `text/event-stream` body. The event row is logged once the stream
/// completes (success or upstream-error).
async fn stream_chat_completions(
    state: AppState,
    started: Instant,
    request_id: Uuid,
    request: Value,
) -> Result<Response, AppError> {
    let cluster_for_error = state.policy().default_cluster.clone();
    let outcome = match cascade::route_streaming(
        state.http(),
        state.config(),
        state.policy(),
        &request,
    )
    .await
    {
        Ok(o) => o,
        Err(err) => {
            let error_code = error_code_for(&err);
            let provider =
                provider_for_cluster(state.policy(), &cluster_for_error).unwrap_or("unknown");
            emit_event_failure(
                &state,
                request_id,
                &request,
                None,
                provider,
                None,
                started,
                error_code,
                cluster_for_error,
            );
            state
                .metrics()
                .requests_total
                .with_label_values(&["chat_completions_stream", "unknown", "error"])
                .inc();
            return Err(err);
        }
    };

    let cluster_id = outcome.cluster_id.clone();
    let final_model = outcome.final_model.clone();
    let final_provider = outcome.final_provider;
    let has_tools_at_start = cascade::has_tools(&request);
    let upstream_status = outcome.stream.status;

    // Prometheus's IntCounterVec / HistogramVec types are internally Arc-
    // wrapped, so cloning is cheap and shares the underlying registry.
    let requests_total = state.metrics().requests_total.clone();
    let request_duration_seconds = state.metrics().request_duration_seconds.clone();
    let events_sender = state.events().cloned();
    let persist_bodies = state.config().persist_bodies;
    let request_for_event = request.clone();
    let status_for_event = upstream_status;
    let model_for_event = final_model.clone();
    let provider_label = final_provider.label();

    // Wrap the upstream stream so once it ends (cleanly or with error), we
    // emit the event row and metrics. `then` lets us run an async finalizer
    // when the inner stream completes — done via a chained empty-stream that
    // fires the finalizer once.
    let mut byte_stream = outcome.stream.body_stream;
    let started_for_stream = started;

    // Manually drive the stream so we can run the finalizer exactly once
    // when it ends. async_stream-style without the dep: spawn a forwarder
    // task that owns the upstream stream and a channel back to axum.
    let (tx, mut rx) = tokio::sync::mpsc::channel::<Result<Bytes, std::io::Error>>(32);
    tokio::spawn(async move {
        while let Some(item) = byte_stream.next().await {
            match item {
                Ok(b) => {
                    if tx.send(Ok(b)).await.is_err() {
                        // Client disconnected; abandon the stream.
                        break;
                    }
                }
                Err(err) => {
                    let _ = tx.send(Err(std::io::Error::other(err.to_string()))).await;
                    break;
                }
            }
        }
        let elapsed = started_for_stream.elapsed();
        let status_label = if is_success(status_for_event) {
            "ok"
        } else {
            "upstream_error"
        };
        requests_total
            .with_label_values(&["chat_completions_stream", provider_label, status_label])
            .inc();
        request_duration_seconds
            .with_label_values(&["chat_completions_stream", provider_label])
            .observe(elapsed.as_secs_f64());

        if let Some(sender) = events_sender {
            let error_code = if is_success(status_for_event) {
                None
            } else {
                Some("upstream_status")
            };
            sender.try_send(Event {
                request_id,
                occurred_at: Utc::now(),
                route: "chat_completions_stream",
                provider: provider_label,
                model: model_for_event,
                upstream_status: Some(status_for_event as i16),
                elapsed_ms: elapsed.as_millis() as i32,
                // Streaming responses don't carry usage in standard chunks
                // (unless the client passes `stream_options.include_usage`),
                // so we don't try to attribute tokens here. Future work:
                // accumulate token counts client-side from chunk content.
                prompt_tokens: None,
                completion_tokens: None,
                request_body: persist_bodies.then(|| request_for_event.clone()),
                response_body: None,
                error_code,
                cluster_id: Some(cluster_id.clone()),
                escalated: Some(false),
                tools_present: Some(has_tools_at_start),
            });
        }
    });

    let body_stream = futures_util::stream::poll_fn(move |cx| rx.poll_recv(cx));

    // Map upstream status to the proxy's HTTP status. 200 on success; pass
    // through the upstream's status on non-success — the body will still
    // contain the OpenAI-shape error chunk emitted by the adapter.
    let http_status = StatusCode::from_u16(upstream_status).unwrap_or(StatusCode::BAD_GATEWAY);
    let response = Response::builder()
        .status(http_status)
        .header(CONTENT_TYPE, "text/event-stream")
        .header("cache-control", "no-cache")
        .header("x-accel-buffering", "no")
        // GDPR correlation: see non-stream path for the rationale.
        .header("x-cascadia-request-id", request_id.to_string())
        .body(Body::from_stream(body_stream))
        .map_err(|e| AppError::Internal(anyhow::anyhow!("building stream response: {e}")))?;
    Ok(response)
}

fn error_code_for(err: &AppError) -> &'static str {
    match err {
        AppError::BadRequest(_) => "bad_request",
        AppError::Unauthorized(_) => "unauthorized",
        AppError::MethodNotAllowed(_) => "method_not_allowed",
        AppError::ProviderUnconfigured(_) => "provider_unconfigured",
        AppError::UpstreamStatus { .. } => "upstream_status",
        AppError::Upstream(_) => "upstream",
        AppError::NotFound(_) => "not_found",
        AppError::Internal(_) => "internal",
    }
}

/// Look up the cluster's cheap_model and return its provider label, for
/// error-event attribution before the cascade has run.
fn provider_for_cluster(
    policy: std::sync::Arc<crate::policy::PolicyTable>,
    cluster_id: &str,
) -> Option<&'static str> {
    let p = policy.lookup(cluster_id);
    parse_model_id(&p.cheap_model)
        .ok()
        .map(|id| id.provider.label())
}

#[allow(clippy::too_many_arguments)]
fn emit_event_failure(
    state: &AppState,
    request_id: Uuid,
    request: &Value,
    final_model: Option<String>,
    provider_label: &'static str,
    upstream_status: Option<i16>,
    started: Instant,
    error_code: &'static str,
    cluster_id: String,
) {
    let Some(sender) = state.events() else {
        return;
    };
    let model = final_model
        .or_else(|| {
            request
                .get("model")
                .and_then(Value::as_str)
                .map(str::to_owned)
        })
        .unwrap_or_else(|| "unknown".to_string());
    let persist_bodies = state.config().persist_bodies;
    sender.try_send(Event {
        request_id,
        occurred_at: Utc::now(),
        route: "chat_completions",
        provider: provider_label,
        model,
        upstream_status,
        elapsed_ms: started.elapsed().as_millis() as i32,
        prompt_tokens: None,
        completion_tokens: None,
        request_body: persist_bodies.then(|| request.clone()),
        response_body: None,
        error_code: Some(error_code),
        cluster_id: Some(cluster_id),
        escalated: None,
        tools_present: Some(cascade::has_tools(request)),
    });
}

#[allow(dead_code)]
fn provider_label(provider: Provider) -> &'static str {
    provider.label()
}

fn parse_usage(body: &Value) -> Option<Usage> {
    body.get("usage")
        .and_then(|u| serde_json::from_value(u.clone()).ok())
}

/// Echo the caller's inbound `model` into the response body's `model` field.
///
/// Only rewrites when `body` is a JSON object: `Value::index_mut` panics on a
/// non-object, non-null value, so an upstream returning a 2xx body that's an
/// array / string / number (misbehaving or compromised OpenAI-compat host)
/// would otherwise panic the handler task and reset the client connection.
/// Such bodies pass through untouched.
fn rewrite_response_model(body: &mut Value, inbound_model: &str) {
    if inbound_model.is_empty() {
        return;
    }
    if let Some(obj) = body.as_object_mut() {
        obj.insert(
            "model".to_string(),
            Value::String(inbound_model.to_string()),
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn rewrite_model_sets_field_on_object_body() {
        let mut body = json!({"model": "served-model", "choices": []});
        rewrite_response_model(&mut body, "gpt-4o");
        assert_eq!(body["model"], json!("gpt-4o"));
    }

    #[test]
    fn rewrite_model_empty_inbound_is_noop() {
        let mut body = json!({"model": "served-model"});
        rewrite_response_model(&mut body, "");
        assert_eq!(body["model"], json!("served-model"));
    }

    #[test]
    fn rewrite_model_on_non_object_body_does_not_panic() {
        // A 2xx upstream body that isn't an object must not panic.
        for mut body in [json!([1, 2, 3]), json!("ok"), json!(42), json!(true)] {
            rewrite_response_model(&mut body, "gpt-4o");
        }
    }
}
