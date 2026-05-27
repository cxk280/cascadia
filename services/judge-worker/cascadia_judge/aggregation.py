"""Combine N judge verdicts on a single pair into one ensemble score.

Three corrections applied, in order:

1.  **Anti-self-preference.** A judge whose model name appears in the
    candidate pair (cheap_model or expensive_model) is dropped — its score
    would be confounded by self-preference (Zheng et al. 2023). Implemented
    as a substring match so `gpt-4o-mini` is correctly dropped when judging
    a `gpt-4o-mini` response. We err on the side of dropping rather than
    keeping when in doubt; a judge that doesn't run is honest, a judge
    that runs biased is poison.

2.  **Position-bias correction.** If both `pairwise_preference_v1` and
    `pairwise_preference_v1_swapped` are present from the same judge model,
    we average them — the swap inverts the score, so the average is the
    bias-corrected pairwise probability. A by-product is the per-judge
    position-bias estimate (`|p + q - 1|`) which we expose for diagnostics.

3.  **Weighted aggregation.** Surviving verdicts are averaged. Weights are
    `confidence` if present, otherwise 1.0. Errors (score==0 with
    confidence==0) are excluded from the weight set so they don't drag the
    mean toward 0.

Returns a single `EnsembleScore` with provenance — n_verdicts going in,
n_dropped_self_pref, n_failed, position_bias_estimate, the model list that
produced the score.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from statistics import mean

from cascadia_judge.types import JudgeVerdict, ShadowPair

# Pair the swapped variant with its un-swapped sibling so we can detect them.
_SWAP_PAIRS = {
    "pairwise_preference_v1": "pairwise_preference_v1_swapped",
    "pairwise_preference_v1_swapped": "pairwise_preference_v1",
}


@dataclass(frozen=True)
class EnsembleScore:
    """Aggregate of N judge verdicts on a single pair."""

    pair_id: str
    score: float                       # in [0, 1] — p(cheap >= expensive)
    confidence: float                  # in [0, 1]
    n_verdicts_in: int                 # raw verdicts handed to aggregate()
    n_used: int                        # verdicts that contributed to the score
    n_dropped_self_pref: int
    n_failed: int
    position_bias_estimate: float | None  # |p + q - 1| averaged across judges
    contributing_models: list[str] = field(default_factory=list)
    # Phase 5.2 — concision adjustment, when `concision_weight > 0`.
    # `score_raw` is the un-adjusted weighted-mean score for audit;
    # `concision_adjustment` is the signed delta applied to it.
    score_raw: float | None = None
    concision_adjustment: float | None = None


def concision_adjustment(
    cheap_response: str,
    expensive_response: str,
    weight: float,
) -> float:
    """Length-normalized concision penalty applied to ensemble scores.

    Phase 5 calibration pilot found that LLM judges have a verbosity bias —
    they reward longer / more detailed responses on common Q&A in ways that
    don't track human preferences for brevity (Zheng et al. 2023; reproduced
    cleanly in the 3-judge panel run on 2026-05-19). This function returns a
    signed adjustment in [-weight, +weight]:

      adjustment = weight * (len(expensive) - len(cheap)) / (len(cheap) + len(expensive))

    The result is positive when cheap is shorter (push toward cheap-wins) and
    negative when cheap is longer. `weight=0` is a no-op; `weight=0.15` is the
    default we tune in `cascadia-judge-llm-panel --concision-sweep`.

    Callers add this adjustment to the base ensemble score and clamp the
    result to [0, 1].
    """

    if weight <= 0:
        return 0.0
    la = len(cheap_response)
    lb = len(expensive_response)
    denom = la + lb
    if denom == 0:
        return 0.0
    return weight * (lb - la) / denom


def aggregate(
    pair: ShadowPair,
    verdicts: Sequence[JudgeVerdict],
    *,
    pair_id: str | None = None,
    concision_weight: float = 0.0,
) -> EnsembleScore:
    """Reduce verdicts to a single ensemble score.

    `pair_id` defaults to `pair.request_id` for tying back to the proxy's
    event row; callers that have a real `shadow_pairs.pair_id` UUID should
    pass it explicitly.

    `concision_weight` (Phase 5.2) applies a length-normalized concision
    penalty to the post-aggregation score. Default 0.0 preserves prior
    behavior. See `concision_adjustment()` for the formula.
    """

    pid = pair_id or pair.request_id
    n_in = len(verdicts)

    # Step 1 — drop self-preferring judges.
    survivors: list[JudgeVerdict] = []
    n_self_pref = 0
    candidate_models = (pair.cheap_model.lower(), pair.expensive_model.lower())
    for v in verdicts:
        if _is_self_preferring(v.model.lower(), candidate_models):
            n_self_pref += 1
            continue
        survivors.append(v)

    # Step 2 — fold position-swapped pairs.
    folded, bias_estimates = _fold_swapped_pairs(survivors)

    # Step 3 — separate errors from real scores. An "error" is a verdict
    # whose `error` field is set or whose score==0.0 with confidence==0.0
    # (the BaseJudge error fallback).
    real, errored = _partition_errors(folded)

    if not real:
        return EnsembleScore(
            pair_id=pid,
            score=0.5,
            confidence=0.0,
            n_verdicts_in=n_in,
            n_used=0,
            n_dropped_self_pref=n_self_pref,
            n_failed=len(errored),
            position_bias_estimate=mean(bias_estimates) if bias_estimates else None,
            contributing_models=[],
            score_raw=0.5,
            concision_adjustment=0.0,
        )

    # Weighted mean. Weight = confidence if reported, else 1.0.
    total_weight = 0.0
    weighted_sum = 0.0
    for v in real:
        w = v.score.confidence if v.score.confidence is not None else 1.0
        if w <= 0:
            w = 0.001
        total_weight += w
        weighted_sum += w * v.score.score

    score_raw = weighted_sum / total_weight
    score_raw = max(0.0, min(1.0, score_raw))
    adjustment = concision_adjustment(
        pair.cheap_response, pair.expensive_response, concision_weight,
    )
    score = max(0.0, min(1.0, score_raw + adjustment))

    # Confidence: average individual confidences if reported, else use the
    # inverse of the dispersion. A tight ensemble (all judges agree) is more
    # trustworthy than one spread across the unit interval.
    explicit_confidences = [
        v.score.confidence for v in real if v.score.confidence is not None
    ]
    if explicit_confidences:
        conf = sum(explicit_confidences) / len(explicit_confidences)
    else:
        # 1 - sample standard deviation, clamped to [0, 1].
        if len(real) == 1:
            conf = 0.5
        else:
            mu = score
            var = sum((v.score.score - mu) ** 2 for v in real) / (len(real) - 1)
            conf = max(0.0, min(1.0, 1.0 - var ** 0.5))

    return EnsembleScore(
        pair_id=pid,
        score=score,
        confidence=conf,
        n_verdicts_in=n_in,
        n_used=len(real),
        n_dropped_self_pref=n_self_pref,
        n_failed=len(errored),
        position_bias_estimate=mean(bias_estimates) if bias_estimates else None,
        contributing_models=sorted({v.model for v in real}),
        score_raw=score_raw,
        concision_adjustment=adjustment,
    )


def _is_self_preferring(judge_model: str, candidate_models: Iterable[str]) -> bool:
    for cm in candidate_models:
        if not cm:
            continue
        # Substring both ways so `gpt-4o-mini` matches `openai/gpt-4o-mini`
        # and a candidate `gpt-4o-mini-2026-05` matches judge `gpt-4o-mini`.
        if cm in judge_model or judge_model in cm:
            return True
    return False


def _fold_swapped_pairs(
    verdicts: Sequence[JudgeVerdict],
) -> tuple[list[JudgeVerdict], list[float]]:
    """Average pairwise + pairwise_swapped from the same model into one verdict.

    Position bias estimates are returned separately so callers can surface
    them as diagnostics without affecting the score.
    """

    by_model: dict[tuple[str, str], dict[str, JudgeVerdict]] = {}
    for v in verdicts:
        sibling = _SWAP_PAIRS.get(v.judge_name)
        if sibling is None:
            continue
        key = (v.model, v.provider)
        by_model.setdefault(key, {})[v.judge_name] = v

    folded: list[JudgeVerdict] = []
    bias_estimates: list[float] = []
    consumed_ids: set[tuple[str, str, str]] = set()

    for (model, provider), pair_map in by_model.items():
        unswapped = pair_map.get("pairwise_preference_v1")
        swapped = pair_map.get("pairwise_preference_v1_swapped")
        if unswapped is None or swapped is None:
            continue
        # Both verdicts report p(cheap >= expensive) — the swapped judge
        # already inverts its raw output before returning. Disagreement is
        # the per-judge position-bias signature.
        p = unswapped.score.score
        bias = abs(p - swapped.score.score)
        bias_estimates.append(bias)

        combined_score = (p + swapped.score.score) / 2.0
        avg_conf_values = [
            x for x in (unswapped.score.confidence, swapped.score.confidence) if x is not None
        ]
        combined_conf = sum(avg_conf_values) / len(avg_conf_values) if avg_conf_values else None

        # Build a synthetic verdict carrying the corrected score. We reuse
        # the unswapped verdict's metadata but mark the variant as the fold.
        folded.append(
            JudgeVerdict(
                request_id=unswapped.request_id,
                judge_name=unswapped.judge_name + "+folded",
                prompt_variant="pairwise/v1#bias_corrected",
                model=model,
                provider=provider,
                score=type(unswapped.score)(
                    score=combined_score,
                    confidence=combined_conf,
                    rationale=(
                        f"bias-corrected (raw={p:.2f}, swapped={swapped.score.score:.2f}, "
                        f"|gap|={bias:.2f})"
                    )[:512],
                ),
                prompt_hash=unswapped.prompt_hash,
                elapsed_ms=unswapped.elapsed_ms + swapped.elapsed_ms,
                error=None,
            )
        )
        consumed_ids.add((unswapped.judge_name, model, provider))
        consumed_ids.add((swapped.judge_name, model, provider))

    # Pass through anything that wasn't part of a pair.
    for v in verdicts:
        if (v.judge_name, v.model, v.provider) in consumed_ids:
            continue
        folded.append(v)

    return folded, bias_estimates


def _partition_errors(
    verdicts: Sequence[JudgeVerdict],
) -> tuple[list[JudgeVerdict], list[JudgeVerdict]]:
    real: list[JudgeVerdict] = []
    errored: list[JudgeVerdict] = []
    for v in verdicts:
        if v.error:
            errored.append(v)
            continue
        if v.score.score == 0.0 and v.score.confidence == 0.0 and "error" in (v.score.rationale or "").lower():
            errored.append(v)
            continue
        real.append(v)
    return real, errored
