//! Routing policy table — supports static (env-loaded) and hot-reloaded
//! (file-loaded) modes.
//!
//! Phase 2 shipped a single default cluster wired from env vars. Phase 4
//! makes the table per-cluster (HashMap) and adds JSON file loading so the
//! Python policy-controller can refit thresholds and atomically swap the
//! table at runtime.
//!
//! File format (`CASCADIA_POLICY_FILE`):
//!
//! ```json
//! {
//!   "version": "2026-05-19T12:00:00Z",
//!   "default_cluster": "default",
//!   "clusters": {
//!     "default":   { "cheap_model": "gpt-4o-mini", "expensive_model": "gpt-4o", "threshold": 0.7, "shadow_rate": 0.05 },
//!     "cluster-0": { "cheap_model": "gpt-4o-mini", "expensive_model": "gpt-4o", "threshold": 0.65, "shadow_rate": 0.05 }
//!   }
//! }
//! ```
//!
//! Unknown clusters fall back to `default_cluster`.

use std::collections::HashMap;
use std::env;
use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::cluster::DEFAULT_CLUSTER;
use crate::model_id::parse_model_id;

/// Per-cluster routing policy.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClusterPolicy {
    #[serde(default = "default_cluster_id")]
    pub cluster_id: String,
    pub cheap_model: String,
    pub expensive_model: String,
    pub threshold: f32,
    pub shadow_rate: f32,
}

fn default_cluster_id() -> String {
    DEFAULT_CLUSTER.to_string()
}

/// In-memory policy table.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PolicyTable {
    #[serde(default = "default_cluster_id")]
    pub default_cluster: String,
    /// Optional version string, set by the policy controller. Useful for
    /// telemetry / dashboard "last refit" labels.
    #[serde(default)]
    pub version: Option<String>,
    /// Map cluster id → policy.
    pub clusters: HashMap<String, ClusterPolicy>,
    /// How many hash buckets the classifier uses. 0/1 = single default cluster.
    #[serde(default)]
    pub cluster_buckets: u32,
}

impl PolicyTable {
    /// Build a policy table from the environment.
    ///
    /// Priority order:
    /// 1. `CASCADIA_POLICY_JSON` — inline JSON literal. Used by deploy
    ///    targets without a writable volume (Railway, Render, Fly). Hot
    ///    reload is N/A here — set the env var and restart the pod.
    /// 2. `CASCADIA_POLICY_FILE` — path to a JSON file. Hot-reloaded by the
    ///    `watcher` task on file change (the policy controller writes here).
    ///    Handled by the caller of `PolicyTable::from_env()` — this function
    ///    intentionally ignores the file path; see `lib.rs`'s `run()`.
    /// 3. Env-var-derived single-cluster default (this function's fallback):
    ///    `CASCADIA_CHEAP_MODEL`, `CASCADIA_EXPENSIVE_MODEL`,
    ///    `CASCADIA_CASCADE_THRESHOLD`, `CASCADIA_SHADOW_RATE`,
    ///    `CASCADIA_CLUSTER_BUCKETS`.
    ///
    /// Phase 7: `CASCADIA_CHEAP_MODEL` / `CASCADIA_EXPENSIVE_MODEL` MUST be
    /// `provider/model` strings (e.g. `openai/gpt-4o-mini`). Defaults are
    /// `openai/`-prefixed to match. Unprefixed values fail at boot.
    pub fn from_env() -> anyhow::Result<Self> {
        // Inline JSON wins if set — used by deploy targets without a
        // writable volume (Railway, Render, Fly). When both POLICY_JSON
        // and POLICY_FILE are set, JSON wins and the file is ignored;
        // emit a warning so an operator doesn't think their file changes
        // are taking effect.
        if let Ok(json) = env::var("CASCADIA_POLICY_JSON") {
            if !json.trim().is_empty() {
                if env::var("CASCADIA_POLICY_FILE").is_ok() {
                    tracing::warn!(
                        "both CASCADIA_POLICY_JSON and CASCADIA_POLICY_FILE are set; \
                         using POLICY_JSON. Unset one to silence this warning."
                    );
                }
                return Self::from_json_str(&json)
                    .map_err(|e| anyhow::anyhow!("CASCADIA_POLICY_JSON: {e}"));
            }
        }
        Self::from_env_fallback()
    }

