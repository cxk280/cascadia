//! Anthropic Messages API adapter.
//!
//! Translates OpenAI's ChatCompletion request shape ↔ Anthropic's `/v1/messages`
//! API, including Phase 7.1 tool-use parity. The proxy speaks OpenAI to its
//! callers; this module is the only place that knows Anthropic's wire shape.
//!
//! Key shape differences:
//!
//! - Anthropic requires `max_tokens`; OpenAI doesn't. We default to 4096 if
//!   the caller didn't specify one.
//! - System prompts are a top-level `system: String` on Anthropic, not a
//!   message with `role: "system"`. We concatenate any system messages with
//!   `\n\n` and lift them out.
//! - OpenAI's `role: "tool"` messages with `tool_call_id` become content
//!   blocks of type `tool_result` inside an adjacent `role: "user"` message
//!   on Anthropic.
//! - OpenAI's `assistant.tool_calls` (array of `{id, type, function:{name,arguments}}`)
//!   become content blocks of type `tool_use` (with `input: object` instead
//!   of `arguments: string`).
//! - `tool_choice` mapping: `auto`→`auto`, `none`→omit (no tools), `required`
//!   →`any`, `{function:{name}}`→`{type:"tool", name}`.
//! - Response: Anthropic returns `content: [{type: "text"|"tool_use", ...}]`;
//!   we coalesce text blocks into `message.content` (string) and tool_use
//!   blocks into `message.tool_calls` (OpenAI shape).

use std::collections::HashMap;

use bytes::Bytes;
use futures_util::StreamExt;
use reqwest::Client;
use serde_json::{json, Map, Value};

use crate::error::AppError;
use crate::upstream::{UpstreamResponse, UpstreamStreamResponse};

const DEFAULT_MAX_TOKENS: u64 = 4096;
const API_VERSION: &str = "2023-06-01";

#[tracing::instrument(skip_all)]
pub async fn forward(
    client: &Client,
    base_url: &str,
    api_key: &str,
    body: &Value,
) -> Result<UpstreamResponse, AppError> {
    let url = format!("{}/v1/messages", base_url.trim_end_matches('/'));
    let anthropic_body = translate_request_checked(body)?;

    let response = client
        .post(&url)
        .header("x-api-key", api_key)
        .header("anthropic-version", API_VERSION)
        .json(&anthropic_body)
        .send()
        .await?;

    let status = response.status().as_u16();
    let anthropic_resp: Value = response.json().await?;

    // Non-success: leave Anthropic's error shape intact so the caller can
    // log it. Success: translate to OpenAI shape so downstream code (cascade
    // confidence extraction, response forwarding) sees a uniform schema.
    let openai_body = if (200..300).contains(&status) {
        translate_response(&anthropic_resp, body)
    } else {
        anthropic_resp
    };
    Ok(UpstreamResponse { status, body: openai_body })
}

// =========================================================================
// Streaming variant: translates Anthropic's typed event stream into
// OpenAI-shape `chat.completion.chunk` SSE events.
// =========================================================================

/// Send a streaming `/v1/messages` request and return an SSE byte stream
/// already translated to OpenAI's `chat.completion.chunk` shape. The caller
/// passes a request that has been forced to `stream: true`; we translate it
/// into Anthropic's request shape via the existing `translate_request()`
/// helper.
#[tracing::instrument(skip_all)]
pub async fn forward_stream(
    client: &Client,
    base_url: &str,
    api_key: &str,
    body: &Value,
) -> Result<UpstreamStreamResponse, AppError> {
    let url = format!("{}/v1/messages", base_url.trim_end_matches('/'));
    let mut anthropic_body = translate_request_checked(body)?;
    // Anthropic uses the same `stream: true` toggle as OpenAI; translate_request
    // doesn't pass `stream` through (we strip it from the OpenAI body shape),
    // so set it explicitly here.
    anthropic_body["stream"] = json!(true);

    let original_model = body
        .get("model")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();

    let response = client
        .post(&url)
        .header("x-api-key", api_key)
        .header("anthropic-version", API_VERSION)
        .json(&anthropic_body)
        .send()
        .await?;

    let status = response.status().as_u16();

    // Non-success: drain the body as a single JSON blob and emit it as one
    // OpenAI-shape error chunk so the client sees something parseable. We
    // still surface the upstream status so the handler can pick a matching
    // HTTP status code.
    if !(200..300).contains(&status) {
        let err_body: Value = response.json().await.unwrap_or(Value::Null);
        let chunk = json!({
            "error": err_body,
        });
        let line = format!("data: {}\n\n", chunk);
        let stream = futures_util::stream::iter(vec![Ok(Bytes::from(line))]);
        return Ok(UpstreamStreamResponse {
            status,
            body_stream: Box::pin(stream),
        });
    }

    // Spawn a translator task. It reads Anthropic SSE events, runs them
    // through the translator state machine, and pushes OpenAI-shape SSE
    // chunks into a bounded mpsc. The returned stream wraps the receiver.
    let (tx, mut rx) = tokio::sync::mpsc::channel::<Result<Bytes, AppError>>(32);
    let mut byte_stream = response.bytes_stream();
    tokio::spawn(async move {
        // A single Anthropic SSE event is small (one token delta). Cap the
        // unframed buffer so a misbehaving/hostile upstream that streams a
        // large or infinite body containing no `\n\n` frame boundary can't
        // grow this buffer without bound and OOM the proxy (which would take
        // down every tenant, not just this stream).
        const MAX_STREAM_BUFFER: usize = 1024 * 1024;
        let mut translator = AnthropicStreamTranslator::new(original_model);
        let mut buffer: Vec<u8> = Vec::with_capacity(4096);

        while let Some(item) = byte_stream.next().await {
            match item {
                Ok(chunk) => {
                    buffer.extend_from_slice(&chunk);
                    // Anthropic frames events with `\n\n`. Process all complete
                    // events; leave any trailing partial event in the buffer.
                    while let Some(end) = find_double_newline(&buffer) {
                        let raw = buffer.drain(..end + 2).collect::<Vec<u8>>();
                        let block = match std::str::from_utf8(&raw) {
                            Ok(s) => s.to_string(),
                            Err(e) => {
                                let _ = tx
                                    .send(Err(AppError::Internal(anyhow::anyhow!(
                                        "anthropic stream: invalid utf8: {e}"
                                    ))))
                                    .await;
                                return;
                            }
                        };
                        for chunk_json in translator.process_event_block(&block) {
                            let line = format!("data: {}\n\n", chunk_json);
                            if tx.send(Ok(Bytes::from(line))).await.is_err() {
                                return; // receiver dropped
                            }
                        }
                        if translator.is_done() {
                            let _ = tx
                                .send(Ok(Bytes::from_static(b"data: [DONE]\n\n")))
                                .await;
                            return;
                        }
                    }
                    if buffer.len() > MAX_STREAM_BUFFER {
                        let _ = tx
                            .send(Err(AppError::Internal(anyhow::anyhow!(
                                "anthropic stream: unframed event exceeded {MAX_STREAM_BUFFER} bytes"
                            ))))
                            .await;
                        return;
                    }
                }
                Err(e) => {
                    let _ = tx.send(Err(AppError::Upstream(e))).await;
                    return;
                }
            }
        }
        // Upstream closed cleanly without an explicit message_stop — emit
        // the terminator so the OpenAI client doesn't hang.
        if !translator.terminated {
            let _ = tx
                .send(Ok(Bytes::from_static(b"data: [DONE]\n\n")))
                .await;
        }
    });

    let stream =
        futures_util::stream::poll_fn(move |cx| rx.poll_recv(cx));
    Ok(UpstreamStreamResponse {
        status,
        body_stream: Box::pin(stream),
    })
}

