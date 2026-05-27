"""Read-only repository. SQL strings live here; routes are thin adapters.

Substitution surface is the `Store` Protocol — `AsyncpgStore` is the
production adapter, `InMemoryStore` is the test fake. Following the same
pattern as `services/judge-worker/cascadia_judge/storage/base.py` so the
codebase stays consistent (Phase 1 SOLID Agent Swarms decision in
`SOLID.md` applied to a different service).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

import asyncpg

from cascadia_dashboard.types import (
    ClusterRow,
    EventRow,
    Overview,
    ParetoPoint,
    RecentVerdict,
)


@runtime_checkable
class Store(Protocol):
    async def overview(self, *, window: timedelta) -> Overview: ...
    async def clusters(self, *, window: timedelta) -> Sequence[ClusterRow]: ...
    async def recent_events(self, *, limit: int) -> Sequence[EventRow]: ...
    async def recent_verdicts(self, *, limit: int) -> Sequence[RecentVerdict]: ...
    async def pareto_points(self, *, window: timedelta) -> Sequence[ParetoPoint]: ...
    async def close(self) -> None: ...


class AsyncpgStore(Store):
    """asyncpg-backed adapter against the proxy's Postgres schema."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str, *, max_size: int = 8) -> "AsyncpgStore":
        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=max_size)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def overview(self, *, window: timedelta) -> Overview:
        cutoff = _cutoff(window)
        sql = """
            SELECT
                COUNT(*) AS request_count,
                AVG(elapsed_ms) AS avg_latency_ms,
                AVG(CASE WHEN escalated THEN 1.0 ELSE 0.0 END) AS escalation_rate,
                AVG(CASE WHEN tools_present THEN 1.0 ELSE 0.0 END) AS tools_use_rate,
                AVG(CASE WHEN upstream_status BETWEEN 200 AND 299 THEN 1.0 ELSE 0.0 END)
                    AS success_rate
              FROM events
             WHERE occurred_at > $1
        """
        row = await self._pool.fetchrow(sql, cutoff)
        score_sql = """
            SELECT AVG(score) AS mean_score, COUNT(*) AS sample_size
              FROM judge_scores
             WHERE occurred_at > $1
        """
        score_row = await self._pool.fetchrow(score_sql, cutoff)
        return Overview(
            window_seconds=int(window.total_seconds()),
            request_count=int(row["request_count"] or 0),
            avg_latency_ms=_as_float(row["avg_latency_ms"]),
            escalation_rate=_as_float(row["escalation_rate"]),
            tools_use_rate=_as_float(row["tools_use_rate"]),
            success_rate=_as_float(row["success_rate"]),
            mean_judge_score=_as_float(score_row["mean_score"]),
            judge_sample_size=int(score_row["sample_size"] or 0),
        )

    async def clusters(self, *, window: timedelta) -> Sequence[ClusterRow]:
        cutoff = _cutoff(window)
        # Phase 7: project the `provider/model` prefix off the most recent
        # shadow pair per cluster so the UI can show which providers each
        # tier is using. NULL split_part on the legacy unprefixed strings
        # returns an empty string — the API layer maps that to None.
        sql = """
            WITH judged AS (
                SELECT sp.cluster_id, AVG(js.score) AS mean_score, COUNT(*) AS sample_size
                  FROM shadow_pairs sp
                  JOIN judge_scores js ON js.pair_id = sp.pair_id
                 WHERE sp.occurred_at > $1
                 GROUP BY sp.cluster_id
            ),
            traffic AS (
                SELECT
                    cluster_id,
                    COUNT(*) AS request_count,
                    AVG(CASE WHEN escalated THEN 1.0 ELSE 0.0 END) AS escalation_rate,
                    AVG(CASE WHEN tools_present THEN 1.0 ELSE 0.0 END) AS tools_use_rate
                  FROM events
                 WHERE occurred_at > $1
                   AND cluster_id IS NOT NULL
                 GROUP BY cluster_id
            ),
            latest_models AS (
                SELECT DISTINCT ON (cluster_id)
                    cluster_id,
                    cheap_model,
                    expensive_model
                  FROM shadow_pairs
                 WHERE occurred_at > $1
                 ORDER BY cluster_id, occurred_at DESC
            )
            SELECT
                COALESCE(t.cluster_id, j.cluster_id) AS cluster_id,
                COALESCE(t.request_count, 0)         AS request_count,
                t.escalation_rate,
                t.tools_use_rate,
                j.mean_score,
                COALESCE(j.sample_size, 0)           AS sample_size,
                CASE WHEN lm.cheap_model ~ '/' THEN split_part(lm.cheap_model, '/', 1)
                     ELSE NULL END                  AS cheap_provider,
                CASE WHEN lm.expensive_model ~ '/' THEN split_part(lm.expensive_model, '/', 1)
                     ELSE NULL END                  AS expensive_provider
              FROM traffic t
              FULL OUTER JOIN judged j ON t.cluster_id = j.cluster_id
              LEFT  JOIN latest_models lm ON lm.cluster_id = COALESCE(t.cluster_id, j.cluster_id)
          ORDER BY request_count DESC NULLS LAST
        """
        rows = await self._pool.fetch(sql, cutoff)
        return [
            ClusterRow(
                cluster_id=row["cluster_id"],
                request_count=int(row["request_count"]),
                escalation_rate=_as_float(row["escalation_rate"]),
                mean_judge_score=_as_float(row["mean_score"]),
                judge_sample_size=int(row["sample_size"]),
                cheap_provider=row["cheap_provider"],
                expensive_provider=row["expensive_provider"],
                tools_use_rate=_as_float(row["tools_use_rate"]),
            )
            for row in rows
        ]

    async def recent_events(self, *, limit: int) -> Sequence[EventRow]:
        sql = """
            SELECT request_id, occurred_at, route, provider, model,
                   upstream_status, elapsed_ms, cluster_id, escalated,
                   tools_present
              FROM events
          ORDER BY occurred_at DESC
             LIMIT $1
        """
        rows = await self._pool.fetch(sql, limit)
        return [
            EventRow(
                request_id=str(row["request_id"]),
                occurred_at=row["occurred_at"],
                route=row["route"],
                provider=row["provider"],
                model=row["model"],
                upstream_status=row["upstream_status"],
                elapsed_ms=int(row["elapsed_ms"]),
                cluster_id=row["cluster_id"],
                escalated=bool(row["escalated"]),
                tools_present=bool(row["tools_present"]),
            )
            for row in rows
        ]

    async def recent_verdicts(self, *, limit: int) -> Sequence[RecentVerdict]:
        sql = """
            SELECT js.score_id, js.pair_id, js.judge_name, js.prompt_variant,
                   js.score, js.confidence, js.occurred_at,
                   sp.cluster_id, sp.cheap_model, sp.expensive_model
              FROM judge_scores js
              JOIN shadow_pairs sp ON sp.pair_id = js.pair_id
          ORDER BY js.occurred_at DESC
             LIMIT $1
        """
        rows = await self._pool.fetch(sql, limit)
        return [
            RecentVerdict(
                score_id=str(row["score_id"]),
                pair_id=str(row["pair_id"]),
                judge_name=row["judge_name"],
                prompt_variant=row["prompt_variant"],
                score=_as_float(row["score"]),
                confidence=_as_float(row["confidence"]),
                occurred_at=row["occurred_at"],
                cluster_id=row["cluster_id"],
                cheap_model=row["cheap_model"],
                expensive_model=row["expensive_model"],
            )
            for row in rows
        ]

    async def pareto_points(self, *, window: timedelta) -> Sequence[ParetoPoint]:
        cutoff = _cutoff(window)
        # The "Pareto chart" maps escalation rate (proxy for cost) against
        # mean judge score (proxy for quality), one point per cluster. A
        # production-grade implementation would project against the canonical
        # frontier curve estimated from MT-Bench; this is the live operating
        # point view that the dashboard ships with.
        sql = """
            SELECT
                sp.cluster_id,
                AVG(js.score) AS mean_quality,
                AVG(CASE WHEN ev.escalated THEN 1.0 ELSE 0.0 END) AS escalation_rate,
                COUNT(*) AS sample_size
              FROM shadow_pairs sp
              JOIN judge_scores js ON js.pair_id = sp.pair_id
              JOIN events ev      ON ev.request_id = sp.request_id
             WHERE sp.occurred_at > $1
             GROUP BY sp.cluster_id
            HAVING COUNT(*) >= 1
          ORDER BY mean_quality DESC
        """
        rows = await self._pool.fetch(sql, cutoff)
        return [
            ParetoPoint(
                cluster_id=row["cluster_id"],
                escalation_rate=_as_float(row["escalation_rate"]) or 0.0,
                mean_quality=_as_float(row["mean_quality"]) or 0.0,
                sample_size=int(row["sample_size"]),
            )
            for row in rows
        ]


