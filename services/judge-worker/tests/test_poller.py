"""Tests for the Poller loop.

Uses the in-memory storage adapter + a `FakeLLMClient` so we exercise the
real `JudgeOrchestrator` without touching Postgres or HTTP. The poller's
correctness is: (1) every pending pair gets one verdict per registered judge,
(2) pairs are marked judged after persistence succeeds, (3) `drain()`
terminates when the queue is empty.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from cascadia_judge.executor import AsyncioJudgeExecutor
from cascadia_judge.judges import REGISTRY
from cascadia_judge.llm.fake import FakeLLMClient
from cascadia_judge.orchestrator import JudgeOrchestrator
from cascadia_judge.poller import Poller, PollerConfig
from cascadia_judge.storage.in_memory import InMemoryShadowPairStorage
from cascadia_judge.types import ShadowPair


def _pair(prompt: str = "what is 2+2?") -> ShadowPair:
    return ShadowPair(
        request_id=f"req-{prompt}",
        prompt=prompt,
        cheap_model="cheap",
        cheap_response="4",
        expensive_model="expensive",
        expensive_response="four (4)",
        cluster_id="default",
    )


def _fake_response() -> str:
    return '{"score": 0.7, "confidence": 0.8, "rationale": "tie-ish"}'


def _make_orchestrator(num_responses: int) -> JudgeOrchestrator:
    fake = FakeLLMClient(model="fake-1")
    for _ in range(num_responses):
        fake.queue(_fake_response())
    return JudgeOrchestrator(
        registry=REGISTRY,
        executor=AsyncioJudgeExecutor(),
        llm_factory=lambda _judge: fake,
    )


@pytest.mark.asyncio
async def test_drain_processes_all_pending() -> None:
    store = InMemoryShadowPairStorage()
    ids = [store.add_pair(_pair(f"prompt-{i}")) for i in range(3)]

    # Pin to a single judge so the FakeLLMClient queue length is predictable;
    # Phase 5 added two more registered judges that this assertion does not
    # care about.
    orchestrator = _make_orchestrator(num_responses=len(ids))
    poller = Poller(
        storage=store, orchestrator=orchestrator,
        config=PollerConfig(batch_size=10, judge_names=("pairwise_preference_v1",)),
    )

    processed = await poller.drain()

    assert processed == 3
    assert store.judged_ids() == set(ids)
    verdicts = store.all_verdicts()
    assert len(verdicts) == 3
    judge_names = {v.judge_name for v in verdicts}
    assert judge_names == {"pairwise_preference_v1"}


@pytest.mark.asyncio
async def test_drain_returns_zero_on_empty_queue() -> None:
    store = InMemoryShadowPairStorage()
    orchestrator = _make_orchestrator(num_responses=0)

    poller = Poller(storage=store, orchestrator=orchestrator)
    assert await poller.drain() == 0


@pytest.mark.asyncio
async def test_max_cycles_terminates_run_forever() -> None:
    store = InMemoryShadowPairStorage()
    pair_id = store.add_pair(_pair("one"))
    orchestrator = _make_orchestrator(num_responses=1)
    poller = Poller(
        storage=store,
        orchestrator=orchestrator,
        config=PollerConfig(
            batch_size=10, max_cycles=1, idle_sleep_s=0.0,
            judge_names=("pairwise_preference_v1",),
        ),
    )

    await poller.run_forever()

    assert store.judged_ids() == {pair_id}
    assert len(store.all_verdicts()) == 1


@pytest.mark.asyncio
async def test_drain_persists_ensemble_score() -> None:
    # EC-O1: the poller now persists the bias-corrected ensemble score per
    # pair so the policy controller can tune on it (instead of a raw AVG over
    # judge_scores rows).
    store = InMemoryShadowPairStorage()
    pid = store.add_pair(_pair("p"))
    orchestrator = _make_orchestrator(num_responses=1)
    poller = Poller(
        storage=store, orchestrator=orchestrator,
        config=PollerConfig(batch_size=10, judge_names=("pairwise_preference_v1",)),
    )
    await poller.drain()
    ens = store.ensemble_for(pid)
    assert ens is not None
    score, confidence = ens
    # Single judge verdict score=0.7, confidence=0.8 → weighted mean 0.7.
    assert score == pytest.approx(0.7)
    assert confidence == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_fetch_pending_claims_rows_so_a_second_fetch_skips_them() -> None:
    # EC-O3: a claimed (fresh) row must not be handed out again, so a second
    # poller replica doesn't re-judge it and double-pay for LLM calls.
    store = InMemoryShadowPairStorage()
    ids = {store.add_pair(_pair(f"p{i}")) for i in range(2)}
    first = await store.fetch_pending(10)
    assert {p.pair_id for p in first} == ids
    # Second fetch before anything is marked judged → claimed, so empty.
    assert await store.fetch_pending(10) == ()
    # Releasing a claim makes the pair available again (failed-pair retry).
    one = next(iter(ids))
    await store.release_claims([one])
    again = await store.fetch_pending(10)
    assert {p.pair_id for p in again} == {one}


@pytest.mark.asyncio
async def test_stale_claim_is_reclaimable() -> None:
    # A claim older than the reclaim window (crashed worker) is re-claimable.
    store = InMemoryShadowPairStorage(reclaim_after=timedelta(0))
    pid = store.add_pair(_pair("p"))
    await store.fetch_pending(10)  # claims it
    again = await store.fetch_pending(10)
    assert {p.pair_id for p in again} == {pid}


class _FailingWriteStorage(InMemoryShadowPairStorage):
    async def write_verdicts(self, pair_id, verdicts):  # type: ignore[override]
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_failed_pair_releases_its_claim_for_retry() -> None:
    store = _FailingWriteStorage()
    pid = store.add_pair(_pair("p"))
    orchestrator = _make_orchestrator(num_responses=1)
    poller = Poller(
        storage=store, orchestrator=orchestrator,
        config=PollerConfig(
            batch_size=10, max_cycles=1, idle_sleep_s=0.0,
            judge_names=("pairwise_preference_v1",),
        ),
    )
    await poller.run_forever()
    assert store.judged_ids() == set()  # not marked judged on failure
    # Claim was released → the pair is fetchable again next cycle.
    again = await store.fetch_pending(10)
    assert {p.pair_id for p in again} == {pid}


@pytest.mark.asyncio
async def test_batch_size_is_respected() -> None:
    store = InMemoryShadowPairStorage()
    for i in range(7):
        store.add_pair(_pair(f"q-{i}"))
    orchestrator = _make_orchestrator(num_responses=7)
    poller = Poller(
        storage=store,
        orchestrator=orchestrator,
        config=PollerConfig(
            batch_size=3, idle_sleep_s=0.0, max_cycles=3,
            judge_names=("pairwise_preference_v1",),
        ),
    )

    await poller.run_forever()

    # 3 cycles × 3 batch = up to 9; but only 7 pending, so all judged.
    assert len(store.judged_ids()) == 7
