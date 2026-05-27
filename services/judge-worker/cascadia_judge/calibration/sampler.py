"""Active-learning sampler for the human-rated calibration set.

The sampler walks shadow_pairs and picks pairs to send into the labeling
queue. It runs in two distinct modes corresponding to active-learning
rounds:

Round 1 (seed) — stratified random.
  We have no ensemble scores yet on these pairs (the bench-time scoring
  was synthetic), so we can't rank by uncertainty. We instead sample
  N/k pairs per cluster, which guarantees no single high-traffic cluster
  eats the budget.

Round 2+ (uncertainty-weighted) — score the unlabeled pool with the
  judge ensemble, then sample by:

      uncertainty(pair) = 0.5 * (1 - ensemble.confidence)
                        + 0.3 * (1 - 2 * |ensemble.score - 0.5|)
                        + 0.2 * ensemble.position_bias_estimate

  Highest-uncertainty pairs go to the labeling queue first. Cluster
  stratification still applies — within each cluster, pick the
  top-uncertainty pairs. The constants are chosen so each term sits in
  [0, 1] and the weighted sum stays in [0, 1].

Why this scoring? Three orthogonal signals of "the ensemble doesn't
know what to do with this pair":
  - low confidence    → the judges hedged.
  - score near 0.5    → small label flips matter most for the metric.
  - high position bias → judges disagree with themselves.

A pair that scores high on any of these is unusually informative to label.

Attention-check pairs (obvious_b_wins synthetic distractors) are inserted
*regardless* of the sampling decision so reviewer quality stays auditable.
"""

from __future__ import annotations

import logging
import random
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Iterable

import asyncpg

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SamplerConfig:
    target_batch_size: int = 30
    attention_check_rate: float = 0.05
    cluster_stratify: bool = True
    rng_seed: int | None = None
    # Round-2+ weighting constants. Tweak if uncertainty starts saturating
    # one signal and starving the others.
    w_confidence: float = 0.5
    w_tie_proximity: float = 0.3
    w_position_bias: float = 0.2


@dataclass(frozen=True)
class CandidatePair:
    """A row from shadow_pairs, optionally augmented with ensemble scores."""

    request_id: str
    prompt: str
    cheap_model: str
    cheap_response: str
    expensive_model: str
    expensive_response: str
    cluster_id: str | None
    ensemble_score: float | None = None
    ensemble_confidence: float | None = None
    ensemble_position_bias: float | None = None

    def uncertainty(self, cfg: SamplerConfig) -> float:
        # Round-1 (no ensemble) → uniform uncertainty so cluster
        # stratification fully decides ordering.
        if self.ensemble_score is None:
            return 0.5
        conf = self.ensemble_confidence if self.ensemble_confidence is not None else 0.5
        bias = self.ensemble_position_bias if self.ensemble_position_bias is not None else 0.0
        tie_prox = 1.0 - 2.0 * abs(self.ensemble_score - 0.5)
        return (
            cfg.w_confidence * (1.0 - conf)
            + cfg.w_tie_proximity * tie_prox
            + cfg.w_position_bias * bias
        )


