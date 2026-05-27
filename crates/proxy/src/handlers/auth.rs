//! Bearer-token auth middleware for the `/v1/*` routes.
//!
//! When `CASCADIA_PROXY_BEARER_TOKEN` is set, requests to `/v1/*` must carry
//! `Authorization: Bearer <token>` matching exactly. When unset, all requests
//! pass — appropriate for private-network deployments where the cluster
//! boundary handles auth.
//!
//! The error envelope matches OpenAI's `authentication_error` shape so SDK
//! consumers' error handling (`error.type == "authentication_error"`) works
//! unmodified.

use axum::extract::{Request, State};
use axum::http::header::AUTHORIZATION;
use axum::middleware::Next;
use axum::response::Response;
use subtle::ConstantTimeEq;

use crate::error::AppError;
use crate::state::AppState;

pub async fn require_bearer(
    State(state): State<AppState>,
    req: Request,
    next: Next,
) -> Result<Response, AppError> {
    let Some(expected) = state.config().proxy_bearer_token.as_deref() else {
        // No token configured → no enforcement. Local-dev / private-network
        // operators get the previous behavior.
        return Ok(next.run(req).await);
    };

    let Some(header) = req
        .headers()
        .get(AUTHORIZATION)
        .and_then(|h| h.to_str().ok())
    else {
        return Err(AppError::Unauthorized(
            "missing Authorization header; send `Authorization: Bearer <token>`",
        ));
    };

    let provided = match header.strip_prefix("Bearer ") {
        Some(p) => p,
        None => {
            return Err(AppError::Unauthorized(
                "Authorization header must be `Bearer <token>`",
            ))
        }
    };

    // Constant-time content compare: no byte-by-byte early exit, so a vanilla
    // `==`'s timing oracle for guessing the token byte-by-byte is closed.
    // (Note `ct_eq` on slices still short-circuits on a length mismatch, so
    // the token *length* is not hidden — acceptable for a fixed shared secret.)
    if provided.as_bytes().ct_eq(expected.as_bytes()).unwrap_u8() != 1 {
        return Err(AppError::Unauthorized("invalid bearer token"));
    }

    Ok(next.run(req).await)
}
