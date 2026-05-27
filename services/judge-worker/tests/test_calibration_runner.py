"""End-to-end calibration run against the golden_v0 set + scripted fixture.

Asserts the Phase 5 acceptance criterion: Kendall's τ-b ≥ 0.7. Runs
offline — no network — by routing through `ScriptedLLMClient` keyed on
(judge_name, request_id[#sub]).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cascadia_judge.calibration import load_dataset, run_calibration
from cascadia_judge.executor import AsyncioJudgeExecutor
from cascadia_judge.judges import REGISTRY
from cascadia_judge.llm.scripted import ScriptedLLMClient
from cascadia_judge.orchestrator import JudgeOrchestrator

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "calibration" / "golden_v0.jsonl"
FIXTURE = ROOT / "calibration" / "scripted_v0.json"


@pytest.mark.asyncio
async def test_golden_v0_meets_phase5_acceptance() -> None:
    dataset = load_dataset(GOLDEN)
    assert len(dataset) == 15

    client = ScriptedLLMClient(FIXTURE)
    orchestrator = JudgeOrchestrator(
        registry=REGISTRY,
        executor=AsyncioJudgeExecutor(),
        llm_factory=lambda _judge: client,
    )

    result = await run_calibration(dataset, orchestrator)

    # Phase 5 acceptance.
    tau = result.metrics.kendall_tau_b
    assert tau is not None, "expected Kendall's τ-b to be defined on golden set"
    assert tau >= 0.7, f"τ-b={tau:.3f} fell below the 0.7 Phase-5 threshold"

    # Sanity: ensemble agrees with humans on a clear majority of pairs.
    assert result.metrics.agreement_rate >= 0.6

    # No self-preference filtering should fire — neither model name appears
    # in the scripted judge's `model` field ("scripted-judge").
    assert all(r.n_dropped_self_pref == 0 for r in result.rows)

    # Position-bias estimates were computed; verify the mean is small (our
    # synthetic fixture is roughly unbiased by construction).
    assert result.metrics.position_bias_mean is not None
    assert result.metrics.position_bias_mean < 0.1
