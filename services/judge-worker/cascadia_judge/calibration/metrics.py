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
