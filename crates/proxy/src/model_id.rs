//! Model-string parsing for Phase 7 cross-provider cascades.
//!
//! Locked decision (PLAN.md §9, 2026-05-19): every model identifier in the
//! policy must carry an explicit provider prefix — `openai/gpt-4o-mini`,
//! `anthropic/claude-haiku-4-5`, `groq/llama-3.3-70b-versatile`,
//! `xai/grok-2-latest`. Unprefixed strings (`gpt-4o-mini`) are rejected at
//! parse time. Hard fail loud, not silent — a user who upgrades and forgets
//! prefixes gets an error on next deploy, not a routing surprise three weeks
//! later.

use std::str::FromStr;

use crate::config::Provider;

/// A parsed `provider/model` pair as it appears in the policy file.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ModelId {
    pub provider: Provider,
    /// The provider-local model name (no slash). Example: `gpt-4o-mini`,
    /// `claude-haiku-4-5`, `llama-3.3-70b-versatile`.
    pub model: String,
}

impl ModelId {
    pub fn new(provider: Provider, model: impl Into<String>) -> Self {
        Self {
            provider,
            model: model.into(),
        }
    }
}

/// Parse `"provider/model"` into a `ModelId`. Returns `Err` for any string
/// without a `/`, with an empty provider, or with an unknown provider name.
pub fn parse_model_id(s: &str) -> anyhow::Result<ModelId> {
    let (prefix, rest) = s.split_once('/').ok_or_else(|| {
        anyhow::anyhow!(
            "model id `{s}` is not prefixed: expected `provider/model` (e.g. `openai/gpt-4o-mini`)"
        )
    })?;
    anyhow::ensure!(
        !prefix.is_empty(),
        "model id `{s}` has empty provider before `/`"
    );
    anyhow::ensure!(!rest.is_empty(), "model id `{s}` has empty model after `/`");
    let provider = Provider::from_str(prefix).map_err(|_| {
        anyhow::anyhow!(
            "model id `{s}`: unknown provider `{prefix}`; expected one of openai, anthropic, groq, xai.\n\
             Hint: if `{prefix}` speaks OpenAI's /v1/chat/completions shape (Mistral, DeepSeek, Together, Fireworks, Perplexity, vLLM, …), \
             use the `openai/` prefix and override CASCADIA_OPENAI_BASE_URL to point at that provider's host. \
             See docs/adding-a-provider.md."
        )
    })?;
    Ok(ModelId {
        provider,
        model: rest.to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_openai() {
        let id = parse_model_id("openai/gpt-4o-mini").unwrap();
        assert_eq!(id.provider, Provider::OpenAI);
        assert_eq!(id.model, "gpt-4o-mini");
    }

    #[test]
    fn parses_anthropic() {
        let id = parse_model_id("anthropic/claude-haiku-4-5").unwrap();
        assert_eq!(id.provider, Provider::Anthropic);
        assert_eq!(id.model, "claude-haiku-4-5");
    }

    #[test]
    fn parses_groq() {
        let id = parse_model_id("groq/llama-3.3-70b-versatile").unwrap();
        assert_eq!(id.provider, Provider::Groq);
        assert_eq!(id.model, "llama-3.3-70b-versatile");
    }

    #[test]
    fn parses_xai() {
        let id = parse_model_id("xai/grok-2-latest").unwrap();
        assert_eq!(id.provider, Provider::XAI);
        assert_eq!(id.model, "grok-2-latest");
    }

    #[test]
    fn rejects_unprefixed() {
        let err = parse_model_id("gpt-4o-mini").unwrap_err().to_string();
        assert!(err.contains("not prefixed"), "got: {err}");
    }

    #[test]
    fn rejects_unknown_provider() {
        let err = parse_model_id("cohere/command-r").unwrap_err().to_string();
        assert!(err.contains("unknown provider"), "got: {err}");
    }

    #[test]
    fn rejects_empty_provider() {
        let err = parse_model_id("/gpt-4o-mini").unwrap_err().to_string();
        assert!(err.contains("empty provider"), "got: {err}");
    }

    #[test]
    fn rejects_empty_model() {
        let err = parse_model_id("openai/").unwrap_err().to_string();
        assert!(err.contains("empty model"), "got: {err}");
    }

    #[test]
    fn model_keeps_internal_slashes() {
        // Edge case: model names with slashes (e.g. `mistral-large/instruct`).
        // Split-once-on-`/` keeps the rest verbatim.
        let id = parse_model_id("openai/some/weird/model").unwrap();
        assert_eq!(id.provider, Provider::OpenAI);
        assert_eq!(id.model, "some/weird/model");
    }
}
