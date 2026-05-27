from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Protocol

from cascadia_judge.judges.base import BaseJudge
from cascadia_judge.types import JudgeVerdict, ShadowPair


class JudgeExecutor(Protocol):
    """Substitutable fan-out strategy.

    Local dev uses asyncio. A future executor (NATS consumer pool, Ray) implements
    this same Protocol so the orchestrator never imports the runtime.
    """

    async def fan_out(
        self,
        judges: Sequence[BaseJudge],
        pair: ShadowPair,
    ) -> list[JudgeVerdict]: ...


class AsyncioJudgeExecutor:
    provider = "asyncio"

    async def fan_out(
        self,
        judges: Sequence[BaseJudge],
        pair: ShadowPair,
    ) -> list[JudgeVerdict]:
        if not judges:
            return []
        return list(await asyncio.gather(*(j.judge(pair) for j in judges)))
