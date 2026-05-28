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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Iterable

import asyncpg

log = logging.getLogger(__name__)


# Coarse quality tiers for the models the cascade routes between. The exact
# integers don't matter — only the *ordering* and the *gap* between two models
# do. A bigger gap (e.g. gpt-3.5 → gpt-4o) makes a pair more discriminating:
# humans can actually express a confident preference, so the label carries
# real signal instead of a coin-flip between two equally-good answers. Matched
# by longest substring so `openai/gpt-4o-mini` resolves to the mini tier, not
# the gpt-4o tier. Override via SamplerConfig.model_tier_ranks.
DEFAULT_MODEL_TIER_RANKS: Mapping[str, int] = {
    "gpt-3.5": 0,
    "llama-3.1-8b": 0,
    "llama-3.2": 0,
    "haiku": 1,
    "gpt-4o-mini": 1,
    "llama-3.3-70b": 2,
    "grok-2": 2,
    "mixtral": 1,
    "gpt-4-turbo": 3,
    "gpt-4o": 3,
    "sonnet": 3,
    "opus": 4,
}


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
    # Selection strategy:
    #   "uncertainty"    — the round-2+ default: label where the ensemble
    #                      hedged / sits near a tie / shows position bias.
    #   "discrimination" — Task 3 refinement: label where the two models are
    #                      far apart in quality (big tier gap, a clear ensemble
    #                      winner, or the ensemble disagrees with an existing
    #                      human label). Steers the budget away from
    #                      "both-fine" pairs that produced the pilot's τ-b ≈ 0.
    selection_strategy: str = "uncertainty"
    w_discrimination_gap: float = 0.5
    w_discrimination_extremity: float = 0.3
    w_discrimination_disagreement: float = 0.2
    model_tier_ranks: Mapping[str, int] = field(default_factory=lambda: DEFAULT_MODEL_TIER_RANKS)


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
    # Present only once a human has labeled this pair (round 3+): 1.0=a wins,
    # 0.5=tie, 0.0=b wins. Lets the discrimination strategy chase pairs where
    # the ensemble and the human disagree.
    human_label_ordinal: float | None = None

    def discrimination(self, cfg: SamplerConfig) -> float:
        """How much a human label on this pair would *discriminate* models.

        Three orthogonal signals that a pair has a real quality gap (so a
        human can give a confident, informative label) rather than being two
        equally-fine answers:
          - model_gap   → the two models are far apart in tier.
          - extremity   → the ensemble already sees a clear winner (far from a
                          0.5 tie); the *opposite* of the uncertainty sampler's
                          tie-proximity term, by design.
          - disagreement→ the ensemble and an existing human label diverge.
        All three sit in [0, 1] and the weighted sum stays in [0, 1].
        """

        gap = _model_tier_gap(self.cheap_model, self.expensive_model, cfg.model_tier_ranks)
        if self.ensemble_score is None:
            extremity = 0.0
        else:
            extremity = 2.0 * abs(self.ensemble_score - 0.5)
        if self.ensemble_score is not None and self.human_label_ordinal is not None:
            disagreement = abs(self.ensemble_score - self.human_label_ordinal)
        else:
            disagreement = 0.0
        return (
            cfg.w_discrimination_gap * gap
            + cfg.w_discrimination_extremity * extremity
            + cfg.w_discrimination_disagreement * disagreement
        )

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


def _priority(c: CandidatePair, config: SamplerConfig) -> float:
    if config.selection_strategy == "discrimination":
        return c.discrimination(config)
    return c.uncertainty(config)


def select_batch(
    candidates: Sequence[CandidatePair],
    *,
    config: SamplerConfig,
    round_number: int,
) -> list[CandidatePair]:
    """Pick the next labeling batch from a pool of candidate pairs.

    Returns pairs ordered by descending priority *within each cluster*, so
    labeling the first few delivers the most metric movement per pair. The
    priority is the uncertainty score (default strategy) or the discrimination
    score (`selection_strategy="discrimination"`).

    Round 1 of the *uncertainty* strategy has no ensemble signal, so it falls
    back to stratified random. The *discrimination* strategy ranks even in
    round 1 — its model-tier-gap signal comes from the model names alone, no
    ensemble scores required.
    """

    rng = random.Random(config.rng_seed)
    if not candidates:
        return []

    rank_round_one = config.selection_strategy == "discrimination"

    if config.cluster_stratify:
        by_cluster: dict[str, list[CandidatePair]] = {}
        for c in candidates:
            by_cluster.setdefault(c.cluster_id or "_none", []).append(c)
        clusters = sorted(by_cluster)
        per_cluster = max(1, config.target_batch_size // max(1, len(clusters)))
        picked: list[CandidatePair] = []
        for cid in clusters:
            pool = by_cluster[cid]
            if round_number == 1 and not rank_round_one:
                # No ensemble signal → uniform random within cluster.
                rng.shuffle(pool)
                picked.extend(pool[:per_cluster])
            else:
                pool_sorted = sorted(pool, key=lambda c: _priority(c, config), reverse=True)
                picked.extend(pool_sorted[:per_cluster])
        # Cap to target size; if some clusters were short, top up from the
        # global pool ranked by priority.
        if len(picked) < config.target_batch_size:
            remaining = [c for c in candidates if c not in picked]
            remaining.sort(key=lambda c: _priority(c, config), reverse=True)
            picked.extend(remaining[: config.target_batch_size - len(picked)])
        return picked[: config.target_batch_size]

    if round_number == 1 and not rank_round_one:
        shuffled = list(candidates)
        rng.shuffle(shuffled)
        return shuffled[: config.target_batch_size]
    return sorted(candidates, key=lambda c: _priority(c, config), reverse=True)[
        : config.target_batch_size
    ]


def _tier_of(model: str, ranks: Mapping[str, int]) -> int | None:
    """Resolve a model string to a tier rank by longest-substring match.

    Longest key wins so `gpt-4o-mini` matches the mini tier, not `gpt-4o`.
    Returns None when no key matches (unknown model → no gap signal).
    """

    m = model.lower()
    best: tuple[int, int] | None = None  # (key_length, rank)
    for key, rank in ranks.items():
        if key in m and (best is None or len(key) > best[0]):
            best = (len(key), rank)
    return None if best is None else best[1]


def _model_tier_gap(cheap_model: str, expensive_model: str, ranks: Mapping[str, int]) -> float:
    """Normalized tier distance between the two models, in [0, 1].

    Returns 0.0 when either model is unknown (no signal to act on) so an
    unrecognized model never inflates a pair's discrimination score.
    """

    rc = _tier_of(cheap_model, ranks)
    re = _tier_of(expensive_model, ranks)
    if rc is None or re is None or not ranks:
        return 0.0
    spread = max(ranks.values()) - min(ranks.values())
    if spread <= 0:
        return 0.0
    return min(1.0, abs(re - rc) / spread)


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
