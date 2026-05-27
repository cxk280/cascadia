//! Configuration, loaded from environment variables.

use std::env;
use std::str::FromStr;

/// Proxy configuration. All fields read from `CASCADIA_*` env vars at startup.
#[derive(Debug, Clone)]
pub struct Config {
    /// Address the HTTP server binds to. Default: `0.0.0.0:8080`.
    pub listen_addr: String,

    /// OpenAI API key for upstream calls. None disables the OpenAI provider.
    pub openai_api_key: Option<String>,
    /// Override the OpenAI base URL (useful for testing against a mock).
    pub openai_base_url: String,

    /// Anthropic API key for upstream calls. None disables the Anthropic provider.
    pub anthropic_api_key: Option<String>,
    /// Anthropic base URL.
    pub anthropic_base_url: String,

    /// Groq API key. None disables the Groq provider.
    pub groq_api_key: Option<String>,
    /// Groq base URL (OpenAI-compatible at `/openai/v1`).
    pub groq_base_url: String,

    /// xAI API key. None disables the xAI provider.
    pub xai_api_key: Option<String>,
    /// xAI base URL (OpenAI-compatible).
    pub xai_base_url: String,

    /// `info` / `debug` / `warn` / `error`. Honored if `RUST_LOG` is unset.
    pub log_level: String,

    /// Emit logs as JSON (one event per line). Default true for production.
    pub log_json: bool,

    /// Optional Postgres connection string. When unset, events are logged
    /// via tracing but not persisted.
    pub database_url: Option<String>,

    /// Persist verbatim request/response bodies in the event log. Off by
    /// default for privacy + storage cost.
    pub persist_bodies: bool,

    /// Redact `shadow_pairs.{prompt, cheap_response, expensive_response}`
    /// columns: write `sha256:HEX` digests instead of verbatim text. On by
    /// default = false (closed-loop quality scoring works). Set to true in
    /// regulated environments where verbatim user-prompt persistence is
    /// unacceptable. With redaction on, the judge worker can correlate
    /// pairs but cannot compute quality scores — the closed loop is
    /// effectively disabled. See [SECURITY.md](../../SECURITY.md) for the
    /// trade-off matrix.
    pub redact_shadow_bodies: bool,

    /// Optional OTLP/HTTP endpoint for trace export. Example:
    /// `http://localhost:4318/v1/traces`. When unset, OpenTelemetry is disabled.
    pub otlp_endpoint: Option<String>,

    /// Optional path to a JSON policy file. When set, the proxy watches this
    /// path and hot-reloads on change.
    pub policy_file: Option<std::path::PathBuf>,

    /// Optional shared bearer token enforced on `/v1/*` routes.
    ///
    /// When set (`CASCADIA_PROXY_BEARER_TOKEN`), the proxy requires an
    /// `Authorization: Bearer <token>` header on every chat-completions
    /// request and responds 401 (OpenAI-shape error envelope) otherwise.
    /// When unset, the `/v1/*` routes accept any caller — appropriate for
    /// private-network deployments where auth is handled at the cluster
    /// boundary. Health, readiness, and metrics endpoints are never gated.
    pub proxy_bearer_token: Option<String>,
}

/// Which upstream provider serves a request. The provider for each tier of
/// the cascade is parsed from the cluster's `cheap_model` / `expensive_model`
/// strings (Phase 7: hard-fail on unprefixed strings).
///
/// ## Before adding a new variant
///
/// Adding a `Provider::*` variant is the RIGHT move only if the provider
/// has its own wire format (a custom request shape that needs translation,
/// like Anthropic's `/v1/messages` or Gemini's `generateContent`). If the
/// provider speaks OpenAI's `/v1/chat/completions` shape (Mistral, DeepSeek,
/// Together, Fireworks, Perplexity, vLLM, …), **don't add a variant** —
/// use the existing `Provider::OpenAI` adapter with a base-URL override:
///
/// ```bash
/// CASCADIA_OPENAI_BASE_URL=https://api.mistral.ai/v1 cascadia-proxy
/// # And in the policy file: `"cheap_model": "openai/mistral-small"`.
/// ```
///
/// See `docs/adding-a-provider.md` for the full recipe and PLAN.md §9
/// (2026-05-19 — Phase 7 scoping) for why the hard-fail-on-unknown-providers
/// rule exists. Adding a new variant requires touching `model_id.rs`,
/// `policy.rs`, `upstream.rs`, `upstream/<name>.rs`, the metrics pre-touch
/// table, and the deploy/helm chart's secret keys; open an issue first.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Provider {
    OpenAI,
    Anthropic,
    Groq,
    XAI,
}

impl Provider {
    /// Stable label used in logs, metrics, and the `events.provider` column.
    pub fn label(self) -> &'static str {
        match self {
            Provider::OpenAI => "openai",
            Provider::Anthropic => "anthropic",
            Provider::Groq => "groq",
            Provider::XAI => "xai",
        }
    }
}

impl FromStr for Provider {
    type Err = anyhow::Error;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "openai" => Ok(Provider::OpenAI),
            "anthropic" => Ok(Provider::Anthropic),
            "groq" => Ok(Provider::Groq),
            "xai" | "x-ai" => Ok(Provider::XAI),
            other => anyhow::bail!(
                "unknown provider `{other}`; expected one of openai, anthropic, groq, xai"
            ),
        }
    }
}

