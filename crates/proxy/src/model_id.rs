//! Model-string parsing for cross-provider cascades.
//!
//! Locked decision (PLAN.md §9, 2026-05-19): every model identifier in the
//! policy carries an explicit provider prefix — `openai/gpt-4o-mini`,
//! `anthropic/claude-haiku-4-5`, `huggingface/meta-llama/Llama-3.3-70B`, … —
//! and unprefixed strings (`gpt-4o-mini`) are rejected. Hard fail loud, not
//! silent.
//!
//! Updated 2026-06-09 (PLAN.md §9 — dynamic provider registry): parsing is now
//! purely *syntactic* (split the `provider/` prefix; reject empty halves). Which
//! prefixes are *known* is no longer a closed enum — it's resolved against the
//! configured registry (`Config::resolve_provider`) at request time, and
//! checked at boot / hot-reload by `PolicyTable::validate_providers`. So an
//! unconfigured provider still fails loudly, just at validation rather than here.

/// A parsed `provider/model` pair as it appears in the policy file.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ModelId {
    /// The lowercased provider prefix (the registry key). Resolution to a
    /// `ProviderConfig` happens via `Config::resolve_provider`.
    pub provider: String,
    /// The provider-local model name. May itself contain slashes
    /// (HuggingFace ids like `meta-llama/Llama-3.3-70B-Instruct`).
    pub model: String,
}

impl ModelId {
    pub fn new(provider: impl Into<String>, model: impl Into<String>) -> Self {
        Self {
            provider: provider.into(),
            model: model.into(),
        }
    }
}

/// Parse `"provider/model"` into a `ModelId`. Returns `Err` for any string
/// without a `/`, with an empty provider, or with an empty model. Does NOT
/// check whether the provider is configured — that's the registry's job (see
/// module docs).
pub fn parse_model_id(s: &str) -> anyhow::Result<ModelId> {
    let (prefix, rest) = s.split_once('/').ok_or_else(|| {
        anyhow::anyhow!(
            "model id `{s}` is not prefixed: expected `provider/model` (e.g. `openai/gpt-4o-mini`)"
        )
    })?;
    anyhow::ensure!(
        !prefix.trim().is_empty(),
        "model id `{s}` has empty provider before `/`"
    );
    anyhow::ensure!(!rest.is_empty(), "model id `{s}` has empty model after `/`");
    Ok(ModelId {
        provider: prefix.trim().to_lowercase(),
        model: rest.to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_openai() {
        let id = parse_model_id("openai/gpt-4o-mini").unwrap();
        assert_eq!(id.provider, "openai");
        assert_eq!(id.model, "gpt-4o-mini");
    }

    #[test]
    fn parses_anthropic() {
        let id = parse_model_id("anthropic/claude-haiku-4-5").unwrap();
        assert_eq!(id.provider, "anthropic");
        assert_eq!(id.model, "claude-haiku-4-5");
    }

    #[test]
    fn lowercases_prefix() {
        let id = parse_model_id("OpenAI/gpt-4o-mini").unwrap();
        assert_eq!(id.provider, "openai");
        assert_eq!(id.model, "gpt-4o-mini"); // model case preserved
    }

    #[test]
    fn parses_unknown_prefix_syntactically() {
        // Syntactic-only: an unconfigured provider parses fine here; the
        // registry-membership check happens at boot/validation, not here.
        let id = parse_model_id("hf/meta-llama/Llama-3.3-70B-Instruct").unwrap();
        assert_eq!(id.provider, "hf");
        assert_eq!(id.model, "meta-llama/Llama-3.3-70B-Instruct");
    }

    #[test]
    fn rejects_unprefixed() {
        let err = parse_model_id("gpt-4o-mini").unwrap_err().to_string();
        assert!(err.contains("not prefixed"), "got: {err}");
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
        let id = parse_model_id("openai/some/weird/model").unwrap();
        assert_eq!(id.provider, "openai");
        assert_eq!(id.model, "some/weird/model");
    }
}
