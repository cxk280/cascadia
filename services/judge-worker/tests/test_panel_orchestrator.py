"""PanelOrchestrator: every registered judge runs against every panel member,
so a pair gets (judges × models) verdicts, each tagged with its member's
model/provider (which the aggregator then folds)."""

from __future__ import annotations

import pytest

from cascadia_judge.executor import AsyncioJudgeExecutor
from cascadia_judge.judges.base import BaseJudge, JudgeRegistry
from cascadia_judge.llm.fake import FakeLLMClient
from cascadia_judge.orchestrator import PanelOrchestrator
from cascadia_judge.types import JudgeScore, JudgeVerdict, ShadowPair


def _pair() -> ShadowPair:
    return ShadowPair(
        request_id="r1",
        prompt="p",
        cheap_model="c",
        cheap_response="cr",
        expensive_model="e",
        expensive_response="er",
    )


def _make_constant_judge_cls(judge_name: str, score: float) -> type[BaseJudge]:
    class _ConstantJudge(BaseJudge):
        name = judge_name
        description = "constant"
        prompt_variant = f"{judge_name}/v1"

        async def judge(self, pair: ShadowPair) -> JudgeVerdict:
            return JudgeVerdict(
                request_id=pair.request_id,
                judge_name=self.name,
                prompt_variant=self.prompt_variant,
                model=self.llm.model,
                provider=self.llm.provider,
                score=JudgeScore(score=score, rationale="constant"),
                prompt_hash="0" * 64,
                elapsed_ms=0,
            )

    return _ConstantJudge


def _client(provider: str, model: str) -> FakeLLMClient:
    c = FakeLLMClient(model=model)
    c.provider = provider  # instance attr shadows the class default ("fake")
    return c


async def test_panel_scores_every_judge_against_every_member() -> None:
    reg = JudgeRegistry()
    reg.register(_make_constant_judge_cls("alpha_v1", 0.4))
    reg.register(_make_constant_judge_cls("beta_v1", 0.7))

    panel = [
        _client("openai", "gpt-4o-mini"),
        _client("openai", "gpt-4o"),
        _client("groq", "llama-3.3-70b"),
    ]
    orch = PanelOrchestrator(
        registry=reg, executor=AsyncioJudgeExecutor(), clients=panel
    )

    verdicts = await orch.evaluate(_pair())

    # 2 judges × 3 panel members = 6 verdicts.
    assert len(verdicts) == 6
    # Every (judge, model) combination appears exactly once.
    combos = {(v.judge_name, v.provider, v.model) for v in verdicts}
    assert combos == {
        ("alpha_v1", "openai", "gpt-4o-mini"),
        ("alpha_v1", "openai", "gpt-4o"),
        ("alpha_v1", "groq", "llama-3.3-70b"),
        ("beta_v1", "openai", "gpt-4o-mini"),
        ("beta_v1", "openai", "gpt-4o"),
        ("beta_v1", "groq", "llama-3.3-70b"),
    }


async def test_panel_respects_judge_name_filter() -> None:
    reg = JudgeRegistry()
    reg.register(_make_constant_judge_cls("alpha_v1", 0.4))
    reg.register(_make_constant_judge_cls("beta_v1", 0.7))
    orch = PanelOrchestrator(
        registry=reg,
        executor=AsyncioJudgeExecutor(),
        clients=[_client("openai", "gpt-4o-mini"), _client("groq", "llama-3.3-70b")],
    )

    verdicts = await orch.evaluate(_pair(), judge_names=["alpha_v1"])

    # 1 selected judge × 2 members = 2 verdicts, all alpha.
    assert len(verdicts) == 2
    assert {v.judge_name for v in verdicts} == {"alpha_v1"}
    assert {v.model for v in verdicts} == {"gpt-4o-mini", "llama-3.3-70b"}


async def test_panel_requires_at_least_one_client() -> None:
    with pytest.raises(ValueError):
        PanelOrchestrator(
            registry=JudgeRegistry(), executor=AsyncioJudgeExecutor(), clients=[]
        )
