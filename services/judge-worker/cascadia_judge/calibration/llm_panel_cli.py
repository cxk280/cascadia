"""`cascadia-judge-llm-panel` — run a 3-model panel against a labeled set.

Loads the human-rated JSONL, runs each panel model over each pair via the
pairwise judge (with position-swap correction), and reports panel-vs-human
+ per-model-vs-human Kendall's τ.

Cost: ~$5 for 200 pairs × 3 models × position-swap. API keys for each
panel provider must be set in the environment.

Example:
    $ OPENAI_API_KEY=… ANTHROPIC_API_KEY=… GROQ_API_KEY=… \\
      cascadia-judge-llm-panel \\
          --dataset calibration/human_rated_v1.jsonl \\
          --panel anthropic:claude-opus-4-7,openai:gpt-4o,groq:llama-3.3-70b
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from cascadia_judge.calibration.dataset import load_dataset
from cascadia_judge.calibration.llm_panel import (
    concision_sweep,
    panel_vs_panel_agreement,
    run_panel,
)
from cascadia_judge.llm.anthropic import AnthropicClient
from cascadia_judge.llm.base import LLMClient
from cascadia_judge.llm.openai_compatible import GroqClient, OpenAIClient, XAIClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cascadia-judge-llm-panel")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument(
        "--panel", required=True,
        help=(
            "Comma-separated provider:model pairs. Supported providers: "
            "openai, anthropic, groq, xai. Example: "
            "anthropic:claude-opus-4-7,openai:gpt-4o,groq:llama-3.3-70b"
        ),
    )
    parser.add_argument("--no-position-swap", action="store_true",
                        help="Skip the per-model position-swap correction (halves cost, loses signal)")
    parser.add_argument("--concision-weight", type=float, default=0.0,
                        help="Length-normalized concision penalty (Phase 5.2). 0.0 disables. "
                             "0.15 is the default we tune in --concision-sweep.")
    parser.add_argument("--concision-sweep", default=None,
                        help="Comma-separated list of concision weights to sweep post-hoc "
                             "(e.g. '0.0,0.05,0.1,0.15,0.2,0.25,0.3'). Reports τ-b per weight "
                             "without re-calling any LLM.")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--tau-min", type=float, default=None,
                        help="If set, exit non-zero when panel-vs-human Kendall's τ falls below this")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level)

    dataset = load_dataset(args.dataset)
    panel = _build_panel(args.panel)

    report = asyncio.run(
        run_panel(
            dataset, panel=panel,
            include_position_swap=not args.no_position_swap,
            concision_weight=args.concision_weight,
        )
    )

    summary: dict[str, object] = {
        "panel_vs_human": _slim_metrics(report.panel_vs_human),
        "per_model_vs_human": {
            name: _slim_metrics(m) for name, m in report.per_model_vs_human.items()
        },
        "panel_internal_kendall_tau_mean": panel_vs_panel_agreement(report),
        "n_unanimous": sum(1 for r in report.rows if r.unanimous),
        "n_total": len(report.rows),
        "concision_weight": args.concision_weight,
    }

    if args.concision_sweep:
        try:
            weights = [float(w.strip()) for w in args.concision_sweep.split(",") if w.strip()]
        except ValueError as exc:
            raise SystemExit(f"--concision-sweep parse error: {exc}")
        sweep = concision_sweep(report, dataset, weights)
        summary["concision_sweep"] = [
            {
                "weight": w,
                "kendall_tau_b": m.kendall_tau_b,
                "agreement_rate": m.agreement_rate,
                "judge_a_rate": m.judge_a_rate,
                "judge_b_rate": m.judge_b_rate,
                "judge_tie_rate": m.judge_tie_rate,
            }
            for w, m in sweep
        ]
        if sweep:
            best = max(
                sweep,
                key=lambda wm: (wm[1].kendall_tau_b if wm[1].kendall_tau_b is not None else -2.0),
            )
            summary["concision_sweep_best"] = {
                "weight": best[0],
                "kendall_tau_b": best[1].kendall_tau_b,
                "agreement_rate": best[1].agreement_rate,
            }
        else:
            # Empty sweep (no weights, or every report row's pair_id is absent
            # from the dataset) → max() would raise. Surface it instead of
            # crashing the CLI with an opaque ValueError.
            summary["concision_sweep_best"] = None
    json.dump(summary, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report.as_dict(), indent=2, default=str))

    if args.tau_min is not None:
        tau = report.panel_vs_human.kendall_tau_b
        if tau is None or tau < args.tau_min:
            print(
                f"panel calibration FAILED: panel-vs-human τ-b = {tau!r} < {args.tau_min}",
                file=sys.stderr,
            )
            return 2
    return 0


def _build_panel(spec: str) -> dict[str, LLMClient]:
    panel: dict[str, LLMClient] = {}
    for entry in spec.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise SystemExit(f"panel entry {entry!r} must be provider:model")
        provider, model = entry.split(":", 1)
        client: LLMClient
        if provider == "openai":
            key = _require_env("OPENAI_API_KEY", provider)
            client = OpenAIClient(model=model, api_key=key)
        elif provider == "groq":
            key = _require_env("GROQ_API_KEY", provider)
            client = GroqClient(model=model, api_key=key)
        elif provider == "xai":
            key = _require_env("XAI_API_KEY", provider)
            client = XAIClient(model=model, api_key=key)
        elif provider == "anthropic":
            key = _require_env("ANTHROPIC_API_KEY", provider)
            client = AnthropicClient(model=model, api_key=key)
        else:
            raise SystemExit(f"unknown provider {provider!r} in panel spec")
        panel[entry] = client
    if not panel:
        raise SystemExit("panel is empty")
    return panel


def _require_env(name: str, provider: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"{name} must be set for panel provider {provider!r}")
    return val


def _slim_metrics(m) -> dict[str, object]:
    return {
        "n": m.n,
        "kendall_tau_b": m.kendall_tau_b,
        "agreement_rate": m.agreement_rate,
        "position_bias_mean": m.position_bias_mean,
    }


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
