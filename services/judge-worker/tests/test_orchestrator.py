from __future__ import annotations


from cascadia_judge.executor import AsyncioJudgeExecutor
from cascadia_judge.judges.base import BaseJudge, JudgeRegistry
from cascadia_judge.llm.base import LLMClient
from cascadia_judge.llm.fake import FakeLLMClient
from cascadia_judge.orchestrator import JudgeOrchestrator
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


async def test_orchestrator_fans_out_to_every_registered_judge() -> None:
    reg = JudgeRegistry()
    reg.register(_make_constant_judge_cls("alpha_v1", 0.4))
    reg.register(_make_constant_judge_cls("beta_v1", 0.7))

    def factory(judge_name: str) -> LLMClient:
        return FakeLLMClient(model=f"model-for-{judge_name}")

    orch = JudgeOrchestrator(
        registry=reg,
        executor=AsyncioJudgeExecutor(),
        llm_factory=factory,
    )

    verdicts = await orch.evaluate(_pair())
    by_name = {v.judge_name: v for v in verdicts}

    assert set(by_name) == {"alpha_v1", "beta_v1"}
    assert by_name["alpha_v1"].score.score == 0.4
    assert by_name["beta_v1"].score.score == 0.7
    assert by_name["alpha_v1"].model == "model-for-alpha_v1"


async def test_orchestrator_can_select_subset_of_judges() -> None:
    reg = JudgeRegistry()
    reg.register(_make_constant_judge_cls("alpha_v1", 0.4))
    reg.register(_make_constant_judge_cls("beta_v1", 0.7))

    orch = JudgeOrchestrator(
        registry=reg,
        executor=AsyncioJudgeExecutor(),
        llm_factory=lambda _name: FakeLLMClient(),
    )

    verdicts = await orch.evaluate(_pair(), judge_names=["beta_v1"])
    assert len(verdicts) == 1
    assert verdicts[0].judge_name == "beta_v1"


async def test_executor_returns_empty_for_no_judges() -> None:
    reg = JudgeRegistry()
    orch = JudgeOrchestrator(
        registry=reg,
        executor=AsyncioJudgeExecutor(),
        llm_factory=lambda _name: FakeLLMClient(),
    )
    assert await orch.evaluate(_pair()) == []
