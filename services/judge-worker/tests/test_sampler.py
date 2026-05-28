"""Unit tests for the active-learning sampler.

Targets:
  - Round 1 stratification: equal-ish picks per cluster.
  - Round 2 uncertainty ranking: pairs with low confidence / near-tie scores
    / high position-bias rank above clean pairs.
  - Attention check fixtures: cycle correctly when count > len(fixtures).
"""

from __future__ import annotations

from cascadia_judge.calibration.sampler import (
    ATTENTION_CHECKS,
    DEFAULT_MODEL_TIER_RANKS,
    CandidatePair,
    SamplerConfig,
    _model_tier_gap,
    materialize_attention_checks,
    select_batch,
)


def _pair(
    request_id: str,
    cluster_id: str,
    *,
    ensemble_score: float | None = None,
    ensemble_confidence: float | None = None,
    ensemble_position_bias: float | None = None,
    cheap_model: str = "cheap-m",
    expensive_model: str = "expensive-m",
    human_label_ordinal: float | None = None,
) -> CandidatePair:
    return CandidatePair(
        request_id=request_id,
        prompt=f"prompt-{request_id}",
        cheap_model=cheap_model,
        cheap_response="A",
        expensive_model=expensive_model,
        expensive_response="B",
        cluster_id=cluster_id,
        ensemble_score=ensemble_score,
        ensemble_confidence=ensemble_confidence,
        ensemble_position_bias=ensemble_position_bias,
        human_label_ordinal=human_label_ordinal,
    )


def test_round1_seed_stratifies_across_clusters() -> None:
    # 9 pairs, 3 clusters, batch=6 → expect 2 per cluster.
    candidates = []
    for cid in ("c0", "c1", "c2"):
        for i in range(3):
            candidates.append(_pair(f"{cid}-{i}", cid))
    cfg = SamplerConfig(target_batch_size=6, rng_seed=42)
    batch = select_batch(candidates, config=cfg, round_number=1)
    assert len(batch) == 6
    by_cluster: dict[str, int] = {}
    for p in batch:
        by_cluster[p.cluster_id or "_"] = by_cluster.get(p.cluster_id or "_", 0) + 1
    assert by_cluster == {"c0": 2, "c1": 2, "c2": 2}


def test_round2_picks_high_uncertainty_first() -> None:
    # All in one cluster so stratification doesn't muddy the test.
    high_uncertainty = _pair(
        "high",
        "c0",
        ensemble_score=0.5,            # tie-proximity = 1
        ensemble_confidence=0.1,       # (1 - conf) = 0.9
        ensemble_position_bias=0.4,
    )
    low_uncertainty = _pair(
        "low",
        "c0",
        ensemble_score=0.95,           # tie-proximity ~ 0.1
        ensemble_confidence=0.95,      # (1 - conf) = 0.05
        ensemble_position_bias=0.02,
    )
    cfg = SamplerConfig(target_batch_size=1)
    batch = select_batch([low_uncertainty, high_uncertainty], config=cfg, round_number=2)
    assert len(batch) == 1
    assert batch[0].request_id == "high"


def test_round2_respects_cluster_stratification() -> None:
    # Two clusters, each with one high-uncertainty pair and one low-.
    # With per_cluster=1 we should get *both* high-uncertainty pairs, not
    # both pairs from whichever cluster is global-best.
    pairs = [
        _pair("c0-high", "c0", ensemble_score=0.5, ensemble_confidence=0.1, ensemble_position_bias=0.4),
        _pair("c0-low",  "c0", ensemble_score=0.9, ensemble_confidence=0.9, ensemble_position_bias=0.0),
        _pair("c1-high", "c1", ensemble_score=0.5, ensemble_confidence=0.2, ensemble_position_bias=0.3),
        _pair("c1-low",  "c1", ensemble_score=0.9, ensemble_confidence=0.9, ensemble_position_bias=0.0),
    ]
    cfg = SamplerConfig(target_batch_size=2)
    batch = select_batch(pairs, config=cfg, round_number=2)
    ids = sorted(p.request_id for p in batch)
    assert ids == ["c0-high", "c1-high"]


def test_attention_checks_cycle() -> None:
    out = materialize_attention_checks(7)
    assert len(out) == 7
    # The first 3 are the unique fixtures; 4-7 cycle from the start.
    assert out[0]["source"] == ATTENTION_CHECKS[0]["source"]
    assert out[3]["source"] == ATTENTION_CHECKS[0]["source"]


def test_attention_checks_zero() -> None:
    assert materialize_attention_checks(0) == []


