"""Direct unit tests for the LLM panel (run_panel + concision_sweep +
panel_vs_panel_agreement). Uses FakeLLMClient — no network."""

from __future__ import annotations

import json

import pytest

from cascadia_judge.calibration.dataset import CalibrationPair
from cascadia_judge.calibration.llm_panel import (
    concision_sweep,
    panel_vs_panel_agreement,
    run_panel,
)
from cascadia_judge.llm.fake import FakeLLMClient


def _pair(pair_id: str, label: str, *, a_len: int = 20, b_len: int = 20) -> CalibrationPair:
    return CalibrationPair(
        id=pair_id,
        prompt=f"prompt-{pair_id}",
        response_a="a" * a_len,
        response_b="b" * b_len,
        model_a="cheap-m",
        model_b="expensive-m",
        human_label=label,  # type: ignore[arg-type]
        category="cat",
    )


def _fake(model: str, *, score: float) -> FakeLLMClient:
    """A FakeLLMClient that always returns the same pairwise score."""
    c = FakeLLMClient(model=model)
    # The panel runs `pairwise_preference_v1` and (with swap)
    # `pairwise_preference_v1_swapped`. Each calls .chat() once per pair.
    # We don't know up front how many pairs the test will use; queue
    # plenty.
    for _ in range(200):
        c.queue(json.dumps({"score": score, "confidence": 0.85, "rationale": "fake"}))
    return c


@pytest.mark.asyncio
async def test_run_panel_basic_shape() -> None:
    pairs = [_pair("p1", "a"), _pair("p2", "b"), _pair("p3", "tie")]
    panel = {
        "fake/cheap": _fake("fake-cheap", score=0.7),
        "fake/expensive": _fake("fake-expensive", score=0.3),
    }
    report = await run_panel(pairs, panel=panel)
    assert len(report.rows) == 3
    # Per-model breakdown was computed for each panel entry.
    assert set(report.per_model_vs_human) == set(panel)
    # The bias-corrected panel score should be the *mean of the two model
    # scores* roughly — one says 0.7, the other 0.3, averaging to ~0.5.
    assert all(0.45 <= r.panel_score <= 0.55 for r in report.rows)


@pytest.mark.asyncio
async def test_run_panel_records_score_raw() -> None:
    pairs = [_pair("p1", "a", a_len=5, b_len=100)]
    panel = {"fake/m": _fake("fake-m", score=0.5)}
    report_no = await run_panel(pairs, panel=panel, concision_weight=0.0)
    report_yes = await run_panel(pairs, panel={"fake/m": _fake("fake-m", score=0.5)},
                                  concision_weight=0.3)
    # With cheap much shorter, weight>0 should push the adjusted score above
    # the raw 0.5 — but the raw is preserved separately.
    assert report_no.rows[0].panel_score_raw == pytest.approx(report_no.rows[0].panel_score)
    assert report_yes.rows[0].panel_score > report_yes.rows[0].panel_score_raw


@pytest.mark.asyncio
async def test_run_panel_unanimous_flag() -> None:
    pairs = [_pair("p1", "a"), _pair("p2", "b")]
    # Both judges return 0.8 on every pair → all on the same side of 0.5 → unanimous=True.
    panel = {
        "fake/x": _fake("fake-x", score=0.8),
        "fake/y": _fake("fake-y", score=0.85),
    }
    report = await run_panel(pairs, panel=panel)
    assert all(r.unanimous for r in report.rows)


@pytest.mark.asyncio
async def test_run_panel_empty_panel_rejects() -> None:
    with pytest.raises(ValueError):
        await run_panel([_pair("p1", "a")], panel={})


@pytest.mark.asyncio
async def test_run_panel_no_position_swap() -> None:
    pairs = [_pair("p1", "a")]
    panel = {"fake/x": _fake("fake-x", score=0.7)}
    report = await run_panel(pairs, panel=panel, include_position_swap=False)
    # Without swap, the per-model score is just the raw pairwise score.
    assert report.rows[0].per_model_scores["fake/x"] == pytest.approx(0.7)


@pytest.mark.asyncio
async def test_concision_sweep_post_hoc_changes_results() -> None:
    pairs = [
        _pair("p1", "a", a_len=5, b_len=100),
        _pair("p2", "b", a_len=100, b_len=5),
    ]
    panel = {"fake/m": _fake("fake-m", score=0.5)}
    report = await run_panel(pairs, panel=panel, concision_weight=0.0)
    sweep = concision_sweep(report, pairs, [0.0, 0.2, 0.5])
    # The sweep should produce three (weight, metrics) tuples.
    assert [w for w, _ in sweep] == [0.0, 0.2, 0.5]
    # At weight 0 the metrics should match the raw report's metrics.
    assert sweep[0][1].judge_tie_rate >= 0.5
    # At weight 0.5 with a length asymmetry, scores should swing meaningfully.
    # We can't predict the τ-b sign without knowing the labels but we can at
    # least confirm the rates change.
    assert sweep[2][1].judge_tie_rate != sweep[0][1].judge_tie_rate \
        or sweep[2][1].judge_a_rate != sweep[0][1].judge_a_rate \
        or sweep[2][1].judge_b_rate != sweep[0][1].judge_b_rate


@pytest.mark.asyncio
async def test_panel_vs_panel_agreement_single_judge_returns_none() -> None:
    pairs = [_pair("p1", "a")]
    panel = {"fake/m": _fake("fake-m", score=0.7)}
    report = await run_panel(pairs, panel=panel)
    # A single-judge panel has no other judges to compare against → None.
    assert panel_vs_panel_agreement(report) is None


@pytest.mark.asyncio
async def test_panel_vs_panel_agreement_two_judges() -> None:
    pairs = [_pair(f"p{i}", "a") for i in range(4)]
    panel = {
        "fake/x": _fake("fake-x", score=0.7),
        "fake/y": _fake("fake-y", score=0.7),
    }
    report = await run_panel(pairs, panel=panel)
    # With both judges returning the same score on every pair, τ should
    # be undefined (all xs identical → zero variance → None).
    assert panel_vs_panel_agreement(report) is None


@pytest.mark.asyncio
async def test_report_as_dict_serialisable() -> None:
    pairs = [_pair("p1", "a")]
    panel = {"fake/m": _fake("fake-m", score=0.6)}
    report = await run_panel(pairs, panel=panel)
    d = report.as_dict()
    # JSON-roundtrips cleanly.
    json.dumps(d, default=str)
    assert "panel_vs_human" in d
    assert "per_model_vs_human" in d
    assert "rows" in d
    assert len(d["rows"]) == 1
    assert "panel_score_raw" in d["rows"][0]
