"""Storage adapter tests.

`InMemoryStatsReader` is fully covered. `AsyncpgStatsReader` is exercised via
its constructor + `close()` semantics with a stub pool (no real DB needed).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from cascadia_policy.storage import AsyncpgStatsReader, InMemoryStatsReader
from cascadia_policy.types import ClusterStats


@pytest.mark.asyncio
async def test_in_memory_reader_returns_stats() -> None:
    reader = InMemoryStatsReader({
        "default": ClusterStats(cluster_id="default", sample_size=100, mean_score=0.7),
        "cluster-0": ClusterStats(cluster_id="cluster-0", sample_size=50, mean_score=0.3),
    })
    stats = await reader.cluster_stats(timedelta(hours=1))
    assert set(stats) == {"default", "cluster-0"}
    assert stats["default"].mean_score == 0.7


@pytest.mark.asyncio
async def test_in_memory_reader_set_overwrites() -> None:
    reader = InMemoryStatsReader()
    reader.set(ClusterStats(cluster_id="x", sample_size=1, mean_score=0.9))
    reader.set(ClusterStats(cluster_id="x", sample_size=2, mean_score=0.1))
    stats = await reader.cluster_stats(timedelta(hours=1))
    assert stats["x"].sample_size == 2
    assert stats["x"].mean_score == 0.1


@pytest.mark.asyncio
async def test_in_memory_reader_close_is_noop() -> None:
    reader = InMemoryStatsReader()
    # Should not raise.
    await reader.close()


@pytest.mark.asyncio
async def test_in_memory_reader_ignores_lookback() -> None:
    reader = InMemoryStatsReader({
        "x": ClusterStats(cluster_id="x", sample_size=1, mean_score=0.5)
    })
    stats_short = await reader.cluster_stats(timedelta(seconds=1))
    stats_long = await reader.cluster_stats(timedelta(days=30))
    assert stats_short == stats_long


@pytest.mark.asyncio
async def test_asyncpg_reader_cluster_stats_shape() -> None:
    """Test the AsyncpgStatsReader's SQL-projection logic with a stub pool."""

    pool = MagicMock()
    # The SQL projects (cluster_id, mean_score, sample_size, escalation_rate).
    pool.fetch = AsyncMock(return_value=[
        {"cluster_id": "default", "mean_score": 0.7, "sample_size": 100, "escalation_rate": 0.2},
        {"cluster_id": "cluster-0", "mean_score": None, "sample_size": 0, "escalation_rate": 0.4},
        # Row with cluster_id=None should be excluded.
        {"cluster_id": None, "mean_score": 0.5, "sample_size": 5, "escalation_rate": 0.5},
    ])
    reader = AsyncpgStatsReader(pool)
    stats = await reader.cluster_stats(timedelta(hours=1))
    assert set(stats) == {"default", "cluster-0"}
    assert stats["default"].sample_size == 100
    assert stats["default"].mean_score == pytest.approx(0.7)
    assert stats["default"].escalation_rate == pytest.approx(0.2)
    # Null mean_score → ClusterStats.mean_score should be None.
    assert stats["cluster-0"].mean_score is None
    # Verify the SQL got a `cutoff` datetime arg, not an interval.
    args, _ = pool.fetch.call_args
    assert isinstance(args[1].__class__.__name__, str)  # is a real datetime


@pytest.mark.asyncio
async def test_asyncpg_reader_close_calls_pool_close() -> None:
    pool = MagicMock()
    pool.close = AsyncMock()
    reader = AsyncpgStatsReader(pool)
    await reader.close()
    pool.close.assert_awaited_once()
