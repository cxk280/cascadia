//! OpenAI Chat Completion request/response types.
//!
//! We model the request loosely so that fields we don't care about (like
//! `frequency_penalty`, `logit_bias`, `seed`, …) are preserved on the way to
//! upstream rather than dropped. The response is parsed only enough to extract
//! token-count and finish-reason info for the event log.
//!
//! Streaming (`stream: true`) is not yet supported — Phase 1 returns 400.

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Deserialize, Serialize)]
pub struct ChatCompletionRequest {
    pub model: String,
    pub messages: Vec<Message>,

    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub stream: Option<bool>,

    /// Everything else (temperature, top_p, max_tokens, tools, ...) is captured
    /// as-is so we can forward it untouched.
    #[serde(flatten)]
    pub extra: serde_json::Map<String, Value>,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct Message {
    pub role: String,
    pub content: Value,

    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,

    #[serde(flatten)]
    pub extra: serde_json::Map<String, Value>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct ChatCompletionResponse {
    pub id: String,
    #[serde(default)]
    pub object: String,
    #[serde(default)]
    pub created: u64,
    pub model: String,
    pub choices: Vec<Choice>,

    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub usage: Option<Usage>,

    #[serde(flatten)]
    pub extra: serde_json::Map<String, Value>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct Choice {
    pub index: u32,
    pub message: Message,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub finish_reason: Option<String>,

    #[serde(flatten)]
    pub extra: serde_json::Map<String, Value>,
}

#[derive(Debug, Deserialize, Serialize, Clone, Copy)]
pub struct Usage {
    #[serde(default)]
    pub prompt_tokens: u32,
    #[serde(default)]
    pub completion_tokens: u32,
    #[serde(default)]
    pub total_tokens: u32,
}
