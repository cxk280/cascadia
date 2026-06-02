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
from cascadia_judge.orchestrator import JudgeOrchestrator, PanelOrchestrator
from cascadia_judge.poller import Poller, PollerConfig

_PROVIDER_CLIENTS = {
    "openai": OpenAIClient,
    "groq": GroqClient,
    "xai": XAIClient,
    "anthropic": AnthropicClient,
}


def _build_client(provider: str, model: str, base_url: str | None = None) -> LLMClient:
    """Construct one judge client, failing fast with a friendly message if its
    API key isn't set. `base_url` overrides the provider's default endpoint —
    used to point the judge at a local mock/gateway (e.g. the keyless demo
    stack, where every client talks to cascadia-mock-upstream)."""
    cls = _PROVIDER_CLIENTS[provider]
    if not os.environ.get(cls.API_KEY_ENV):
        print(
            f"missing {cls.API_KEY_ENV} env var (needed for judge {provider}:{model})",
            file=sys.stderr,
        )
        sys.exit(2)
    return cls(model=model, base_url=base_url)


def _parse_panel(spec: str) -> list[tuple[str, str]]:
    """Parse `provider:model,provider:model,...` into [(provider, model), ...]."""
    members: list[tuple[str, str]] = []
    for raw in spec.split(","):
        part = raw.strip()
        if not part:
            continue
        if ":" not in part:
            print(
                f"--panel members must be provider:model, got {part!r}", file=sys.stderr
            )
            sys.exit(2)
        provider, model = part.split(":", 1)
        provider, model = provider.strip(), model.strip()
        if provider not in _PROVIDER_CLIENTS:
            print(
                f"unknown provider {provider!r} in --panel "
                f"(choose from {sorted(_PROVIDER_CLIENTS)})",
                file=sys.stderr,
            )
            sys.exit(2)
        if not model:
            print(f"--panel member {part!r} has an empty model", file=sys.stderr)
            sys.exit(2)
        members.append((provider, model))
    if not members:
        print("--panel was empty", file=sys.stderr)
        sys.exit(2)
    return members


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="cascadia-judge-poll")
    p.add_argument(
        "--database-url",
        default=os.environ.get("CASCADIA_DATABASE_URL"),
        help="postgres://… DSN. Defaults to $CASCADIA_DATABASE_URL.",
    )
    p.add_argument("--provider", default="openai", choices=sorted(_PROVIDER_CLIENTS))
    p.add_argument("--model", default="gpt-4o-mini")
    p.add_argument(
        "--base-url",
        default=os.environ.get("CASCADIA_JUDGE_BASE_URL"),
        help=(
            "Override the provider endpoint for every judge client (e.g. point "
            "at a local mock/gateway). Defaults to $CASCADIA_JUDGE_BASE_URL. "
            "The keyless demo sets this to the mock upstream so judging needs no keys."
        ),
    )
    p.add_argument(
        "--panel",
        default=os.environ.get("CASCADIA_JUDGE_PANEL"),
        help=(
            "Cross-provider judge panel as 'provider:model,provider:model,...' "
            "(e.g. 'openai:gpt-4o-mini,groq:llama-3.3-70b'). Each pair is scored "
            "by every registered judge against EVERY panel member; the aggregator "
            "folds the verdicts (anti-self-preference + position-fold). Overrides "
            "--provider/--model. Defaults to $CASCADIA_JUDGE_PANEL."
        ),
    )
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


def _live_factory(provider: str, model: str, base_url: str | None = None):
    cls = _PROVIDER_CLIENTS[provider]
    if not os.environ.get(cls.API_KEY_ENV):
        print(f"missing {cls.API_KEY_ENV} env var", file=sys.stderr)
        sys.exit(2)

    def factory(_judge_name: str) -> LLMClient:
        return cls(model=model, base_url=base_url)

    return factory


async def _run(args: argparse.Namespace) -> int:
    if not args.database_url:
        print("--database-url or CASCADIA_DATABASE_URL is required", file=sys.stderr)
        return 2

    # Import here so the CLI imports work in environments without asyncpg.
    from cascadia_judge.storage.postgres import AsyncpgShadowPairStorage

    storage = await AsyncpgShadowPairStorage.connect(args.database_url)
    executor = AsyncioJudgeExecutor()
    orchestrator: JudgeOrchestrator | PanelOrchestrator
    if args.panel:
        members = _parse_panel(args.panel)
        clients = [_build_client(provider, model, args.base_url) for provider, model in members]
        logging.info(
            "judge panel: %s%s",
            ", ".join(f"{p}:{m}" for p, m in members),
            f" (base_url={args.base_url})" if args.base_url else "",
        )
        orchestrator = PanelOrchestrator(
            registry=REGISTRY, executor=executor, clients=clients
        )
    else:
        orchestrator = JudgeOrchestrator(
            registry=REGISTRY,
            executor=executor,
            llm_factory=_live_factory(args.provider, args.model, args.base_url),
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