fn find_double_newline(buf: &[u8]) -> Option<usize> {
    buf.windows(2).position(|w| w == b"\n\n")
}

/// State carried across Anthropic stream events to drive the translation.
/// Anthropic emits `content_block_start`/`content_block_delta` referenced by
/// per-block index; OpenAI's `tool_calls` array is indexed independently.
/// This struct maintains the mapping plus the message id/model captured at
/// `message_start`.
struct AnthropicStreamTranslator {
    id: String,
    model: String,
    created: i64,
    sent_role: bool,
    blocks: HashMap<u64, BlockMeta>,
    next_tool_index: usize,
    /// Set once `message_stop` is observed. The driver checks this to emit
    /// the `[DONE]` sentinel and tear down the channel.
    terminated: bool,
}

#[derive(Default)]
struct BlockMeta {
    is_tool_use: bool,
    tool_index: Option<usize>,
}

impl AnthropicStreamTranslator {
    fn new(fallback_model: String) -> Self {
        Self {
            id: String::new(),
            model: fallback_model,
            created: chrono::Utc::now().timestamp(),
            sent_role: false,
            blocks: HashMap::new(),
            next_tool_index: 0,
            terminated: false,
        }
    }

    fn is_done(&self) -> bool {
        self.terminated
    }

    /// Parse one `\n\n`-terminated SSE block and emit zero or more OpenAI
    /// `chat.completion.chunk` JSON values.
    fn process_event_block(&mut self, block: &str) -> Vec<Value> {
        let mut event_type: Option<&str> = None;
        let mut data_lines: Vec<&str> = Vec::new();
        for line in block.lines() {
            if let Some(rest) = line.strip_prefix("event:") {
                event_type = Some(rest.trim());
            } else if let Some(rest) = line.strip_prefix("data:") {
                data_lines.push(rest.trim_start());
            }
            // Other SSE field lines (id:, retry:, comments) are ignored.
        }
        let Some(event_type) = event_type else {
            return Vec::new();
        };
        if data_lines.is_empty() {
            return Vec::new();
        }
        let data_joined = data_lines.join("\n");
        let data: Value = match serde_json::from_str(&data_joined) {
            Ok(v) => v,
            Err(_) => return Vec::new(), // skip malformed events; upstream may emit comments
        };
        self.translate(event_type, &data)
    }

