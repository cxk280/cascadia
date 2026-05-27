"""Run the judge ensemble across a calibration dataset and report metrics.

This is offline: each `CalibrationPair` is wrapped in a `ShadowPair` (cheap
= response_a, expensive = response_b, prompt = pair.prompt) and run through
the orchestrator. The resulting verdicts are aggregated into an
`EnsembleScore`, scores are paired with human labels, and Kendall's τ is
computed.

A scored row is returned per pair so the CLI can persist a CSV/JSONL report
suitable for plotting or for ad-hoc inspection.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from cascadia_judge.aggregation import EnsembleScore, aggregate
from cascadia_judge.calibration.dataset import CalibrationPair
from cascadia_judge.calibration.metrics import CalibrationMetrics, compute_metrics
from cascadia_judge.orchestrator import JudgeOrchestrator
from cascadia_judge.types import ShadowPair

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScoredCalibrationRow:
    pair_id: str
    category: str
    source: str
    human_label: str
    ensemble_score: float
    ensemble_confidence: float
    position_bias_estimate: float | None
    n_verdicts_in: int
    n_used: int
    n_dropped_self_pref: int
    n_failed: int
    contributing_models: list[str]


@dataclass(frozen=True)
class CalibrationResult:
    rows: list[ScoredCalibrationRow]
    metrics: CalibrationMetrics

    def to_dict(self) -> dict[str, object]:
        return {
            "rows": [asdict(r) for r in self.rows],
            "metrics": asdict(self.metrics),
        }


async def run_calibration(
    dataset: Sequence[CalibrationPair],
    orchestrator: JudgeOrchestrator,
    *,
    judge_names: Sequence[str] | None = None,
    concision_weight: float = 0.0,
) -> CalibrationResult:
    rows: list[ScoredCalibrationRow] = []
    for pair in dataset:
        shadow = ShadowPair(
            request_id=pair.id,
            prompt=pair.prompt,
            cheap_model=pair.model_a,
            cheap_response=pair.response_a,
            expensive_model=pair.model_b,
            expensive_response=pair.response_b,
            cluster_id=pair.category,
        )
        verdicts = await orchestrator.evaluate(shadow, judge_names=judge_names)
        ensemble: EnsembleScore = aggregate(
            shadow, verdicts, pair_id=pair.id,
            concision_weight=concision_weight,
        )
        rows.append(
            ScoredCalibrationRow(
                pair_id=pair.id,
                category=pair.category,
                source=pair.source,
                human_label=pair.human_label,
                ensemble_score=ensemble.score,
                ensemble_confidence=ensemble.confidence,
                position_bias_estimate=ensemble.position_bias_estimate,
                n_verdicts_in=ensemble.n_verdicts_in,
                n_used=ensemble.n_used,
                n_dropped_self_pref=ensemble.n_dropped_self_pref,
                n_failed=ensemble.n_failed,
                contributing_models=ensemble.contributing_models,
            )
        )
        log.debug(
            "calibrated pair=%s human=%s ensemble=%.3f (used=%d, self_pref=%d)",
            pair.id, pair.human_label, ensemble.score,
            ensemble.n_used, ensemble.n_dropped_self_pref,
        )

    judge_scores = [r.ensemble_score for r in rows]
    human_labels = [r.human_label for r in rows]
    bias = [r.position_bias_estimate for r in rows if r.position_bias_estimate is not None]
    metrics = compute_metrics(
        judge_scores, human_labels, position_bias_estimates=bias or None,
    )
    return CalibrationResult(rows=rows, metrics=metrics)
