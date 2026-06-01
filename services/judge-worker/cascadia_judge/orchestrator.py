from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Protocol, runtime_checkable

from cascadia_judge.executor import JudgeExecutor
from cascadia_judge.judges.base import BaseJudge, JudgeRegistry
from cascadia_judge.llm.base import LLMClient
from cascadia_judge.types import JudgeVerdict, ShadowPair

LLMClientFactory = Callable[[str], LLMClient]


@runtime_checkable
class PairEvaluator(Protocol):
    """What the poller needs: score one pair, return its verdicts. Both the
    single-model `JudgeOrchestrator` and the multi-model `PanelOrchestrator`
    satisfy this, so the poller is agnostic to which one it drives."""

    async def evaluate(
        self,
        pair: ShadowPair,
        *,
        judge_names: Sequence[str] | None = None,
    ) -> list[JudgeVerdict]: ...


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


class PanelOrchestrator:
    """Runs every selected judge against EVERY member of a model panel, so each
    shadow pair is scored by (judges × panel-models) verdicts.

    Each verdict is tagged with its panel member's model/provider, so the
    aggregator's anti-self-preference filter, position-fold, and error-exclusion
    deduplicate and correct exactly as they do for the single-model case — no
    poller or aggregator changes needed. This is the live, online equivalent of
    the offline cross-provider calibration panel (`cascadia-judge-llm-panel`):
    a true multi-model ensemble scoring production shadow traffic.
    """

    def __init__(
        self,
        registry: JudgeRegistry,
        executor: JudgeExecutor,
        clients: Sequence[LLMClient],
    ) -> None:
        if not clients:
            raise ValueError("PanelOrchestrator needs at least one LLM client")
        self.registry = registry
        self.executor = executor
        self.clients = list(clients)

    def _build_judges(self, names: Iterable[str] | None) -> list[BaseJudge]:
        # judge × panel-model cross product. A judge instance binds to exactly
        # one client, so its verdict carries that client's model/provider.
        return [
            cls(client)
            for cls in self.registry.select(names)
            for client in self.clients
        ]

    async def evaluate(
        self,
        pair: ShadowPair,
        *,
        judge_names: Sequence[str] | None = None,
    ) -> list[JudgeVerdict]:
        judges = self._build_judges(judge_names)
        return await self.executor.fan_out(judges, pair)
