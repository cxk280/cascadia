"""AsyncpgCalibrationStore unit tests with a stubbed asyncpg pool.

Same approach as test_asyncpg_store.py — stub `fetchrow` / `fetch` / `execute`
returning shaped data; verify the python-side type mapping + the
position-swap routing logic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from cascadia_dashboard.calibrate.store import AsyncpgCalibrationStore


def _pool() -> MagicMock:
    return MagicMock()


@pytest.mark.asyncio
async def test_upsert_reviewer_inserted_flag() -> None:
    pool = _pool()
    now = datetime.now(timezone.utc)
    pool.fetchrow = AsyncMock(
        return_value={"onboarded_at": now, "display_name": "Chris", "inserted": True}
    )
    store = AsyncpgCalibrationStore(pool)
    onboarded_at, already_existed, display_name = await store.upsert_reviewer(
        "chris", "Chris"
    )
    assert onboarded_at == now
    assert already_existed is False
    assert display_name == "Chris"


@pytest.mark.asyncio
async def test_upsert_reviewer_idempotent() -> None:
    pool = _pool()
    now = datetime.now(timezone.utc)
    # On collision the row keeps the ORIGINAL display_name — Bob typing
    # "chris" with "Bob Smith" gets "Chris" back.
    pool.fetchrow = AsyncMock(
        return_value={"onboarded_at": now, "display_name": "Chris", "inserted": False}
    )
    store = AsyncpgCalibrationStore(pool)
    _, already_existed, display_name = await store.upsert_reviewer(
        "chris", "Bob Smith"
    )
    assert already_existed is True
    assert display_name == "Chris"


@pytest.mark.asyncio
async def test_next_pair_for_returns_none_on_empty_queue() -> None:
    pool = _pool()
    pool.fetchrow = AsyncMock(return_value=None)
    store = AsyncpgCalibrationStore(pool)
    out = await store.next_pair_for("alex")
    assert out is None


@pytest.mark.asyncio
async def test_next_pair_for_returns_pending_pair() -> None:
    pool = _pool()
    # First fetchrow → the pending pair; second fetchrow → the position computation.
    pool.fetchrow = AsyncMock(side_effect=[
        {
            "pair_id": "ad7990a8-0000-0000-0000-000000000000",
            "prompt": "test prompt", "response_a": "A", "response_b": "B",
            "cluster_id": "cluster-0", "selection_round": 1,
            "selection_reason": "seed_stratified",
        },
        {"pos": 3},
    ])
    store = AsyncpgCalibrationStore(pool)
    out = await store.next_pair_for("alex")
    assert out is not None
    assert out.pair_id == "ad7990a8-0000-0000-0000-000000000000"
    assert out.queue_position == 3


@pytest.mark.asyncio
async def test_queue_size_for() -> None:
    pool = _pool()
    pool.fetchrow = AsyncMock(return_value={"n": 42})
    store = AsyncpgCalibrationStore(pool)
    assert await store.queue_size_for("alex") == 42


@pytest.mark.asyncio
async def test_submit_label_returns_label_id() -> None:
    pool = _pool()
    pool.fetchrow = AsyncMock(return_value={"label_id": "label-uuid-here"})
    store = AsyncpgCalibrationStore(pool)
    label_id = await store.submit_label(
        pair_id="p1", reviewer_id="r1",
        shown_swapped=False, raw_label="a",
        rationale=None, time_ms=1234, rubric_version="v2",
    )
    assert label_id == "label-uuid-here"


@pytest.mark.asyncio
async def test_progress_for_aggregates_counts() -> None:
    pool = _pool()
    # `_ensure_unswap_function` call (returns nothing meaningful — just must not raise).
    pool.execute = AsyncMock(return_value=None)
    pool.fetchrow = AsyncMock(side_effect=[
        # progress query
        {"n_labeled": 30, "n_attention_passed": 2, "n_attention_failed": 0},
        # queue size query
        {"n": 5},
    ])
    store = AsyncpgCalibrationStore(pool)
    p = await store.progress_for("alex")
    assert p.n_labeled == 30
    assert p.n_attention_passed == 2
    assert p.n_attention_failed == 0
    assert p.n_pending == 5


@pytest.mark.asyncio
async def test_progress_for_handles_null_aggregates() -> None:
    pool = _pool()
    pool.execute = AsyncMock(return_value=None)
    pool.fetchrow = AsyncMock(side_effect=[
        {"n_labeled": 0, "n_attention_passed": None, "n_attention_failed": None},
        {"n": 0},
    ])
    store = AsyncpgCalibrationStore(pool)
    p = await store.progress_for("alex")
    assert p.n_labeled == 0
    assert p.n_attention_passed == 0
    assert p.n_attention_failed == 0