impl Config {
    /// Load configuration from environment variables, applying defaults.
    pub fn from_env() -> anyhow::Result<Self> {
        // Listen address resolution (12-factor + Railway/Render/Heroku friendly):
        // 1. CASCADIA_LISTEN_ADDR if explicitly set (full host:port form)
        // 2. PORT if set (common platform convention — bind 0.0.0.0:$PORT)
        // 3. fallback to 0.0.0.0:8080 for local dev
        let listen_addr = match env::var("CASCADIA_LISTEN_ADDR") {
            Ok(v) if !v.is_empty() && !v.ends_with(':') => v,
            _ => match env::var("PORT") {
                Ok(p) if !p.is_empty() => format!("0.0.0.0:{p}"),
                _ => "0.0.0.0:8080".to_string(),
            },
        };

        let openai_api_key = env::var("CASCADIA_OPENAI_API_KEY").ok();
        let openai_base_url = env::var("CASCADIA_OPENAI_BASE_URL")
            .unwrap_or_else(|_| "https://api.openai.com".to_string());

        let anthropic_api_key = env::var("CASCADIA_ANTHROPIC_API_KEY").ok();
        let anthropic_base_url = env::var("CASCADIA_ANTHROPIC_BASE_URL")
            .unwrap_or_else(|_| "https://api.anthropic.com".to_string());

        let groq_api_key = env::var("CASCADIA_GROQ_API_KEY").ok();
        // Groq's OpenAI-compatible endpoint lives at /openai/v1; we treat it
        // as a standard OpenAI base URL (handlers append /v1/chat/completions).
        let groq_base_url = env::var("CASCADIA_GROQ_BASE_URL")
            .unwrap_or_else(|_| "https://api.groq.com/openai".to_string());

        let xai_api_key = env::var("CASCADIA_XAI_API_KEY").ok();
        let xai_base_url = env::var("CASCADIA_XAI_BASE_URL")
            .unwrap_or_else(|_| "https://api.x.ai".to_string());

        let log_level = env::var("CASCADIA_LOG_LEVEL").unwrap_or_else(|_| "info".to_string());
        let log_json = env::var("CASCADIA_LOG_JSON")
            .ok()
            .map(|v| !matches!(v.to_lowercase().as_str(), "0" | "false" | "no"))
            .unwrap_or(true);

        let database_url = env::var("CASCADIA_DATABASE_URL").ok();
        let persist_bodies = env::var("CASCADIA_PERSIST_BODIES")
            .ok()
            .map(|v| matches!(v.to_lowercase().as_str(), "1" | "true" | "yes"))
            .unwrap_or(false);
        let redact_shadow_bodies = env::var("CASCADIA_REDACT_SHADOW_BODIES")
            .ok()
            .map(|v| matches!(v.to_lowercase().as_str(), "1" | "true" | "yes"))
            .unwrap_or(false);

        let otlp_endpoint = env::var("CASCADIA_OTLP_ENDPOINT").ok();
        let policy_file = env::var("CASCADIA_POLICY_FILE")
            .ok()
            .map(std::path::PathBuf::from);
        let proxy_bearer_token = env::var("CASCADIA_PROXY_BEARER_TOKEN")
            .ok()
            .filter(|s| !s.is_empty());

        // Sanity: at least one upstream must be configured.
        if openai_api_key.is_none()
            && anthropic_api_key.is_none()
            && groq_api_key.is_none()
            && xai_api_key.is_none()
        {
            anyhow::bail!(
                "no upstream configured: set CASCADIA_OPENAI_API_KEY / CASCADIA_ANTHROPIC_API_KEY / CASCADIA_GROQ_API_KEY / CASCADIA_XAI_API_KEY"
            );
        }

        Ok(Self {
            listen_addr,
            openai_api_key,
            openai_base_url,
            anthropic_api_key,
            anthropic_base_url,
            groq_api_key,
            groq_base_url,
            xai_api_key,
            xai_base_url,
            log_level,
            log_json,
            database_url,
            persist_bodies,
            redact_shadow_bodies,
            otlp_endpoint,
            policy_file,
            proxy_bearer_token,
        })
    }

    /// Return the API key + base URL for a given provider, or
    /// `ProviderUnconfigured` if its key isn't set.
    pub fn provider_credentials(&self, provider: Provider) -> Option<(&str, &str)> {
        match provider {
            Provider::OpenAI => self.openai_api_key.as_deref().map(|k| (k, self.openai_base_url.as_str())),
            Provider::Anthropic => self.anthropic_api_key.as_deref().map(|k| (k, self.anthropic_base_url.as_str())),
            Provider::Groq => self.groq_api_key.as_deref().map(|k| (k, self.groq_base_url.as_str())),
            Provider::XAI => self.xai_api_key.as_deref().map(|k| (k, self.xai_base_url.as_str())),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn provider_from_str_accepts_all_four() {
        assert_eq!(Provider::from_str("openai").unwrap(), Provider::OpenAI);
        assert_eq!(Provider::from_str("anthropic").unwrap(), Provider::Anthropic);
        assert_eq!(Provider::from_str("groq").unwrap(), Provider::Groq);
        assert_eq!(Provider::from_str("xai").unwrap(), Provider::XAI);
        assert_eq!(Provider::from_str("XAI").unwrap(), Provider::XAI); // case-insensitive
        assert_eq!(Provider::from_str("x-ai").unwrap(), Provider::XAI);
    }

    #[test]
    fn provider_from_str_rejects_unknown() {
        assert!(Provider::from_str("cohere").is_err());
        assert!(Provider::from_str("").is_err());
    }

    #[test]
    fn provider_labels_are_stable() {
        assert_eq!(Provider::OpenAI.label(), "openai");
        assert_eq!(Provider::Anthropic.label(), "anthropic");
        assert_eq!(Provider::Groq.label(), "groq");
        assert_eq!(Provider::XAI.label(), "xai");
    }
}
