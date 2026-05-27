"""Storage adapters for the policy controller.

`StatsReader` is the substitution surface. `AsyncpgStatsReader` is the
concrete production adapter; `InMemoryStatsReader` is for tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

import asyncpg

from cascadia_policy.types import ClusterStats


@runtime_checkable
class StatsReader(Protocol):
    async def cluster_stats(self, lookback: timedelta) -> Mapping[str, ClusterStats]:
        ...

    async def close(self) -> None:
        ...


class AsyncpgStatsReader(StatsReader):
    """Reads aggregate stats from the proxy's events + judge_scores tables."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> "AsyncpgStatsReader":
        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=4)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def cluster_stats(self, lookback: timedelta) -> Mapping[str, ClusterStats]:
        # We want, per cluster:
        #   - mean ensemble score (the bias-corrected per-pair score the judge
        #     worker persists on shadow_pairs.ensemble_score)
        #   - sample size (# of judged *pairs*, not judge_scores rows)
        #   - escalation rate from events
        # We average shadow_pairs.ensemble_score rather than the raw
        # judge_scores.score: the ensemble already drops self-preferring judges,
        # folds position-swapped siblings, and excludes errored verdicts, so the
        # controller tunes on the same statistic the panel is calibrated against
        # (raw AVG(js.score) counted error rows as 0, double-counted swapped
        # siblings, and included self-preferring judges). NULL ensemble means
        # "no usable signal" → excluded. COUNT here is therefore per-pair, so
        # `min_sample_size` means pairs, matching the operator's mental model.
        # Compute the cutoff timestamp here rather than `NOW() - $1` in SQL —
        # asyncpg's binary protocol gets type inference wrong on NOW() minus a
        # bound parameter ("operator does not exist: timestamptz > interval").
        cutoff = datetime.now(timezone.utc) - lookback
        sql = """
        WITH judged AS (
            SELECT cluster_id,
                   AVG(ensemble_score) AS mean_score,
                   COUNT(*) AS sample_size
              FROM shadow_pairs
             WHERE occurred_at > $1
               AND ensemble_score IS NOT NULL
             GROUP BY cluster_id
        ),
        events_agg AS (
            SELECT cluster_id,
                   AVG(CASE WHEN escalated THEN 1.0 ELSE 0.0 END) AS escalation_rate,
                   COUNT(*) AS request_count
              FROM events
             WHERE occurred_at > $1
               AND cluster_id IS NOT NULL
             GROUP BY cluster_id
        )
        SELECT
            COALESCE(j.cluster_id, e.cluster_id) AS cluster_id,
            j.mean_score,
            COALESCE(j.sample_size, 0)            AS sample_size,
            e.escalation_rate
          FROM judged j
          FULL OUTER JOIN events_agg e ON j.cluster_id = e.cluster_id
        """
        rows = await self._pool.fetch(sql, cutoff)
        out: dict[str, ClusterStats] = {}
        for row in rows:
            cid = row["cluster_id"]
            if cid is None:
                continue
            mean = row["mean_score"]
            out[cid] = ClusterStats(
                cluster_id=cid,
                sample_size=int(row["sample_size"]),
                mean_score=float(mean) if mean is not None else None,
                escalation_rate=(
                    float(row["escalation_rate"]) if row["escalation_rate"] is not None else None
                ),
            )
        return out


class InMemoryStatsReader(StatsReader):
    """Test double; lets you script the stats table."""

    def __init__(self, stats: Mapping[str, ClusterStats] | None = None) -> None:
        self._stats: dict[str, ClusterStats] = dict(stats or {})

    def set(self, stats: ClusterStats) -> None:
        self._stats[stats.cluster_id] = stats

    async def cluster_stats(self, lookback: timedelta) -> Mapping[str, ClusterStats]:
        del lookback  # ignored in fake
        return dict(self._stats)

    async def close(self) -> None:  # pragma: no cover
        return None