    fn translate(&mut self, event_type: &str, data: &Value) -> Vec<Value> {
        match event_type {
            "message_start" => self.on_message_start(data),
            "content_block_start" => self.on_content_block_start(data),
            "content_block_delta" => self.on_content_block_delta(data),
            "content_block_stop" => Vec::new(),
            "message_delta" => self.on_message_delta(data),
            "message_stop" => {
                self.terminated = true;
                Vec::new()
            }
            "ping" => Vec::new(),
            "error" => {
                // Emit a minimal OpenAI-shape chunk with `finish_reason:
                // "stop"` so the client sees the stream end gracefully; the
                // raw error JSON also rides along for clients that inspect.
                self.terminated = true;
                vec![json!({
                    "id": self.chunk_id(),
                    "object": "chat.completion.chunk",
                    "created": self.created,
                    "model": self.model,
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }],
                    "error": data.get("error").cloned().unwrap_or(Value::Null),
                })]
            }
            _ => Vec::new(),
        }
    }

    fn on_message_start(&mut self, data: &Value) -> Vec<Value> {
        let msg = data.get("message");
        if let Some(id) = msg.and_then(|m| m.get("id")).and_then(Value::as_str) {
            // Anthropic uses `msg_xxx`; OpenAI clients sometimes look for
            // the `chatcmpl-` prefix. Translate so behavior matches the
            // OpenAI shape closely; original ID is preserved minus the
            // `msg_` and re-prefixed.
            let suffix = id.strip_prefix("msg_").unwrap_or(id);
            self.id = format!("chatcmpl-{}", suffix);
        }
        if let Some(model) = msg.and_then(|m| m.get("model")).and_then(Value::as_str) {
            if !model.is_empty() {
                self.model = model.to_string();
            }
        }
        if self.sent_role {
            return Vec::new();
        }
        self.sent_role = true;
        vec![self.role_chunk()]
    }

    fn on_content_block_start(&mut self, data: &Value) -> Vec<Value> {
        let index = data.get("index").and_then(Value::as_u64).unwrap_or(0);
        let block = data.get("content_block");
        let block_type = block
            .and_then(|b| b.get("type"))
            .and_then(Value::as_str)
            .unwrap_or("");
        match block_type {
            "text" => {
                self.blocks.insert(
                    index,
                    BlockMeta {
                        is_tool_use: false,
                        tool_index: None,
                    },
                );
                Vec::new()
            }
            "tool_use" => {
                let tool_index = self.next_tool_index;
                self.next_tool_index += 1;
                self.blocks.insert(
                    index,
                    BlockMeta {
                        is_tool_use: true,
                        tool_index: Some(tool_index),
                    },
                );
                let id = block
                    .and_then(|b| b.get("id"))
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string();
                let name = block
                    .and_then(|b| b.get("name"))
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string();
                vec![self.chunk_with_delta(json!({
                    "tool_calls": [{
                        "index": tool_index,
                        "id": id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": "",
                        }
                    }]
                }))]
            }
            _ => Vec::new(),
        }
    }

    fn on_content_block_delta(&mut self, data: &Value) -> Vec<Value> {
        let index = data.get("index").and_then(Value::as_u64).unwrap_or(0);
        let delta = match data.get("delta") {
            Some(d) => d,
            None => return Vec::new(),
        };
        let delta_type = delta.get("type").and_then(Value::as_str).unwrap_or("");
        match delta_type {
            "text_delta" => {
                let text = delta.get("text").and_then(Value::as_str).unwrap_or("");
                if text.is_empty() {
                    return Vec::new();
                }
                vec![self.chunk_with_delta(json!({ "content": text }))]
            }
            "input_json_delta" => {
                let partial = delta
                    .get("partial_json")
                    .and_then(Value::as_str)
                    .unwrap_or("");
                let tool_index = self
                    .blocks
                    .get(&index)
                    .and_then(|m| m.tool_index)
                    .unwrap_or(0);
                vec![self.chunk_with_delta(json!({
                    "tool_calls": [{
                        "index": tool_index,
                        "function": {
                            "arguments": partial,
                        }
                    }]
                }))]
            }
            _ => Vec::new(),
        }
    }

    fn on_message_delta(&mut self, data: &Value) -> Vec<Value> {
        let stop_reason = data
            .get("delta")
            .and_then(|d| d.get("stop_reason"))
            .and_then(Value::as_str)
            .unwrap_or("");
        let has_tool_calls = self
            .blocks
            .values()
            .any(|m| m.is_tool_use && m.tool_index.is_some());
        let finish = map_stop_reason(stop_reason, has_tool_calls);
        vec![json!({
            "id": self.chunk_id(),
            "object": "chat.completion.chunk",
            "created": self.created,
            "model": self.model,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": finish,
            }],
        })]
    }

    fn chunk_id(&self) -> String {
        if self.id.is_empty() {
            "chatcmpl-stream".to_string()
        } else {
            self.id.clone()
        }
    }

    fn role_chunk(&self) -> Value {
        json!({
            "id": self.chunk_id(),
            "object": "chat.completion.chunk",
            "created": self.created,
            "model": self.model,
            "choices": [{
                "index": 0,
                "delta": { "role": "assistant" },
                "finish_reason": Value::Null,
            }],
        })
    }

    fn chunk_with_delta(&self, delta: Value) -> Value {
        json!({
            "id": self.chunk_id(),
            "object": "chat.completion.chunk",
            "created": self.created,
            "model": self.model,
            "choices": [{
                "index": 0,
                "delta": delta,
                "finish_reason": Value::Null,
            }],
        })
    }
}

// =========================================================================
// Request translation: OpenAI ChatCompletion → Anthropic Messages
// =========================================================================

/// Validate the request and translate. Errors when the caller asks for
/// something Anthropic can't honor (currently: `response_format: {type:
/// "json_schema"}` which has no native Anthropic equivalent — clients should
/// route json_schema traffic through an OpenAI-shape provider).
pub fn translate_request_checked(req: &Value) -> Result<Value, AppError> {
    if let Some(rf) = req.get("response_format") {
        let rf_type = rf.get("type").and_then(Value::as_str).unwrap_or("");
        if rf_type == "json_schema" {
            return Err(AppError::BadRequest(
                "response_format `json_schema` is not supported on the Anthropic adapter. \
                 Anthropic enforces structured output via tool_use, not response_format. \
                 Either route this cluster to an OpenAI-shape provider, or restructure the \
                 request as a `tools=[{...}]` call with `tool_choice` set to your target tool."
                    .to_string(),
            ));
        }
        // `response_format: {"type": "json_object"}` and the legacy `{"type":
        // "text"}` shapes are honored by injecting a system-prompt nudge —
        // Anthropic doesn't have a native JSON mode but reliably emits valid
        // JSON when the system prompt says so. See `translate_request` body
        // for the injection.
    }
    Ok(translate_request(req))
}

