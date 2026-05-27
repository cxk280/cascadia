//! Error type returned from HTTP handlers.
//!
//! Response envelope matches OpenAI's error shape so SDK consumers can rely
//! on standard error handling patterns (`error.type == "invalid_request_error"`).

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::json;
use thiserror::Error;

/// Errors that can occur while handling a request. Each variant maps to an
/// HTTP status code so the client gets something useful instead of a 500.
#[derive(Error, Debug)]
pub enum AppError {
    #[error("upstream provider error: {0}")]
    Upstream(#[from] reqwest::Error),

    #[error("upstream returned non-success status {status}: {body}")]
    UpstreamStatus { status: u16, body: String },

    #[error("bad request: {0}")]
    BadRequest(String),

    #[error("unauthorized: {0}")]
    Unauthorized(&'static str),

    #[error("method not allowed: {0}")]
    MethodNotAllowed(&'static str),

    #[error("upstream provider not configured: {0}")]
    ProviderUnconfigured(&'static str),

    #[error("not found: {0}")]
    NotFound(&'static str),

    #[error("internal error: {0}")]
    Internal(#[from] anyhow::Error),
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        // Map each error to (HTTP status, OpenAI-shape `type` string, our
        // internal `code` string). The envelope below mirrors OpenAI's error
        // response: `error.{type, message, param, code}` — `param` is null
        // for the top-level errors we emit; per-field validation errors
        // would populate it.
        let (status, error_type, code) = match &self {
            AppError::BadRequest(_) => (
                StatusCode::BAD_REQUEST,
                "invalid_request_error",
                "bad_request",
            ),
            AppError::Unauthorized(_) => (
                StatusCode::UNAUTHORIZED,
                "authentication_error",
                "unauthorized",
            ),
            AppError::MethodNotAllowed(_) => (
                StatusCode::METHOD_NOT_ALLOWED,
                "invalid_request_error",
                "method_not_allowed",
            ),
            AppError::ProviderUnconfigured(_) => (
                StatusCode::SERVICE_UNAVAILABLE,
                "service_unavailable",
                "provider_unconfigured",
            ),
            AppError::UpstreamStatus { status, .. } => (
                StatusCode::from_u16(*status).unwrap_or(StatusCode::BAD_GATEWAY),
                "upstream_error",
                "upstream_status",
            ),
            AppError::Upstream(_) => (StatusCode::BAD_GATEWAY, "upstream_error", "upstream_error"),
            AppError::NotFound(_) => (StatusCode::NOT_FOUND, "invalid_request_error", "not_found"),
            AppError::Internal(_) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "internal_error",
                "internal_error",
            ),
        };

        tracing::warn!(error = %self, status = status.as_u16(), code, "request failed");

        let body = Json(json!({
            "error": {
                "message": self.to_string(),
                "type": error_type,
                "param": serde_json::Value::Null,
                "code": code,
            }
        }));
        (status, body).into_response()
    }
}
