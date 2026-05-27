//! OpenAI-compatible adapter — covers OpenAI itself plus Groq and xAI.
//!
//! All three providers expose the same `/v1/chat/completions` request and
//! response shape, including tool-use (function-calling) semantics. The only
//! per-provider configuration is the base URL and API key, both passed in
//! from `upstream::forward_chat()`.

use futures_util::TryStreamExt;
use reqwest::Client;
use serde_json::Value;

use crate::error::AppError;
use crate::upstream::{UpstreamResponse, UpstreamStreamResponse};

/// Bare hosts we know are NOT OpenAI-compatible despite using HTTPS. If an
/// operator points the OpenAI adapter at one of these (a classic
/// misconfiguration), we want to fail with a *clear* message instead of
/// passing through whatever cryptic auth error the upstream returns. Air-
/// gapped operators are especially impacted: a misconfigured URL becomes
/// silent connection timeout with no signal that the wrong adapter was used.
const KNOWN_NON_OPENAI_HOSTS: &[&str] = &[
    "api.anthropic.com",
    "generativelanguage.googleapis.com", // Gemini
    "bedrock-runtime",                   // any AWS Bedrock regional host substring
];

fn detect_misconfigured_host(base_url: &str) -> Option<&'static str> {
    for needle in KNOWN_NON_OPENAI_HOSTS {
        if base_url.contains(needle) {
            return Some(*needle);
        }
    }
    None
}

#[tracing::instrument(skip_all)]
pub async fn forward(
    client: &Client,
    base_url: &str,
    api_key: &str,
    body: &Value,
) -> Result<UpstreamResponse, AppError> {
    if let Some(host) = detect_misconfigured_host(base_url) {
        return Err(AppError::BadRequest(format!(
            "OpenAI adapter pointed at `{base_url}`, which is `{host}` — that host does not speak the OpenAI /v1/chat/completions shape. \
            Use the matching prefix (e.g. `anthropic/<model>`) in your policy file and set `CASCADIA_ANTHROPIC_BASE_URL` instead. \
            For private OpenAI-compatible endpoints (vLLM, Together, DeepInfra), this check is bypassed — point the URL at your private host."
        )));
    }
    let url = format!("{}/v1/chat/completions", base_url.trim_end_matches('/'));

    let response = client
        .post(&url)
        .bearer_auth(api_key)
        .json(body)
        .send()
        .await?; // reqwest::Error → AppError::Upstream via #[from]

    let status = response.status().as_u16();
    let body: Value = response.json().await?;
    Ok(UpstreamResponse { status, body })
}

/// Streaming variant of `forward`. The request body must already carry
/// `stream: true`. The upstream's `text/event-stream` bytes pass through to
/// the caller verbatim — OpenAI / Groq / xAI all emit OpenAI-spec
/// `data: {...}\n\n` chunks and the terminating `data: [DONE]\n\n` sentinel.
#[tracing::instrument(skip_all)]
pub async fn forward_stream(
    client: &Client,
    base_url: &str,
    api_key: &str,
    body: &Value,
) -> Result<UpstreamStreamResponse, AppError> {
    if let Some(host) = detect_misconfigured_host(base_url) {
        return Err(AppError::BadRequest(format!(
            "OpenAI adapter pointed at `{base_url}`, which is `{host}` — that host does not speak the OpenAI /v1/chat/completions shape. \
            Use the matching prefix (e.g. `anthropic/<model>`) in your policy file and set `CASCADIA_ANTHROPIC_BASE_URL` instead. \
            For private OpenAI-compatible endpoints (vLLM, Together, DeepInfra), this check is bypassed — point the URL at your private host."
        )));
    }
    let url = format!("{}/v1/chat/completions", base_url.trim_end_matches('/'));

    let response = client
        .post(&url)
        .bearer_auth(api_key)
        .json(body)
        .send()
        .await?;

    let status = response.status().as_u16();
    // Map reqwest's stream error type into AppError so the body_stream type
    // is uniform across providers and the handler can box it once.
    let body_stream = response.bytes_stream().map_err(AppError::Upstream);
    Ok(UpstreamStreamResponse {
        status,
        body_stream: Box::pin(body_stream),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detect_misconfigured_anthropic() {
        assert_eq!(
            detect_misconfigured_host("https://api.anthropic.com"),
            Some("api.anthropic.com")
        );
    }

    #[test]
    fn detect_misconfigured_gemini() {
        assert_eq!(
            detect_misconfigured_host("https://generativelanguage.googleapis.com/v1"),
            Some("generativelanguage.googleapis.com")
        );
    }

    #[test]
    fn legitimate_openai_passes() {
        assert_eq!(detect_misconfigured_host("https://api.openai.com"), None);
    }

    #[test]
    fn legitimate_vllm_passes() {
        assert_eq!(
            detect_misconfigured_host("http://vllm.internal.corp:8000"),
            None
        );
    }

    #[test]
    fn legitimate_groq_passes() {
        assert_eq!(
            detect_misconfigured_host("https://api.groq.com/openai"),
            None
        );
    }
}
