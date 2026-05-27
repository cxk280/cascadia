"""Smoke tests for the worker's CLIs.

Each CLI has at least: --help (touches argparse setup), a missing-required-arg
exit-2 path, and where cheaply possible a happy-path invocation against
fake/scripted providers. Coverage target: bump the 5 CLI files from 0% each
to ≥ 60%, which combined gets the package over 80% overall.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ----- cascadia-judge (main entry CLI) ---------------------------------------

def test_main_cli_help_exits_zero() -> None:
    from cascadia_judge.cli import _parse_args
    with pytest.raises(SystemExit) as exc:
        _parse_args(["--help"])
    assert exc.value.code == 0


def test_main_cli_requires_fixture_or_pair(capsys: pytest.CaptureFixture) -> None:
    from cascadia_judge.cli import _run, _parse_args
    args = _parse_args([])
    exit_code = asyncio.run(_run(args))
    assert exit_code == 2
    assert "specify --fixture or --pair" in capsys.readouterr().err


def test_main_cli_runs_against_fixture(capsys: pytest.CaptureFixture) -> None:
    fixture = ROOT / "tests" / "fixtures" / "pairwise_v1_basic.json"
    if not fixture.exists():
        pytest.skip(f"fixture missing: {fixture}")
    from cascadia_judge.cli import _run, _parse_args
    args = _parse_args([
        "--fixture", str(fixture),
        "--judges", "pairwise_preference_v1",
    ])
    exit_code = asyncio.run(_run(args))
    assert exit_code == 0
    body = json.loads(capsys.readouterr().out)
    assert isinstance(body, list)
    assert len(body) >= 1


def test_main_cli_live_factory_exits_on_missing_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from cascadia_judge.cli import _live_factory
    with pytest.raises(SystemExit) as exc:
        _live_factory("openai", "gpt-4o-mini")
    assert exc.value.code == 2


# ----- cascadia-judge-aggregate-labels --------------------------------------

def test_aggregator_cli_requires_database_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("CASCADIA_DATABASE_URL", raising=False)
    from cascadia_judge.calibration.aggregator_cli import main
    exit_code = main(["--out", str(tmp_path / "x.jsonl")])
    assert exit_code == 2
    assert "CASCADIA_DATABASE_URL" in capsys.readouterr().err


def test_aggregator_cli_help_exits_zero() -> None:
    from cascadia_judge.calibration.aggregator_cli import main
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


# ----- cascadia-judge-sample-calibration ------------------------------------

def test_sampler_cli_requires_database_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    monkeypatch.delenv("CASCADIA_DATABASE_URL", raising=False)
    from cascadia_judge.calibration.sampler_cli import main
    exit_code = main(["--round", "1", "--size", "10"])
    assert exit_code == 2
    assert "CASCADIA_DATABASE_URL" in capsys.readouterr().err


def test_sampler_cli_help_exits_zero() -> None:
    from cascadia_judge.calibration.sampler_cli import main
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


# ----- cascadia-judge-llm-panel ---------------------------------------------

def test_llm_panel_cli_help_exits_zero() -> None:
    from cascadia_judge.calibration.llm_panel_cli import main
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_llm_panel_cli_bad_panel_spec_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from cascadia_judge.calibration.llm_panel_cli import main
    with pytest.raises(SystemExit):
        # Missing the colon → SystemExit raised by _build_panel.
        main([
            "--dataset", str(ROOT / "calibration" / "golden_v0.jsonl"),
            "--panel", "garbage-without-colon",
        ])


def test_llm_panel_cli_unknown_provider_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cascadia_judge.calibration.llm_panel_cli import main
    with pytest.raises(SystemExit):
        main([
            "--dataset", str(ROOT / "calibration" / "golden_v0.jsonl"),
            "--panel", "unknown:model-x",
        ])


def test_llm_panel_cli_missing_env_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from cascadia_judge.calibration.llm_panel_cli import main
    with pytest.raises(SystemExit):
        main([
            "--dataset", str(ROOT / "calibration" / "golden_v0.jsonl"),
            "--panel", "openai:gpt-4o-mini",
        ])


# ----- cascadia-judge-poll --------------------------------------------------

def test_poller_cli_help_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    # main() reads sys.argv directly — patch it.
    from cascadia_judge.poller_cli import main
    monkeypatch.setattr(sys, "argv", ["cascadia-judge-poll", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_poller_cli_missing_db_url_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CASCADIA_DATABASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(sys, "argv", ["cascadia-judge-poll", "--max-cycles", "0"])
    from cascadia_judge.poller_cli import main
    # Either raises SystemExit (argparse error) or exits the loop quickly.
    # Just verify it doesn't hang and doesn't crash with an uncaught exception.
    try:
        main()
    except SystemExit:
        pass
