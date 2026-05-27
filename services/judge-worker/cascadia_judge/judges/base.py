from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from typing import ClassVar

from cascadia_judge.llm.base import LLMClient
from cascadia_judge.types import JudgeScore, JudgeVerdict, Message, ShadowPair

ResponseParser = Callable[[str], JudgeScore]


class BaseJudge(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    prompt_variant: ClassVar[str]

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    @abstractmethod
    async def judge(self, pair: ShadowPair) -> JudgeVerdict: ...

    async def _score_with_llm(
        self,
        pair: ShadowPair,
        system: str,
        user: str,
        *,
        parse: ResponseParser,
    ) -> JudgeVerdict:
        prompt_hash = _hash_prompt(self.llm.model, self.prompt_variant, system, user)
        bind = getattr(self.llm, "bind", None)
        if callable(bind):
            bind(self.name, pair.request_id)
        started = time.perf_counter()
        error: str | None = None
        score: JudgeScore
        try:
            resp = await self.llm.chat(
                system=system,
                messages=[Message(role="user", content=user)],
            )
            score = parse(resp.text)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            score = JudgeScore(score=0.0, confidence=0.0, rationale=f"judge error: {error}")
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return JudgeVerdict(
            request_id=pair.request_id,
            judge_name=self.name,
            prompt_variant=self.prompt_variant,
            model=self.llm.model,
            provider=self.llm.provider,
            score=score,
            prompt_hash=prompt_hash,
            elapsed_ms=elapsed_ms,
            error=error,
        )


def _hash_prompt(model: str, variant: str, system: str, user: str) -> str:
    h = hashlib.sha256()
    for piece in (model, variant, system, user):
        h.update(piece.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class JudgeRegistry:
    """Decorator-based registry. Adding a judge requires no orchestrator edits."""

    def __init__(self) -> None:
        self._judges: dict[str, type[BaseJudge]] = {}

    def register(self, cls: type[BaseJudge]) -> type[BaseJudge]:
        for attr in ("name", "description", "prompt_variant"):
            if not getattr(cls, attr, None):
                raise TypeError(f"{cls.__name__} missing required class attr {attr!r}")
        existing = self._judges.get(cls.name)
        if existing is not None and existing is not cls:
            raise ValueError(
                f"judge name collision: {cls.name!r} already registered to {existing.__name__}"
            )
        self._judges[cls.name] = cls
        return cls

    def get(self, name: str) -> type[BaseJudge]:
        return self._judges[name]

    def names(self) -> list[str]:
        return sorted(self._judges)

    def all(self) -> Iterator[type[BaseJudge]]:
        return iter(self._judges.values())

    def select(self, names: Iterable[str] | None = None) -> list[type[BaseJudge]]:
        if names is None:
            return list(self._judges.values())
        return [self._judges[n] for n in names]


REGISTRY = JudgeRegistry()


def register_judge(cls: type[BaseJudge]) -> type[BaseJudge]:
    return REGISTRY.register(cls)
