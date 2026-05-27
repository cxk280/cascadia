"""Storage protocols for the judge worker.

These are the substitution surfaces between the eval plane (orchestrator,
judges) and the persistence layer (Postgres, or anything else later — Kafka,
S3 snapshots). The orchestrator never imports concrete adapters; the
`poller_cli` does. That keeps the SOLID-D dependency-inversion property the
deck pattern is built around.

Two protocols, single combined concrete class for convenience:

- `ShadowPairReader`  — fetch pending pairs, mark them judged.
- `JudgeVerdictWriter` — persist verdicts.
- `ShadowPairStorage`  — combined protocol; concrete adapters typically
  implement both halves backed by the same connection pool.

`PendingPair` is the shape the reader returns. It mirrors `ShadowPair` from
`types.py` but includes the `pair_id` (which the events-table `request_id`
alone doesn't provide; one request can in theory produce multiple pairs
across versions).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from cascadia_judge.types import JudgeVerdict, ShadowPair


@dataclass(frozen=True)
class PendingPair:
    """One row from `shadow_pairs` ready for scoring.

    The pair_id is the row's primary key; the orchestrator uses
    `ShadowPair.request_id` internally but verdicts persist against pair_id
    because that's the FK shadow_pairs(pair_id) → judge_scores.pair_id.
    """

    pair_id: str
    shadow_pair: ShadowPair


@dataclass(frozen=True)
class PairsAndVerdicts:
    """Result of one poller cycle.

    Returned by the storage adapter so callers (tests, the poller) can
    inspect what happened without re-querying Postgres.
    """

    pair_id: str
    verdicts: tuple[JudgeVerdict, ...]


@runtime_checkable
class ShadowPairReader(Protocol):
    """Read shadow_pairs that haven't been judged yet."""

    async def fetch_pending(self, limit: int) -> Sequence[PendingPair]:
        """Claim and return up to `limit` un-judged pairs, oldest first.

        Adapters should order by `occurred_at ASC` so the poller doesn't
        starve old pairs when a backlog accumulates, and must *claim* the
        rows they return (so a second poller replica doesn't re-fetch and
        re-judge the same pairs). A claim older than the adapter's reclaim
        window is treated as stale and may be re-claimed.
        """
        ...

    async def mark_judged(self, pair_ids: Sequence[str]) -> None:
        """Set shadow_pairs.judged_at = NOW() for the given pair ids."""
        ...

    async def release_claims(self, pair_ids: Sequence[str]) -> None:
        """Clear the claim on the given (still-unjudged) pairs.

        Called when processing failed so the pair retries on the next cycle
        instead of waiting out the stale-reclaim window.
        """
        ...


@runtime_checkable
class JudgeVerdictWriter(Protocol):
    """Persist judge verdicts. Idempotent on (pair_id, judge_name, prompt_variant)."""

    async def write_verdicts(
        self,
        pair_id: str,
        verdicts: Sequence[JudgeVerdict],
    ) -> None:
        ...

    async def set_ensemble_score(
        self,
        pair_id: str,
        score: float | None,
        confidence: float | None,
    ) -> None:
        """Persist the bias-corrected ensemble score for a pair.

        `None`/`None` records "judged, but no usable signal" so the policy
        controller excludes the pair from its mean.
        """
        ...


@runtime_checkable
class ShadowPairStorage(ShadowPairReader, JudgeVerdictWriter, Protocol):
    """Convenience: an adapter that implements both halves with one resource pool."""

    async def close(self) -> None:
        """Release any underlying resources (connection pools, etc.)."""
        ...