pub fn translate_request(req: &Value) -> Value {
    let mut out = Map::new();

    if let Some(model) = req.get("model").and_then(Value::as_str) {
        out.insert("model".to_string(), json!(model));
    }
    out.insert(
        "max_tokens".to_string(),
        req.get("max_tokens").cloned().unwrap_or(json!(DEFAULT_MAX_TOKENS)),
    );

    // OpenAI: messages[]; system messages concatenated → Anthropic system.
    let mut system_parts: Vec<String> = Vec::new();
    let mut messages: Vec<Value> = Vec::new();

    // OpenAI `response_format: {"type": "json_object"}` has no Anthropic
    // wire-level equivalent; Anthropic reliably emits valid JSON when the
    // *system prompt* instructs it to. Inject a directive that joins any
    // existing system messages so the structured-output contract round-
    // trips. `json_schema` was rejected upstream by translate_request_checked.
    if let Some(rf) = req.get("response_format") {
        if rf.get("type").and_then(Value::as_str) == Some("json_object") {
            system_parts.push(
                "Respond with a single valid JSON object. \
                 Do not include any prose, code fences, or commentary outside the JSON."
                    .to_string(),
            );
        }
    }

    if let Some(msg_array) = req.get("messages").and_then(Value::as_array) {
        for msg in msg_array {
            let role = msg.get("role").and_then(Value::as_str).unwrap_or("");
            match role {
                "system" => {
                    if let Some(text) = extract_message_text(msg) {
                        system_parts.push(text);
                    }
                }
                "user" | "assistant" => {
                    messages.push(translate_user_or_assistant_message(role, msg));
                }
                "tool" => {
                    // OpenAI tool result → Anthropic tool_result block on a
                    // user-role message. Merge with the preceding user
                    // message if there is one, otherwise emit a new user.
                    let block = json!({
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id").cloned().unwrap_or(json!("")),
                        "content": extract_message_text(msg).unwrap_or_default(),
                    });
                    merge_into_user_message(&mut messages, block);
                }
                _ => { /* Unknown roles are dropped — Anthropic would 400. */ }
            }
        }
    }

    if !system_parts.is_empty() {
        out.insert("system".to_string(), json!(system_parts.join("\n\n")));
    }
    out.insert("messages".to_string(), Value::Array(messages));

    // Pass-through fields where the semantic matches.
    for key in &["temperature", "top_p", "stop_sequences", "metadata"] {
        if let Some(v) = req.get(*key) {
            out.insert((*key).to_string(), v.clone());
        }
    }
    // OpenAI uses `stop` (string or array); Anthropic uses `stop_sequences` (array).
    if let Some(stop) = req.get("stop") {
        let seqs = match stop {
            Value::String(s) => vec![Value::String(s.clone())],
            Value::Array(arr) => arr.clone(),
            _ => vec![],
        };
        if !seqs.is_empty() {
            out.insert("stop_sequences".to_string(), Value::Array(seqs));
        }
    }

    // Tool-use parity (Phase 7.1).
    if let Some(tools) = req.get("tools").and_then(Value::as_array) {
        let translated: Vec<Value> = tools.iter().map(translate_tool).collect();
        out.insert("tools".to_string(), Value::Array(translated));
    }
    if let Some(choice) = req.get("tool_choice") {
        if let Some(anthropic_choice) = translate_tool_choice(choice) {
            out.insert("tool_choice".to_string(), anthropic_choice);
        }
    }

    Value::Object(out)
}

fn translate_user_or_assistant_message(role: &str, msg: &Value) -> Value {
    // If assistant has tool_calls, build a content array with text + tool_use
    // blocks. Otherwise mirror OpenAI's content shape directly.
    if role == "assistant" {
        if let Some(tool_calls) = msg.get("tool_calls").and_then(Value::as_array) {
            let mut blocks: Vec<Value> = Vec::new();
            if let Some(text) = msg.get("content").and_then(Value::as_str) {
                if !text.is_empty() {
                    blocks.push(json!({ "type": "text", "text": text }));
                }
            }
            for call in tool_calls {
                let id = call.get("id").and_then(Value::as_str).unwrap_or("");
                let name = call
                    .get("function")
                    .and_then(|f| f.get("name"))
                    .and_then(Value::as_str)
                    .unwrap_or("");
                let args_str = call
                    .get("function")
                    .and_then(|f| f.get("arguments"))
                    .and_then(Value::as_str)
                    .unwrap_or("{}");
                let args: Value = serde_json::from_str(args_str).unwrap_or(json!({}));
                blocks.push(json!({
                    "type": "tool_use",
                    "id": id,
                    "name": name,
                    "input": args,
                }));
            }
            return json!({ "role": "assistant", "content": blocks });
        }
    }

    // Plain message: content can be a string or an array of content parts.
    let content = msg.get("content").cloned().unwrap_or(Value::Null);
    json!({ "role": role, "content": content })
}

fn merge_into_user_message(messages: &mut Vec<Value>, block: Value) {
    // If the last entry is a user message, append the tool_result block to
    // its content array. Otherwise emit a new user message containing only
    // this block.
    if let Some(last) = messages.last_mut() {
        if last.get("role").and_then(Value::as_str) == Some("user") {
            let content = last.get_mut("content");
            match content {
                Some(Value::Array(arr)) => {
                    arr.push(block);
                    return;
                }
                Some(Value::String(s)) => {
                    let prior = std::mem::take(s);
                    *content.unwrap() = Value::Array(vec![
                        json!({ "type": "text", "text": prior }),
                        block,
                    ]);
                    return;
                }
                _ => {}
            }
        }
    }
    messages.push(json!({ "role": "user", "content": [block] }));
}

