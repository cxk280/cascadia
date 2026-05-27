"""`cascadia-judge-aggregate-labels` — turn raw DB labels into canonical JSONL.

Usage:
    $ cascadia-judge-aggregate-labels --out calibration/human_rated_v1.jsonl

Prints a quality report to stdout (reviewer stats, Cohen's κ, consensus
counts) and writes the canonical JSONL that `cascadia-judge-calibrate`
can immediately consume.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import asyncpg

from cascadia_judge.calibration.aggregator import (
    aggregate_labels,
    fetch_pairs_with_labels,
    write_canonical_jsonl,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cascadia-judge-aggregate-labels")
    parser.add_argument("--database-url", default=os.environ.get("CASCADIA_DATABASE_URL"))
    parser.add_argument("--out", type=Path, required=True,
                        help="Path to write the canonical JSONL")
    parser.add_argument("--attention-failure-max", type=int, default=1,
                        help="Max attention-check misses per reviewer before drop (default 1)")
    parser.add_argument("--min-reviewers", type=int, default=1,
                        help="Minimum reviewers per pair to include it in canonical output")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level)
    if not args.database_url:
        print("--database-url or CASCADIA_DATABASE_URL must be set", file=sys.stderr)
        return 2
    return asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> int:
    pool = await asyncpg.create_pool(dsn=args.database_url, min_size=1, max_size=4)
    try:
        pairs = await fetch_pairs_with_labels(pool)
        report, rows = aggregate_labels(
            pairs,
            attention_failure_max=args.attention_failure_max,
            min_reviewers_for_consensus=args.min_reviewers,
        )
        write_canonical_jsonl(rows, args.out)
        json.dump(report.as_dict(), sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        print(f"wrote {len(rows)} canonical rows to {args.out}", file=sys.stderr)
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
