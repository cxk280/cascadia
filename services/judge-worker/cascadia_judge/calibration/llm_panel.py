"""Run a panel of N strong LLMs as the "synthetic gold standard" backstop.

Most LLM calibration setups use one judge model. The panel-of-judges
pattern (Hugging Face Open LLM Leaderboard, Chatbot Arena's elo-style
panel) is the consensus check: if 3 different top-tier models, each with
different training data and biases, all agree on the same label, you
have a much stronger prior than any single judge.

For Cascadia the panel is *not* the primary signal — humans are. The
panel:

  1. Provides an audit trail when humans label a pair: did the panel
     agree? If not, the pair is likely ambiguous and worth flagging in
     the rubric.
  2. Lets us *cheaply* extend the calibration set when scaling up beyond
     the budget for human reviewers. A pair where the panel unanimously
     agrees can stand in for a single human label.
  3. Provides a model-vs-model agreement number for the methodology blog.

Cost estimate: 200 pairs × 3 models × ~$0.01 per pairwise call ≈ $6.

The panel does NOT use rubric judges — pairwise only — both to keep
costs down and because adding the rubric variant doubles call count for
marginal signal.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from cascadia_judge.aggregation import aggregate, concision_adjustment
from cascadia_judge.calibration.dataset import CalibrationPair
from cascadia_judge.calibration.metrics import (
    CalibrationMetrics,
    compute_metrics,
    kendall_tau,
)
from cascadia_judge.judges.pairwise_preference import PairwisePreferenceJudge
from cascadia_judge.judges.pairwise_swapped import PairwisePreferenceSwappedJudge
from cascadia_judge.llm.base import LLMClient
from cascadia_judge.types import JudgeVerdict, ShadowPair

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PanelResult:
    pair_id: str
    human_label: str
    panel_score: float                 # bias-corrected consensus across models
    panel_score_raw: float             # consensus BEFORE concision adjustment
    per_model_scores: dict[str, float]
    unanimous: bool                    # all models on the same side of 0.5


@dataclass(frozen=True)
class PanelReport:
    rows: list[PanelResult]
    panel_vs_human: CalibrationMetrics
    per_model_vs_human: Mapping[str, CalibrationMetrics] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "panel_vs_human": _metrics_to_dict(self.panel_vs_human),
            "per_model_vs_human": {
                model: _metrics_to_dict(m) for model, m in self.per_model_vs_human.items()
            },
            "rows": [
                {
                    "pair_id": r.pair_id,
                    "human_label": r.human_label,
                    "panel_score": r.panel_score,
                    "panel_score_raw": r.panel_score_raw,
                    "per_model_scores": r.per_model_scores,
                    "unanimous": r.unanimous,
                }
                for r in self.rows
            ],
        }


async def run_panel(
    dataset: Sequence[CalibrationPair],
    *,
    panel: Mapping[str, LLMClient],
    include_position_swap: bool = True,
    concision_weight: float = 0.0,
) -> PanelReport:
    """Score the canonical dataset with each panel model and report.

    `panel` is a mapping `display_name → LLMClient`. The display name is
    what shows up in the per-model report.

    `include_position_swap` runs each model in both un-swapped and swapped
    configurations and averages — the same position-bias correction the
    main judge ensemble uses. Doubles cost but the correction matters at
    this scale.

    `concision_weight` (Phase 5.2) applies a length-normalized concision
    penalty to the panel consensus score. Default 0.0 preserves prior
    behavior. The penalty pushes the panel score toward whichever response
    is shorter — Phase 5 calibration found LLM judges have a verbosity
    bias on common Q&A that the bias-corrected pairwise + rubric judges
    don't fix on their own.
    """

    if not panel:
        raise ValueError("panel must not be empty")

    rows: list[PanelResult] = []
    per_model_score_lists: dict[str, list[float]] = {name: [] for name in panel}
    human_labels: list[str] = []

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
        verdicts: list[JudgeVerdict] = []
        per_model_score: dict[str, float] = {}
        for name, client in panel.items():
            tasks = [PairwisePreferenceJudge(client).judge(shadow)]
            if include_position_swap:
                tasks.append(PairwisePreferenceSwappedJudge(client).judge(shadow))
            model_verdicts = await asyncio.gather(*tasks)
            verdicts.extend(model_verdicts)
            # Per-model score = the bias-corrected average of un-swapped
            # and swapped *for this model* (matches the aggregation
            # logic but scoped to one model so we can report per-model
            # numbers).
            if include_position_swap:
                per_model_score[name] = (model_verdicts[0].score.score + model_verdicts[1].score.score) / 2.0
            else:
                per_model_score[name] = model_verdicts[0].score.score

        ensemble = aggregate(
            shadow, verdicts, pair_id=pair.id,
            concision_weight=concision_weight,
        )
        unanimous = (
            all(s >= 0.5 for s in per_model_score.values())
            or all(s <= 0.5 for s in per_model_score.values())
        )
        rows.append(PanelResult(
            pair_id=pair.id,
            human_label=pair.human_label,
            panel_score=ensemble.score,
            panel_score_raw=ensemble.score_raw if ensemble.score_raw is not None else ensemble.score,
            per_model_scores=per_model_score,
            unanimous=unanimous,
        ))
        for name, s in per_model_score.items():
            per_model_score_lists[name].append(s)
        human_labels.append(pair.human_label)

    panel_scores = [r.panel_score for r in rows]
    panel_vs_human = compute_metrics(panel_scores, human_labels)

    per_model_metrics: dict[str, CalibrationMetrics] = {}
    for name, scores in per_model_score_lists.items():
        per_model_metrics[name] = compute_metrics(scores, human_labels)

    return PanelReport(
        rows=rows,
        panel_vs_human=panel_vs_human,
        per_model_vs_human=per_model_metrics,
    )


def concision_sweep(
    report: PanelReport,
    dataset: Sequence[CalibrationPair],
    weights: Sequence[float],
) -> list[tuple[float, CalibrationMetrics]]:
    """Apply concision penalty post-hoc at each weight; recompute metrics.

    The expensive part of a panel run is the LLM calls. The concision
    adjustment is a pure-Python shift on the raw consensus score, so we can
    sweep across weights without re-calling any provider. Used by
    `cascadia-judge-llm-panel --concision-sweep`.
    """

    by_id = {p.id: p for p in dataset}
    out: list[tuple[float, CalibrationMetrics]] = []
    for w in weights:
        scores: list[float] = []
        humans: list[str] = []
        for r in report.rows:
            pair = by_id.get(r.pair_id)
            if pair is None:
                continue
            adj = concision_adjustment(pair.response_a, pair.response_b, w)
            scores.append(max(0.0, min(1.0, r.panel_score_raw + adj)))
            humans.append(r.human_label)
        out.append((w, compute_metrics(scores, humans)))
    return out


def panel_vs_panel_agreement(report: PanelReport) -> float | None:
    """Cross-model Kendall's τ — measures whether the panel members
    actually agree with each other. Low here means the panel is just
    averaging noise; consider expanding it or swapping a model out.
    """

    model_names = sorted(set().union(*(r.per_model_scores.keys() for r in report.rows)))
    if len(model_names) < 2:
        return None
    taus: list[float] = []
    for i, a in enumerate(model_names):
        for b in model_names[i + 1 :]:
            xs = [r.per_model_scores[a] for r in report.rows if a in r.per_model_scores and b in r.per_model_scores]
            ys = [r.per_model_scores[b] for r in report.rows if a in r.per_model_scores and b in r.per_model_scores]
            t = kendall_tau(xs, ys)
            if t is not None:
                taus.append(t)
    if not taus:
        return None
    return sum(taus) / len(taus)


def _metrics_to_dict(m: CalibrationMetrics) -> dict[str, object]:
    return {
        "n": m.n,
        "kendall_tau_b": m.kendall_tau_b,
        "agreement_rate": m.agreement_rate,
        "position_bias_mean": m.position_bias_mean,
        "judge_a_rate": m.judge_a_rate,
        "judge_b_rate": m.judge_b_rate,
        "judge_tie_rate": m.judge_tie_rate,
        "human_a_rate": m.human_a_rate,
        "human_b_rate": m.human_b_rate,
        "human_tie_rate": m.human_tie_rate,
    }