fn translate_tool(t: &Value) -> Value {
    let func = t.get("function").unwrap_or(t);
    let name = func.get("name").cloned().unwrap_or(Value::Null);
    let description = func.get("description").cloned().unwrap_or(Value::Null);
    let parameters = func
        .get("parameters")
        .cloned()
        .unwrap_or(json!({ "type": "object", "properties": {} }));
    json!({
        "name": name,
        "description": description,
        "input_schema": parameters,
    })
}

fn translate_tool_choice(choice: &Value) -> Option<Value> {
    if let Some(s) = choice.as_str() {
        return match s {
            "auto" => Some(json!({ "type": "auto" })),
            "required" => Some(json!({ "type": "any" })),
            "none" => None, // Drop tools entirely on Anthropic's "no tools" path.
            _ => None,
        };
    }
    if let Some(obj) = choice.as_object() {
        if obj.get("type").and_then(Value::as_str) == Some("function") {
            let name = obj
                .get("function")
                .and_then(|f| f.get("name"))
                .cloned()
                .unwrap_or(Value::Null);
            return Some(json!({ "type": "tool", "name": name }));
        }
    }
    None
}

fn extract_message_text(msg: &Value) -> Option<String> {
    let content = msg.get("content")?;
    if let Some(s) = content.as_str() {
        return Some(s.to_string());
    }
    if let Some(arr) = content.as_array() {
        let joined: String = arr
            .iter()
            .filter_map(|p| p.get("text").and_then(Value::as_str))
            .collect::<Vec<_>>()
            .join("\n");
        if !joined.is_empty() {
            return Some(joined);
        }
    }
    None
}

// =========================================================================
// Response translation: Anthropic Messages → OpenAI ChatCompletion
// =========================================================================

pub fn translate_response(anthropic: &Value, original_req: &Value) -> Value {
    let id = anthropic
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let model = anthropic
        .get("model")
        .and_then(Value::as_str)
        .or_else(|| original_req.get("model").and_then(Value::as_str))
        .unwrap_or("")
        .to_string();

    let (text, tool_calls) = collect_content_blocks(anthropic.get("content"));
    let finish_reason = map_stop_reason(
        anthropic.get("stop_reason").and_then(Value::as_str).unwrap_or(""),
        !tool_calls.is_empty(),
    );

    let mut message = Map::new();
    message.insert("role".to_string(), json!("assistant"));
    message.insert("content".to_string(), if text.is_empty() && !tool_calls.is_empty() {
        Value::Null
    } else {
        json!(text)
    });
    if !tool_calls.is_empty() {
        message.insert("tool_calls".to_string(), Value::Array(tool_calls));
    }

    let usage = anthropic.get("usage").cloned().unwrap_or(json!({}));
    let prompt_tokens = usage.get("input_tokens").and_then(Value::as_u64).unwrap_or(0);
    let completion_tokens = usage.get("output_tokens").and_then(Value::as_u64).unwrap_or(0);

    json!({
        "id": id,
        "object": "chat.completion",
        "created": chrono::Utc::now().timestamp(),
        "model": model,
        "choices": [{
            "index": 0,
            "message": Value::Object(message),
            "finish_reason": finish_reason,
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            // saturating_add: in release builds `u64 + u64` wraps silently on
            // an absurd upstream-controlled token count; in debug it panics.
            "total_tokens": prompt_tokens.saturating_add(completion_tokens),
        }
    })
}

fn collect_content_blocks(content: Option<&Value>) -> (String, Vec<Value>) {
    let mut text_parts: Vec<String> = Vec::new();
    let mut tool_calls: Vec<Value> = Vec::new();
    let Some(arr) = content.and_then(Value::as_array) else {
        // Anthropic content is always an array; if it's missing, return empty.
        return (String::new(), tool_calls);
    };
    for block in arr {
        let block_type = block.get("type").and_then(Value::as_str).unwrap_or("");
        match block_type {
            "text" => {
                if let Some(t) = block.get("text").and_then(Value::as_str) {
                    text_parts.push(t.to_string());
                }
            }
            "tool_use" => {
                let id = block.get("id").and_then(Value::as_str).unwrap_or("");
                let name = block.get("name").and_then(Value::as_str).unwrap_or("");
                let input = block.get("input").cloned().unwrap_or(json!({}));
                tool_calls.push(json!({
                    "id": id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": serde_json::to_string(&input).unwrap_or_else(|_| "{}".into()),
                    }
                }));
            }
            _ => { /* Unknown block types (e.g., future "image"); drop. */ }
        }
    }
    (text_parts.join(""), tool_calls)
}

