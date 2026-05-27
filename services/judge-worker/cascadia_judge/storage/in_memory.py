"""In-memory implementation of `ShadowPairStorage`.

Used by the unit tests so the poller and orchestrator can be exercised
without a Postgres process. Not intended for production.

Behavior notes:
- `fetch_pending` returns pairs in insertion order (matches Postgres
  `ORDER BY occurred_at ASC`).
- `mark_judged` is idempotent.
- `write_verdicts` deduplicates by `(pair_id, judge_name, prompt_variant)`
  to mirror the Postgres UNIQUE constraint.
- `close` is a no-op.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence

from cascadia_judge.storage.base import PendingPair, ShadowPairStorage
from cascadia_judge.types import JudgeVerdict, ShadowPair


class InMemoryShadowPairStorage(ShadowPairStorage):
    def __init__(self) -> None:
        self._pending: dict[str, ShadowPair] = {}
        self._judged: set[str] = set()
        self._verdicts: dict[tuple[str, str, str], JudgeVerdict] = {}
        self._lock = asyncio.Lock()
        self._insertion_order: list[str] = []

    # --- test setup helpers ---

    def add_pair(self, pair: ShadowPair) -> str:
        """Add a pair and return the generated pair_id."""
        pair_id = str(uuid.uuid4())
        self._pending[pair_id] = pair
        self._insertion_order.append(pair_id)
        return pair_id

    def all_verdicts(self) -> list[JudgeVerdict]:
        return list(self._verdicts.values())

    def judged_ids(self) -> set[str]:
        return set(self._judged)

    # --- protocol implementation ---

    async def fetch_pending(self, limit: int) -> Sequence[PendingPair]:
        async with self._lock:
            unjudged_ids = [pid for pid in self._insertion_order if pid not in self._judged]
            return tuple(
                PendingPair(pair_id=pid, shadow_pair=self._pending[pid])
                for pid in unjudged_ids[:limit]
            )

    async def mark_judged(self, pair_ids: Sequence[str]) -> None:
        async with self._lock:
            for pid in pair_ids:
                self._judged.add(pid)

    async def write_verdicts(
        self,
        pair_id: str,
        verdicts: Sequence[JudgeVerdict],
    ) -> None:
        async with self._lock:
            for v in verdicts:
                key = (pair_id, v.judge_name, v.prompt_variant)
                # Mirror Postgres `ON CONFLICT … DO NOTHING`: first writer wins.
                # Tests that assume re-writes are visible will catch real
                # behavior drift on the Postgres side.
                self._verdicts.setdefault(key, v)

    async def close(self) -> None:  # pragma: no cover (no-op)
        return None
