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
    CandidatePair,
    SamplerConfig,
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
) -> CandidatePair:
    return CandidatePair(
        request_id=request_id,
        prompt=f"prompt-{request_id}",
        cheap_model="cheap-m",
        cheap_response="A",
        expensive_model="expensive-m",
        expensive_response="B",
        cluster_id=cluster_id,
        ensemble_score=ensemble_score,
        ensemble_confidence=ensemble_confidence,
        ensemble_position_bias=ensemble_position_bias,
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
