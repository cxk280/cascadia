"""Unit tests for Kendall's τ + agreement metrics."""

from __future__ import annotations

import pytest

from cascadia_judge.calibration.metrics import (
    agreement_rate,
    cohens_kappa,
    compute_metrics,
    compute_multi_axis_metrics,
    kendall_tau,
    panel_internal_kappa,
)


def test_perfect_concordance_tau_one() -> None:
    xs = [0.1, 0.4, 0.7, 0.9]
    ys = [1, 2, 3, 4]
    assert kendall_tau(xs, ys) == pytest.approx(1.0)


def test_perfect_discordance_tau_minus_one() -> None:
    xs = [0.1, 0.4, 0.7, 0.9]
    ys = [4, 3, 2, 1]
    assert kendall_tau(xs, ys) == pytest.approx(-1.0)


def test_independent_zero_tau() -> None:
    # Symmetric pattern: any move is canceled.
    xs = [0.1, 0.9, 0.1, 0.9]
    ys = [0.0, 0.0, 1.0, 1.0]
    tau = kendall_tau(xs, ys)
    assert tau == pytest.approx(0.0, abs=0.1)


def test_zero_variance_returns_none() -> None:
    # All xs equal — no signal.
    assert kendall_tau([0.5, 0.5, 0.5], [1, 2, 3]) is None


def test_agreement_rate_perfect() -> None:
    scores = [0.9, 0.1, 0.5]
    labels = ["a", "b", "tie"]
    assert agreement_rate(scores, labels) == pytest.approx(1.0)


def test_agreement_rate_partial() -> None:
    # 0.9 -> a (match), 0.5 -> tie (mismatch with "b"), 0.1 -> b (match).
    scores = [0.9, 0.5, 0.1]
    labels = ["a", "b", "b"]
    assert agreement_rate(scores, labels) == pytest.approx(2 / 3)


def test_compute_metrics_synthetic() -> None:
    scores = [0.9, 0.8, 0.5, 0.2, 0.1]
    labels = ["a", "a", "tie", "b", "b"]
    m = compute_metrics(scores, labels)
    assert m.n == 5
    # τ-b denominator is inflated by the human "tie" label, so a perfectly
    # ordered prediction caps around 0.89 here, not 1.0.
    assert m.kendall_tau_b is not None and m.kendall_tau_b > 0.85
    assert m.agreement_rate == pytest.approx(1.0)
    assert m.judge_a_rate == pytest.approx(0.4)  # 2/5 ≥ 0.6
    assert m.judge_b_rate == pytest.approx(0.4)
    assert m.judge_tie_rate == pytest.approx(0.2)


# --- Task 3: multi-axis reporting -----------------------------------------


def test_cohens_kappa_perfect_agreement() -> None:
    assert cohens_kappa(["a", "b", "a", "tie"], ["a", "b", "a", "tie"]) == pytest.approx(1.0)


def test_cohens_kappa_undefined_single_category() -> None:
    # Both raters always pick "a" → expected agreement 1.0 → κ undefined.
    assert cohens_kappa(["a", "a"], ["a", "a"]) is None


def test_panel_internal_kappa_two_agreeing_judges() -> None:
    labels = {
        "judge-1": {"p1": "a", "p2": "b", "p3": "a"},
        "judge-2": {"p1": "a", "p2": "b", "p3": "a"},
    }
    assert panel_internal_kappa(labels) == pytest.approx(1.0)


def test_panel_internal_kappa_single_judge_is_none() -> None:
    assert panel_internal_kappa({"judge-1": {"p1": "a", "p2": "b"}}) is None


def test_panel_internal_kappa_aligns_on_common_pairs() -> None:
    # judge-2 covers a different (overlapping) set of pairs; κ is computed on
    # the {p2, p3} intersection where both agree → 1.0.
    labels = {
        "judge-1": {"p1": "a", "p2": "b", "p3": "a"},
        "judge-2": {"p2": "b", "p3": "a", "p4": "tie"},
    }
    assert panel_internal_kappa(labels) == pytest.approx(1.0)


def test_multi_axis_concision_and_completeness_diverge() -> None:
    # Concision pushes score by +adj, completeness by -adj. With these
    # adjustments the two axes reorder the pairs in opposite directions
    # relative to the human labels, so their τ-b have opposite sign — exactly
    # the verbosity-bias split a single τ-b would hide.
    raw_scores = [0.6, 0.5]
    concision_adjustments = [-0.3, 0.3]
    human_labels = ["a", "b"]
    m = compute_multi_axis_metrics(
        raw_scores, concision_adjustments, human_labels,
        concision_weight=0.30,
        panel_internal_kappa_value=0.42,
    )
    assert m.n == 2
    assert m.concision_weight == pytest.approx(0.30)
    assert m.tau_b_unweighted == pytest.approx(1.0)
    assert m.tau_b_concision_weighted == pytest.approx(-1.0)
    assert m.tau_b_completeness_weighted == pytest.approx(1.0)
    assert m.panel_internal_kappa == pytest.approx(0.42)


def test_multi_axis_empty_is_safe() -> None:
    m = compute_multi_axis_metrics([], [], [], concision_weight=0.3)
    assert m.n == 0
    assert m.tau_b_unweighted is None
    assert m.tau_b_concision_weighted is None
    assert m.tau_b_completeness_weighted is None
