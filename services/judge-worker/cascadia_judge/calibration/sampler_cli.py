"""`cascadia-judge-sample-calibration` — pull a labeling batch.

Active-learning runs as a series of rounds. Each round pulls the next N
pairs from `shadow_pairs`, optionally augmented with ensemble scores, and
inserts them into `calibration_pairs`. Reviewers then label via the
Next.js app.

  $ cascadia-judge-sample-calibration --round 1 --size 20  # seed
  $ cascadia-judge-sample-calibration --round 2 --size 20 --score-with-ensemble
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

import asyncpg

from cascadia_judge.aggregation import aggregate
from cascadia_judge.calibration.sampler import (
    CandidatePair,
    SamplerConfig,
    fetch_candidates_from_db,
    materialize_attention_checks,
    persist_batch,
    select_batch,
)
from cascadia_judge.executor import AsyncioJudgeExecutor
from cascadia_judge.judges import REGISTRY
from cascadia_judge.llm.fake import FakeLLMClient
from cascadia_judge.llm.openai_compatible import GroqClient, OpenAIClient, XAIClient
from cascadia_judge.llm.scripted import ScriptedLLMClient
from cascadia_judge.orchestrator import JudgeOrchestrator
from cascadia_judge.types import ShadowPair

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cascadia-judge-sample-calibration")
    parser.add_argument("--database-url", default=os.environ.get("CASCADIA_DATABASE_URL"))
    parser.add_argument("--round", type=int, required=True,
                        help="1 = seed (stratified random); 2+ = uncertainty-weighted")
    parser.add_argument("--size", type=int, default=30,
                        help="Target batch size (per-cluster stratification splits evenly)")
    parser.add_argument("--attention-check-rate", type=float, default=0.05,
                        help="Fraction of pairs to insert as attention checks")
    parser.add_argument("--candidate-pool", type=int, default=1000,
                        help="Pull this many candidates from shadow_pairs before sampling")
    parser.add_argument("--score-with-ensemble", action="store_true",
                        help="Run the judge ensemble over the candidate pool first "
                             "(only meaningful for round ≥ 2)")
    parser.add_argument("--ensemble-provider", default="fake",
                        choices=["fake", "scripted", "openai", "groq", "xai"])
    parser.add_argument("--ensemble-model", default="fake-judge")
    parser.add_argument("--scripted-fixture", default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level)
    if not args.database_url:
        print("--database-url or CASCADIA_DATABASE_URL must be set", file=sys.stderr)
        return 2

    return asyncio.run(_main(args))


async def _main(args: argparse.Namespace) -> int:
    pool = await asyncpg.create_pool(dsn=args.database_url, min_size=1, max_size=4)
    try:
        candidates = await fetch_candidates_from_db(pool, limit=args.candidate_pool)
        log.info("fetched %d candidate pairs from shadow_pairs", len(candidates))
        if not candidates:
            print("no unlabeled shadow_pairs available — drive some traffic first", file=sys.stderr)
            return 3

        if args.round >= 2 and args.score_with_ensemble:
            log.info("scoring %d candidates with the ensemble", len(candidates))
            orchestrator = _build_orchestrator(args)
            candidates = await _score_candidates(candidates, orchestrator)

        cfg = SamplerConfig(
            target_batch_size=args.size,
            attention_check_rate=args.attention_check_rate,
            rng_seed=args.seed,
        )
        batch = select_batch(candidates, config=cfg, round_number=args.round)
        log.info("selected %d pairs", len(batch))

        attention_count = max(0, int(round(args.size * cfg.attention_check_rate)))
        attention = materialize_attention_checks(attention_count)

        reason = "seed_stratified" if args.round == 1 else "uncertainty_weighted"
        inserted = await persist_batch(
            pool,
            batch=batch,
            attention_checks=attention,
            round_number=args.round,
            selection_reason=reason,
        )
        print(
            f"inserted {inserted} pairs (round={args.round}, "
            f"{len(batch)} sampled + {len(attention)} attention checks)"
        )
        return 0
    finally:
        await pool.close()


def _build_orchestrator(args: argparse.Namespace) -> JudgeOrchestrator:
    if args.ensemble_provider == "fake":
        fake = FakeLLMClient(model=args.ensemble_model)
        factory = lambda _j: fake  # noqa: E731
    elif args.ensemble_provider == "scripted":
        if not args.scripted_fixture:
            raise SystemExit("--scripted-fixture required for --ensemble-provider scripted")
        client = ScriptedLLMClient(args.scripted_fixture)
        factory = lambda _j: client  # noqa: E731
    elif args.ensemble_provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise SystemExit("OPENAI_API_KEY required for --ensemble-provider openai")
        client = OpenAIClient(model=args.ensemble_model, api_key=api_key)
        factory = lambda _j: client  # noqa: E731
    elif args.ensemble_provider == "groq":
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise SystemExit("GROQ_API_KEY required for --ensemble-provider groq")
        client = GroqClient(model=args.ensemble_model, api_key=api_key)
        factory = lambda _j: client  # noqa: E731
    elif args.ensemble_provider == "xai":
        api_key = os.environ.get("XAI_API_KEY")
        if not api_key:
            raise SystemExit("XAI_API_KEY required for --ensemble-provider xai")
        client = XAIClient(model=args.ensemble_model, api_key=api_key)
        factory = lambda _j: client  # noqa: E731
    else:
        raise SystemExit(f"unknown provider {args.ensemble_provider}")
    return JudgeOrchestrator(
        registry=REGISTRY,
        executor=AsyncioJudgeExecutor(),
        llm_factory=factory,
    )


async def _score_candidates(
    candidates: list[CandidatePair],
    orchestrator: JudgeOrchestrator,
) -> list[CandidatePair]:
    scored: list[CandidatePair] = []
    for c in candidates:
        shadow = ShadowPair(
            request_id=c.request_id,
            prompt=c.prompt,
            cheap_model=c.cheap_model,
            cheap_response=c.cheap_response,
            expensive_model=c.expensive_model,
            expensive_response=c.expensive_response,
            cluster_id=c.cluster_id,
        )
        verdicts = await orchestrator.evaluate(shadow)
        ensemble = aggregate(shadow, verdicts, pair_id=c.request_id)
        scored.append(
            CandidatePair(
                request_id=c.request_id,
                prompt=c.prompt,
                cheap_model=c.cheap_model,
                cheap_response=c.cheap_response,
                expensive_model=c.expensive_model,
                expensive_response=c.expensive_response,
                cluster_id=c.cluster_id,
                ensemble_score=ensemble.score,
                ensemble_confidence=ensemble.confidence,
                ensemble_position_bias=ensemble.position_bias_estimate,
            )
        )
    return scored


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
