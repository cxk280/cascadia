"""Storage adapters for the judge worker.

The base module defines the `ShadowPairReader` and `JudgeVerdictWriter`
protocols. Concrete adapters (Postgres via asyncpg, in-memory for tests)
implement those protocols. The orchestrator never imports anything from this
package — wiring happens at the CLI / service boundary.
"""

from cascadia_judge.storage.base import (
    JudgeVerdictWriter,
    PairsAndVerdicts,
    PendingPair,
    ShadowPairReader,
    ShadowPairStorage,
)

__all__ = [
    "JudgeVerdictWriter",
    "PairsAndVerdicts",
    "PendingPair",
    "ShadowPairReader",
    "ShadowPairStorage",
]
