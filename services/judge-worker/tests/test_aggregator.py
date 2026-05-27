"""Unit tests for the calibration label aggregator.

Targets:
  - Position un-swap inverts a/b but leaves tie/unknown alone.
  - Attention-check failures count, reviewers above the threshold get dropped.
  - Cohen's κ on two reviewers with synthetic overlap.
  - Canonical JSONL rows have the schema the existing harness consumes.
"""

from __future__ import annotations

import pytest

from cascadia_judge.calibration.aggregator import (
    NormalisedLabel,
    PairLabel,
    aggregate_labels,
    unswap,
    _cohens_kappa,
)


def _pair(
    pair_id: str,
    *,
    labels: list[NormalisedLabel],
    attention: str | None = None,
    cluster: str = "math",
) -> PairLabel:
    return PairLabel(
        pair_id=pair_id,
        source=f"synthetic:{pair_id}",
        prompt="p",
        response_a="A",
        response_b="B",
        model_a="cheap-m",
        model_b="expensive-m",
        cluster_id=cluster,
        attention_check_answer=attention,
        labels=labels,
    )


def _label(reviewer: str, label: str, *, raw: str | None = None, swapped: bool = False) -> NormalisedLabel:
    return NormalisedLabel(
        reviewer_id=reviewer,
        label=label,  # type: ignore[arg-type]
        raw_label=(raw or label),  # type: ignore[arg-type]
        shown_swapped=swapped,
        time_ms=None,
        rationale=None,
    )


def test_unswap_flips_a_and_b() -> None:
    assert unswap("a", True) == "b"
    assert unswap("b", True) == "a"
    assert unswap("tie", True) == "tie"
    assert unswap("unknown", True) == "unknown"
    assert unswap("a", False) == "a"


def test_consensus_unanimous() -> None:
    pairs = [
        _pair("p1", labels=[_label("chris", "a"), _label("alex", "a")]),
        _pair("p2", labels=[_label("chris", "b"), _label("alex", "b")]),
    ]
    report, rows = aggregate_labels(pairs)
    assert report.n_pairs_with_consensus == 2
    assert report.n_pairs_disagreement == 0
    assert {r["id"] for r in rows} == {"p1", "p2"}
    assert {r["human_label"] for r in rows} == {"a", "b"}


def test_consensus_disagreement_falls_back_to_tie() -> None:
    pairs = [
        _pair("p1", labels=[_label("chris", "a"), _label("alex", "b")]),
    ]
    report, rows = aggregate_labels(pairs)
    assert report.n_pairs_disagreement == 1
    assert rows[0]["human_label"] == "tie"
    # Both reviewers picked an unambiguous side; neither actually picked
    # "tie", so consensus_strength of the synthesized "tie" is 0. This is
    # the honest reading — the row is informative as a disagreement
    # outlier, not as a tie endorsement.
    assert rows[0]["consensus_strength"] == 0.0


def test_attention_check_pairs_excluded_from_canonical() -> None:
    pairs = [
        _pair("attn-1", labels=[_label("chris", "a"), _label("alex", "a")], attention="a"),
        _pair("real-1", labels=[_label("chris", "b"), _label("alex", "b")]),
    ]
    report, rows = aggregate_labels(pairs)
    # Only the real pair is in canonical output.
    assert len(rows) == 1
    assert rows[0]["id"] == "real-1"
    # Attention pair counted as excluded.
    assert report.n_pairs_excluded == 1


def test_attention_check_failure_drops_reviewer() -> None:
    pairs = [
        # `alex` fails both attention checks → dropped.
        _pair("attn-1", labels=[_label("chris", "a"), _label("alex", "b")], attention="a"),
        _pair("attn-2", labels=[_label("chris", "tie"), _label("alex", "a")], attention="tie"),
        _pair("real-1", labels=[_label("chris", "a"), _label("alex", "b")]),
        _pair("real-2", labels=[_label("chris", "b"), _label("alex", "a")]),
    ]
    report, rows = aggregate_labels(pairs, attention_failure_max=1)
    alex = next(r for r in report.reviewers if r.reviewer_id == "alex")
    chris = next(r for r in report.reviewers if r.reviewer_id == "chris")
    assert alex.dropped is True
    assert alex.n_attention_failed == 2
    assert chris.dropped is False
    # With alex dropped, chris's labels stand alone — consensus = chris's pick.
    assert {r["id"]: r["human_label"] for r in rows} == {"real-1": "a", "real-2": "b"}


def test_unknown_labels_excluded_from_consensus() -> None:
    pairs = [
        _pair("p1", labels=[_label("chris", "a"), _label("alex", "unknown")]),
    ]
    report, rows = aggregate_labels(pairs)
    # Only chris contributed a usable label → consensus = "a".
    assert rows[0]["human_label"] == "a"
    assert rows[0]["n_reviewers"] == 1


def test_cohens_kappa_perfect_agreement() -> None:
    # All 6 pairs agree; categories are 'a' and 'b'.
    k = _cohens_kappa(
        ["a", "a", "b", "b", "a", "b"],
        ["a", "a", "b", "b", "a", "b"],
    )
    assert k == pytest.approx(1.0)


def test_cohens_kappa_chance_agreement() -> None:
    # Two reviewers picking near-randomly — observed agreement on 3/6 = 0.5
    # against expected agreement 0.5 yields κ ≈ 0. This is the canonical
    # "reviewers are no better than chance" reading.
    a = ["a", "b", "a", "b", "a", "b"]
    b = ["a", "a", "b", "b", "a", "a"]
    k = _cohens_kappa(a, b)
    assert k == pytest.approx(0.0, abs=0.01)


def test_kappa_undefined_when_one_category() -> None:
    # Both reviewers always pick 'a' — expected agreement is 1, κ undefined.
    k = _cohens_kappa(["a", "a", "a"], ["a", "a", "a"])
    assert k is None
