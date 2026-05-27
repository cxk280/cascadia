"""Unit tests for Kendall's τ + agreement metrics."""

from __future__ import annotations

import pytest

from cascadia_judge.calibration.metrics import (
    agreement_rate,
    compute_metrics,
    kendall_tau,
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