def test_round1_falls_back_to_uniform_for_no_cluster() -> None:
    candidates = [_pair(f"x{i}", None) for i in range(5)]  # type: ignore[arg-type]
    cfg = SamplerConfig(target_batch_size=3, rng_seed=1)
    batch = select_batch(candidates, config=cfg, round_number=1)
    assert len(batch) == 3


# --- Task 3: discriminating-pair strategy ---------------------------------


def test_model_tier_gap_longest_substring_match() -> None:
    # gpt-4o-mini must resolve to the mini tier, not gpt-4o, so the gap to
    # gpt-4o is small but the gap to gpt-3.5 (a real quality drop) is large.
    small = _model_tier_gap("openai/gpt-4o-mini", "openai/gpt-4o", DEFAULT_MODEL_TIER_RANKS)
    large = _model_tier_gap("openai/gpt-3.5-turbo", "openai/gpt-4o", DEFAULT_MODEL_TIER_RANKS)
    assert 0.0 < small < large <= 1.0


def test_model_tier_gap_unknown_model_is_zero() -> None:
    # An unrecognized model never inflates discrimination.
    assert _model_tier_gap("mystery/model-x", "openai/gpt-4o", DEFAULT_MODEL_TIER_RANKS) == 0.0


def test_discrimination_prefers_large_quality_gap_in_round_one() -> None:
    # Round 1, discrimination strategy: a big-gap pair (gpt-3.5 → gpt-4o)
    # outranks a both-fine pair (gpt-4o-mini → gpt-4o) with NO ensemble
    # scores, because the model-tier signal works off names alone.
    big_gap = _pair("big", "c0", cheap_model="openai/gpt-3.5-turbo", expensive_model="openai/gpt-4o")
    small_gap = _pair("small", "c0", cheap_model="openai/gpt-4o-mini", expensive_model="openai/gpt-4o")
    cfg = SamplerConfig(target_batch_size=1, selection_strategy="discrimination")
    batch = select_batch([small_gap, big_gap], config=cfg, round_number=1)
    assert [p.request_id for p in batch] == ["big"]


def test_discrimination_rewards_clear_winner_over_tie() -> None:
    # Same models → tier gap is equal; the pair where the ensemble sees a
    # clear winner (far from 0.5) is more discriminating than a coin-flip tie.
    clear = _pair("clear", "c0", cheap_model="openai/gpt-4o-mini",
                  expensive_model="openai/gpt-4o", ensemble_score=0.95)
    tie = _pair("tie", "c0", cheap_model="openai/gpt-4o-mini",
                expensive_model="openai/gpt-4o", ensemble_score=0.5)
    cfg = SamplerConfig(target_batch_size=1, selection_strategy="discrimination")
    batch = select_batch([tie, clear], config=cfg, round_number=2)
    assert [p.request_id for p in batch] == ["clear"]


def test_discrimination_chases_ensemble_human_disagreement() -> None:
    # Two pairs identical except one has the ensemble disagreeing with the
    # human label (ensemble says cheap wins, human said b/expensive wins).
    agree = _pair("agree", "c0", cheap_model="openai/gpt-4o-mini",
                  expensive_model="openai/gpt-4o", ensemble_score=0.9,
                  human_label_ordinal=1.0)   # both say "a" → no disagreement
    disagree = _pair("disagree", "c0", cheap_model="openai/gpt-4o-mini",
                     expensive_model="openai/gpt-4o", ensemble_score=0.9,
                     human_label_ordinal=0.0)  # human says "b" → large gap
    cfg = SamplerConfig(target_batch_size=1, selection_strategy="discrimination")
    batch = select_batch([agree, disagree], config=cfg, round_number=3)
    assert [p.request_id for p in batch] == ["disagree"]


def test_discrimination_opposite_of_uncertainty_on_ties() -> None:
    # A near-tie pair is HIGH uncertainty but LOW discrimination; the two
    # strategies should rank the same two pairs in opposite order.
    tie = _pair("tie", "c0", cheap_model="openai/gpt-4o-mini",
                expensive_model="openai/gpt-4o", ensemble_score=0.5,
                ensemble_confidence=0.1)
    decisive = _pair("decisive", "c0", cheap_model="openai/gpt-3.5-turbo",
                     expensive_model="openai/gpt-4o", ensemble_score=0.95,
                     ensemble_confidence=0.95)
    unc = SamplerConfig(target_batch_size=1, selection_strategy="uncertainty")
    disc = SamplerConfig(target_batch_size=1, selection_strategy="discrimination")
    assert select_batch([tie, decisive], config=unc, round_number=2)[0].request_id == "tie"
    assert select_batch([tie, decisive], config=disc, round_number=2)[0].request_id == "decisive"
