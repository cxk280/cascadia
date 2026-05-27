"""Repository for the labeling write surface.

Holds the (small) bit of server-side state needed for position
randomization: when a reviewer asks for their next pair, we record which
direction we showed them in a short-lived map keyed by (pair_id,
reviewer_id) — even though the *persisted* swap direction only lands when
they actually submit a label. That lets retries (browser refresh) keep
the same direction for the same pair.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

import asyncpg


@runtime_checkable
class CalibrationStore(Protocol):
    async def upsert_reviewer(
        self, reviewer_id: str, display_name: str
    ) -> tuple[datetime, bool, str]: ...
    async def next_pair_for(self, reviewer_id: str) -> "PendingPair | None": ...
    async def queue_size_for(self, reviewer_id: str) -> int: ...
    async def submit_label(
        self,
        *,
        pair_id: str,
        reviewer_id: str,
        shown_swapped: bool,
        raw_label: str,
        rationale: str | None,
        time_ms: int | None,
        rubric_version: str,
    ) -> str: ...
    async def progress_for(self, reviewer_id: str) -> "ReviewerProgress": ...


@dataclass(frozen=True)
class PendingPair:
    pair_id: str
    prompt: str
    response_a: str
    response_b: str
    cluster_id: str | None
    selection_round: int
    selection_reason: str
    queue_position: int


@dataclass(frozen=True)
class ReviewerProgress:
    n_labeled: int
    n_pending: int
    n_attention_passed: int
    n_attention_failed: int


def decide_swap(*, pair_id: str, reviewer_id: str) -> bool:
    """Deterministic position-swap per (pair, reviewer).

    Why deterministic rather than random? A reviewer who refreshes their
    browser mid-label-batch should see the *same* slot ordering they saw
    a moment ago — otherwise their in-flight mental model breaks. Hashing
    `pair_id + reviewer_id` to a coin flip gets us that without any
    server-side session storage.
    """

    rng = random.Random(f"{pair_id}::{reviewer_id}")
    return rng.random() < 0.5


class AsyncpgCalibrationStore(CalibrationStore):
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._unswap_ensured = False

    async def upsert_reviewer(
        self, reviewer_id: str, display_name: str
    ) -> tuple[datetime, bool, str]:
        # ON CONFLICT keeps the EXISTING display_name. A second call with a
        # different display_name no longer silently clobbers the row — that
        # was a real foot-gun where Bob typing "chris" with name "Bob Smith"
        # would rename the existing Chris reviewer. Return the row's actual
        # display_name so the caller can show "already_existed under name X"
        # to the user.
        sql = """
            INSERT INTO calibration_reviewers (reviewer_id, display_name, onboarded_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (reviewer_id) DO UPDATE
                SET display_name = calibration_reviewers.display_name
            RETURNING onboarded_at, display_name, (xmax = 0) AS inserted
        """
        row = await self._pool.fetchrow(sql, reviewer_id, display_name)
        if row is None:
            raise RuntimeError("upsert returned no row")
        already_existed = not bool(row["inserted"])
        return row["onboarded_at"], already_existed, row["display_name"]

    async def next_pair_for(self, reviewer_id: str) -> PendingPair | None:
        # First make sure the reviewer is known — `calibration_pending` is
        # a CROSS JOIN against `calibration_reviewers`, so an unknown
        # reviewer just gets an empty queue.
        sql = """
            SELECT pair_id, prompt, response_a, response_b, cluster_id,
                   selection_round, selection_reason
              FROM calibration_pending
             WHERE reviewer_id = $1
             LIMIT 1
        """
        row = await self._pool.fetchrow(sql, reviewer_id)
        if row is None:
            return None
        position = await self._position_in_queue(reviewer_id, str(row["pair_id"]))
        return PendingPair(
            pair_id=str(row["pair_id"]),
            prompt=row["prompt"],
            response_a=row["response_a"],
            response_b=row["response_b"],
            cluster_id=row["cluster_id"],
            selection_round=row["selection_round"],
            selection_reason=row["selection_reason"],
            queue_position=position,
        )

    async def _position_in_queue(self, reviewer_id: str, pair_id: str) -> int:
        sql = """
            SELECT COUNT(*) + 1 AS pos
              FROM calibration_pending
             WHERE reviewer_id = $1
               AND pair_id < $2::uuid
        """
        row = await self._pool.fetchrow(sql, reviewer_id, pair_id)
        return int(row["pos"]) if row else 1

    async def queue_size_for(self, reviewer_id: str) -> int:
        sql = "SELECT COUNT(*) AS n FROM calibration_pending WHERE reviewer_id = $1"
        row = await self._pool.fetchrow(sql, reviewer_id)
        return int(row["n"]) if row else 0

    async def submit_label(
        self,
        *,
        pair_id: str,
        reviewer_id: str,
        shown_swapped: bool,
        raw_label: str,
        rationale: str | None,
        time_ms: int | None,
        rubric_version: str,
    ) -> str:
        label_id = uuid.uuid4()
        sql = """
            INSERT INTO calibration_labels (
                label_id, pair_id, reviewer_id, shown_swapped,
                raw_label, rationale, time_ms, rubric_version, labeled_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
            ON CONFLICT (pair_id, reviewer_id) DO UPDATE
                SET shown_swapped = EXCLUDED.shown_swapped,
                    raw_label     = EXCLUDED.raw_label,
                    rationale     = EXCLUDED.rationale,
                    time_ms       = EXCLUDED.time_ms,
                    rubric_version= EXCLUDED.rubric_version,
                    labeled_at    = NOW()
            RETURNING label_id
        """
        row = await self._pool.fetchrow(
            sql, label_id, pair_id, reviewer_id, shown_swapped,
            raw_label, rationale, time_ms, rubric_version,
        )
        if row is None:
            raise RuntimeError("label insert returned no row")
        return str(row["label_id"])

    async def progress_for(self, reviewer_id: str) -> ReviewerProgress:
        sql = """
            WITH labeled AS (
                SELECT l.pair_id, p.attention_check_answer, l.raw_label, l.shown_swapped
                  FROM calibration_labels l
                  JOIN calibration_pairs   p ON p.pair_id = l.pair_id
                 WHERE l.reviewer_id = $1
            )
            SELECT
                COUNT(*) AS n_labeled,
                SUM(CASE
                    WHEN attention_check_answer IS NOT NULL
                     AND _unswap(raw_label, shown_swapped) = attention_check_answer THEN 1
                    ELSE 0
                END) AS n_attention_passed,
                SUM(CASE
                    WHEN attention_check_answer IS NOT NULL
                     AND _unswap(raw_label, shown_swapped) <> attention_check_answer THEN 1
                    ELSE 0
                END) AS n_attention_failed
              FROM labeled
        """
        # We need an SQL helper for un-swap. Define inline if not already there.
        await self._ensure_unswap_function()
        row = await self._pool.fetchrow(sql, reviewer_id)
        n_pending = await self.queue_size_for(reviewer_id)
        return ReviewerProgress(
            n_labeled=int(row["n_labeled"] or 0),
            n_pending=n_pending,
            n_attention_passed=int(row["n_attention_passed"] or 0),
            n_attention_failed=int(row["n_attention_failed"] or 0),
        )

    async def _ensure_unswap_function(self) -> None:
        # Run the DDL once per process, not on every /progress read. The
        # previous per-call CREATE OR REPLACE took an ACCESS EXCLUSIVE lock on
        # the function on a hot read path; concurrent reads serialized on it.
        # CREATE OR REPLACE is idempotent so the worst a startup race does is
        # run the (identical) DDL twice.
        if self._unswap_ensured:
            return
        await self._pool.execute(
            """
            CREATE OR REPLACE FUNCTION _unswap(raw TEXT, swapped BOOLEAN)
            RETURNS TEXT AS $$
                SELECT CASE
                    WHEN NOT swapped THEN raw
                    WHEN raw = 'a'   THEN 'b'
                    WHEN raw = 'b'   THEN 'a'
                    ELSE raw
                END
            $$ LANGUAGE SQL IMMUTABLE;
            """
        )
        self._unswap_ensured = True


class InMemoryCalibrationStore(CalibrationStore):
    """Test fake. Holds pairs in an ordered list; reviewers each get all of
    them in insertion order minus what they've already labeled."""

    def __init__(self) -> None:
        self._reviewers: dict[str, datetime] = {}
        self._pairs: list[PendingPair] = []
        self._pair_attention: dict[str, str | None] = {}
        self._labels: list[dict] = []

    def seed_pair(
        self,
        *,
        pair_id: str,
        prompt: str,
        response_a: str,
        response_b: str,
        cluster_id: str | None = None,
        selection_round: int = 1,
        selection_reason: str = "seed",
        attention_check_answer: str | None = None,
    ) -> None:
        self._pairs.append(PendingPair(
            pair_id=pair_id, prompt=prompt,
            response_a=response_a, response_b=response_b,
            cluster_id=cluster_id, selection_round=selection_round,
            selection_reason=selection_reason, queue_position=1,
        ))
        self._pair_attention[pair_id] = attention_check_answer

    async def upsert_reviewer(
        self, reviewer_id: str, display_name: str
    ) -> tuple[datetime, bool, str]:
        already = reviewer_id in self._reviewers
        if not already:
            self._reviewers[reviewer_id] = (
                datetime.now(timezone.utc),
                display_name,
            )
        onboarded_at, existing_display_name = self._reviewers[reviewer_id]
        return onboarded_at, already, existing_display_name

    async def next_pair_for(self, reviewer_id: str) -> PendingPair | None:
        labeled = {row["pair_id"] for row in self._labels if row["reviewer_id"] == reviewer_id}
        for i, pair in enumerate(self._pairs):
            if pair.pair_id not in labeled:
                pending = list(p for p in self._pairs if p.pair_id not in labeled)
                position = next(
                    (idx for idx, p in enumerate(pending) if p.pair_id == pair.pair_id), 0
                ) + 1
                return PendingPair(
                    pair_id=pair.pair_id, prompt=pair.prompt,
                    response_a=pair.response_a, response_b=pair.response_b,
                    cluster_id=pair.cluster_id, selection_round=pair.selection_round,
                    selection_reason=pair.selection_reason, queue_position=position,
                )
        return None

    async def queue_size_for(self, reviewer_id: str) -> int:
        labeled = {row["pair_id"] for row in self._labels if row["reviewer_id"] == reviewer_id}
        return sum(1 for p in self._pairs if p.pair_id not in labeled)

    async def submit_label(
        self,
        *,
        pair_id: str,
        reviewer_id: str,
        shown_swapped: bool,
        raw_label: str,
        rationale: str | None,
        time_ms: int | None,
        rubric_version: str,
    ) -> str:
        # Idempotent upsert by (pair_id, reviewer_id).
        for entry in self._labels:
            if entry["pair_id"] == pair_id and entry["reviewer_id"] == reviewer_id:
                entry.update({
                    "shown_swapped": shown_swapped, "raw_label": raw_label,
                    "rationale": rationale, "time_ms": time_ms,
                    "rubric_version": rubric_version,
                })
                return str(entry["label_id"])
        label_id = str(uuid.uuid4())
        self._labels.append({
            "label_id": label_id, "pair_id": pair_id, "reviewer_id": reviewer_id,
            "shown_swapped": shown_swapped, "raw_label": raw_label,
            "rationale": rationale, "time_ms": time_ms, "rubric_version": rubric_version,
        })
        return label_id

    async def progress_for(self, reviewer_id: str) -> ReviewerProgress:
        labeled_entries = [row for row in self._labels if row["reviewer_id"] == reviewer_id]
        passed = 0
        failed = 0
        for entry in labeled_entries:
            correct = self._pair_attention.get(entry["pair_id"])
            if correct is None:
                continue
            actual = _unswap(entry["raw_label"], entry["shown_swapped"])
            if actual == correct:
                passed += 1
            else:
                failed += 1
        return ReviewerProgress(
            n_labeled=len(labeled_entries),
            n_pending=await self.queue_size_for(reviewer_id),
            n_attention_passed=passed,
            n_attention_failed=failed,
        )


def _unswap(raw: str, shown_swapped: bool) -> str:
    if not shown_swapped:
        return raw
    if raw == "a":
        return "b"
    if raw == "b":
        return "a"
    return raw
