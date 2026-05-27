"""AsyncpgStore unit tests using a stubbed asyncpg pool.

We don't run real Postgres here — the SQL is exercised indirectly through
stubbed `fetch` / `fetchrow` returning shaped rows. Catches projection bugs
(missing column → AttributeError) and type-mapping bugs without needing a DB.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from cascadia_dashboard.store import AsyncpgStore


def _pool() -> MagicMock:
    return MagicMock()


@pytest.mark.asyncio
async def test_overview_projects_all_fields() -> None:
    pool = _pool()
    pool.fetchrow = AsyncMock(side_effect=[
        # events row
        {"request_count": 42, "avg_latency_ms": 1.8, "escalation_rate": 0.25,
         "tools_use_rate": 0.10, "success_rate": 1.0},
        # judge_scores row
        {"mean_score": 0.78, "sample_size": 18},
    ])
    store = AsyncpgStore(pool)
    from datetime import timedelta
    o = await store.overview(window=timedelta(minutes=60))
    assert o.request_count == 42
    assert o.avg_latency_ms == 1.8
    assert o.escalation_rate == 0.25
    assert o.success_rate == 1.0
    assert o.mean_judge_score == 0.78
    assert o.judge_sample_size == 18
    assert o.window_seconds == 3600


@pytest.mark.asyncio
async def test_overview_handles_null_aggregates() -> None:
    pool = _pool()
    pool.fetchrow = AsyncMock(side_effect=[
        {"request_count": 0, "avg_latency_ms": None, "escalation_rate": None,
         "tools_use_rate": None, "success_rate": None},
        {"mean_score": None, "sample_size": 0},
    ])
    store = AsyncpgStore(pool)
    from datetime import timedelta
    o = await store.overview(window=timedelta(minutes=60))
    assert o.request_count == 0
    assert o.avg_latency_ms is None
    assert o.escalation_rate is None
    assert o.mean_judge_score is None


@pytest.mark.asyncio
async def test_clusters_skips_null_metrics() -> None:
    pool = _pool()
    pool.fetch = AsyncMock(return_value=[
        {"cluster_id": "default", "request_count": 100, "escalation_rate": 0.2,
         "tools_use_rate": 0.1, "mean_score": 0.8, "sample_size": 50,
         "cheap_provider": "openai", "expensive_provider": "openai"},
        {"cluster_id": "cluster-0", "request_count": 50, "escalation_rate": None,
         "tools_use_rate": None, "mean_score": None, "sample_size": 0,
         "cheap_provider": None, "expensive_provider": None},
    ])
    store = AsyncpgStore(pool)
    from datetime import timedelta
    rows = await store.clusters(window=timedelta(minutes=60))
    assert len(rows) == 2
    assert rows[0].mean_judge_score == 0.8
    assert rows[1].escalation_rate is None
    assert rows[1].mean_judge_score is None


@pytest.mark.asyncio
async def test_recent_events_shape() -> None:
    pool = _pool()
    now = datetime.now(timezone.utc)
    pool.fetch = AsyncMock(return_value=[
        {
            "request_id": "req-1",
            "occurred_at": now,
            "route": "chat_completions",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "upstream_status": 200,
            "elapsed_ms": 50,
            "cluster_id": "cluster-0",
            "escalated": False,
            "tools_present": False,
        }
    ])
    store = AsyncpgStore(pool)
    rows = await store.recent_events(limit=10)
    assert len(rows) == 1
    assert rows[0].request_id == "req-1"
    assert rows[0].escalated is False


@pytest.mark.asyncio
async def test_recent_verdicts_shape() -> None:
    pool = _pool()
    now = datetime.now(timezone.utc)
    pool.fetch = AsyncMock(return_value=[
        {
            "score_id": "s1", "pair_id": "p1", "judge_name": "pairwise_preference_v1",
            "prompt_variant": "pairwise/v1", "score": 0.8, "confidence": 0.9,
            "occurred_at": now, "cluster_id": "cluster-0",
            "cheap_model": "gpt-4o-mini", "expensive_model": "gpt-4o",
        }
    ])
    store = AsyncpgStore(pool)
    rows = await store.recent_verdicts(limit=10)
    assert len(rows) == 1
    assert rows[0].score == 0.8


@pytest.mark.asyncio
async def test_pareto_points_shape() -> None:
    pool = _pool()
    pool.fetch = AsyncMock(return_value=[
        {"cluster_id": "cluster-0", "escalation_rate": 0.1, "mean_quality": 0.9, "sample_size": 30},
        {"cluster_id": "cluster-1", "escalation_rate": 0.5, "mean_quality": 0.6, "sample_size": 25},
    ])
    store = AsyncpgStore(pool)
    from datetime import timedelta
    rows = await store.pareto_points(window=timedelta(minutes=60))
    assert len(rows) == 2
    assert rows[0].cluster_id == "cluster-0"
    assert rows[0].mean_quality == 0.9


@pytest.mark.asyncio
async def test_recent_verdicts_coerces_nonfinite_to_null() -> None:
    # Regression: a NaN/Inf score serialized to the literal `NaN`/`Infinity`
    # tokens (invalid JSON), breaking the whole /verdicts response in the
    # browser. Non-finite values now become null.
    import json

    pool = _pool()
    now = datetime.now(timezone.utc)
    pool.fetch = AsyncMock(return_value=[
        {
            "score_id": "s1", "pair_id": "p1", "judge_name": "j",
            "prompt_variant": "pairwise/v1", "score": float("nan"),
            "confidence": float("inf"), "occurred_at": now, "cluster_id": "c0",
            "cheap_model": "a", "expensive_model": "b",
        }
    ])
    store = AsyncpgStore(pool)
    rows = await store.recent_verdicts(limit=10)
    assert rows[0].score is None
    assert rows[0].confidence is None
    # Serializes to valid JSON (no NaN/Infinity tokens).
    json.loads(rows[0].model_dump_json())


@pytest.mark.asyncio
async def test_overview_coerces_nonfinite_avg_latency_to_null() -> None:
    pool = _pool()
    pool.fetchrow = AsyncMock(side_effect=[
        {"request_count": 1, "avg_latency_ms": float("nan"), "escalation_rate": 0.0,
         "tools_use_rate": 0.0, "success_rate": 1.0},
        {"mean_score": 0.5, "sample_size": 1},
    ])
    store = AsyncpgStore(pool)
    from datetime import timedelta
    o = await store.overview(window=timedelta(minutes=60))
    assert o.avg_latency_ms is None


@pytest.mark.asyncio
async def test_close_calls_pool_close() -> None:
    pool = _pool()
    pool.close = AsyncMock()
    store = AsyncpgStore(pool)
    await store.close()
    pool.close.assert_awaited_once()