    fn from_env_fallback() -> anyhow::Result<Self> {
        let cheap_model =
            env::var("CASCADIA_CHEAP_MODEL").unwrap_or_else(|_| "openai/gpt-4o-mini".into());
        let expensive_model =
            env::var("CASCADIA_EXPENSIVE_MODEL").unwrap_or_else(|_| "openai/gpt-4o".into());
        let threshold = parse_f32(env::var("CASCADIA_CASCADE_THRESHOLD").ok(), 0.7)?;
        let shadow_rate = parse_f32(env::var("CASCADIA_SHADOW_RATE").ok(), 0.05)?;
        let cluster_buckets = parse_u32(env::var("CASCADIA_CLUSTER_BUCKETS").ok(), 1)?;

        validate_bounds(threshold, shadow_rate)?;
        // Hard-fail loud: refuse to boot with unprefixed model strings.
        parse_model_id(&cheap_model)
            .map_err(|e| anyhow::anyhow!("CASCADIA_CHEAP_MODEL invalid: {e}"))?;
        parse_model_id(&expensive_model)
            .map_err(|e| anyhow::anyhow!("CASCADIA_EXPENSIVE_MODEL invalid: {e}"))?;

        let default = ClusterPolicy {
            cluster_id: DEFAULT_CLUSTER.to_string(),
            cheap_model,
            expensive_model,
            threshold,
            shadow_rate,
        };
        let mut clusters = HashMap::with_capacity(1);
        clusters.insert(DEFAULT_CLUSTER.to_string(), default);
        Ok(Self {
            default_cluster: DEFAULT_CLUSTER.to_string(),
            version: None,
            clusters,
            cluster_buckets,
        })
    }

    /// Parse a policy table from a JSON file. Used by the policy hot-reload
    /// watcher and the controller's end-to-end test fixture. Includes the
    /// file path in any error so an operator sees *which* file failed.
    pub fn from_json_file(path: impl AsRef<Path>) -> anyhow::Result<Self> {
        let path_ref = path.as_ref();
        let text = std::fs::read_to_string(path_ref)
            .map_err(|e| anyhow::anyhow!("reading policy file {}: {e}", path_ref.display()))?;
        Self::from_json_str(&text)
            .map_err(|e| anyhow::anyhow!("parsing policy file {}: {e}", path_ref.display()))
    }

    pub fn from_json_str(text: &str) -> anyhow::Result<Self> {
        let mut table: Self = serde_json::from_str(text).map_err(|e| {
            // serde_json's default error names missing/wrong fields with line
            // + column. Wrap it with a hint pointing operators at the schema
            // so a typo like `escalation_threshold` (no such field — use
            // `threshold`) is debuggable from the message alone. Translate
            // common shape mismatches into something a non-Rust operator can
            // act on.
            let msg = e.to_string();
            let hint = if msg.contains("invalid type: sequence") {
                "  Hint: `clusters` must be a JSON object/map keyed by cluster name, not an array. \
                Example: `\"clusters\": {\"default\": {...}}` — not `\"clusters\": [{...}]`."
            } else if msg.contains("missing field") {
                "  Hint: each cluster must have all of: cheap_model, expensive_model, threshold, shadow_rate. \
                See README quick-start for a complete example."
            } else {
                "  Hint: See README quick-start for the canonical policy file shape."
            };
            anyhow::anyhow!("{e}\n{hint}")
        })?;
        // Force each policy's `cluster_id` to match the map key — the key is
        // authoritative. (The `cluster_id` field on `ClusterPolicy` exists for
        // convenient pass-through to logs/metrics; we don't want it to drift.)
        for (key, policy) in table.clusters.iter_mut() {
            policy.cluster_id = key.clone();
            validate_bounds(policy.threshold, policy.shadow_rate)?;
            // Phase 7 hard-fail: every model string must be `provider/model`.
            parse_model_id(&policy.cheap_model)
                .map_err(|e| anyhow::anyhow!("cluster '{key}' cheap_model invalid: {e}"))?;
            parse_model_id(&policy.expensive_model)
                .map_err(|e| anyhow::anyhow!("cluster '{key}' expensive_model invalid: {e}"))?;
        }
        anyhow::ensure!(
            table.clusters.contains_key(&table.default_cluster),
            "policy file: default_cluster '{}' is not in clusters map",
            table.default_cluster
        );
        Ok(table)
    }

    /// Look up the policy for `cluster_id`. Falls back to `default_cluster`'s
    /// policy if the id is unknown.
    pub fn lookup(&self, cluster_id: &str) -> &ClusterPolicy {
        self.clusters
            .get(cluster_id)
            .or_else(|| self.clusters.get(&self.default_cluster))
            .expect("default_cluster must exist per from_json_str invariant")
    }
}

fn parse_f32(value: Option<String>, default: f32) -> anyhow::Result<f32> {
    match value {
        Some(v) => v
            .parse()
            .map_err(|err| anyhow::anyhow!("failed to parse float `{v}`: {err}")),
        None => Ok(default),
    }
}

fn parse_u32(value: Option<String>, default: u32) -> anyhow::Result<u32> {
    match value {
        Some(v) => v
            .parse()
            .map_err(|err| anyhow::anyhow!("failed to parse u32 `{v}`: {err}")),
        None => Ok(default),
    }
}

