//! Upstream provider dispatch.
//!
//! Phase 7: every cascade tier carries an explicit `provider/model` string in
//! its policy (parsed via `model_id::parse_model_id`). At call time we route
//! to the right adapter based on that parsed provider:
//!
//! - `Provider::OpenAI`, `Provider::Groq`, `Provider::XAI` → `openai_compat`
//!   adapter (all three speak the same `/v1/chat/completions` shape).
//! - `Provider::Anthropic` → `anthropic` adapter, which translates OpenAI's
//!   ChatCompletion request shape into Anthropic's `/v1/messages` API and
//!   back. Tool-use parity is included (Phase 7.1).
//!
//! The dispatch surface is just `forward_chat(http, config, provider, model,
//! request_body)`. Adapters never see the `Provider` enum — they take the
//! base URL + API key directly so a future per-cluster credential
//! override is a one-line change.

pub mod anthropic;
pub mod openai_compat;

use std::pin::Pin;

use bytes::Bytes;
use futures_util::Stream;
use reqwest::Client;
use serde_json::{json, Value};

use crate::config::{Config, Provider};
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
pub type SseByteStream =
    Pin<Box<dyn Stream<Item = Result<Bytes, AppError>> + Send + 'static>>;

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
    config: &Config,
    provider: Provider,
    request_body: &Value,
) -> Result<UpstreamResponse, AppError> {
    let (api_key, base_url) = config.provider_credentials(provider).ok_or_else(|| {
        AppError::ProviderUnconfigured(provider_unconfigured_msg(provider))
    })?;
    match provider {
        Provider::OpenAI | Provider::Groq | Provider::XAI => {
            openai_compat::forward(client, base_url, api_key, request_body).await
        }
        Provider::Anthropic => {
            anthropic::forward(client, base_url, api_key, request_body).await
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
    config: &Config,
    provider: Provider,
    request_body: &Value,
) -> Result<UpstreamStreamResponse, AppError> {
    let (api_key, base_url) = config.provider_credentials(provider).ok_or_else(|| {
        AppError::ProviderUnconfigured(provider_unconfigured_msg(provider))
    })?;
    match provider {
        Provider::OpenAI | Provider::Groq | Provider::XAI => {
            openai_compat::forward_stream(client, base_url, api_key, request_body).await
        }
        Provider::Anthropic => {
            anthropic::forward_stream(client, base_url, api_key, request_body).await
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

fn provider_unconfigured_msg(provider: Provider) -> &'static str {
    match provider {
        Provider::OpenAI => "CASCADIA_OPENAI_API_KEY not set",
        Provider::Anthropic => "CASCADIA_ANTHROPIC_API_KEY not set",
        Provider::Groq => "CASCADIA_GROQ_API_KEY not set",
        Provider::XAI => "CASCADIA_XAI_API_KEY not set",
    }
}