def select_batch(
    candidates: Sequence[CandidatePair],
    *,
    config: SamplerConfig,
    round_number: int,
) -> list[CandidatePair]:
    """Pick the next labeling batch from a pool of candidate pairs.

    Returns pairs ordered by descending uncertainty *within each cluster*,
    so labeling the first few delivers the most metric movement per pair.
    """

    rng = random.Random(config.rng_seed)
    if not candidates:
        return []

    if config.cluster_stratify:
        by_cluster: dict[str, list[CandidatePair]] = {}
        for c in candidates:
            by_cluster.setdefault(c.cluster_id or "_none", []).append(c)
        clusters = sorted(by_cluster)
        per_cluster = max(1, config.target_batch_size // max(1, len(clusters)))
        picked: list[CandidatePair] = []
        for cid in clusters:
            pool = by_cluster[cid]
            if round_number == 1:
                # No ensemble signal → uniform random within cluster.
                rng.shuffle(pool)
                picked.extend(pool[:per_cluster])
            else:
                pool_sorted = sorted(pool, key=lambda c: c.uncertainty(config), reverse=True)
                picked.extend(pool_sorted[:per_cluster])
        # Cap to target size; if some clusters were short, top up from the
        # global pool ranked by uncertainty.
        if len(picked) < config.target_batch_size:
            remaining = [c for c in candidates if c not in picked]
            remaining.sort(key=lambda c: c.uncertainty(config), reverse=True)
            picked.extend(remaining[: config.target_batch_size - len(picked)])
        return picked[: config.target_batch_size]

    if round_number == 1:
        shuffled = list(candidates)
        rng.shuffle(shuffled)
        return shuffled[: config.target_batch_size]
    return sorted(candidates, key=lambda c: c.uncertainty(config), reverse=True)[
        : config.target_batch_size
    ]


# Static attention-check fixtures. Obvious-by-construction pairs whose
# correct answer is unambiguous. Any reviewer who picks the wrong one is
# flagged for review (a sign of inattention or rushing). The fixtures live
# here rather than in a JSON file so they version with the code.
ATTENTION_CHECKS: list[dict[str, str]] = [
    {
        "source": "attention_check:b_wins_clear",
        "prompt": "What is the capital of Japan?",
        "response_a": "I am unable to provide that information.",
        "response_b": "Tokyo.",
        "model_a": "attention-cheap",
        "model_b": "attention-expensive",
        "cluster_id": "attention",
        "correct": "b",
    },
    {
        "source": "attention_check:a_wins_clear",
        "prompt": "What is 2 + 2?",
        "response_a": "4.",
        "response_b": "It is approximately fourteen, give or take.",
        "model_a": "attention-cheap",
        "model_b": "attention-expensive",
        "cluster_id": "attention",
        "correct": "a",
    },
    {
        "source": "attention_check:tie_obvious",
        "prompt": "Say hello.",
        "response_a": "Hello.",
        "response_b": "Hi there.",
        "model_a": "attention-cheap",
        "model_b": "attention-expensive",
        "cluster_id": "attention",
        "correct": "tie",
    },
]


def materialize_attention_checks(count: int) -> list[dict[str, str]]:
    """Yield `count` attention checks, cycling through the fixture list."""

    if count <= 0:
        return []
    out: list[dict[str, str]] = []
    for i in range(count):
        out.append(dict(ATTENTION_CHECKS[i % len(ATTENTION_CHECKS)]))
    return out


async def fetch_candidates_from_db(
    pool: asyncpg.Pool,
    *,
    limit: int = 1000,
    exclude_already_sampled: bool = True,
) -> list[CandidatePair]:
    """Pull unlabeled shadow pairs as `CandidatePair` rows.

    `exclude_already_sampled=True` filters out pairs that are already in
    `calibration_pairs` so successive sampling rounds don't double-pick.
    """

    sql = """
        SELECT sp.request_id, sp.prompt, sp.cheap_model, sp.cheap_response,
               sp.expensive_model, sp.expensive_response, sp.cluster_id
          FROM shadow_pairs sp
         WHERE sp.judged_at IS NOT NULL
    """
    if exclude_already_sampled:
        sql += """
           AND NOT EXISTS (
               SELECT 1 FROM calibration_pairs cp
                WHERE cp.source = 'shadow_pairs:' || sp.request_id
           )
        """
    sql += " ORDER BY sp.occurred_at DESC LIMIT $1"
    rows = await pool.fetch(sql, limit)
    return [
        CandidatePair(
            request_id=str(row["request_id"]),
            prompt=row["prompt"],
            cheap_model=row["cheap_model"],
            cheap_response=row["cheap_response"],
            expensive_model=row["expensive_model"],
            expensive_response=row["expensive_response"],
            cluster_id=row["cluster_id"],
        )
        for row in rows
    ]


async def persist_batch(
    pool: asyncpg.Pool,
    *,
    batch: Iterable[CandidatePair],
    attention_checks: Iterable[dict[str, str]],
    round_number: int,
    selection_reason: str,
) -> int:
    """Insert sampled pairs (and any attention checks) into calibration_pairs."""

    pair_sql = """
        INSERT INTO calibration_pairs (
            pair_id, source, prompt, response_a, response_b,
            model_a, model_b, cluster_id,
            ensemble_score, ensemble_confidence, ensemble_position_bias,
            selection_round, selection_reason, attention_check_answer
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
        ON CONFLICT (pair_id) DO NOTHING
    """
    rows: list[tuple] = []
    for c in batch:
        rows.append((
            uuid.uuid4(),
            f"shadow_pairs:{c.request_id}",
            c.prompt,
            c.cheap_response,
            c.expensive_response,
            c.cheap_model,
            c.expensive_model,
            c.cluster_id,
            c.ensemble_score,
            c.ensemble_confidence,
            c.ensemble_position_bias,
            round_number,
            selection_reason,
            None,
        ))
    for a in attention_checks:
        rows.append((
            uuid.uuid4(),
            a["source"],
            a["prompt"],
            a["response_a"],
            a["response_b"],
            a.get("model_a"),
            a.get("model_b"),
            a.get("cluster_id"),
            None, None, None,
            round_number,
            "attention_check",
            a["correct"],
        ))
    async with pool.acquire() as conn:
        await conn.executemany(pair_sql, rows)
    return len(rows)
