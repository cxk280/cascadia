"""Tests for the in-memory storage adapter.

These also pin down the `ShadowPairStorage` contract — anything Postgres
must do, the in-memory has to do first.
"""

from __future__ import annotations

import pytest

from cascadia_judge.storage.in_memory import InMemoryShadowPairStorage
from cascadia_judge.types import JudgeScore, JudgeVerdict, ShadowPair


def _pair(prompt: str = "hi") -> ShadowPair:
    return ShadowPair(
        request_id="req-1",
        prompt=prompt,
        cheap_model="cheap",
        cheap_response="answer A",
        expensive_model="expensive",
        expensive_response="answer B",
        cluster_id="default",
    )


def _verdict(judge_name: str = "pairwise_v1", variant: str = "pairwise/v1") -> JudgeVerdict:
    return JudgeVerdict(
        request_id="req-1",
        judge_name=judge_name,
        prompt_variant=variant,
        model="test-model",
        provider="test",
        score=JudgeScore(score=0.6, confidence=0.8, rationale="ok"),
        prompt_hash="abc",
        elapsed_ms=12,
        error=None,
    )


@pytest.mark.asyncio
async def test_fetch_pending_returns_in_insertion_order() -> None:
    store = InMemoryShadowPairStorage()
    a = store.add_pair(_pair("a"))
    b = store.add_pair(_pair("b"))
    c = store.add_pair(_pair("c"))

    pending = await store.fetch_pending(limit=10)

    assert [p.pair_id for p in pending] == [a, b, c]


@pytest.mark.asyncio
async def test_mark_judged_removes_from_pending() -> None:
    store = InMemoryShadowPairStorage()
    a = store.add_pair(_pair("a"))
    b = store.add_pair(_pair("b"))

    await store.mark_judged([a])
    pending = await store.fetch_pending(limit=10)

    assert [p.pair_id for p in pending] == [b]
    assert a in store.judged_ids()


@pytest.mark.asyncio
async def test_mark_judged_is_idempotent() -> None:
    store = InMemoryShadowPairStorage()
    a = store.add_pair(_pair("a"))

    await store.mark_judged([a])
    await store.mark_judged([a])  # again

    assert store.judged_ids() == {a}


@pytest.mark.asyncio
async def test_write_verdicts_dedups_on_pair_judge_variant() -> None:
    store = InMemoryShadowPairStorage()
    a = store.add_pair(_pair("a"))

    v1 = _verdict()
    v2 = _verdict()  # same judge/variant — should overwrite-or-noop

    await store.write_verdicts(a, [v1])
    await store.write_verdicts(a, [v2])

    assert len(store.all_verdicts()) == 1


@pytest.mark.asyncio
async def test_fetch_pending_respects_limit() -> None:
    store = InMemoryShadowPairStorage()
    for _ in range(10):
        store.add_pair(_pair("x"))

    pending = await store.fetch_pending(limit=3)
    assert len(pending) == 3
