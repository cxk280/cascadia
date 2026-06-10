//! Upstream provider dispatch.
//!
//! Phase 7: every cascade tier carries an explicit `provider/model` string in
//! its policy (parsed via `model_id::parse_model_id`). At call time we route
//! to the right adapter based on that parsed provider:
//!
//! - `Wire::OpenAi` providers (OpenAI, Groq, xAI, HuggingFace, vLLM, …) →
//!   `openai_compat` adapter (they all speak `/v1/chat/completions`).
//! - `Wire::Anthropic` providers → `anthropic` adapter, which translates
//!   OpenAI's ChatCompletion request shape into Anthropic's `/v1/messages` API
//!   and back. Tool-use parity is included (Phase 7.1).
//!
//! The dispatch surface is `forward_chat(http, provider, request_body)`, where
//! `provider` is a resolved `ProviderConfig` (the cascade resolves the policy's
//! `provider/` prefix against `Config`'s registry). Adapters never see the
//! provider identity — they take the base URL + API key directly.

pub mod anthropic;
pub mod openai_compat;

use std::pin::Pin;

use bytes::Bytes;
use futures_util::Stream;
use reqwest::Client;
use serde_json::{json, Value};

use crate::config::{ProviderConfig, Wire};
use crate::error::AppError;

/// Result of an upstream call: the JSON response (normalized to OpenAI's
/// ChatCompletion shape regardless of which upstream produced it) plus the
/// HTTP status. Status is returned so the caller can pass it through to the
/// client when the upstream returns a non-success code.
pub struct UpstreamResponse {
    pub status: u16,
    pub body: Value,
}

/// Byte stream of OpenAI-shape SSE chunks (`data: {...}\n\n`) plus the trailing
/// `data: [DONE]\n\n` sentinel. For OpenAI/Groq/xAI this is the upstream stream
/// passed through verbatim; for Anthropic it's a translation of the typed
/// Anthropic event stream into OpenAI's delta shape.
pub type SseByteStream = Pin<Box<dyn Stream<Item = Result<Bytes, AppError>> + Send + 'static>>;

/// Result of a streaming upstream call. Status is the upstream HTTP status
/// (200 on success; the caller propagates non-success without consuming the
/// stream). `body_stream` yields SSE chunks already framed with `data: ` and
/// `\n\n`, normalized to OpenAI's ChatCompletion-chunk shape.
pub struct UpstreamStreamResponse {
    pub status: u16,
    pub body_stream: SseByteStream,
}

/// Forward an OpenAI-shaped chat-completion request to the chosen provider.
/// The caller is responsible for ensuring `request_body.model` is the
/// provider-local model name (no `provider/` prefix) — cascade::with_model
/// handles this.
pub async fn forward_chat(
    client: &Client,
    provider: &ProviderConfig,
    request_body: &Value,
) -> Result<UpstreamResponse, AppError> {
    let api_key = provider
        .api_key
        .as_deref()
        .ok_or_else(|| AppError::ProviderUnconfigured(unconfigured_msg(provider)))?;
    match provider.wire {
        Wire::OpenAi => {
            openai_compat::forward(client, &provider.base_url, api_key, request_body).await
        }
        Wire::Anthropic => {
            anthropic::forward(client, &provider.base_url, api_key, request_body).await
        }
    }
}

/// Forward an OpenAI-shaped *streaming* chat-completion request to the chosen
/// provider. The caller is responsible for setting `stream: true` on the body
/// (cascade does this when entering the streaming path). Returns a stream of
/// SSE-framed bytes in OpenAI's ChatCompletion-chunk shape — Anthropic events
/// are translated inside its adapter; OpenAI-compat providers pass through.
pub async fn forward_chat_stream(
    client: &Client,
    provider: &ProviderConfig,
    request_body: &Value,
) -> Result<UpstreamStreamResponse, AppError> {
    let api_key = provider
        .api_key
        .as_deref()
        .ok_or_else(|| AppError::ProviderUnconfigured(unconfigured_msg(provider)))?;
    match provider.wire {
        Wire::OpenAi => {
            openai_compat::forward_stream(client, &provider.base_url, api_key, request_body).await
        }
        Wire::Anthropic => {
            anthropic::forward_stream(client, &provider.base_url, api_key, request_body).await
        }
    }
}

/// Replace the `model` field of an OpenAI-shaped request with the
/// provider-local name (post-`provider/` slash). Used by `cascade::route()`.
pub fn rewrite_model(request: &Value, model: &str) -> Value {
    let mut cloned = request.clone();
    cloned["model"] = json!(model);
    cloned
}

/// Force a JSON request body to advertise `stream: true`. The streaming
/// adapters require this — clients may submit `stream: true` already, but
/// cascade::route_streaming() also calls this defensively so an upstream
/// adapter never opens a non-streaming connection by accident.
pub fn force_stream(request: &Value) -> Value {
    let mut cloned = request.clone();
    cloned["stream"] = json!(true);
    cloned
}

/// Build the "provider has no key" message, naming the env var the operator
/// needs to set — the historical `CASCADIA_<NAME>_API_KEY` for the four
/// built-ins, or `CASCADIA_PROVIDER_<NAME>_API_KEY` for a registry entry.
fn unconfigured_msg(provider: &ProviderConfig) -> String {
    let env_var = match provider.name.as_str() {
        "openai" | "anthropic" | "groq" | "xai" => {
            format!("CASCADIA_{}_API_KEY", provider.name.to_uppercase())
        }
        other => format!(
            "CASCADIA_PROVIDER_{}_API_KEY",
            other.to_uppercase().replace('-', "_")
        ),
    };
    format!(
        "provider `{}` has no API key set ({env_var} unset)",
        provider.name
    )
}
