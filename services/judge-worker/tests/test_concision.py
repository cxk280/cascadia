"""Phase 5.2 — concision-adjustment unit tests.

Targets the helper directly + checks the aggregate() integration applies and
records the adjustment correctly.
"""

from __future__ import annotations

import pytest

from cascadia_judge.aggregation import aggregate, concision_adjustment
from cascadia_judge.types import JudgeScore, JudgeVerdict, ShadowPair


def _pair(cheap: str = "A short.", expensive: str = "B short.") -> ShadowPair:
    return ShadowPair(
        request_id="req-1", prompt="p",
        cheap_model="cheap-m", cheap_response=cheap,
        expensive_model="expensive-m", expensive_response=expensive,
    )


def _verdict(score: float, *, conf: float = 0.8) -> JudgeVerdict:
    return JudgeVerdict(
        request_id="req-1", judge_name="pairwise_preference_v1",
        prompt_variant="pairwise/v1", model="judge-x", provider="fake",
        score=JudgeScore(score=score, confidence=conf, rationale=""),
        prompt_hash="h", elapsed_ms=10,
    )


def test_concision_adjustment_zero_weight_is_noop() -> None:
    assert concision_adjustment("short", "much longer response here", weight=0.0) == 0.0


def test_concision_adjustment_pushes_toward_shorter() -> None:
    # cheap is much shorter — positive adjustment (push toward cheap-wins).
    adj = concision_adjustment("a", "x" * 99, weight=0.15)
    assert adj > 0
    # Bounded by weight.
    assert adj <= 0.15


def test_concision_adjustment_symmetric() -> None:
    # If expensive is the shorter one, adjustment goes negative.
    a = concision_adjustment("a", "x" * 99, weight=0.15)
    b = concision_adjustment("x" * 99, "a", weight=0.15)
    assert a == pytest.approx(-b)


def test_concision_adjustment_empty_strings_safe() -> None:
    assert concision_adjustment("", "", weight=0.15) == 0.0


def test_aggregate_records_raw_and_adjustment() -> None:
    pair = _pair(cheap="hi", expensive="x" * 200)
    out = aggregate(pair, [_verdict(0.55)], concision_weight=0.15)
    assert out.score_raw == pytest.approx(0.55)
    assert out.concision_adjustment is not None
    assert out.concision_adjustment > 0  # cheap is short → positive
    # Adjusted score is base + adjustment, clamped to [0, 1].
    assert out.score == pytest.approx(min(1.0, 0.55 + out.concision_adjustment))


def test_aggregate_clamps_at_unit_interval() -> None:
    pair = _pair(cheap="hi", expensive="x" * 1000)
    out = aggregate(pair, [_verdict(0.98)], concision_weight=0.5)
    assert out.score == pytest.approx(1.0)
    assert out.score_raw == pytest.approx(0.98)


def test_aggregate_default_weight_zero_unchanged() -> None:
    # With concision_weight=0 (default), score_raw == score and the
    # adjustment is exactly 0 — backward compatibility.
    pair = _pair(cheap="hi", expensive="hello world")
    out = aggregate(pair, [_verdict(0.7)])
    assert out.score == out.score_raw == pytest.approx(0.7)
    assert out.concision_adjustment == 0.0
