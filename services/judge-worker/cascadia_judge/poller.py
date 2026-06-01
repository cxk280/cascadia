"""Long-running poller: fetch unjudged shadow_pairs, score them, persist.

The poller depends only on `ShadowPairStorage` (a protocol) and a
`JudgeOrchestrator`. It has no provider-specific imports. Backoff and stop
conditions are inputs, not magic numbers — see `PollerConfig`.

Typical lifecycle:

    storage = await AsyncpgShadowPairStorage.connect(dsn)
    poller = Poller(storage=storage, orchestrator=orchestrator)
    try:
        await poller.run_forever()       # or await poller.drain() for one cycle
    finally:
        await storage.close()
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from cascadia_judge.aggregation import aggregate
from cascadia_judge.orchestrator import PairEvaluator
from cascadia_judge.storage.base import PendingPair, ShadowPairStorage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PollerConfig:
    """Knobs for the polling loop. Defaults are dev-friendly."""

    batch_size: int = 16
    idle_sleep_s: float = 1.0
    """Sleep this long when fetch_pending returns no rows."""
    error_backoff_s: float = 5.0
    """Sleep this long after a fetch/persist error before retrying."""
    judge_names: Sequence[str] | None = None
    """If set, restrict orchestrator.evaluate to these judges."""
    max_cycles: int | None = None
    """If set, stop after N polling cycles. Tests use this; prod leaves None."""


class Poller:
    """Drives the eval loop. Test it with InMemoryShadowPairStorage."""

    def __init__(
        self,
        *,
        storage: ShadowPairStorage,
        orchestrator: PairEvaluator,
        config: PollerConfig | None = None,
    ) -> None:
        self._storage = storage
        self._orchestrator = orchestrator
        self._config = config or PollerConfig()
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        """Signal the loop to exit at the next safe point."""
        self._stopping.set()

    async def run_forever(self) -> None:
        cycle = 0
        while not self._stopping.is_set():
            try:
                processed = await self._cycle()
            except Exception:  # noqa: BLE001 — we don't want to crash the poller
                logger.exception("poller cycle failed; backing off")
                await self._sleep(self._config.error_backoff_s)
                continue

            cycle += 1
            if self._config.max_cycles is not None and cycle >= self._config.max_cycles:
                return
            if processed == 0:
                await self._sleep(self._config.idle_sleep_s)

    async def drain(self) -> int:
        """Run cycles until fetch returns no pending pairs. Returns total processed."""
        total = 0
        while True:
            processed = await self._cycle()
            total += processed
            if processed == 0:
                return total

    async def _cycle(self) -> int:
        pending = await self._storage.fetch_pending(self._config.batch_size)
        if not pending:
            return 0
        results = await asyncio.gather(
            *(self._process_pair(p) for p in pending),
            return_exceptions=True,
        )
        # Only mark_judged the pairs that fully succeeded. Failures are
        # logged and will be retried on the next cycle (where the dedup
        # constraint in judge_scores prevents double-billing).
        succeeded = [
            pending[i].pair_id for i, r in enumerate(results) if not isinstance(r, BaseException)
        ]
        if succeeded:
            await self._storage.mark_judged(succeeded)
        failures = [(pending[i].pair_id, r) for i, r in enumerate(results) if isinstance(r, BaseException)]
        if failures:
            # Release the claim so a failed pair retries on the next cycle
            # rather than waiting out the stale-reclaim window. A crashed
            # worker can't reach this path, so its claim is reclaimed later.
            await self._storage.release_claims([pair_id for pair_id, _ in failures])
        for pair_id, err in failures:
            logger.warning("pair %s failed to judge: %r", pair_id, err)
        return len(succeeded)

    async def _process_pair(self, pending: PendingPair) -> None:
        verdicts = await self._orchestrator.evaluate(
            pending.shadow_pair,
            judge_names=self._config.judge_names,
        )
        await self._storage.write_verdicts(pending.pair_id, verdicts)
        # Persist the bias-corrected ensemble score the policy controller tunes
        # on (anti-self-preference + position-fold + error-exclusion). When no
        # judge produced a usable signal, persist NULL so the controller
        # excludes the pair instead of averaging in a neutral 0.5. concision
        # weight stays at the documented 0.0 default — the 0.30 pilot value is
        # a characterized correction, not the default.
        ensemble = aggregate(
            pending.shadow_pair, verdicts, pair_id=pending.pair_id
        )
        if ensemble.n_used > 0:
            await self._storage.set_ensemble_score(
                pending.pair_id, ensemble.score, ensemble.confidence
            )
        else:
            await self._storage.set_ensemble_score(pending.pair_id, None, None)

    async def _sleep(self, seconds: float) -> None:
        # Make sleep cancellable by `stop()` so tests don't hang.
        try:
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return
