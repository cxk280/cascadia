//! Configuration, loaded from environment variables.

use std::collections::{HashMap, HashSet};
use std::env;

/// Proxy configuration. All fields read from `CASCADIA_*` env vars at startup.
#[derive(Debug, Clone)]
pub struct Config {
    /// Address the HTTP server binds to. Default: `0.0.0.0:8080`.
    pub listen_addr: String,

    /// Upstream provider registry, keyed by lowercased `provider/` prefix.
    ///
    /// Replaces the former closed `Provider` enum: providers are now a config
    /// entry, not a code change (PLAN.md §9 2026-06-09 — dynamic provider
    /// registry, reversing the 2026-05-19 closed-enum decision). The four
    /// native providers (openai, anthropic, groq, xai) are seeded as built-ins;
    /// `CASCADIA_PROVIDERS` adds more (HuggingFace, Together, vLLM, …).
    pub providers: HashMap<String, ProviderConfig>,

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
    /// columns: write `sha256:HEX` digests instead of verbatim text. Default
    /// false (closed-loop quality scoring works). Set true in regulated
    /// environments where verbatim user-prompt persistence is unacceptable.
    /// See [SECURITY.md](../../SECURITY.md) for the trade-off matrix.
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
    /// request and responds 401 otherwise. When unset, the `/v1/*` routes
    /// accept any caller — appropriate for private-network deployments.
    pub proxy_bearer_token: Option<String>,
}

/// The request/response wire format a provider speaks. Dispatch in
/// `upstream::forward_chat` keys off this rather than a closed provider enum,
/// so a new provider is a config entry, not a new match arm.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Wire {
    /// OpenAI `/v1/chat/completions` shape (OpenAI, Groq, xAI, the HuggingFace
    /// router, Together, Fireworks, vLLM, …). Pass-through, no translation.
    OpenAi,
    /// Anthropic `/v1/messages` shape — needs request/response translation
    /// (see `upstream::anthropic`).
    Anthropic,
}

impl Wire {
    /// Stable label for logs/diagnostics.
    pub fn label(self) -> &'static str {
        match self {
            Wire::OpenAi => "openai",
            Wire::Anthropic => "anthropic",
        }
    }

    /// Parse a `CASCADIA_PROVIDER_<N>_WIRE` value. Defaults are applied by the
    /// caller (OpenAI-compatible); this only validates an explicit value.
    fn parse(s: &str) -> anyhow::Result<Wire> {
        match s.trim().to_lowercase().as_str() {
            "openai" | "openai-compat" | "openai_compat" | "oai" => Ok(Wire::OpenAi),
            "anthropic" | "claude" => Ok(Wire::Anthropic),
            other => anyhow::bail!(
                "unknown wire `{other}`; expected `openai` (OpenAI-compatible) or `anthropic`"
            ),
        }
    }
}

/// A resolved upstream provider: the label that appears as the `provider/`
/// prefix in policy model strings, the wire format it speaks, its endpoint, and
/// its credential. Built once at boot into `Config.providers`.
///
/// The four built-ins (openai, anthropic, groq, xai) are always present unless a
/// `CASCADIA_PROVIDERS` entry overrides one by name.
#[derive(Debug, Clone)]
pub struct ProviderConfig {
    /// Lowercased registry key / `provider/` prefix, e.g. `openai`, `hf`.
    pub name: String,
    pub wire: Wire,
    pub base_url: String,
    /// None disables the provider — it resolves but yields a
    /// `ProviderUnconfigured` error at request time (matching the pre-registry
    /// "key unset disables the provider" behavior).
    pub api_key: Option<String>,
}

