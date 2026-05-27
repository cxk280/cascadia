//! 404 + 405 fallbacks. Every error response the proxy emits should match
//! OpenAI's `{error: {message, type, param, code}}` envelope so SDK
//! consumers never see an empty body or a raw parser dump.

use axum::extract::Request;
use axum::http::Method;
use axum::response::{IntoResponse, Response};

use crate::error::AppError;

pub async fn not_found(req: Request) -> Response {
    let path = req.uri().path();
    let method = req.method();
    // Special-case the two legacy OpenAI endpoints that the README explicitly
    // calls out as unsupported. A consultant pointing a 2023-vintage codebase
    // at this proxy will see a JSON envelope with the actual remediation
    // instead of a content-free 404.
    if path == "/v1/completions" {
        return AppError::NotFound(
            "POST /v1/completions (legacy OpenAI Completions API) is not supported. \
             Migrate to POST /v1/chat/completions with \
             `messages=[{\"role\":\"user\",\"content\":\"...\"}]`.",
        )
        .into_response();
    }
    if path == "/v1/embeddings" {
        return AppError::NotFound(
            "POST /v1/embeddings is not implemented. Cascadia is a chat-completion \
             cascade router, not an embeddings proxy. Route embeddings traffic to \
             the provider directly.",
        )
        .into_response();
    }
    // axum's fallback fires for both unknown paths and unknown methods on
    // known paths (when MethodRouter doesn't carve out an alternative). The
    // README lists POST /v1/chat/completions + the GET probe endpoints; if
    // the caller hit something else, hint at the right surface.
    let suffix = if *method != Method::GET && *method != Method::POST {
        " (the proxy only handles POST /v1/chat/completions and GET on the probe / metrics / policy endpoints)"
    } else {
        ""
    };
    let _ = suffix; // currently unused but kept for the next iter's polish
    AppError::NotFound(
        "endpoint not found. Cascadia exposes POST /v1/chat/completions plus \
         GET /livez, /readyz, /health, /metrics, /policy.",
    )
    .into_response()
}

pub async fn method_not_allowed_chat() -> Response {
    AppError::MethodNotAllowed(
        "method not allowed on /v1/chat/completions; only POST is supported. \
         OpenAI's chat-completions API is a POST endpoint.",
    )
    .into_response()
}
