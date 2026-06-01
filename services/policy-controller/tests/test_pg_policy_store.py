"""Tests for the Postgres-backed policy channel (CASCADIA_POLICY_SOURCE=postgres).

`AsyncpgPolicyStore` is exercised with a stub asyncpg pool (no real DB);
`InMemoryPolicyStore` and the `_thresholds_changed` skip-no-op helper are pure.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from cascadia_policy.cli import _thresholds_changed
from cascadia_policy.storage import AsyncpgPolicyStore, InMemoryPolicyStore
from cascadia_policy.types import ClusterPolicy, PolicyTable


def _table(threshold: float = 0.55, version: str = "v1") -> PolicyTable:
    return PolicyTable(
        default_cluster="cluster-0",
        version=version,
        cluster_buckets=4,
        clusters={
            "cluster-0": ClusterPolicy(
                cluster_id="cluster-0",
                cheap_model="openai/gpt-4o-mini",
                expensive_model="openai/gpt-4o",
                threshold=threshold,
                shadow_rate=0.2,
            )
        },
    )


@pytest.mark.asyncio
async def test_read_latest_returns_none_when_empty() -> None:
    pool = AsyncMock()
    pool.fetchrow.return_value = None
    store = AsyncpgPolicyStore(pool)
    assert await store.read_latest() is None


@pytest.mark.asyncio
async def test_read_latest_parses_body() -> None:
    pool = AsyncMock()
    pool.fetchrow.return_value = {"body": _table(threshold=0.62).model_dump_json()}
    store = AsyncpgPolicyStore(pool)
    table = await store.read_latest()
    assert table is not None
    assert table.clusters["cluster-0"].threshold == pytest.approx(0.62)


@pytest.mark.asyncio
async def test_write_inserts_version_and_body() -> None:
    pool = AsyncMock()
    store = AsyncpgPolicyStore(pool)
    await store.write(_table(version="abc"))
    assert pool.execute.await_count == 1
    sql, version, body = pool.execute.await_args.args
    assert "INSERT INTO policy_store" in sql
    assert version == "abc"
    assert '"cluster-0"' in body  # serialized policy JSON


@pytest.mark.asyncio
async def test_write_rejects_dangling_default_cluster() -> None:
    pool = AsyncMock()
    store = AsyncpgPolicyStore(pool)
    bad = _table()
    bad.default_cluster = "ghost"  # not a key in clusters
    with pytest.raises(ValueError, match="default_cluster"):
        await store.write(bad)
    pool.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_in_memory_store_round_trips() -> None:
    store = InMemoryPolicyStore(current=_table(threshold=0.55))
    first = await store.read_latest()
    assert first is not None and first.clusters["cluster-0"].threshold == pytest.approx(0.55)
    await store.write(_table(threshold=0.58, version="v2"))
    latest = await store.read_latest()
    assert latest is not None and latest.clusters["cluster-0"].threshold == pytest.approx(0.58)
    assert len(store.published) == 1


def test_thresholds_changed_detects_delta() -> None:
    assert _thresholds_changed(_table(0.55), _table(0.58)) is True
    assert _thresholds_changed(_table(0.55), _table(0.55)) is False


def test_thresholds_changed_detects_new_cluster() -> None:
    old = _table(0.55)
    new = _table(0.55)
    new.clusters["cluster-1"] = ClusterPolicy(
        cluster_id="cluster-1",
        cheap_model="anthropic/claude-haiku-4-5",
        expensive_model="anthropic/claude-sonnet-4-6",
        threshold=0.6,
        shadow_rate=0.2,
    )
    assert _thresholds_changed(old, new) is True
