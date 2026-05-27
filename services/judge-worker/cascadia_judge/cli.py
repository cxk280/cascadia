from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from cascadia_judge.executor import AsyncioJudgeExecutor
from cascadia_judge.judges import REGISTRY
from cascadia_judge.llm.base import LLMClient
from cascadia_judge.llm.openai_compatible import GroqClient, OpenAIClient, XAIClient
from cascadia_judge.llm.scripted import ScriptedLLMClient
from cascadia_judge.orchestrator import JudgeOrchestrator
from cascadia_judge.types import ShadowPair

_PROVIDER_CLIENTS = {
    "openai": OpenAIClient,
    "groq": GroqClient,
    "xai": XAIClient,
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="cascadia-judge")
    p.add_argument(
        "--fixture",
        type=Path,
        help="JSON fixture with .shadow_pair + .scripted (offline; no API keys).",
    )
    p.add_argument("--pair", type=Path, help="JSON file with a single ShadowPair (live mode).")
    p.add_argument("--provider", default="openai", choices=sorted(_PROVIDER_CLIENTS))
    p.add_argument("--model", default="gpt-4o-mini")
    p.add_argument("--judges", nargs="*", help="Judge names to run. Default: all registered.")
    return p.parse_args(argv)


def _load_fixture(path: Path) -> tuple[ShadowPair, ScriptedLLMClient]:
    data: dict[str, Any] = json.loads(path.read_text())
    pair = ShadowPair.model_validate(data["shadow_pair"])
    scripted = ScriptedLLMClient(data["scripted"])
    return pair, scripted


def _live_factory(provider: str, model: str) -> "callable":
    cls = _PROVIDER_CLIENTS[provider]
    if not os.environ.get(cls.API_KEY_ENV):
        print(f"missing {cls.API_KEY_ENV} env var", file=sys.stderr)
        sys.exit(2)

    def factory(_judge_name: str) -> LLMClient:
        return cls(model=model)

    return factory


async def _run(args: argparse.Namespace) -> int:
    if args.fixture is not None:
        pair, scripted = _load_fixture(args.fixture)
        llm_factory = lambda _judge_name: scripted  # noqa: E731
    elif args.pair is not None:
        pair = ShadowPair.model_validate(json.loads(args.pair.read_text()))
        llm_factory = _live_factory(args.provider, args.model)
    else:
        print("specify --fixture or --pair", file=sys.stderr)
        return 2

    orchestrator = JudgeOrchestrator(
        registry=REGISTRY,
        executor=AsyncioJudgeExecutor(),
        llm_factory=llm_factory,
    )
    verdicts = await orchestrator.evaluate(pair, judge_names=args.judges)
    print(json.dumps([v.model_dump() for v in verdicts], indent=2))
    return 0


def main() -> None:
    args = _parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
