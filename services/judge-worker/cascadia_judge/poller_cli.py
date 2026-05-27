"""`cascadia-judge-poll` entry point — runs the long-running poller.

The existing `cascadia-judge` CLI is one-shot (fixture or single-pair). This
binary connects to Postgres, drains unjudged shadow_pairs forever, and writes
judge_scores. Stops cleanly on SIGINT / SIGTERM.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys

from cascadia_judge.executor import AsyncioJudgeExecutor
from cascadia_judge.judges import REGISTRY
from cascadia_judge.llm.anthropic import AnthropicClient
from cascadia_judge.llm.base import LLMClient
from cascadia_judge.llm.openai_compatible import GroqClient, OpenAIClient, XAIClient
from cascadia_judge.orchestrator import JudgeOrchestrator
from cascadia_judge.poller import Poller, PollerConfig

_PROVIDER_CLIENTS = {
    "openai": OpenAIClient,
    "groq": GroqClient,
    "xai": XAIClient,
    "anthropic": AnthropicClient,
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="cascadia-judge-poll")
    p.add_argument(
        "--database-url",
        default=os.environ.get("CASCADIA_DATABASE_URL"),
        help="postgres://… DSN. Defaults to $CASCADIA_DATABASE_URL.",
    )
    p.add_argument("--provider", default="openai", choices=sorted(_PROVIDER_CLIENTS))
    p.add_argument("--model", default="gpt-4o-mini")
    p.add_argument("--judges", nargs="*", help="Judge names to run. Default: all registered.")
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--idle-sleep-s", type=float, default=1.0)
    p.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Exit after N cycles. Default: forever.",
    )
    return p.parse_args(argv)


def _live_factory(provider: str, model: str):
    cls = _PROVIDER_CLIENTS[provider]
    if not os.environ.get(cls.API_KEY_ENV):
        print(f"missing {cls.API_KEY_ENV} env var", file=sys.stderr)
        sys.exit(2)

    def factory(_judge_name: str) -> LLMClient:
        return cls(model=model)

    return factory


async def _run(args: argparse.Namespace) -> int:
    if not args.database_url:
        print("--database-url or CASCADIA_DATABASE_URL is required", file=sys.stderr)
        return 2

    # Import here so the CLI imports work in environments without asyncpg.
    from cascadia_judge.storage.postgres import AsyncpgShadowPairStorage

    storage = await AsyncpgShadowPairStorage.connect(args.database_url)
    orchestrator = JudgeOrchestrator(
        registry=REGISTRY,
        executor=AsyncioJudgeExecutor(),
        llm_factory=_live_factory(args.provider, args.model),
    )
    poller = Poller(
        storage=storage,
        orchestrator=orchestrator,
        config=PollerConfig(
            batch_size=args.batch_size,
            idle_sleep_s=args.idle_sleep_s,
            judge_names=tuple(args.judges) if args.judges else None,
            max_cycles=args.max_cycles,
        ),
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, poller.stop)

    logging.info("cascadia-judge-poll starting")
    try:
        await poller.run_forever()
    finally:
        await storage.close()
    return 0


def main() -> None:
    logging.basicConfig(level=os.environ.get("CASCADIA_LOG_LEVEL", "INFO").upper())
    args = _parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
