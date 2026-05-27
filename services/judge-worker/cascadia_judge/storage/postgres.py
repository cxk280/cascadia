"""Postgres adapter via asyncpg.

One class — `AsyncpgShadowPairStorage` — implements `ShadowPairStorage`.
Holds an `asyncpg.Pool`; no SDK churn outside this file.

The SQL is hand-written; we deliberately don't pull in SQLAlchemy or
SQLModel. Per SOLID.md §8 ("Provider SDK imports banned"), the worker keeps
its dependency surface tight. asyncpg is the only Postgres client.

Schema referenced (migration `0002_cascade.sql` in `crates/proxy/`):

    shadow_pairs(pair_id UUID PK, …, judged_at TIMESTAMPTZ)
    judge_scores(score_id UUID PK, pair_id UUID FK, judge_name TEXT,
                 prompt_variant TEXT, …,
                 UNIQUE (pair_id, judge_name, prompt_variant))
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import asyncpg

from cascadia_judge.storage.base import PendingPair, ShadowPairStorage
from cascadia_judge.types import JudgeVerdict, ShadowPair


class AsyncpgShadowPairStorage(ShadowPairStorage):
    """asyncpg-backed shadow_pairs + judge_scores adapter."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(
        cls,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 4,
    ) -> "AsyncpgShadowPairStorage":
        pool = await asyncpg.create_pool(dsn=dsn, min_size=min_size, max_size=max_size)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def fetch_pending(self, limit: int) -> Sequence[PendingPair]:
        # `FOR UPDATE SKIP LOCKED` lets multiple poller replicas race for
        # rows without ever picking up the same pair. Without it, two
        # concurrent pollers would re-judge identical pairs and burn tokens
        # (Postgres' UNIQUE constraint dedupes the *write*, but each LLM
        # call still costs money).
        sql = """
            SELECT pair_id, request_id, cluster_id, prompt,
                   cheap_model, cheap_response,
                   expensive_model, expensive_response
              FROM shadow_pairs
             WHERE judged_at IS NULL
          ORDER BY occurred_at ASC
             LIMIT $1
        FOR UPDATE SKIP LOCKED
        """
        rows = await self._pool.fetch(sql, limit)
        return tuple(_row_to_pending_pair(row) for row in rows)

    async def mark_judged(self, pair_ids: Sequence[str]) -> None:
        if not pair_ids:
            return
        # asyncpg binds list params as PostgreSQL arrays — perfect for the IN.
        sql = "UPDATE shadow_pairs SET judged_at = NOW() WHERE pair_id = ANY($1::uuid[])"
        await self._pool.execute(sql, [uuid.UUID(p) for p in pair_ids])

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
