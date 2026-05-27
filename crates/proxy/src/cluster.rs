//! Query classifier — bins incoming requests into a cluster.
//!
//! Phase 2 shipped a stub that returned `"default"`. Phase 4 introduces a
//! `HashClassifier` that deterministically buckets prompts by their hash.
//! This isn't the learned embedder yet — that's Phase 5+. But it gives us
//! more than one cluster, which is what the policy controller needs to
//! observe per-cluster quality and refit thresholds independently.
//!
//! The interface (`classify(num_buckets, request) -> ClusterId`) stays
//! stable. Phase 5 swaps the implementation for a real embedder + online
//! clustering — call sites in cascade.rs don't change.

use std::hash::Hasher;

use serde_json::Value;
use twox_hash::XxHash64;

pub const DEFAULT_CLUSTER: &str = "default";

/// Classify the prompt into one of `num_buckets` clusters. `num_buckets == 0`
/// or `num_buckets == 1` yields `"default"` (Phase-2 compatible behavior).
///
/// Other values produce cluster ids of the form `"cluster-{0..num_buckets-1}"`
/// using a stable xxHash64 of the prompt's last user message. Same prompt →
/// same cluster, always.
pub fn classify(num_buckets: u32, request: &Value) -> String {
    if num_buckets <= 1 {
        return DEFAULT_CLUSTER.to_string();
    }
    let prompt = last_user_text(request);
    let idx = xxhash(&prompt) % (num_buckets as u64);
    format!("cluster-{idx}")
}

fn xxhash(s: &str) -> u64 {
    // Hash the raw bytes directly (not via Hash::hash) so the result is the
    // canonical XXH64 of the string — stable across Rust stdlib updates that
    // change the internal `Hash for str` representation.
    let mut h = XxHash64::with_seed(0);
    h.write(s.as_bytes());
    h.finish()
}

fn last_user_text(request: &Value) -> String {
    let Some(messages) = request.get("messages").and_then(Value::as_array) else {
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

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn request(prompt: &str) -> Value {
        json!({"messages": [{"role": "user", "content": prompt}]})
    }

    #[test]
    fn zero_or_one_bucket_returns_default() {
        let r = request("anything");
        assert_eq!(classify(0, &r), DEFAULT_CLUSTER);
        assert_eq!(classify(1, &r), DEFAULT_CLUSTER);
    }

    #[test]
    fn same_prompt_yields_same_cluster() {
        let r = request("what is the capital of norway?");
        let a = classify(8, &r);
        let b = classify(8, &r);
        assert_eq!(a, b);
    }

    #[test]
    fn cluster_id_is_within_range() {
        for i in 0..50 {
            let r = request(&format!("prompt number {i}"));
            let id = classify(8, &r);
            assert!(id.starts_with("cluster-"));
            let idx: u32 = id["cluster-".len()..].parse().expect("trailing int");
            assert!(idx < 8, "out of range: {id}");
        }
    }

    #[test]
    fn classifier_distributes_across_buckets() {
        // Crude smoke check: with 4 buckets and 200 distinct prompts, each
        // bucket should see at least one assignment. Hash collisions can
        // skew but 200 is more than enough to hit all 4 buckets.
        use std::collections::HashSet;
        let mut seen = HashSet::new();
        for i in 0..200 {
            let r = request(&format!("test prompt {i}"));
            seen.insert(classify(4, &r));
        }
        assert_eq!(
            seen.len(),
            4,
            "expected all buckets to be hit, saw {seen:?}"
        );
    }
}
