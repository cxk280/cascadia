"""Agreement metrics: Kendall's τ-b (with tie correction), simple agreement,
and a per-pair position-bias summary.

We roll Kendall's τ-b by hand rather than depending on scipy. The
calibration set is small (~hundreds of pairs); O(n²) is fine and shipping
without scipy keeps the judge-worker dependency surface minimal (per
SOLID.md §8: "no provider SDK imports outside the LLM adapter layer" —
similar spirit applies to keeping the runtime lean).

Definitions used:

  Concordant pair (i, j): sign(x_i - x_j) == sign(y_i - y_j) and both ≠ 0.
  Discordant pair (i, j): sign(x_i - x_j) == -sign(y_i - y_j) and both ≠ 0.
  Tied-in-x: x_i == x_j.   Tied-in-y: y_i == y_j.

  τ-b = (C - D) / sqrt((C + D + T_x) * (C + D + T_y))

  where T_x = # pairs tied in x only, T_y = # pairs tied in y only.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# Human label → ordinal so we can run Kendall's τ over it.
_LABEL_TO_ORDINAL: Mapping[str, float] = {"a": 1.0, "tie": 0.5, "b": 0.0}


@dataclass(frozen=True)
class CalibrationMetrics:
    n: int
    kendall_tau_b: float | None  # None if undefined (zero variance)
    agreement_rate: float        # fraction where rounded judge label == human
    position_bias_mean: float | None  # mean |p+q-1| across pairs that had a swap-pair
    judge_a_rate: float          # fraction where ensemble strongly favored A (≥0.6)
    judge_b_rate: float          # fraction where ensemble strongly favored B (≤0.4)
    judge_tie_rate: float        # fraction in [0.4, 0.6]
    human_a_rate: float
    human_b_rate: float
    human_tie_rate: float


def kendall_tau(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Kendall's τ-b on real-valued sequences.

    Returns None when the denominator is zero (e.g., all xs equal — no signal
    to compare against).
    """

    if len(xs) != len(ys):
        raise ValueError(f"length mismatch: {len(xs)} vs {len(ys)}")
    n = len(xs)
    if n < 2:
        return None

    concordant = 0
    discordant = 0
    tied_x = 0
    tied_y = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx = xs[i] - xs[j]
            dy = ys[i] - ys[j]
            if dx == 0 and dy == 0:
                # Tied in both — contributes to neither numerator nor denominator.
                continue
            if dx == 0:
                tied_x += 1
                continue
            if dy == 0:
                tied_y += 1
                continue
            if (dx > 0) == (dy > 0):
                concordant += 1
            else:
                discordant += 1

    denom = math.sqrt((concordant + discordant + tied_x) * (concordant + discordant + tied_y))
    if denom == 0:
        return None
    return (concordant - discordant) / denom


def agreement_rate(
    judge_scores: Sequence[float],
    human_labels: Sequence[str],
    *,
    tie_window: tuple[float, float] = (0.4, 0.6),
) -> float:
    """Fraction where ensemble's discretized label matches the human label.

    Discretization: score ≥ tie_window[1] → "a"; score ≤ tie_window[0] → "b";
    otherwise → "tie".
    """

    if len(judge_scores) != len(human_labels):
        raise ValueError(
            f"length mismatch: scores={len(judge_scores)} labels={len(human_labels)}"
        )
    if not judge_scores:
        return 0.0
    matches = 0
    for s, h in zip(judge_scores, human_labels):
        if _discretize(s, tie_window) == h:
            matches += 1
    return matches / len(judge_scores)


def compute_metrics(
    judge_scores: Sequence[float],
    human_labels: Sequence[str],
    *,
    position_bias_estimates: Sequence[float] | None = None,
    tie_window: tuple[float, float] = (0.4, 0.6),
) -> CalibrationMetrics:
    if len(judge_scores) != len(human_labels):
        raise ValueError("scores and labels must align")
    n = len(judge_scores)
    if n == 0:
        return CalibrationMetrics(
            n=0, kendall_tau_b=None, agreement_rate=0.0,
            position_bias_mean=None,
            judge_a_rate=0.0, judge_b_rate=0.0, judge_tie_rate=0.0,
            human_a_rate=0.0, human_b_rate=0.0, human_tie_rate=0.0,
        )

    human_numeric = [_LABEL_TO_ORDINAL[h] for h in human_labels]
    tau = kendall_tau(list(judge_scores), human_numeric)
    agree = agreement_rate(judge_scores, human_labels, tie_window=tie_window)

    judge_labels = [_discretize(s, tie_window) for s in judge_scores]
    judge_a = judge_labels.count("a") / n
    judge_b = judge_labels.count("b") / n
    judge_tie = judge_labels.count("tie") / n
    human_a = human_labels.count("a") / n
    human_b = human_labels.count("b") / n
    human_tie = human_labels.count("tie") / n

    if position_bias_estimates:
        pos = [p for p in position_bias_estimates if p is not None]
        bias_mean = sum(pos) / len(pos) if pos else None
    else:
        bias_mean = None

    return CalibrationMetrics(
        n=n,
        kendall_tau_b=tau,
        agreement_rate=agree,
        position_bias_mean=bias_mean,
        judge_a_rate=judge_a, judge_b_rate=judge_b, judge_tie_rate=judge_tie,
        human_a_rate=human_a, human_b_rate=human_b, human_tie_rate=human_tie,
    )


