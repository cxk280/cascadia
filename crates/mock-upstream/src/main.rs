//! `cascadia-mock-upstream` — tiny axum server that returns a fixed
//! OpenAI-shaped chat-completion response in O(microseconds).
//!
//! Used by the bench scripts to measure Cascadia proxy overhead without
//! polluting the measurement with real provider latency. Point the proxy at it:
//!
//!   CASCADIA_OPENAI_API_KEY=anything \
//!   CASCADIA_OPENAI_BASE_URL=http://127.0.0.1:18081 \
//!   cascadia-proxy
//!
//! The mock varies its response based on the last user message so that the
//! Phase-2 cascade exercises both paths:
//!
//! - prompt contains "uncertain" → hedge-heavy response (cheap-tier
//!   confidence stays below threshold → proxy escalates).
//! - prompt contains "long" → padded medium-length response.
//! - otherwise → terse confident response (cheap-tier confidence above
//!   threshold → proxy returns cheap without escalation).

use std::net::SocketAddr;

use axum::body::Body;
use axum::http::header::CONTENT_TYPE;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use axum::{Json, Router};
use bytes::Bytes;
use serde_json::{json, Value};
use tokio::net::TcpListener;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt().with_target(false).init();

    let addr: SocketAddr = std::env::var("CASCADIA_MOCK_LISTEN_ADDR")
        .unwrap_or_else(|_| "127.0.0.1:18081".to_string())
        .parse()?;

    let app = Router::new().route("/v1/chat/completions", post(chat));

    tracing::info!(%addr, "cascadia-mock-upstream listening");
    let listener = TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}

async fn chat(Json(req): Json<Value>) -> Response {
    let stream = req.get("stream").and_then(Value::as_bool).unwrap_or(false);
    if stream {
        return stream_chat(&req);
    }
    Json(chat_body(&req)).into_response()
}

fn chat_body(req: &Value) -> Value {
    let model = req
        .get("model")
        .and_then(Value::as_str)
        .unwrap_or("mock-model")
        .to_string();

    let user_text = last_user_message_text(req).to_lowercase();
    let (content, completion_tokens) = if user_text.contains("uncertain") {
        // Hedge-heavy → low cheap-tier confidence.
        (
            "I'm not sure — it could be one of several things. \
             As far as I know, the answer depends on more context, \
             and I don't know enough to commit.",
            32,
        )
    } else if user_text.contains("long") {
        (
            "The answer is approximately 42. Based on the data, this holds with \
             confidence above 95%. There are some edge cases worth noting, but \
             they do not materially change the conclusion.",
            44,
        )
    } else {
        ("Yes.", 1)
    };

    json!({
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": content,
            },
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": user_text.split_whitespace().count() as u32,
            "completion_tokens": completion_tokens,
            "total_tokens": completion_tokens + user_text.split_whitespace().count() as u32,
        }
    })
}

/// Stream the same response as `chat_body` but emit it as OpenAI-shape
/// `chat.completion.chunk` SSE events. Splits the content into 3 word-groups
/// so the proxy sees more than one delta in the wire.
fn stream_chat(req: &Value) -> Response {
    let body = chat_body(req);
    let id = body["id"].as_str().unwrap_or("chatcmpl-mock").to_string();
    let model = body["model"].as_str().unwrap_or("mock-model").to_string();
    let content = body["choices"][0]["message"]["content"]
        .as_str()
        .unwrap_or("")
        .to_string();

    // 3 roughly-equal chunks so streaming clients see progressive delivery.
    let chunks = split_into_chunks(&content, 3);

    let mut events: Vec<Bytes> = Vec::new();
    // Role chunk first.
    let role_chunk = json!({
        "id": id,
        "object": "chat.completion.chunk",
        "created": 0,
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant"},
            "finish_reason": Value::Null
        }]
    });
    events.push(Bytes::from(format!("data: {role_chunk}\n\n")));
    for piece in chunks {
        if piece.is_empty() {
            continue;
        }
        let c = json!({
            "id": id,
            "object": "chat.completion.chunk",
            "created": 0,
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {"content": piece},
                "finish_reason": Value::Null
            }]
        });
        events.push(Bytes::from(format!("data: {c}\n\n")));
    }
    let final_chunk = json!({
        "id": id,
        "object": "chat.completion.chunk",
        "created": 0,
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop"
        }]
    });
    events.push(Bytes::from(format!("data: {final_chunk}\n\n")));
    events.push(Bytes::from_static(b"data: [DONE]\n\n"));

    let stream =
        futures_util::stream::iter(events.into_iter().map(Ok::<Bytes, std::io::Error>));
    Response::builder()
        .status(StatusCode::OK)
        .header(CONTENT_TYPE, "text/event-stream")
        .header("cache-control", "no-cache")
        .body(Body::from_stream(stream))
        .unwrap()
}

fn split_into_chunks(s: &str, n: usize) -> Vec<String> {
    if s.is_empty() || n == 0 {
        return vec![s.to_string()];
    }
    let chars: Vec<char> = s.chars().collect();
    let chunk_size = chars.len().div_ceil(n);
    let mut out: Vec<String> = Vec::new();
    for i in 0..n {
        let start = i * chunk_size;
        if start >= chars.len() {
            break;
        }
        let end = ((i + 1) * chunk_size).min(chars.len());
        out.push(chars[start..end].iter().collect());
    }
    out
}

fn last_user_message_text(req: &Value) -> String {
    let Some(messages) = req.get("messages").and_then(Value::as_array) else {
        return String::new();
    };
    for message in messages.iter().rev() {
        if message.get("role").and_then(Value::as_str) != Some("user") {
            continue;
        }
        if let Some(text) = message.get("content").and_then(Value::as_str) {
            return text.to_string();
        }
    }
    String::new()
}
