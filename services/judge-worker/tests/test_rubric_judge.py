"""RubricJudge unit tests — two-call shape, sigmoid mapping, error paths."""

from __future__ import annotations

import json
import math

import pytest

from cascadia_judge.judges.rubric import RubricJudge
from cascadia_judge.llm.scripted import ScriptedLLMClient
from cascadia_judge.types import ShadowPair


def _pair() -> ShadowPair:
    return ShadowPair(
        request_id="r1",
        prompt="What is 2+2?",
        cheap_model="cheap-m",
        cheap_response="4",
        expensive_model="expensive-m",
        expensive_response="The answer is 4.",
    )


def _fixture(cheap_score: float, expensive_score: float) -> dict:
    return {
        "model": "scripted",
        "responses": {
            "rubric_v1::r1#cheap": json.dumps(
                {"score": cheap_score, "rationale": "ok"}
            ),
            "rubric_v1::r1#expensive": json.dumps(
                {"score": expensive_score, "rationale": "ok"}
            ),
        },
    }


@pytest.mark.asyncio
async def test_rubric_judge_cheap_clearly_better() -> None:
    client = ScriptedLLMClient(_fixture(cheap_score=9, expensive_score=3))
    judge = RubricJudge(client)
    v = await judge.judge(_pair())
    expected = 1 / (1 + math.exp(-(9 - 3) / 4.0))
    assert v.score.score == pytest.approx(expected)
    assert v.score.confidence == pytest.approx(min(1.0, 6 / 10))
    assert v.error is None


@pytest.mark.asyncio
async def test_rubric_judge_tied_responses_score_half() -> None:
    client = ScriptedLLMClient(_fixture(cheap_score=7, expensive_score=7))
    judge = RubricJudge(client)
    v = await judge.judge(_pair())
    assert v.score.score == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_rubric_judge_invalid_response_sets_error() -> None:
    client = ScriptedLLMClient({
        "model": "scripted",
        "responses": {
            "rubric_v1::r1#cheap": "I am not JSON.",
            "rubric_v1::r1#expensive": json.dumps({"score": 5, "rationale": "x"}),
        },
    })
    judge = RubricJudge(client)
    v = await judge.judge(_pair())
    assert v.error is not None
    assert "ValueError" in v.error or "JSON" in v.error.lower() or "json" in v.error
    assert v.score.score == 0.0
    assert v.score.confidence == 0.0


@pytest.mark.asyncio
async def test_rubric_judge_nonfinite_score_sets_error() -> None:
    # NaN must not leak into the sigmoid (max/min against NaN is order-
    # dependent). It becomes a clean error verdict instead.
    client = ScriptedLLMClient(_fixture(cheap_score=float("nan"), expensive_score=5))
    v = await RubricJudge(client).judge(_pair())
    assert v.error is not None
    assert v.score.score == 0.0