def _discretize(score: float, tie_window: tuple[float, float]) -> str:
    low, high = tie_window
    if score >= high:
        return "a"
    if score <= low:
        return "b"
    return "tie"


# ---------------------------------------------------------------------------
# Multi-axis reporting (Task 3 — quality vector, not a single number).
#
# The 30-pair pilot reported one τ-b and it landed ≈ 0, which reads as "the
# judge is worthless" when the real story is subtler: the panel and humans
# *agree on which answer is more complete* but *split on whether brevity or
# completeness is "better"*. A single τ-b collapses that distinction. Here we
# report the same agreement under three quality priors — neutral, concision-
# weighted, completeness-weighted — plus the panel's internal κ, so the
# operator can see which dimension the judge actually tracks and pick the one
# to optimize. The concision adjustment is linear in its weight, so the
# completeness axis is just the concision adjustment applied in reverse; no
# extra LLM calls are needed beyond the single evaluation pass.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MultiAxisMetrics:
    n: int
    concision_weight: float
    tau_b_unweighted: float | None
    tau_b_concision_weighted: float | None
    tau_b_completeness_weighted: float | None
    panel_internal_kappa: float | None  # mean pairwise Cohen's κ across judge models

    def as_dict(self) -> dict[str, object]:
        return {
            "n": self.n,
            "concision_weight": self.concision_weight,
            "tau_b_unweighted": self.tau_b_unweighted,
            "tau_b_concision_weighted": self.tau_b_concision_weighted,
            "tau_b_completeness_weighted": self.tau_b_completeness_weighted,
            "panel_internal_kappa": self.panel_internal_kappa,
        }


def cohens_kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    """Two-rater Cohen's κ over categorical labels on the same items.

    Returns None when expected agreement is 1.0 (zero denominator — both
    raters always pick the same single category) or when there are no items.
    """

    if len(a) != len(b):
        raise ValueError("rater sequences must align")
    n = len(a)
    if n == 0:
        return None
    categories = set(a) | set(b)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pe = 0.0
    for cat in categories:
        pe += (a.count(cat) / n) * (b.count(cat) / n)
    denom = 1.0 - pe
    if abs(denom) < 1e-12:
        return None
    return (po - pe) / denom


def panel_internal_kappa(
    per_judge_labels: Mapping[str, Mapping[str, str]],
) -> float | None:
    """Mean pairwise Cohen's κ across judge models in the panel.

    `per_judge_labels` maps judge model name → `{pair_id: discretized_label}`.
    Judges need not cover the same pairs — each judge pair is compared over the
    intersection of pair_ids they both labeled (mirroring how the human-rater
    κ is computed in `aggregator`). Judge pairs sharing fewer than two items,
    or whose κ is undefined, are skipped. Returns None when no judge pair
    yields a defined κ (e.g., a one-judge panel).
    """

    judges = sorted(per_judge_labels)
    if len(judges) < 2:
        return None
    kappas: list[float] = []
    for i, ja in enumerate(judges):
        for jb in judges[i + 1 :]:
            common = sorted(set(per_judge_labels[ja]) & set(per_judge_labels[jb]))
            if len(common) < 2:
                continue
            la = [per_judge_labels[ja][pid] for pid in common]
            lb = [per_judge_labels[jb][pid] for pid in common]
            k = cohens_kappa(la, lb)
            if k is not None:
                kappas.append(k)
    if not kappas:
        return None
    return sum(kappas) / len(kappas)


def compute_multi_axis_metrics(
    raw_scores: Sequence[float],
    concision_adjustments: Sequence[float],
    human_labels: Sequence[str],
    *,
    concision_weight: float,
    panel_internal_kappa_value: float | None = None,
) -> MultiAxisMetrics:
    """Compute τ-b under neutral / concision / completeness quality priors.

    `raw_scores` are the un-adjusted ensemble scores (one per pair).
    `concision_adjustments` is the signed concision delta per pair at
    `concision_weight` (see `aggregation.concision_adjustment`). The
    completeness axis is that delta reversed — rewarding the more thorough
    answer instead of the briefer one.
    """

    if not (len(raw_scores) == len(concision_adjustments) == len(human_labels)):
        raise ValueError("raw_scores, concision_adjustments, human_labels must align")
    n = len(raw_scores)
    if n == 0:
        return MultiAxisMetrics(
            n=0, concision_weight=concision_weight,
            tau_b_unweighted=None,
            tau_b_concision_weighted=None,
            tau_b_completeness_weighted=None,
            panel_internal_kappa=panel_internal_kappa_value,
        )

    human_numeric = [_LABEL_TO_ORDINAL[h] for h in human_labels]
    concise = [
        max(0.0, min(1.0, s + adj)) for s, adj in zip(raw_scores, concision_adjustments)
    ]
    complete = [
        max(0.0, min(1.0, s - adj)) for s, adj in zip(raw_scores, concision_adjustments)
    ]
    return MultiAxisMetrics(
        n=n,
        concision_weight=concision_weight,
        tau_b_unweighted=kendall_tau(list(raw_scores), human_numeric),
        tau_b_concision_weighted=kendall_tau(concise, human_numeric),
        tau_b_completeness_weighted=kendall_tau(complete, human_numeric),
        panel_internal_kappa=panel_internal_kappa_value,
    )