/// Built-in providers: `(name, wire, default base URL)`. Their credentials and
/// base-URL overrides use the historical `CASCADIA_<NAME>_API_KEY` /
/// `CASCADIA_<NAME>_BASE_URL` env vars (unchanged — backward compatible).
const BUILTIN_PROVIDERS: &[(&str, Wire, &str)] = &[
    ("openai", Wire::OpenAi, "https://api.openai.com"),
    ("anthropic", Wire::Anthropic, "https://api.anthropic.com"),
    // Groq's OpenAI-compatible endpoint lives at /openai/v1; treated as a
    // standard OpenAI base URL (handlers append /v1/chat/completions).
    ("groq", Wire::OpenAi, "https://api.groq.com/openai"),
    ("xai", Wire::OpenAi, "https://api.x.ai"),
];

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

        let providers = load_providers()?;

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

        // Sanity: at least one provider must carry a credential.
        if !providers.values().any(|p| p.api_key.is_some()) {
            anyhow::bail!(
                "no upstream configured: set an API key for at least one provider \
                 (CASCADIA_OPENAI_API_KEY / CASCADIA_ANTHROPIC_API_KEY / \
                 CASCADIA_GROQ_API_KEY / CASCADIA_XAI_API_KEY, or a \
                 CASCADIA_PROVIDER_<NAME>_API_KEY for a CASCADIA_PROVIDERS entry)"
            );
        }

        Ok(Self {
            listen_addr,
            providers,
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

    /// Resolve a `provider/` prefix to its configured provider, or `None` if no
    /// provider with that name is configured. Case-insensitive; folds the
    /// historical `x-ai` alias onto `xai`.
    pub fn resolve_provider(&self, prefix: &str) -> Option<&ProviderConfig> {
        self.providers.get(&normalize_provider_key(prefix))
    }

    /// Sorted list of configured provider names — for the `/providers`
    /// endpoint, boot-validation error messages, and diagnostics.
    pub fn provider_names(&self) -> Vec<String> {
        let mut v: Vec<String> = self.providers.keys().cloned().collect();
        v.sort();
        v
    }

    /// The set of configured provider names, for policy validation at boot and
    /// on hot-reload (`PolicyTable::validate_providers`).
    pub fn provider_name_set(&self) -> HashSet<String> {
        self.providers.keys().cloned().collect()
    }

    /// Whether at least one provider has a credential (used by readiness).
    pub fn any_provider_configured(&self) -> bool {
        self.providers.values().any(|p| p.api_key.is_some())
    }
}

/// Build the provider registry: the four built-ins (reading their historical
/// `CASCADIA_<NAME>_*` env vars), then any `CASCADIA_PROVIDERS` entries (each
/// configured via `CASCADIA_PROVIDER_<NAME>_{BASE_URL,API_KEY,WIRE}`). A
/// configured entry overrides a built-in of the same name.
fn load_providers() -> anyhow::Result<HashMap<String, ProviderConfig>> {
    let mut providers: HashMap<String, ProviderConfig> = HashMap::new();

    for &(name, wire, default_base) in BUILTIN_PROVIDERS {
        let upper = name.to_uppercase();
        let api_key = env::var(format!("CASCADIA_{upper}_API_KEY"))
            .ok()
            .filter(|s| !s.is_empty());
        let base_url = env::var(format!("CASCADIA_{upper}_BASE_URL"))
            .ok()
            .filter(|s| !s.trim().is_empty())
            .unwrap_or_else(|| default_base.to_string());
        providers.insert(
            name.to_string(),
            ProviderConfig {
                name: name.to_string(),
                wire,
                base_url,
                api_key,
            },
        );
    }

    let Some(list) = env::var("CASCADIA_PROVIDERS")
        .ok()
        .filter(|s| !s.trim().is_empty())
    else {
        return Ok(providers);
    };

    let mut seen: HashSet<String> = HashSet::new();
    for raw in list.split(',') {
        let token = raw.trim();
        if token.is_empty() {
            continue;
        }
        let name = normalize_provider_key(token);
        anyhow::ensure!(
            is_valid_provider_name(&name),
            "CASCADIA_PROVIDERS entry `{token}` is not a valid provider name; \
             use only letters, digits, `-`, `_` (it becomes the `provider/` prefix)"
        );
        anyhow::ensure!(
            seen.insert(name.clone()),
            "CASCADIA_PROVIDERS lists `{name}` more than once"
        );

        let env_token = env_token_for(&name);
        let base_url = env::var(format!("CASCADIA_PROVIDER_{env_token}_BASE_URL"))
            .ok()
            .filter(|s| !s.trim().is_empty())
            .ok_or_else(|| {
                anyhow::anyhow!(
                    "provider `{name}` (from CASCADIA_PROVIDERS) requires \
                     CASCADIA_PROVIDER_{env_token}_BASE_URL to be set"
                )
            })?;
        let api_key = env::var(format!("CASCADIA_PROVIDER_{env_token}_API_KEY"))
            .ok()
            .filter(|s| !s.is_empty());
        let wire = match env::var(format!("CASCADIA_PROVIDER_{env_token}_WIRE"))
            .ok()
            .filter(|s| !s.trim().is_empty())
        {
            Some(w) => Wire::parse(&w).map_err(|e| {
                anyhow::anyhow!("provider `{name}`: CASCADIA_PROVIDER_{env_token}_WIRE: {e}")
            })?,
            None => Wire::OpenAi,
        };

        if providers.contains_key(&name) {
            tracing::warn!(
                provider = %name,
                "CASCADIA_PROVIDERS entry overrides a built-in provider of the same name"
            );
        }
        providers.insert(
            name.clone(),
            ProviderConfig {
                name,
                wire,
                base_url,
                api_key,
            },
        );
    }

    Ok(providers)
}

/// Normalize a provider prefix to its registry key: trimmed, lowercased, with
/// the historical `x-ai` alias folded onto `xai`. Shared by `resolve_provider`
/// and `PolicyTable::validate_providers` so boot-validation and request-time
/// resolution agree on what counts as "the same provider".
pub(crate) fn normalize_provider_key(s: &str) -> String {
    let lower = s.trim().to_lowercase();
    if lower == "x-ai" {
        "xai".to_string()
    } else {
        lower
    }
}

fn is_valid_provider_name(s: &str) -> bool {
    !s.is_empty()
        && s.chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

/// Map a provider name to the token used in its `CASCADIA_PROVIDER_<TOKEN>_*`
/// env vars: uppercased, with `-` → `_` (env var names can't contain dashes).
fn env_token_for(name: &str) -> String {
    name.to_uppercase().replace('-', "_")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_lowercases_and_folds_xai_alias() {
        assert_eq!(normalize_provider_key("OpenAI"), "openai");
        assert_eq!(normalize_provider_key("  Anthropic "), "anthropic");
        assert_eq!(normalize_provider_key("x-ai"), "xai");
        assert_eq!(normalize_provider_key("XAI"), "xai");
        assert_eq!(normalize_provider_key("hf"), "hf");
    }

    #[test]
    fn wire_parse_accepts_known_and_rejects_unknown() {
        assert_eq!(Wire::parse("openai").unwrap(), Wire::OpenAi);
        assert_eq!(Wire::parse("OpenAI-Compat").unwrap(), Wire::OpenAi);
        assert_eq!(Wire::parse("anthropic").unwrap(), Wire::Anthropic);
        assert!(Wire::parse("gemini").is_err());
        assert_eq!(Wire::OpenAi.label(), "openai");
        assert_eq!(Wire::Anthropic.label(), "anthropic");
    }

    #[test]
    fn valid_provider_names() {
        assert!(is_valid_provider_name("hf"));
        assert!(is_valid_provider_name("together-ai"));
        assert!(is_valid_provider_name("local_vllm"));
        assert!(!is_valid_provider_name(""));
        assert!(!is_valid_provider_name("has/slash"));
        assert!(!is_valid_provider_name("has space"));
    }

    #[test]
    fn env_token_uppercases_and_replaces_dashes() {
        assert_eq!(env_token_for("hf"), "HF");
        assert_eq!(env_token_for("together-ai"), "TOGETHER_AI");
        assert_eq!(env_token_for("local_vllm"), "LOCAL_VLLM");
    }
}
