"""`cascadia-policy-controller` entry point.

Reads the current policy file, fetches cluster stats from Postgres, refits
thresholds, writes the new policy. `--once` runs a single refit and exits;
without it, runs forever on a configurable interval.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from datetime import timedelta
from pathlib import Path

from pydantic import ValidationError

from cascadia_policy.controller import PolicyController, UpdateRule
from cascadia_policy.storage import AsyncpgStatsReader
from cascadia_policy.types import PolicyTable
from cascadia_policy.writer import JsonFileWriter


class PolicyFileError(Exception):
    """The on-disk policy file exists but can't be parsed into a PolicyTable.

    Distinct from a transient (DB) error: re-reading a corrupt file won't fix
    it, so the controller logs it as an actionable error and skips the cycle
    rather than crashing (--once) or spamming stack traces forever (loop).
    """


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="cascadia-policy-controller")
    p.add_argument("--database-url", default=os.environ.get("CASCADIA_DATABASE_URL"))
    p.add_argument(
        "--policy-file",
        default=os.environ.get("CASCADIA_POLICY_FILE", "/tmp/cascadia-policy.json"),
        help="Path to the policy JSON that the proxy watches.",
    )
    p.add_argument(
        "--lookback-minutes",
        type=int,
        default=int(os.environ.get("CASCADIA_LOOKBACK_MINUTES", "60")),
    )
    p.add_argument(
        "--interval-seconds",
        type=int,
        default=int(os.environ.get("CASCADIA_REFIT_INTERVAL_SEC", "300")),
        help="Sleep this long between refits. Ignored with --once.",
    )
    p.add_argument("--once", action="store_true", help="Run one refit and exit.")
    p.add_argument("--target", type=float, default=0.5)
    p.add_argument("--margin", type=float, default=0.05)
    p.add_argument("--step", type=float, default=0.03)
    p.add_argument("--min-sample-size", type=int, default=20)
    return p.parse_args(argv)


def _load_current_policy(path: Path) -> PolicyTable:
    text = path.read_text()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PolicyFileError(
            f"policy file {path} is not valid JSON ({exc}); refusing to refit "
            "against a corrupt policy — fix or remove the file"
        ) from exc
    try:
        return PolicyTable.model_validate(data)
    except ValidationError as exc:
        raise PolicyFileError(
            f"policy file {path} is not a valid policy table ({exc}); refusing to refit"
        ) from exc


async def _refit_once(
    controller: PolicyController,
    reader: AsyncpgStatsReader,
    writer: JsonFileWriter,
    policy_path: Path,
    lookback: timedelta,
) -> None:
    if not policy_path.exists():
        logging.warning("policy file %s missing — controller has nothing to refit yet", policy_path)
        return
    try:
        current = _load_current_policy(policy_path)
    except PolicyFileError as exc:
        # Re-reading won't self-heal a corrupt file: log an actionable error
        # and skip this cycle instead of crashing or spinning on tracebacks.
        logging.error("%s", exc)
        return
    stats = await reader.cluster_stats(lookback)
    new_table = controller.refit(current, stats)
    await writer.write(new_table)
    logging.info(
        "refit complete: version=%s clusters=%d sample_sizes=%s",
        new_table.version,
        len(new_table.clusters),
        {cid: s.sample_size for cid, s in stats.items()},
    )


async def _run(args: argparse.Namespace) -> int:
    if not args.database_url:
        print("--database-url or CASCADIA_DATABASE_URL required", file=sys.stderr)
        return 2

    reader = await AsyncpgStatsReader.connect(args.database_url)
    writer = JsonFileWriter(args.policy_file)
    controller = PolicyController(
        UpdateRule(
            target=args.target,
            margin=args.margin,
            step=args.step,
            min_sample_size=args.min_sample_size,
        )
    )
    lookback = timedelta(minutes=args.lookback_minutes)
    policy_path = Path(args.policy_file)

    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopping.set)

    try:
        if args.once:
            await _refit_once(controller, reader, writer, policy_path, lookback)
            return 0
        while not stopping.is_set():
            try:
                await _refit_once(controller, reader, writer, policy_path, lookback)
            except Exception:  # noqa: BLE001 — keep running after transient errors
                logging.exception("refit cycle failed; will retry")
            try:
                await asyncio.wait_for(stopping.wait(), timeout=args.interval_seconds)
            except asyncio.TimeoutError:
                continue
    finally:
        await reader.close()
    return 0


def main() -> None:
    logging.basicConfig(level=os.environ.get("CASCADIA_LOG_LEVEL", "INFO").upper())
    sys.exit(asyncio.run(_run(_parse_args())))


if __name__ == "__main__":
    main()