class InMemoryStore(Store):
    """Test fake — scriptable from inside pytest."""

    def __init__(self) -> None:
        self.overview_data: Overview = Overview(
            window_seconds=3600,
            request_count=0,
            avg_latency_ms=None,
            escalation_rate=None,
            success_rate=None,
            mean_judge_score=None,
            judge_sample_size=0,
        )
        self.clusters_data: list[ClusterRow] = []
        self.events_data: list[EventRow] = []
        self.verdicts_data: list[RecentVerdict] = []
        self.pareto_data: list[ParetoPoint] = []

    async def overview(self, *, window: timedelta) -> Overview:
        return self.overview_data

    async def clusters(self, *, window: timedelta) -> Sequence[ClusterRow]:
        return list(self.clusters_data)

    async def recent_events(self, *, limit: int) -> Sequence[EventRow]:
        return self.events_data[:limit]

    async def recent_verdicts(self, *, limit: int) -> Sequence[RecentVerdict]:
        return self.verdicts_data[:limit]

    async def pareto_points(self, *, window: timedelta) -> Sequence[ParetoPoint]:
        return list(self.pareto_data)

    async def close(self) -> None:  # pragma: no cover
        return None


def _cutoff(window: timedelta) -> datetime:
    return datetime.now(timezone.utc) - window


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    f = float(value)
    # NaN / ±Infinity serialize to the literal tokens `NaN` / `Infinity`,
    # which are NOT valid JSON (RFC 8259) — the browser's JSON.parse rejects
    # them and the whole dashboard response fails to load. A single poisoned
    # score row shouldn't take down /overview or /verdicts, so coerce any
    # non-finite value to null.
    if not math.isfinite(f):
        return None
    return f
