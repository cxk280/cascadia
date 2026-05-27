from __future__ import annotations


from cascadia_judge.judges.pairwise_preference import PairwisePreferenceJudge
from cascadia_judge.llm.fake import FakeLLMClient
from cascadia_judge.types import ShadowPair


def _pair() -> ShadowPair:
    return ShadowPair(
        request_id="req-1",
        prompt="What is 2+2?",
        cheap_model="cheap",
        cheap_response="4",
        expensive_model="expensive",
        expensive_response="Four.",
    )


async def test_happy_path_parses_score_and_records_provenance() -> None:
    llm = FakeLLMClient(model="cheap-judge")
    llm.queue('{"score": 0.92, "confidence": 0.8, "rationale": "tied"}')
    judge = PairwisePreferenceJudge(llm)

    verdict = await judge.judge(_pair())

    assert verdict.score.score == 0.92
    assert verdict.score.confidence == 0.8
    assert verdict.score.rationale == "tied"
    assert verdict.judge_name == "pairwise_preference_v1"
    assert verdict.prompt_variant == "pairwise/v1"
    assert verdict.model == "cheap-judge"
    assert verdict.provider == "fake"
    assert len(verdict.prompt_hash) == 64  # sha256 hex
    assert verdict.error is None


async def test_malformed_response_becomes_error_score() -> None:
    llm = FakeLLMClient()
    llm.queue("definitely not json")
    judge = PairwisePreferenceJudge(llm)

    verdict = await judge.judge(_pair())

    assert verdict.error is not None
    assert verdict.score.score == 0.0


async def test_partial_json_is_extracted_from_wrapper_text() -> None:
    llm = FakeLLMClient()
    llm.queue('Sure! Here is my verdict: {"score": 0.5, "rationale": "tie"} -- done.')
    judge = PairwisePreferenceJudge(llm)

    verdict = await judge.judge(_pair())

    assert verdict.score.score == 0.5
    assert verdict.score.rationale == "tie"
    assert verdict.error is None


async def test_prompt_hash_is_stable_across_runs() -> None:
    llm1 = FakeLLMClient()
    llm1.queue('{"score": 0.5, "rationale": "x"}')
    llm2 = FakeLLMClient()
    llm2.queue('{"score": 0.5, "rationale": "x"}')

    v1 = await PairwisePreferenceJudge(llm1).judge(_pair())
    v2 = await PairwisePreferenceJudge(llm2).judge(_pair())

    assert v1.prompt_hash == v2.prompt_hash


async def test_pydantic_rejects_out_of_range_score() -> None:
    llm = FakeLLMClient()
    llm.queue('{"score": 1.7, "rationale": "broken"}')
    judge = PairwisePreferenceJudge(llm)

    verdict = await judge.judge(_pair())
    assert verdict.error is not None


async def test_nan_score_becomes_error_not_silent_pass() -> None:
    # json.loads accepts the literal `NaN` token, and NaN slips past range
    # checks (every comparison is False). It must become a clean error
    # verdict, not a poisoned score that flows into aggregation.
    llm = FakeLLMClient()
    llm.queue('{"score": NaN, "confidence": 0.5, "rationale": "x"}')
    verdict = await PairwisePreferenceJudge(llm).judge(_pair())
    assert verdict.error is not None
    assert verdict.score.score == 0.0


async def test_infinity_score_becomes_error() -> None:
    llm = FakeLLMClient()
    llm.queue('{"score": Infinity, "rationale": "x"}')
    verdict = await PairwisePreferenceJudge(llm).judge(_pair())
    assert verdict.error is not None


async def test_nan_confidence_coerced_to_none() -> None:
    llm = FakeLLMClient()
    llm.queue('{"score": 0.6, "confidence": NaN, "rationale": "x"}')
    verdict = await PairwisePreferenceJudge(llm).judge(_pair())
    assert verdict.error is None
    assert verdict.score.score == 0.6
    assert verdict.score.confidence is None
