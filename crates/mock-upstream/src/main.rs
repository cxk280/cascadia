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
//!
//! It also doubles as a **keyless judge** for the `npx cascadia demo` stack: a
//! request whose system prompt is the pairwise-judge rubric (or whose user
//! message carries `<response_a>` tags) gets a single-line JSON verdict
//! `{"score","confidence","rationale"}` instead of prose — exactly what the
//! judge-worker's parser expects. The score is a deterministic function of the
//! cheap response (hedging markers + a content hash) so the Pareto/quality view
//! is non-degenerate across clusters without any API keys or cost.

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

    // Judge requests get a JSON verdict, not prose (keyless-demo path). The
    // judge COMPARES the two responses, so the score survives the position-swap
    // fold (an A-only score would cancel to 0.5 when A and B are identical).
    if is_judge_request(req) {
        let user = last_user_message_text(req);
        let resp_a = extract_tag(&user, "response_a").unwrap_or_default();
        let resp_b = extract_tag(&user, "response_b").unwrap_or_default();
        let score = mock_judge_score(&resp_a, &resp_b);
        let verdict = json!({
            "score": score,
            "confidence": 0.8,
            "rationale": "mock-judge"
        })
        .to_string();
        let toks = verdict.split_whitespace().count() as u32;
        return completion_body(&model, &verdict, toks);
    }

    let user_text = last_user_message_text(req).to_lowercase();
    // The two tiers answer DIFFERENTLY so the judge has a real gap to score —
    // otherwise identical cheap/expensive content folds to a 0.5 tie under the
    // position-swapped judge and no cluster ever tunes. `mock-expensive` always
    // gives a solid answer; `mock-cheap` gives the prompt-shaped one (which
    // hedges on "uncertain"). The cluster (a hash of the prompt) therefore has a
    // characteristic cheap-vs-expensive gap → a mean score off 0.5 → tuning.
    let expensive = model.contains("expensive");
    let (content, completion_tokens) = mock_answer(&user_text, expensive);
    completion_body(&model, content, completion_tokens)
}

/// The tier-dependent answer. Expensive is consistently solid; cheap is terse
/// (and good enough) on easy prompts but hedges on "uncertain" ones.
fn mock_answer(user_text: &str, expensive: bool) -> (&'static str, u32) {
    if user_text.contains("uncertain") {
        if expensive {
            // Confident + complete → clearly better than the cheap hedge.
            (
                "Yes — concretely, it proceeds in three well-defined steps and the \
                 result is deterministic; here is exactly how and why.",
                24,
            )
        } else {
            // Hedge-heavy → the judge marks the cheap tier down here.
            (
                "I'm not sure — it could be one of several things. \
                 As far as I know, the answer depends on more context, \
                 and I don't know enough to commit.",
                32,
            )
        }
    } else if user_text.contains("long") {
        (
            "The answer is approximately 42. Based on the data, this holds with \
             confidence above 95%. There are some edge cases worth noting, but \
             they do not materially change the conclusion.",
            44,
        )
    } else if expensive {
        // Verbose-but-correct; a discerning judge prefers the cheap tier's
        // crisp answer to a simple question, so cheap "wins" → threshold drops.
        (
            "Yes, that is correct; to elaborate at some length, the affirmative \
             holds in essentially all standard cases and is well established.",
            26,
        )
    } else {
        ("Yes.", 1)
    }
}

/// Build an OpenAI-shaped non-streaming chat completion around `content`.
fn completion_body(model: &str, content: &str, completion_tokens: u32) -> Value {
    let prompt_tokens = content.split_whitespace().count() as u32;
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
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": completion_tokens + prompt_tokens,
        }
    })
}

/// True iff this looks like a pairwise-judge scoring request — either the
/// system prompt is the judge rubric, or the user message carries the
/// `<response_a>`/`<response_b>` envelope the judge templates emit.
fn is_judge_request(req: &Value) -> bool {
    let sys = system_message_text(req).to_lowercase();
    if sys.contains("impartial evaluator") || sys.contains("evaluator comparing") {
        return true;
    }
    last_user_message_text(req).contains("<response_a")
}

/// A keyless stand-in for an LLM judge's score: the probability that response A
/// is at least as good as response B. It COMPARES the two (not just A) so that
/// the position-swapped sibling judge — which sends B as A and inverts — folds
/// to the same verdict instead of cancelling to 0.5. Deterministic.
fn mock_judge_score(resp_a: &str, resp_b: &str) -> f64 {
    let ha = hedges(resp_a);
    let hb = hedges(resp_b);
    let base = if ha && !hb {
        0.22 // A hedged, B didn't → B clearly better
    } else if hb && !ha {
        0.78 // B hedged, A didn't → A clearly better
    } else if ha && hb {
        0.50 // both hedged → tie
    } else if resp_a.len() + 2 < resp_b.len() {
        0.70 // neither hedged; A is crisper → A preferred
    } else if resp_b.len() + 2 < resp_a.len() {
        0.40 // neither hedged; B is crisper → B preferred
    } else {
        0.55 // near-identical → slight tie-break
    };
    // Small deterministic ±0.05 jitter so identical-shape pairs aren't all
    // pinned to one value (keeps the Pareto cloud from collapsing to points).
    let jitter = (djb2(resp_a) % 11) as f64 - 5.0;
    (base + jitter / 100.0).clamp(0.02, 0.98)
}