fn validate_bounds(threshold: f32, shadow_rate: f32) -> anyhow::Result<()> {
    anyhow::ensure!(
        (0.0..=1.0).contains(&threshold),
        "policy threshold must be in [0, 1]; got {threshold}"
    );
    anyhow::ensure!(
        (0.0..=1.0).contains(&shadow_rate),
        "policy shadow_rate must be in [0, 1]; got {shadow_rate}"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn one_cluster(threshold: f32) -> PolicyTable {
        let mut clusters = HashMap::new();
        clusters.insert(
            DEFAULT_CLUSTER.to_string(),
            ClusterPolicy {
                cluster_id: DEFAULT_CLUSTER.to_string(),
                cheap_model: "openai/cheap".to_string(),
                expensive_model: "openai/expensive".to_string(),
                threshold,
                shadow_rate: 0.05,
            },
        );
        PolicyTable {
            default_cluster: DEFAULT_CLUSTER.to_string(),
            version: None,
            clusters,
            cluster_buckets: 1,
        }
    }

    #[test]
    fn lookup_returns_default_for_unknown_cluster() {
        let table = one_cluster(0.7);
        assert_eq!(table.lookup("does-not-exist").cluster_id, DEFAULT_CLUSTER);
    }

    #[test]
    fn lookup_returns_specific_for_known_cluster() {
        let mut table = one_cluster(0.7);
        table.clusters.insert(
            "cluster-1".to_string(),
            ClusterPolicy {
                cluster_id: "cluster-1".to_string(),
                cheap_model: "anthropic/haiku".to_string(),
                expensive_model: "anthropic/sonnet".to_string(),
                threshold: 0.55,
                shadow_rate: 0.1,
            },
        );
        let p = table.lookup("cluster-1");
        assert_eq!(p.threshold, 0.55);
        assert_eq!(p.cheap_model, "anthropic/haiku");
    }

    #[test]
    fn from_json_str_parses_valid_table() {
        let json = r#"{
            "default_cluster": "default",
            "version": "test-v1",
            "cluster_buckets": 4,
            "clusters": {
                "default":   {"cheap_model": "openai/a", "expensive_model": "openai/b", "threshold": 0.7, "shadow_rate": 0.1},
                "cluster-0": {"cheap_model": "openai/c", "expensive_model": "openai/d", "threshold": 0.6, "shadow_rate": 0.05}
            }
        }"#;
        let t = PolicyTable::from_json_str(json).unwrap();
        assert_eq!(t.version.as_deref(), Some("test-v1"));
        assert_eq!(t.cluster_buckets, 4);
        assert_eq!(t.lookup("cluster-0").threshold, 0.6);
        assert_eq!(t.lookup("default").threshold, 0.7);
    }

    #[test]
    fn from_json_str_rejects_missing_default_cluster() {
        let json = r#"{
            "default_cluster": "ghost",
            "clusters": {
                "default": {"cheap_model": "openai/a", "expensive_model": "openai/b", "threshold": 0.7, "shadow_rate": 0.1}
            }
        }"#;
        assert!(PolicyTable::from_json_str(json).is_err());
    }

    #[test]
    fn from_json_str_rejects_out_of_bounds_threshold() {
        let json = r#"{
            "default_cluster": "default",
            "clusters": {
                "default": {"cheap_model": "openai/a", "expensive_model": "openai/b", "threshold": 1.5, "shadow_rate": 0.1}
            }
        }"#;
        assert!(PolicyTable::from_json_str(json).is_err());
    }

    #[test]
    fn from_json_str_rejects_unprefixed_cheap_model() {
        let json = r#"{
            "default_cluster": "default",
            "clusters": {
                "default": {"cheap_model": "gpt-4o-mini", "expensive_model": "openai/gpt-4o", "threshold": 0.7, "shadow_rate": 0.1}
            }
        }"#;
        let err = PolicyTable::from_json_str(json).unwrap_err().to_string();
        assert!(err.contains("cheap_model invalid"), "got: {err}");
        assert!(err.contains("not prefixed"), "got: {err}");
    }

    #[test]
    fn from_json_str_rejects_unknown_provider() {
        let json = r#"{
            "default_cluster": "default",
            "clusters": {
                "default": {"cheap_model": "cohere/command-r", "expensive_model": "openai/gpt-4o", "threshold": 0.7, "shadow_rate": 0.1}
            }
        }"#;
        let err = PolicyTable::from_json_str(json).unwrap_err().to_string();
        assert!(err.contains("unknown provider"), "got: {err}");
    }

    #[test]
    fn from_json_str_accepts_mixed_provider_cluster() {
        let json = r#"{
            "default_cluster": "default",
            "clusters": {
                "default": {"cheap_model": "groq/llama-3.3-70b", "expensive_model": "anthropic/claude-sonnet", "threshold": 0.7, "shadow_rate": 0.1}
            }
        }"#;
        let t = PolicyTable::from_json_str(json).unwrap();
        assert_eq!(t.lookup("default").cheap_model, "groq/llama-3.3-70b");
        assert_eq!(
            t.lookup("default").expensive_model,
            "anthropic/claude-sonnet"
        );
    }
}
