"""Postgres adapter via asyncpg.

One class — `AsyncpgShadowPairStorage` — implements `ShadowPairStorage`.
Holds an `asyncpg.Pool`; no SDK churn outside this file.

The SQL is hand-written; we deliberately don't pull in SQLAlchemy or
SQLModel. The worker keeps its dependency surface tight (no ORMs, no
provider SDKs outside the adapter layer). asyncpg is the only Postgres client.

Schema referenced (migration `0002_cascade.sql` in `crates/proxy/`):

    shadow_pairs(pair_id UUID PK, …, judged_at TIMESTAMPTZ)
    judge_scores(score_id UUID PK, pair_id UUID FK, judge_name TEXT,
                 prompt_variant TEXT, …,
                 UNIQUE (pair_id, judge_name, prompt_variant))
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from cascadia_judge.storage.base import PendingPair, ShadowPairStorage
from cascadia_judge.types import JudgeVerdict, ShadowPair

# A claim older than this is treated as stale: the worker that held it has
# almost certainly crashed, so the pair becomes eligible to be re-claimed.
# Generous relative to a judging cycle (seconds) so a slow-but-alive worker
# isn't double-claimed.
DEFAULT_RECLAIM_AFTER = timedelta(minutes=15)


class AsyncpgShadowPairStorage(ShadowPairStorage):
    """asyncpg-backed shadow_pairs + judge_scores adapter."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        reclaim_after: timedelta = DEFAULT_RECLAIM_AFTER,
    ) -> None:
        self._pool = pool
        self._reclaim_after = reclaim_after

    @classmethod
    async def connect(
        cls,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 4,
        reclaim_after: timedelta = DEFAULT_RECLAIM_AFTER,
    ) -> "AsyncpgShadowPairStorage":
        pool = await asyncpg.create_pool(dsn=dsn, min_size=min_size, max_size=max_size)
        return cls(pool, reclaim_after=reclaim_after)

    async def close(self) -> None:
        await self._pool.close()

    async def fetch_pending(self, limit: int) -> Sequence[PendingPair]:
        # Claim the oldest unjudged, unclaimed (or stale-claimed) rows in a
        # single statement: the CTE selects with `FOR UPDATE SKIP LOCKED`
        # (concurrent replicas skip each other's locked rows) and the outer
        # UPDATE stamps `claimed_at`, so even after this statement commits a
        # second replica won't re-fetch the same pairs until the reclaim
        # window elapses. Previously the bare `SELECT … FOR UPDATE SKIP
        # LOCKED` released its row locks the moment the pooled query returned,
        # so replicas still re-judged the same pairs and double-paid for LLM
        # calls (the UNIQUE constraint only dedupes the write, not the call).
        stale_cutoff = datetime.now(timezone.utc) - self._reclaim_after
        sql = """
            WITH claimable AS (
                SELECT pair_id
                  FROM shadow_pairs
                 WHERE judged_at IS NULL
                   AND (claimed_at IS NULL OR claimed_at < $2)
              ORDER BY occurred_at ASC
                 LIMIT $1
            FOR UPDATE SKIP LOCKED
            )
            UPDATE shadow_pairs sp
               SET claimed_at = NOW()
              FROM claimable c
             WHERE sp.pair_id = c.pair_id
         RETURNING sp.pair_id, sp.request_id, sp.cluster_id, sp.prompt,
                   sp.cheap_model, sp.cheap_response,
                   sp.expensive_model, sp.expensive_response
        """
        rows = await self._pool.fetch(sql, limit, stale_cutoff)
        return tuple(_row_to_pending_pair(row) for row in rows)

    async def mark_judged(self, pair_ids: Sequence[str]) -> None:
        if not pair_ids:
            return
        # asyncpg binds list params as PostgreSQL arrays — perfect for the IN.
        sql = "UPDATE shadow_pairs SET judged_at = NOW() WHERE pair_id = ANY($1::uuid[])"
        await self._pool.execute(sql, [uuid.UUID(p) for p in pair_ids])

    async def release_claims(self, pair_ids: Sequence[str]) -> None:
        if not pair_ids:
            return
        # Only release rows that are still unjudged — never un-finalize a pair.
        sql = """
            UPDATE shadow_pairs SET claimed_at = NULL
             WHERE pair_id = ANY($1::uuid[]) AND judged_at IS NULL
        """
        await self._pool.execute(sql, [uuid.UUID(p) for p in pair_ids])

    async def set_ensemble_score(
        self,
        pair_id: str,
        score: float | None,
        confidence: float | None,
    ) -> None:
        sql = """
            UPDATE shadow_pairs
               SET ensemble_score = $2, ensemble_confidence = $3
             WHERE pair_id = $1
        """
        await self._pool.execute(sql, uuid.UUID(pair_id), score, confidence)

    async def write_verdicts(
        self,
        pair_id: str,
        verdicts: Sequence[JudgeVerdict],
    ) -> None:
        if not verdicts:
            return
        sql = """
            INSERT INTO judge_scores (
                score_id, pair_id, judge_name, prompt_variant,
                model, provider, score, confidence, rationale,
                prompt_hash, elapsed_ms, error
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (pair_id, judge_name, prompt_variant) DO NOTHING
        """
        rows = [_verdict_to_row(uuid.UUID(pair_id), v) for v in verdicts]
        async with self._pool.acquire() as conn:
            # Wrap in an explicit transaction so the verdicts for a pair land
            # all-or-nothing. A mid-`executemany` failure must not leave a
            # partial verdict set that then gets marked judged and aggregated
            # on fewer judges than intended.
            async with conn.transaction():
                await conn.executemany(sql, rows)


def _row_to_pending_pair(row: Any) -> PendingPair:
    pair = ShadowPair(
        request_id=str(row["request_id"]),
        prompt=row["prompt"],
        cheap_model=row["cheap_model"],
        cheap_response=row["cheap_response"],
        expensive_model=row["expensive_model"],
        expensive_response=row["expensive_response"],
        cluster_id=row["cluster_id"],
    )
    return PendingPair(pair_id=str(row["pair_id"]), shadow_pair=pair)


def _verdict_to_row(pair_uuid: uuid.UUID, v: JudgeVerdict) -> tuple:
    return (
        uuid.uuid4(),                # score_id
        pair_uuid,                   # pair_id
        v.judge_name,
        v.prompt_variant,
        v.model,
        v.provider,
        float(v.score.score),
        float(v.score.confidence) if v.score.confidence is not None else None,
        v.score.rationale,
        v.prompt_hash,
        v.elapsed_ms,
        v.error,
    )
