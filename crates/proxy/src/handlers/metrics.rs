//! Prometheus exposition endpoint.

use axum::extract::State;
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};

use crate::state::AppState;

pub async fn metrics(State(state): State<AppState>) -> Response {
    match state.metrics().render() {
        Ok(body) => (
            StatusCode::OK,
            [(
                header::CONTENT_TYPE,
                HeaderValue::from_static("text/plain; version=0.0.4"),
            )],
            body,
        )
            .into_response(),
        Err(err) => {
            tracing::error!(?err, "rendering Prometheus metrics");
            (StatusCode::INTERNAL_SERVER_ERROR, "metrics render failed").into_response()
        }
    }
}
