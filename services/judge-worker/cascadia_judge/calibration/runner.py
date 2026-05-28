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

from cascadia_judge.aggregation import (
    EnsembleScore,
    aggregate,
    concision_adjustment,
)
from cascadia_judge.calibration.dataset import CalibrationPair
from cascadia_judge.calibration.metrics import (
    CalibrationMetrics,
    MultiAxisMetrics,
    _discretize,
    compute_metrics,
    compute_multi_axis_metrics,
    panel_internal_kappa,
)
from cascadia_judge.orchestrator import JudgeOrchestrator
from cascadia_judge.types import JudgeVerdict, ShadowPair

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


@dataclass(frozen=True)
class MultiAxisResult:
    rows: list[ScoredCalibrationRow]
    metrics: CalibrationMetrics
    multi_axis: MultiAxisMetrics

    def to_dict(self) -> dict[str, object]:
        return {
            "rows": [asdict(r) for r in self.rows],
            "metrics": asdict(self.metrics),
            "multi_axis": self.multi_axis.as_dict(),
        }


def _per_judge_label(
    verdicts: Sequence[JudgeVerdict],
    *,
    tie_window: tuple[float, float] = (0.4, 0.6),
) -> dict[str, str]:
    """One discretized label per judge *model* for a single pair.

    A model contributes the mean of its non-error verdict scores (averaging
    its pairwise + swapped + rubric variants), discretized into a/b/tie. Used
    to measure how much the judges in the panel agree with each other,
    independent of the human labels.
    """

    by_model: dict[str, list[float]] = {}
    for v in verdicts:
        if v.error:
            continue
        if v.score.score == 0.0 and v.score.confidence == 0.0 and "error" in (
            v.score.rationale or ""
        ).lower():
            continue
        by_model.setdefault(v.model, []).append(v.score.score)
    return {
        model: _discretize(sum(scores) / len(scores), tie_window)
        for model, scores in by_model.items()
        if scores
    }


async def run_multi_axis_calibration(
    dataset: Sequence[CalibrationPair],
    orchestrator: JudgeOrchestrator,
    *,
    judge_names: Sequence[str] | None = None,
    concision_weight: float = 0.30,
) -> MultiAxisResult:
    """Calibrate once, then report a τ-b *vector* instead of a single number.

    Each pair is evaluated a single time. From the cached verdicts we derive:
      - the neutral ensemble score (concision_weight = 0),
      - the concision delta at `concision_weight` (completeness = its reverse),
      - each judge model's label (for panel-internal κ).

    Default `concision_weight=0.30` is the *characterized* correction from the
    pilot (it improved panel-vs-human τ-b); it is deliberately not the runtime
    aggregation default, which stays 0.0 (see CLAUDE.md). Reporting both axes
    is the honest way to expose that knob rather than silently baking it in.
    """

    rows: list[ScoredCalibrationRow] = []
    raw_scores: list[float] = []
    concision_deltas: list[float] = []
    per_judge_labels: dict[str, dict[str, str]] = {}

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
        ensemble: EnsembleScore = aggregate(shadow, verdicts, pair_id=pair.id)
        raw = ensemble.score_raw if ensemble.score_raw is not None else ensemble.score
        delta = concision_adjustment(
            pair.response_a, pair.response_b, concision_weight,
        )
        raw_scores.append(raw)
        concision_deltas.append(delta)
        for model, label in _per_judge_label(verdicts).items():
            per_judge_labels.setdefault(model, {})[pair.id] = label
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

    human_labels = [r.human_label for r in rows]
    bias = [r.position_bias_estimate for r in rows if r.position_bias_estimate is not None]
    metrics = compute_metrics(
        [r.ensemble_score for r in rows], human_labels,
        position_bias_estimates=bias or None,
    )
    multi_axis = compute_multi_axis_metrics(
        raw_scores, concision_deltas, human_labels,
        concision_weight=concision_weight,
        panel_internal_kappa_value=panel_internal_kappa(per_judge_labels),
    )
    return MultiAxisResult(rows=rows, metrics=metrics, multi_axis=multi_axis)