/// Whether a response hedges — the signal the cheap tier emits on "uncertain"
/// prompts. Matches the phrases `mock_answer` produces.
fn hedges(s: &str) -> bool {
    let lc = s.to_lowercase();
    lc.contains("not sure")
        || lc.contains("don't know")
        || lc.contains("depends")
        || lc.contains("as far as i know")
}

/// Tiny stable string hash (djb2). Avoids a dependency and `Math.random`-style
/// nondeterminism — same input always yields the same verdict.
fn djb2(s: &str) -> u64 {
    let mut h: u64 = 5381;
    for b in s.bytes() {
        h = h.wrapping_mul(33).wrapping_add(b as u64);
    }
    h
}

/// Extract the inner text of the first `<tag ...>…</tag>` in `s`, if present.
fn extract_tag(s: &str, tag: &str) -> Option<String> {
    let open = format!("<{tag}");
    let start = s.find(&open)?;
    let after_open = s[start..].find('>')? + start + 1;
    let close = format!("</{tag}>");
    let end = s[after_open..].find(&close)? + after_open;
    Some(s[after_open..end].trim().to_string())
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

    let stream = futures_util::stream::iter(events.into_iter().map(Ok::<Bytes, std::io::Error>));
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
    message_text(req, "user")
}

fn system_message_text(req: &Value) -> String {
    message_text(req, "system")
}

fn message_text(req: &Value, role: &str) -> String {
    let Some(messages) = req.get("messages").and_then(Value::as_array) else {
        return String::new();
    };
    for message in messages.iter().rev() {
        if message.get("role").and_then(Value::as_str) != Some(role) {
            continue;
        }
        if let Some(text) = message.get("content").and_then(Value::as_str) {
            return text.to_string();
        }
    }
    String::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn judge_req(resp_a: &str, resp_b: &str) -> Value {
        json!({
            "model": "mock-judge",
            "messages": [
                {"role": "system", "content": "You are a strict, impartial evaluator comparing two AI responses to the same prompt."},
                {"role": "user", "content": format!(
                    "<prompt>q</prompt>\n<response_a model=\"openai/mock-cheap\">{resp_a}</response_a>\n<response_b model=\"openai/mock-expensive\">{resp_b}</response_b>"
                )}
            ]
        })
    }

    #[test]
    fn judge_request_returns_parseable_verdict() {
        let req = judge_req("Yes.", "Yes, to elaborate at length, that is correct.");
        assert!(is_judge_request(&req));
        let body = chat_body(&req);
        let content = body["choices"][0]["message"]["content"].as_str().unwrap();
        let v: Value = serde_json::from_str(content).expect("verdict must be a JSON object");
        let score = v["score"].as_f64().unwrap();
        assert!((0.0..=1.0).contains(&score), "score in range: {score}");
        assert!(v["confidence"].as_f64().unwrap() >= 0.0);
        assert!(v["rationale"].is_string());
    }

    #[test]
    fn normal_request_is_not_a_judge_request() {
        let req = json!({"model": "openai/mock-cheap", "messages": [{"role": "user", "content": "hello"}]});
        assert!(!is_judge_request(&req));
        let body = chat_body(&req);
        assert_eq!(body["choices"][0]["message"]["content"], "Yes.");
    }

    #[test]
    fn tiers_answer_differently_so_the_judge_has_a_gap() {
        let cheap = chat_body(&json!({"model": "openai/mock-cheap",
            "messages": [{"role": "user", "content": "I'm uncertain about X"}]}));
        let exp = chat_body(&json!({"model": "openai/mock-expensive",
            "messages": [{"role": "user", "content": "I'm uncertain about X"}]}));
        let c = cheap["choices"][0]["message"]["content"].as_str().unwrap();
        let e = exp["choices"][0]["message"]["content"].as_str().unwrap();
        assert_ne!(c, e, "cheap and expensive must differ");
        assert!(hedges(c), "cheap hedges on 'uncertain'");
        assert!(!hedges(e), "expensive does not hedge");
    }

    #[test]
    fn judge_prefers_non_hedging_response() {
        // A hedges, B doesn't → A is worse → score well below 0.5.
        let a_worse = mock_judge_score("I'm not sure, it depends.", "Yes, definitely.");
        // Swapped roles → A is better → score well above 0.5 (and the swapped
        // sibling judge inverts this, so the fold agrees).
        let a_better = mock_judge_score("Yes, definitely.", "I'm not sure, it depends.");
        assert!(a_worse < 0.45, "hedged A scores low: {a_worse}");
        assert!(a_better > 0.55, "non-hedged A scores high: {a_better}");
    }

    #[test]
    fn judge_prefers_crisp_answer_when_neither_hedges() {
        // Easy question: terse cheap answer beats a verbose expensive one.
        let crisp_a = mock_judge_score("Yes.", "Yes, to elaborate at considerable length, indeed.");
        assert!(crisp_a > 0.55, "crisp A preferred: {crisp_a}");
    }

    #[test]
    fn extract_tag_pulls_inner_text() {
        let s = "<response_a model=\"x\">hello there</response_a>";
        assert_eq!(extract_tag(s, "response_a").as_deref(), Some("hello there"));
        assert_eq!(extract_tag(s, "response_b"), None);
    }
}
