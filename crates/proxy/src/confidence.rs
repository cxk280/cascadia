//! Confidence signal for the Phase-2 cascade.
//!
//! Returns a value in [0, 1] estimating how confidently the cheap tier
//! answered. ≥ policy.threshold → return cheap. Else → escalate to expensive.
//!
//! Phase 2 uses an intentionally simple rule:
//!
//! - **Start from 1.0** ("confident unless we see a reason to doubt").
//! - Each uncertainty marker ("I'm not sure", "I don't know", "could be", …)
//!   subtracts a fixed penalty. Hedging is the main quality signal at this
//!   stage; models that need to escalate usually hedge.
//! - **Length overshoot** also penalizes — a response that runs on far past
//!   target length is usually the model padding around an unclear answer.
//!
//! This is intentionally crude. Phase 3 replaces it with judge-as-confidence,
//! and Phase 4 with a learned classifier. The shape of the API
//! (`fn confidence(response: &str) -> f32`) is what stays stable.

const TARGET_LEN: usize = 600;
const PENALTY_PER_MARKER: f32 = 0.17;
const OVERSHOOT_PENALTY_MAX: f32 = 0.4;

const UNCERTAINTY_MARKERS: &[&str] = &[
    "i don't know",
    "i'm not sure",
    "i am not sure",
    "i'm not certain",
    "i can't say for certain",
    "as far as i know",
    "i could be wrong",
    "i'm uncertain",
    "i don't have enough",
    "it depends",
    "without more context",
    "i need more information",
];

/// Compute confidence in [0, 1] for a cheap-tier response.
pub fn confidence(response: &str) -> f32 {
    if response.is_empty() {
        // No content == no confidence. Force escalate.
        return 0.0;
    }
    let marker_penalty = uncertainty_penalty(response);
    let length_penalty = length_overshoot_penalty(response);
    (1.0 - marker_penalty - length_penalty).clamp(0.0, 1.0)
}

fn length_overshoot_penalty(response: &str) -> f32 {
    let len = response.chars().count();
    if len <= TARGET_LEN {
        0.0
    } else {
        // Linear ramp from 0 (at target) to OVERSHOOT_PENALTY_MAX (at 2× target).
        let overshoot = (len - TARGET_LEN) as f32 / TARGET_LEN as f32;
        OVERSHOOT_PENALTY_MAX * overshoot.min(1.0)
    }
}

fn uncertainty_penalty(response: &str) -> f32 {
    let lower = response.to_lowercase();
    let mut hits = 0;
    for m in UNCERTAINTY_MARKERS {
        if lower.contains(m) {
            hits += 1;
        }
    }
    hits as f32 * PENALTY_PER_MARKER
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_response_is_zero_confidence() {
        assert_eq!(confidence(""), 0.0);
    }

    #[test]
    fn short_clean_response_is_high_confidence() {
        let c = confidence("Yes.");
        assert!(
            c > 0.9,
            "expected high confidence for short clean reply, got {c}"
        );
    }

    #[test]
    fn target_length_clean_response_is_at_least_target() {
        let response = "a".repeat(TARGET_LEN);
        let c = confidence(&response);
        assert!(c >= 0.95, "expected near-1, got {c}");
    }

    #[test]
    fn overshoot_decays_smoothly() {
        let short = confidence(&"a".repeat(TARGET_LEN));
        let long = confidence(&"a".repeat(TARGET_LEN * 3));
        assert!(long < short, "long={long} short={short}");
        assert!(long >= 0.5, "should floor at 0.5, got {long}");
    }

    #[test]
    fn uncertainty_markers_penalize() {
        let clean = confidence("The capital of Norway is Oslo.");
        let hedged = confidence("I'm not sure, but I think the capital of Norway is Oslo.");
        assert!(
            hedged < clean,
            "hedged should score lower; clean={clean} hedged={hedged}"
        );
    }

    #[test]
    fn multiple_markers_compound() {
        let many = confidence("I don't know. As far as I know, I could be wrong about this.");
        assert!(many < 0.5, "expected heavy penalty, got {many}");
    }

    #[test]
    fn output_always_in_unit_interval() {
        let inputs = [
            "",
            "yes",
            &"x".repeat(10_000),
            "I don't know I'm not sure I could be wrong",
        ];
        for input in inputs {
            let c = confidence(input);
            assert!((0.0..=1.0).contains(&c), "out of range: {c} for {input:?}");
        }
    }
}
