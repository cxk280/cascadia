from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from cascadia_judge.executor import JudgeExecutor
from cascadia_judge.judges.base import BaseJudge, JudgeRegistry
from cascadia_judge.llm.base import LLMClient
from cascadia_judge.types import JudgeVerdict, ShadowPair

LLMClientFactory = Callable[[str], LLMClient]


class JudgeOrchestrator:
    """Composition root.

    Holds abstractions only. Concrete LLM clients and executor are injected at the
    CLI / service boundary; the orchestrator never imports a provider SDK or a
    runtime backend.
    """

    def __init__(
        self,
        registry: JudgeRegistry,
        executor: JudgeExecutor,
        llm_factory: LLMClientFactory,
    ) -> None:
        self.registry = registry
        self.executor = executor
        self.llm_factory = llm_factory

    def _build_judges(self, names: Iterable[str] | None) -> list[BaseJudge]:
        judges: list[BaseJudge] = []
        for cls in self.registry.select(names):
            llm = self.llm_factory(cls.name)
            judges.append(cls(llm))
        return judges

    async def evaluate(
        self,
        pair: ShadowPair,
        *,
        judge_names: Sequence[str] | None = None,
    ) -> list[JudgeVerdict]:
        judges = self._build_judges(judge_names)
        return await self.executor.fan_out(judges, pair)
