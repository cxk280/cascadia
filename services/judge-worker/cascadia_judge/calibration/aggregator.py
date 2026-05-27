"""Turn raw `calibration_labels` rows into the canonical JSONL the existing
calibration harness consumes.

Three transforms applied:

1. **Position un-swap.** Labels carry `shown_swapped` — reviewers who saw
   the responses in slot A/B swapped have their `raw_label` un-swapped
   here so the final canonical label is always "did *response_a* (the
   cheap-tier-style response) win". This is the cardinal correctness rule;
   skip it and the human labels point the wrong way half the time.

2. **Attention-check filtering.** Reviewers who failed an attention-check
   pair (picked something other than the documented correct answer) are
   flagged. The aggregator surfaces the failure count per reviewer; a
   reviewer above the failure threshold is dropped from the canonical
   aggregation (their labels still live in the DB for audit).

3. **Inter-rater agreement.** For pairs with ≥2 reviewers, compute Cohen's
   κ pairwise across reviewers and report the average. Below κ = 0.5 the
   labeling task is broken (rubric ambiguity or reviewer confusion).

The canonical JSONL output matches the shape `cascadia_judge.calibration.
dataset.CalibrationPair` consumes — same field names, same valid label
strings — so the existing `cascadia-judge-calibrate` CLI works against it
unchanged.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import asyncpg

log = logging.getLogger(__name__)

Label = Literal["a", "b", "tie", "unknown"]
_VALID_FINAL_LABELS: set[str] = {"a", "b", "tie"}


@dataclass(frozen=True)
class ReviewerStats:
    reviewer_id: str
    n_labels: int
    n_attention_passed: int
    n_attention_failed: int
    avg_time_ms: float | None
    dropped: bool
    drop_reason: str | None = None


@dataclass(frozen=True)
class AggregationReport:
    n_pairs_total: int
    n_pairs_with_consensus: int
    n_pairs_disagreement: int
    n_pairs_excluded: int     # all-reviewers-dropped, or unknown-only labels
    cohens_kappa_mean: float | None
    reviewers: list[ReviewerStats] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "n_pairs_total": self.n_pairs_total,
            "n_pairs_with_consensus": self.n_pairs_with_consensus,
            "n_pairs_disagreement": self.n_pairs_disagreement,
            "n_pairs_excluded": self.n_pairs_excluded,
            "cohens_kappa_mean": self.cohens_kappa_mean,
            "reviewers": [
                {
                    "reviewer_id": r.reviewer_id,
                    "n_labels": r.n_labels,
                    "n_attention_passed": r.n_attention_passed,
                    "n_attention_failed": r.n_attention_failed,
                    "avg_time_ms": r.avg_time_ms,
                    "dropped": r.dropped,
                    "drop_reason": r.drop_reason,
                }
                for r in self.reviewers
            ],
        }


@dataclass(frozen=True)
class PairLabel:
    pair_id: str
    source: str
    prompt: str
    response_a: str
    response_b: str
    model_a: str | None
    model_b: str | None
    cluster_id: str | None
    attention_check_answer: str | None
    labels: list["NormalisedLabel"]


@dataclass(frozen=True)
class NormalisedLabel:
    reviewer_id: str
    label: Label                 # already un-swapped
    raw_label: Label             # what the reviewer clicked, pre-unswap
    shown_swapped: bool
    time_ms: int | None
    rationale: str | None


def unswap(raw: Label, shown_swapped: bool) -> Label:
    """If the reviewer saw the responses swapped, flip the label so it
    refers to the canonical response_a / response_b ordering."""
    if not shown_swapped:
        return raw
    if raw == "a":
        return "b"
    if raw == "b":
        return "a"
    return raw  # 'tie' / 'unknown' are direction-independent


def aggregate_labels(
    pairs: Sequence[PairLabel],
    *,
    attention_failure_max: int = 1,
    min_reviewers_for_consensus: int = 1,
) -> tuple[AggregationReport, list[dict[str, object]]]:
    """Reduce raw labels to consensus per pair + a report on reviewer quality.

    `attention_failure_max` is the number of attention-check misses a
    reviewer is allowed before being dropped. Default 1 (an extremely
    lenient threshold appropriate for the friend-and-me pilot — for paid
    reviewers we'd tighten to 0).

    Returns `(report, canonical_rows)`. `canonical_rows` are dicts that
    match the JSONL schema the existing calibration harness consumes.
    """

    reviewer_failures, reviewer_passes, reviewer_times, reviewer_label_counts = (
        _per_reviewer_quality(pairs)
    )
    dropped: dict[str, str] = {}
    for reviewer_id, fails in reviewer_failures.items():
        if fails > attention_failure_max:
            dropped[reviewer_id] = (
                f"{fails} attention-check misses (limit {attention_failure_max})"
            )

    consensus_rows: list[dict[str, object]] = []
    n_consensus = 0
    n_disagree = 0
    n_excluded = 0
    kappa_inputs: list[tuple[str, str, list[tuple[str, Label]]]] = []

    for pair in pairs:
        if pair.attention_check_answer is not None:
            # Attention checks are quality controls, not part of the
            # final dataset.
            n_excluded += 1
            continue

        valid_labels = [lbl for lbl in pair.labels if lbl.reviewer_id not in dropped]
        # Drop 'unknown' from consensus computation but keep the reviewer.
        scoring_labels = [lbl for lbl in valid_labels if lbl.label != "unknown"]
        if len(scoring_labels) < min_reviewers_for_consensus:
            n_excluded += 1
            continue

        consensus, agreed = _majority(scoring_labels)
        if not agreed:
            n_disagree += 1
            # Disagreement pairs still ship, with `consensus_strength`
            # downgraded — they're informative outliers.
        else:
            n_consensus += 1

        consensus_rows.append({
            "id": pair.pair_id,
            "prompt": pair.prompt,
            "response_a": pair.response_a,
            "response_b": pair.response_b,
            "model_a": pair.model_a or "unknown-cheap",
            "model_b": pair.model_b or "unknown-expensive",
            "human_label": consensus,
            "source": pair.source,
            "category": pair.cluster_id or "uncategorized",
            "n_reviewers": len(scoring_labels),
            "consensus_strength": _consensus_strength(scoring_labels, consensus),
        })

        # Collect overlap data for inter-rater agreement.
        if len(scoring_labels) >= 2:
            for i, a in enumerate(scoring_labels):
                for b in scoring_labels[i + 1 :]:
                    kappa_inputs.append((
                        a.reviewer_id, b.reviewer_id,
                        [(a.reviewer_id, a.label), (b.reviewer_id, b.label)],
                    ))

    kappa = _mean_pairwise_cohens_kappa(pairs, exclude_reviewers=set(dropped))

    reviewer_stats: list[ReviewerStats] = []
    for reviewer_id in sorted({lbl.reviewer_id for p in pairs for lbl in p.labels}):
        times = reviewer_times.get(reviewer_id, [])
        avg = sum(times) / len(times) if times else None
        reviewer_stats.append(ReviewerStats(
            reviewer_id=reviewer_id,
            n_labels=reviewer_label_counts.get(reviewer_id, 0),
            n_attention_passed=reviewer_passes.get(reviewer_id, 0),
            n_attention_failed=reviewer_failures.get(reviewer_id, 0),
            avg_time_ms=avg,
            dropped=reviewer_id in dropped,
            drop_reason=dropped.get(reviewer_id),
        ))

    report = AggregationReport(
        n_pairs_total=len(pairs),
        n_pairs_with_consensus=n_consensus,
        n_pairs_disagreement=n_disagree,
        n_pairs_excluded=n_excluded,
        cohens_kappa_mean=kappa,
        reviewers=reviewer_stats,
    )
    return report, consensus_rows


def _per_reviewer_quality(
    pairs: Sequence[PairLabel],
) -> tuple[dict[str, int], dict[str, int], dict[str, list[int]], dict[str, int]]:
    fails: dict[str, int] = {}
    passes: dict[str, int] = {}
    times: dict[str, list[int]] = {}
    counts: dict[str, int] = {}
    for pair in pairs:
        for lbl in pair.labels:
            counts[lbl.reviewer_id] = counts.get(lbl.reviewer_id, 0) + 1
            if lbl.time_ms is not None:
                times.setdefault(lbl.reviewer_id, []).append(lbl.time_ms)
            if pair.attention_check_answer is None:
                continue
            if lbl.label == pair.attention_check_answer:
                passes[lbl.reviewer_id] = passes.get(lbl.reviewer_id, 0) + 1
            else:
                fails[lbl.reviewer_id] = fails.get(lbl.reviewer_id, 0) + 1
    return fails, passes, times, counts


def _majority(labels: Sequence[NormalisedLabel]) -> tuple[Label, bool]:
    counts: dict[Label, int] = {}
    for lbl in labels:
        counts[lbl.label] = counts.get(lbl.label, 0) + 1
    sorted_counts = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    top_label, top_n = sorted_counts[0]
    agreed = top_n == len(labels)
    if len(sorted_counts) > 1 and sorted_counts[0][1] == sorted_counts[1][1]:
        # Tie among top labels → fall back to "tie" rather than coin-flipping
        # between two equally-popular options.
        return ("tie", False)
    return (top_label, agreed)


def _consensus_strength(labels: Sequence[NormalisedLabel], consensus: Label) -> float:
    if not labels:
        return 0.0
    matching = sum(1 for lbl in labels if lbl.label == consensus)
    return matching / len(labels)


def _mean_pairwise_cohens_kappa(
    pairs: Sequence[PairLabel],
    *,
    exclude_reviewers: set[str],
) -> float | None:
    """Average Cohen's κ across every reviewer pair that overlapped ≥ 2 pairs.

    Returns None when there's no overlap (e.g., only one reviewer in the
    pilot).
    """

    by_reviewer: dict[str, dict[str, Label]] = {}
    for pair in pairs:
        if pair.attention_check_answer is not None:
            continue
        for lbl in pair.labels:
            if lbl.reviewer_id in exclude_reviewers or lbl.label == "unknown":
                continue
            by_reviewer.setdefault(lbl.reviewer_id, {})[pair.pair_id] = lbl.label

    reviewers = sorted(by_reviewer)
    if len(reviewers) < 2:
        return None

    kappas: list[float] = []
    for i, a in enumerate(reviewers):
        for b in reviewers[i + 1 :]:
            common = set(by_reviewer[a]) & set(by_reviewer[b])
            if len(common) < 2:
                continue
            la = [by_reviewer[a][p] for p in sorted(common)]
            lb = [by_reviewer[b][p] for p in sorted(common)]
            k = _cohens_kappa(la, lb)
            if k is not None:
                kappas.append(k)
    if not kappas:
        return None
    return sum(kappas) / len(kappas)


def _cohens_kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    """Cohen's κ between two reviewers' label sequences over the same pairs.

    Implementation note: classic two-rater κ. Categories are 'a', 'b',
    'tie'. Returns None if expected agreement is exactly 1 (zero
    denominator — happens when both reviewers always pick the same single
    category, in which case κ is undefined).
    """

    if len(a) != len(b):
        raise ValueError("rater sequences must align")
    n = len(a)
    if n == 0:
        return None
    categories = sorted(set(a) | set(b))
    # Observed agreement.
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    # Expected agreement under independence.
    pe = 0.0
    for cat in categories:
        pa = a.count(cat) / n
        pb = b.count(cat) / n
        pe += pa * pb
    denom = 1.0 - pe
    if abs(denom) < 1e-12:
        return None
    return (po - pe) / denom


async def fetch_pairs_with_labels(pool: asyncpg.Pool) -> list[PairLabel]:
    pair_sql = """
        SELECT pair_id, source, prompt, response_a, response_b,
               model_a, model_b, cluster_id, attention_check_answer
          FROM calibration_pairs
      ORDER BY created_at ASC
    """
    label_sql = """
        SELECT label_id, pair_id, reviewer_id, shown_swapped, raw_label,
               rationale, time_ms
          FROM calibration_labels
    """
    pair_rows = await pool.fetch(pair_sql)
    label_rows = await pool.fetch(label_sql)

    labels_by_pair: dict[str, list[NormalisedLabel]] = {}
    for row in label_rows:
        pair_id = str(row["pair_id"])
        raw: Label = row["raw_label"]  # type: ignore[assignment]
        labels_by_pair.setdefault(pair_id, []).append(NormalisedLabel(
            reviewer_id=row["reviewer_id"],
            label=unswap(raw, row["shown_swapped"]),
            raw_label=raw,
            shown_swapped=row["shown_swapped"],
            time_ms=row["time_ms"],
            rationale=row["rationale"],
        ))

    return [
        PairLabel(
            pair_id=str(row["pair_id"]),
            source=row["source"],
            prompt=row["prompt"],
            response_a=row["response_a"],
            response_b=row["response_b"],
            model_a=row["model_a"],
            model_b=row["model_b"],
            cluster_id=row["cluster_id"],
            attention_check_answer=row["attention_check_answer"],
            labels=labels_by_pair.get(str(row["pair_id"]), []),
        )
        for row in pair_rows
    ]


def write_canonical_jsonl(rows: Iterable[Mapping[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
