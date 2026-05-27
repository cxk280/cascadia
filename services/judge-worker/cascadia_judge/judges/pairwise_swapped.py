"""Position-swapped sibling of `PairwisePreferenceJudge`.

Same prompt template, same parser — but A/B are swapped before sending and
the score is inverted before returning. Run alongside the un-swapped judge
to measure (and average out) position bias.

If `p` is the un-swapped score (probability cheap ≥ expensive) and `q` is
the swapped score (probability expensive ≥ cheap), then with a perfectly
unbiased judge `p + q == 1`. Deviation from 1 is the per-pair bias estimate
and is logged by the aggregation step.
"""

from __future__ import annotations

from cascadia_judge.judges.base import BaseJudge, register_judge
from cascadia_judge.judges.pairwise_preference import (
    _SYSTEM,
    _USER_TEMPLATE,
    _parse,
)
from cascadia_judge.types import JudgeScore, JudgeVerdict, ShadowPair


@register_judge
class PairwisePreferenceSwappedJudge(BaseJudge):
    name = "pairwise_preference_v1_swapped"
    description = (
        "Position-swapped pairwise judge. Renders cheap as B and expensive as A, "
        "then inverts the parsed score so the returned value remains "
        "p(cheap >= expensive)."
    )
    prompt_variant = "pairwise/v1#swapped"

    async def judge(self, pair: ShadowPair) -> JudgeVerdict:
        # Swap the order in the user prompt.
        user = _USER_TEMPLATE.format(
            prompt=pair.prompt,
            cheap_model=pair.expensive_model,
            cheap_response=pair.expensive_response,
            expensive_model=pair.cheap_model,
            expensive_response=pair.cheap_response,
        )
        return await self._score_with_llm(
            pair,
            system=_SYSTEM,
            user=user,
            parse=_invert(_parse),
        )


def _invert(parse):
    def parser(text: str) -> JudgeScore:
        s = parse(text)
        return JudgeScore(
            score=1.0 - s.score,
            confidence=s.confidence,
            rationale=f"[swapped] {s.rationale}",
        )

    return parser
