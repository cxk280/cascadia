"""Unit tests for ensemble aggregation (self-pref filter, position-bias fold,
weighted reduction)."""

from __future__ import annotations

import pytest

from cascadia_judge.aggregation import aggregate
from cascadia_judge.types import JudgeScore, JudgeVerdict, ShadowPair


def _pair(cheap: str = "cheap-m", expensive: str = "expensive-m") -> ShadowPair:
    return ShadowPair(
        request_id="req-1",
        prompt="hi",
        cheap_model=cheap,
        cheap_response="A response.",
        expensive_model=expensive,
        expensive_response="B response.",
    )


def _verdict(
    *,
    judge_name: str,
    model: str,
    score: float,
    confidence: float | None = 0.8,
    error: str | None = None,
    rationale: str = "",
) -> JudgeVerdict:
    return JudgeVerdict(
        request_id="req-1",
        judge_name=judge_name,
        prompt_variant="dummy/v1",
        model=model,
        provider="fake",
        score=JudgeScore(score=score, confidence=confidence, rationale=rationale),
        prompt_hash="h",
        elapsed_ms=10,
        error=error,
    )


def test_single_verdict_returns_its_score() -> None:
    out = aggregate(
        _pair(),
        [_verdict(judge_name="pairwise_preference_v1", model="judge-x", score=0.7)],
    )
    assert out.n_used == 1
    assert out.score == pytest.approx(0.7)
    assert out.n_dropped_self_pref == 0


def test_self_preferring_judge_dropped() -> None:
    # Judge model overlaps with cheap-model — should be dropped.
    out = aggregate(
        _pair(cheap="judge-x"),
        [_verdict(judge_name="pairwise_preference_v1", model="judge-x", score=0.95)],
    )
    assert out.n_dropped_self_pref == 1
    assert out.n_used == 0
    assert out.score == 0.5  # falls back to no-signal default


def test_position_swapped_pair_averaged() -> None:
    # Bias-free case: p=0.8 raw, swapped raw=0.2 -> swapped.score=1-0.2 doesn't
    # apply here (we hand the aggregator the post-inversion score). Both
    # estimates of p(cheap>=expensive) agree at 0.8 -> bias 0.
    verdicts = [
        _verdict(judge_name="pairwise_preference_v1",         model="m1", score=0.80),
        _verdict(judge_name="pairwise_preference_v1_swapped", model="m1", score=0.80),
    ]
    out = aggregate(_pair(), verdicts)
    assert out.score == pytest.approx(0.8)
    assert out.position_bias_estimate == pytest.approx(0.0)
    # The fold collapses 2 verdicts into 1 bias-corrected verdict, so n_used=1.
    assert out.n_used == 1


def test_position_bias_surfaced() -> None:
    # Mild bias: unswapped 0.8, swapped 0.6 -> |0.8 - 0.6| = 0.2.
    verdicts = [
        _verdict(judge_name="pairwise_preference_v1",         model="m1", score=0.80),
        _verdict(judge_name="pairwise_preference_v1_swapped", model="m1", score=0.60),
    ]
    out = aggregate(_pair(), verdicts)
    assert out.position_bias_estimate == pytest.approx(0.2)
    assert out.score == pytest.approx(0.7)  # midpoint of 0.8 and 0.6


def test_errored_verdict_excluded_from_score() -> None:
    verdicts = [
        _verdict(judge_name="pairwise_preference_v1", model="m1", score=0.8, confidence=0.9),
        _verdict(
            judge_name="rubric_v1", model="m1", score=0.0, confidence=0.0,
            rationale="rubric error: something blew up",
            error="ValueError: boom",
        ),
    ]
    out = aggregate(_pair(), verdicts)
    assert out.n_failed == 1
    assert out.n_used == 1
    assert out.score == pytest.approx(0.8)


def test_weighted_by_confidence() -> None:
    # High-confidence judge says 0.9, low-confidence judge says 0.1. The
    # weighted mean should lean toward 0.9.
    verdicts = [
        _verdict(judge_name="pairwise_preference_v1", model="m1", score=0.9, confidence=0.9),
        _verdict(judge_name="rubric_v1",               model="m2", score=0.1, confidence=0.1),
    ]
    out = aggregate(_pair(), verdicts)
    # Weighted: (0.9*0.9 + 0.1*0.1) / (0.9 + 0.1) = (0.81 + 0.01) / 1.0 = 0.82.
    assert out.score == pytest.approx(0.82)


def test_contributing_models_recorded() -> None:
    verdicts = [
        _verdict(judge_name="pairwise_preference_v1", model="judge-A", score=0.7),
        _verdict(judge_name="rubric_v1",               model="judge-B", score=0.6),
    ]
    out = aggregate(_pair(), verdicts)
    assert out.contributing_models == ["judge-A", "judge-B"]
