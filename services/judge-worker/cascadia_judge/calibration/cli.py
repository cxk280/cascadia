"""`cascadia-judge-calibrate` — run the ensemble on a JSONL calibration set
and print/persist agreement metrics.

Defaults to live OpenAI judges. `--provider fake --fake-script PATH` runs
against a scripted FakeLLMClient for offline reproducibility (used by tests
and by the in-repo synthetic golden set).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import asdict
from pathlib import Path

from cascadia_judge.calibration.dataset import load_dataset
from cascadia_judge.calibration.runner import (
    CalibrationResult,
    MultiAxisResult,
    run_calibration,
    run_multi_axis_calibration,
)
from cascadia_judge.executor import AsyncioJudgeExecutor
from cascadia_judge.judges import REGISTRY
from cascadia_judge.llm.base import LLMClient
from cascadia_judge.llm.fake import FakeLLMClient
from cascadia_judge.llm.openai_compatible import GroqClient, OpenAIClient, XAIClient
from cascadia_judge.llm.scripted import ScriptedLLMClient
from cascadia_judge.orchestrator import JudgeOrchestrator


def _build_llm_factory(
    provider: str,
    model: str,
    fake_script: Path | None,
    scripted_fixture: Path | None,
):
    if provider == "fake":
        responses: list[str] = []
        if fake_script is not None:
            responses = [
                ln.strip()
                for ln in fake_script.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.lstrip().startswith("#")
            ]
        fake = FakeLLMClient(model=model, responses=responses)
        return lambda _judge: fake

    if provider == "scripted":
        if scripted_fixture is None:
            raise SystemExit("--scripted-fixture is required for --provider scripted")
        client: LLMClient = ScriptedLLMClient(scripted_fixture)
        return lambda _judge: client

    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise SystemExit("OPENAI_API_KEY must be set for --provider openai")
        client: LLMClient = OpenAIClient(model=model, api_key=api_key)
    elif provider == "groq":
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise SystemExit("GROQ_API_KEY must be set for --provider groq")
        client = GroqClient(model=model, api_key=api_key)
    elif provider == "xai":
        api_key = os.environ.get("XAI_API_KEY")
        if not api_key:
            raise SystemExit("XAI_API_KEY must be set for --provider xai")
        client = XAIClient(model=model, api_key=api_key)
    else:
        raise SystemExit(f"unknown provider: {provider}")
    return lambda _judge: client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cascadia-judge-calibrate")
    parser.add_argument("--dataset", required=True, type=Path,
                        help="JSONL calibration set (one CalibrationPair per line)")
    parser.add_argument("--provider", default="fake",
                        choices=["fake", "scripted", "openai", "groq", "xai"])
    parser.add_argument("--model", default="fake-judge",
                        help="Model id passed to the LLM client (e.g. gpt-4o-mini)")
    parser.add_argument("--fake-script", type=Path, default=None,
                        help="When --provider=fake, read pre-canned JSON responses from this file")
    parser.add_argument("--scripted-fixture", type=Path, default=None,
                        help="When --provider=scripted, fixture JSON mapping (judge::request_id) → response")
    parser.add_argument("--judges", nargs="*", default=None,
                        help="Restrict to these judge names. Defaults to the full registry.")
    parser.add_argument("--out", type=Path, default=None,
                        help="Write the full JSON report to this path. Stdout is metrics-only.")
    parser.add_argument("--tau-min", type=float, default=None,
                        help="If set, exit non-zero when Kendall's τ-b falls below this threshold.")
    parser.add_argument("--concision-weight", type=float, default=0.0,
                        help="Phase 5.2 concision penalty applied to each ensemble score "
                             "(default 0.0 = disabled).")
    parser.add_argument("--multi-axis", action="store_true",
                        help="Report a τ-b *vector* (neutral / concision-weighted / "
                             "completeness-weighted) plus panel-internal κ, instead of a "
                             "single τ-b. The concision magnitude is --concision-weight "
                             "(defaults to 0.30, the characterized pilot correction, when "
                             "left at 0).")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level)

    dataset = load_dataset(args.dataset)
    factory = _build_llm_factory(args.provider, args.model, args.fake_script, args.scripted_fixture)
    orchestrator = JudgeOrchestrator(
        registry=REGISTRY,
        executor=AsyncioJudgeExecutor(),
        llm_factory=factory,
    )

    if args.multi_axis:
        # The completeness axis needs a non-zero magnitude to differ from the
        # neutral axis; fall back to the characterized 0.30 when unset.
        axis_weight = args.concision_weight if args.concision_weight > 0 else 0.30
        multi: MultiAxisResult = asyncio.run(
            run_multi_axis_calibration(
                dataset, orchestrator,
                judge_names=args.judges,
                concision_weight=axis_weight,
            ),
        )
        result: CalibrationResult = CalibrationResult(rows=multi.rows, metrics=multi.metrics)
        report_dict: dict[str, object] = {
            "metrics": asdict(multi.metrics),
            "multi_axis": multi.multi_axis.as_dict(),
        }
        json.dump(report_dict, sys.stdout, indent=2, default=_json_default)
        sys.stdout.write("\n")
        if args.out is not None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(multi.to_dict(), indent=2, default=_json_default))
        return _tau_gate(result, args.tau_min)

    result = asyncio.run(
        run_calibration(
            dataset, orchestrator,
            judge_names=args.judges,
            concision_weight=args.concision_weight,
        ),
    )

    metrics_dict = asdict(result.metrics)
    json.dump(metrics_dict, sys.stdout, indent=2, default=_json_default)
    sys.stdout.write("\n")

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result.to_dict(), indent=2, default=_json_default))

    return _tau_gate(result, args.tau_min)


def _tau_gate(result: CalibrationResult, tau_min: float | None) -> int:
    if tau_min is not None:
        tau = result.metrics.kendall_tau_b
        if tau is None or tau < tau_min:
            print(
                f"calibration FAILED: Kendall's τ-b = {tau!r} < {tau_min}",
                file=sys.stderr,
            )
            return 2
    return 0


def _json_default(o: object) -> object:
    if hasattr(o, "isoformat"):
        return o.isoformat()  # type: ignore[no-any-return]
    raise TypeError(f"unserializable: {type(o)!r}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