fn map_stop_reason(anthropic_reason: &str, has_tool_calls: bool) -> &'static str {
    if has_tool_calls {
        return "tool_calls";
    }
    match anthropic_reason {
        "end_turn" => "stop",
        "max_tokens" => "length",
        "stop_sequence" => "stop",
        "tool_use" => "tool_calls",
        _ => "stop",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn translate_request_lifts_system_messages() {
        let req = json!({
            "model": "claude-haiku-4-5",
            "messages": [
                {"role": "system", "content": "you are helpful"},
                {"role": "system", "content": "be concise"},
                {"role": "user", "content": "hi"}
            ]
        });
        let out = translate_request(&req);
        assert_eq!(out["system"], json!("you are helpful\n\nbe concise"));
        assert_eq!(out["messages"].as_array().unwrap().len(), 1);
        assert_eq!(out["messages"][0]["role"], json!("user"));
    }

    #[test]
    fn translate_request_defaults_max_tokens() {
        let req = json!({"model": "x", "messages": [{"role": "user", "content": "hi"}]});
        let out = translate_request(&req);
        assert_eq!(out["max_tokens"], json!(DEFAULT_MAX_TOKENS));
    }

    #[test]
    fn translate_request_passes_max_tokens_through() {
        let req = json!({"model": "x", "messages": [], "max_tokens": 256});
        let out = translate_request(&req);
        assert_eq!(out["max_tokens"], json!(256));
    }

    #[test]
    fn translate_request_converts_stop_string_to_array() {
        let req = json!({"model": "x", "messages": [], "stop": "END"});
        let out = translate_request(&req);
        assert_eq!(out["stop_sequences"], json!(["END"]));
    }

    #[test]
    fn translate_request_translates_tools() {
        let req = json!({
            "model": "x", "messages": [],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the weather",
                    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}
                }
            }]
        });
        let out = translate_request(&req);
        let tools = out["tools"].as_array().unwrap();
        assert_eq!(tools.len(), 1);
        assert_eq!(tools[0]["name"], json!("get_weather"));
        assert_eq!(tools[0]["input_schema"]["type"], json!("object"));
    }

    #[test]
    fn translate_request_translates_tool_choice() {
        assert_eq!(
            translate_tool_choice(&json!("auto")),
            Some(json!({"type": "auto"}))
        );
        assert_eq!(
            translate_tool_choice(&json!("required")),
            Some(json!({"type": "any"}))
        );
        assert_eq!(translate_tool_choice(&json!("none")), None);
        assert_eq!(
            translate_tool_choice(&json!({"type": "function", "function": {"name": "f"}})),
            Some(json!({"type": "tool", "name": "f"}))
        );
    }

    #[test]
    fn translate_request_translates_assistant_tool_calls() {
        let req = json!({
            "model": "x",
            "messages": [
                {"role": "user", "content": "weather?"},
                {
                    "role": "assistant",
                    "content": "Sure, let me check.",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": "{\"city\": \"SF\"}"}
                    }]
                }
            ]
        });
        let out = translate_request(&req);
        let assistant = &out["messages"][1];
        assert_eq!(assistant["role"], json!("assistant"));
        let blocks = assistant["content"].as_array().unwrap();
        assert_eq!(blocks.len(), 2);
        assert_eq!(blocks[0]["type"], json!("text"));
        assert_eq!(blocks[1]["type"], json!("tool_use"));
        assert_eq!(blocks[1]["id"], json!("call_1"));
        assert_eq!(blocks[1]["name"], json!("get_weather"));
        assert_eq!(blocks[1]["input"], json!({"city": "SF"}));
    }

    #[test]
    fn translate_request_merges_tool_results_into_user_message() {
        let req = json!({
            "model": "x",
            "messages": [
                {"role": "user", "content": "follow up"},
                {"role": "tool", "tool_call_id": "call_1", "content": "sunny"}
            ]
        });
        let out = translate_request(&req);
        let messages = out["messages"].as_array().unwrap();
        assert_eq!(messages.len(), 1);
        let content = messages[0]["content"].as_array().unwrap();
        assert_eq!(content.len(), 2);
        assert_eq!(content[1]["type"], json!("tool_result"));
        assert_eq!(content[1]["tool_use_id"], json!("call_1"));
        assert_eq!(content[1]["content"], json!("sunny"));
    }

    #[test]
    fn translate_response_text_only() {
        let anthropic = json!({
            "id": "msg_01",
            "model": "claude-haiku-4-5",
            "content": [{"type": "text", "text": "hello world"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 2}
        });
        let out = translate_response(&anthropic, &json!({}));
        assert_eq!(out["id"], json!("msg_01"));
        assert_eq!(out["model"], json!("claude-haiku-4-5"));
        assert_eq!(out["choices"][0]["message"]["content"], json!("hello world"));
        assert_eq!(out["choices"][0]["finish_reason"], json!("stop"));
        assert_eq!(out["usage"]["prompt_tokens"], json!(5));
        assert_eq!(out["usage"]["completion_tokens"], json!(2));
        assert_eq!(out["usage"]["total_tokens"], json!(7));
    }

    #[test]
    fn translate_response_total_tokens_saturates_on_overflow() {
        // Absurd upstream-controlled counts must not wrap (release) / panic
        // (debug) when summed for total_tokens.
        let anthropic = json!({
            "id": "msg_ovf",
            "model": "claude-haiku-4-5",
            "content": [{"type": "text", "text": "x"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": u64::MAX, "output_tokens": u64::MAX}
        });
        let out = translate_response(&anthropic, &json!({}));
        assert_eq!(out["usage"]["total_tokens"], json!(u64::MAX));
    }

    #[test]
    fn translate_response_with_tool_use() {
        let anthropic = json!({
            "id": "msg_02",
            "model": "claude-haiku-4-5",
            "content": [
                {"type": "text", "text": "Looking up..."},
                {"type": "tool_use", "id": "toolu_01", "name": "get_weather", "input": {"city": "SF"}}
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 10, "output_tokens": 8}
        });
        let out = translate_response(&anthropic, &json!({}));
        assert_eq!(out["choices"][0]["message"]["content"], json!("Looking up..."));
        let tool_calls = out["choices"][0]["message"]["tool_calls"].as_array().unwrap();
        assert_eq!(tool_calls.len(), 1);
        assert_eq!(tool_calls[0]["id"], json!("toolu_01"));
        assert_eq!(tool_calls[0]["function"]["name"], json!("get_weather"));
        // Arguments must be a JSON-encoded string (OpenAI shape) not an object.
        let args = tool_calls[0]["function"]["arguments"].as_str().unwrap();
        let parsed: Value = serde_json::from_str(args).unwrap();
        assert_eq!(parsed, json!({"city": "SF"}));
        assert_eq!(out["choices"][0]["finish_reason"], json!("tool_calls"));
    }

    #[test]
    fn translate_request_rejects_json_schema_response_format() {
        let req = json!({
            "model": "claude-haiku-4-5",
            "messages": [{"role": "user", "content": "hi"}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "x"}}
        });
        let err = translate_request_checked(&req)
            .expect_err("json_schema must be rejected");
        let msg = err.to_string();
        assert!(msg.contains("json_schema"), "got: {msg}");
        assert!(msg.contains("tool_use"), "expected remediation hint, got: {msg}");
    }

    #[test]
    fn translate_request_translates_json_object_to_system_directive() {
        let req = json!({
            "model": "claude-haiku-4-5",
            "messages": [{"role": "user", "content": "give me JSON"}],
            "response_format": {"type": "json_object"}
        });
        let out = translate_request_checked(&req).unwrap();
        let system = out["system"].as_str().unwrap();
        assert!(
            system.contains("valid JSON object"),
            "expected JSON-mode directive in system prompt, got: {system}"
        );
    }

    #[test]
    fn translate_request_json_object_joins_with_existing_system_prompt() {
        let req = json!({
            "model": "claude-haiku-4-5",
            "messages": [
                {"role": "system", "content": "you are a classifier"},
                {"role": "user", "content": "classify this"}
            ],
            "response_format": {"type": "json_object"}
        });
        let out = translate_request_checked(&req).unwrap();
        let system = out["system"].as_str().unwrap();
        // Both directives appear, joined by \n\n.
        assert!(system.contains("classifier"), "got: {system}");
        assert!(system.contains("valid JSON object"), "got: {system}");
    }

    #[test]
    fn translate_request_no_response_format_passes_through() {
        let req = json!({
            "model": "x",
            "messages": [{"role": "user", "content": "hi"}]
        });
        let out = translate_request_checked(&req).unwrap();
        // No system directive injected when caller didn't ask for JSON.
        assert!(
            !out.get("system").map(|s| s.as_str().unwrap_or("").contains("valid JSON"))
                .unwrap_or(false),
            "should not inject JSON directive when caller didn't ask"
        );
    }

    #[test]
    fn map_stop_reason_handles_known_codes() {
        assert_eq!(map_stop_reason("end_turn", false), "stop");
        assert_eq!(map_stop_reason("max_tokens", false), "length");
        assert_eq!(map_stop_reason("stop_sequence", false), "stop");
        assert_eq!(map_stop_reason("tool_use", true), "tool_calls");
        // has_tool_calls overrides whatever Anthropic says (e.g. for malformed responses).
        assert_eq!(map_stop_reason("end_turn", true), "tool_calls");
        assert_eq!(map_stop_reason("anything_else", false), "stop");
    }

    // =====================================================================
    // Streaming translation tests (Phase 7.2).
    // =====================================================================

    fn block(event: &str, data: &Value) -> String {
        format!("event: {event}\ndata: {data}\n\n")
    }

    #[test]
    fn stream_translator_message_start_emits_role_chunk() {
        let mut t = AnthropicStreamTranslator::new("claude-haiku-4-5".to_string());
        let chunks = t.process_event_block(&block(
            "message_start",
            &json!({
                "type": "message_start",
                "message": {
                    "id": "msg_abc",
                    "role": "assistant",
                    "model": "claude-haiku-4-5",
                    "content": [],
                    "usage": {"input_tokens": 12, "output_tokens": 0}
                }
            }),
        ));
        assert_eq!(chunks.len(), 1);
        let c = &chunks[0];
        assert_eq!(c["object"], json!("chat.completion.chunk"));
        assert_eq!(c["model"], json!("claude-haiku-4-5"));
        assert_eq!(c["id"], json!("chatcmpl-abc"));
        assert_eq!(c["choices"][0]["delta"]["role"], json!("assistant"));
        assert_eq!(c["choices"][0]["finish_reason"], Value::Null);
    }

    #[test]
    fn stream_translator_text_delta_emits_content_chunk() {
        let mut t = AnthropicStreamTranslator::new("claude-haiku-4-5".to_string());
        t.process_event_block(&block(
            "message_start",
            &json!({"message": {"id": "msg_1", "model": "claude-haiku-4-5"}}),
        ));
        t.process_event_block(&block(
            "content_block_start",
            &json!({"index": 0, "content_block": {"type": "text", "text": ""}}),
        ));
        let chunks = t.process_event_block(&block(
            "content_block_delta",
            &json!({"index": 0, "delta": {"type": "text_delta", "text": "Hello"}}),
        ));
        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0]["choices"][0]["delta"]["content"], json!("Hello"));
    }

    #[test]
    fn stream_translator_tool_use_block_start_emits_tool_call_init() {
        let mut t = AnthropicStreamTranslator::new("claude-haiku-4-5".to_string());
        t.process_event_block(&block(
            "message_start",
            &json!({"message": {"id": "msg_1", "model": "claude-haiku-4-5"}}),
        ));
        let chunks = t.process_event_block(&block(
            "content_block_start",
            &json!({
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_42",
                    "name": "get_weather",
                    "input": {}
                }
            }),
        ));
        assert_eq!(chunks.len(), 1);
        let tc = &chunks[0]["choices"][0]["delta"]["tool_calls"][0];
        assert_eq!(tc["index"], json!(0));
        assert_eq!(tc["id"], json!("toolu_42"));
        assert_eq!(tc["type"], json!("function"));
        assert_eq!(tc["function"]["name"], json!("get_weather"));
        assert_eq!(tc["function"]["arguments"], json!(""));
    }

    #[test]
    fn stream_translator_input_json_delta_emits_tool_call_arg_chunk() {
        let mut t = AnthropicStreamTranslator::new("claude-haiku-4-5".to_string());
        t.process_event_block(&block(
            "message_start",
            &json!({"message": {"id": "msg_1", "model": "claude-haiku-4-5"}}),
        ));
        t.process_event_block(&block(
            "content_block_start",
            &json!({
                "index": 0,
                "content_block": {"type": "tool_use", "id": "toolu_42", "name": "f", "input": {}}
            }),
        ));
        let chunks = t.process_event_block(&block(
            "content_block_delta",
            &json!({
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": "{\"city\": "}
            }),
        ));
        assert_eq!(chunks.len(), 1);
        let tc = &chunks[0]["choices"][0]["delta"]["tool_calls"][0];
        assert_eq!(tc["index"], json!(0));
        assert_eq!(tc["function"]["arguments"], json!("{\"city\": "));
    }

    #[test]
    fn stream_translator_message_delta_emits_finish_reason() {
        let mut t = AnthropicStreamTranslator::new("claude-haiku-4-5".to_string());
        t.process_event_block(&block(
            "message_start",
            &json!({"message": {"id": "msg_1", "model": "claude-haiku-4-5"}}),
        ));
        let chunks = t.process_event_block(&block(
            "message_delta",
            &json!({
                "delta": {"stop_reason": "end_turn", "stop_sequence": Value::Null},
                "usage": {"output_tokens": 8}
            }),
        ));
        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0]["choices"][0]["finish_reason"], json!("stop"));
        assert!(chunks[0]["choices"][0]["delta"].as_object().unwrap().is_empty());
    }

    #[test]
    fn stream_translator_message_stop_sets_terminated() {
        let mut t = AnthropicStreamTranslator::new("claude-haiku-4-5".to_string());
        let chunks = t.process_event_block(&block("message_stop", &json!({"type": "message_stop"})));
        assert!(chunks.is_empty());
        assert!(t.is_done());
    }

    #[test]
    fn stream_translator_ping_emits_nothing() {
        let mut t = AnthropicStreamTranslator::new("m".to_string());
        let chunks = t.process_event_block(&block("ping", &json!({"type": "ping"})));
        assert!(chunks.is_empty());
        assert!(!t.is_done());
    }

    #[test]
    fn stream_translator_full_text_flow() {
        let mut t = AnthropicStreamTranslator::new("claude-haiku-4-5".to_string());
        let mut all: Vec<Value> = Vec::new();
        for (event, data) in &[
            ("message_start", json!({"message": {"id": "msg_xyz", "model": "claude-haiku-4-5"}})),
            ("content_block_start", json!({"index": 0, "content_block": {"type": "text", "text": ""}})),
            ("content_block_delta", json!({"index": 0, "delta": {"type": "text_delta", "text": "Hi"}})),
            ("content_block_delta", json!({"index": 0, "delta": {"type": "text_delta", "text": " there"}})),
            ("content_block_stop", json!({"index": 0})),
            ("message_delta", json!({"delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 2}})),
            ("message_stop", json!({"type": "message_stop"})),
        ] {
            all.extend(t.process_event_block(&block(event, data)));
        }
        assert!(t.is_done());
        // Expect: role, "Hi", " there", finish.
        assert_eq!(all.len(), 4);
        assert_eq!(all[0]["choices"][0]["delta"]["role"], json!("assistant"));
        assert_eq!(all[1]["choices"][0]["delta"]["content"], json!("Hi"));
        assert_eq!(all[2]["choices"][0]["delta"]["content"], json!(" there"));
        assert_eq!(all[3]["choices"][0]["finish_reason"], json!("stop"));
    }

    #[test]
    fn stream_translator_full_tool_use_flow() {
        let mut t = AnthropicStreamTranslator::new("claude-haiku-4-5".to_string());
        let mut all: Vec<Value> = Vec::new();
        for (event, data) in &[
            ("message_start", json!({"message": {"id": "msg_t", "model": "claude-haiku-4-5"}})),
            ("content_block_start", json!({"index": 0, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {}}})),
            ("content_block_delta", json!({"index": 0, "delta": {"type": "input_json_delta", "partial_json": "{\"city\":"}})),
            ("content_block_delta", json!({"index": 0, "delta": {"type": "input_json_delta", "partial_json": " \"SF\"}"}})),
            ("content_block_stop", json!({"index": 0})),
            ("message_delta", json!({"delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 5}})),
            ("message_stop", json!({"type": "message_stop"})),
        ] {
            all.extend(t.process_event_block(&block(event, data)));
        }
        // Expect: role, tool_call init, 2 arg deltas, finish.
        assert_eq!(all.len(), 5);
        // Reassemble arguments.
        let arg1 = all[2]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"]
            .as_str()
            .unwrap();
        let arg2 = all[3]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"]
            .as_str()
            .unwrap();
        let combined = format!("{arg1}{arg2}");
        let parsed: Value = serde_json::from_str(&combined).unwrap();
        assert_eq!(parsed, json!({"city": "SF"}));
        assert_eq!(all[4]["choices"][0]["finish_reason"], json!("tool_calls"));
    }

    #[test]
    fn stream_translator_skips_malformed_event_blocks() {
        let mut t = AnthropicStreamTranslator::new("m".to_string());
        // Missing data line entirely.
        assert!(t.process_event_block("event: message_start\n\n").is_empty());
        // Malformed JSON in data.
        assert!(t
            .process_event_block("event: message_start\ndata: {not json\n\n")
            .is_empty());
        // No event line.
        assert!(t.process_event_block("data: {\"x\": 1}\n\n").is_empty());
    }
}
