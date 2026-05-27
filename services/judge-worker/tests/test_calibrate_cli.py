"""Smoke tests for the cascadia-judge-calibrate CLI's main() entry point.

Uses --provider scripted to stay offline. Exercises the argparse surface +
the success-exit-code path + the --tau-min gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cascadia_judge.calibration.cli import main

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "calibration" / "golden_v0.jsonl"
FIXTURE = ROOT / "calibration" / "scripted_v0.json"


def test_calibrate_cli_scripted_provider_succeeds(capsys: pytest.CaptureFixture) -> None:
    exit_code = main([
        "--dataset", str(GOLDEN),
        "--provider", "scripted",
        "--scripted-fixture", str(FIXTURE),
        "--log-level", "WARNING",
    ])
    assert exit_code == 0
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert body["n"] == 15
    assert body["kendall_tau_b"] is not None and body["kendall_tau_b"] > 0.7


def test_calibrate_cli_tau_min_gate_fails(capsys: pytest.CaptureFixture) -> None:
    # An unachievable tau threshold → exit 2.
    exit_code = main([
        "--dataset", str(GOLDEN),
        "--provider", "scripted",
        "--scripted-fixture", str(FIXTURE),
        "--tau-min", "0.99",
        "--log-level", "WARNING",
    ])
    assert exit_code == 2


def test_calibrate_cli_writes_out_file(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    exit_code = main([
        "--dataset", str(GOLDEN),
        "--provider", "scripted",
        "--scripted-fixture", str(FIXTURE),
        "--out", str(out),
        "--log-level", "WARNING",
    ])
    assert exit_code == 0
    assert out.exists()
    body = json.loads(out.read_text())
    assert "rows" in body
    assert "metrics" in body
    assert len(body["rows"]) == 15


def test_calibrate_cli_concision_weight_changes_metrics(capsys: pytest.CaptureFixture) -> None:
    main([
        "--dataset", str(GOLDEN),
        "--provider", "scripted",
        "--scripted-fixture", str(FIXTURE),
        "--concision-weight", "0.2",
        "--log-level", "WARNING",
    ])
    body = json.loads(capsys.readouterr().out)
    # Concision weight ≠ 0 should still produce a valid τ-b on the golden
    # set (the synthetic fixture isn't built around verbosity bias, so the
    # number might shift but should remain defined).
    assert body["kendall_tau_b"] is not None
