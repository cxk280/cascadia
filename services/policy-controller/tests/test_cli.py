"""Smoke + integration tests for the controller CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cascadia_policy.cli import (
    PolicyFileError,
    _load_current_policy,
    _parse_args,
    _refit_once,
)
from cascadia_policy.controller import PolicyController, UpdateRule
from cascadia_policy.storage import InMemoryStatsReader
from cascadia_policy.types import ClusterPolicy, ClusterStats, PolicyTable
from cascadia_policy.writer import JsonFileWriter
from datetime import timedelta


def _table(threshold: float = 0.7) -> PolicyTable:
    return PolicyTable(
        default_cluster="default",
        cluster_buckets=1,
        version="initial",
        clusters={
            "default": ClusterPolicy(
                cluster_id="default", cheap_model="cheap", expensive_model="expensive",
                threshold=threshold, shadow_rate=0.05,
            ),
        },
    )


def test_parse_args_defaults_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASCADIA_DATABASE_URL", "postgres://test")
    monkeypatch.setenv("CASCADIA_POLICY_FILE", "/tmp/x.json")
    monkeypatch.setenv("CASCADIA_LOOKBACK_MINUTES", "120")
    args = _parse_args([])
    assert args.database_url == "postgres://test"
    assert args.policy_file == "/tmp/x.json"
    assert args.lookback_minutes == 120


def test_parse_args_cli_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASCADIA_DATABASE_URL", "postgres://env")
    args = _parse_args(["--database-url", "postgres://cli", "--once"])
    assert args.database_url == "postgres://cli"
    assert args.once is True


def test_parse_args_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc:
        _parse_args(["--help"])
    assert exc.value.code == 0


def test_load_current_policy_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({
        "default_cluster": "default",
        "cluster_buckets": 1,
        "version": "abc",
        "clusters": {
            "default": {
                "cluster_id": "default",
                "cheap_model": "x",
                "expensive_model": "y",
                "threshold": 0.5,
                "shadow_rate": 0.1,
            }
        },
    }))
    loaded = _load_current_policy(path)
    assert loaded.version == "abc"
    assert loaded.clusters["default"].cheap_model == "x"


@pytest.mark.asyncio
async def test_refit_once_writes_new_policy(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    initial = _table(0.7)
    policy_path.write_text(initial.model_dump_json())
    reader = InMemoryStatsReader({
        "default": ClusterStats(cluster_id="default", sample_size=100, mean_score=0.8),
    })
    writer = JsonFileWriter(str(policy_path))
    controller = PolicyController(UpdateRule(step=0.05))
    await _refit_once(controller, reader, writer, policy_path, timedelta(hours=1))
    new = _load_current_policy(policy_path)
    # cheap-winning (mean=0.8 > 0.55) → threshold lowered.
    assert new.clusters["default"].threshold < 0.7


def test_load_current_policy_empty_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text("")  # zero-byte / truncated write
    with pytest.raises(PolicyFileError):
        _load_current_policy(path)


def test_load_current_policy_wrong_shape_raises(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"not": "a policy"}))
    with pytest.raises(PolicyFileError):
        _load_current_policy(path)


@pytest.mark.asyncio
async def test_refit_once_corrupt_file_logs_and_skips(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A corrupt policy file must not crash the controller or get overwritten;
    # it logs an actionable error and skips the cycle.
    policy_path = tmp_path / "policy.json"
    policy_path.write_text("{ this is not json")
    reader = InMemoryStatsReader({
        "default": ClusterStats(cluster_id="default", sample_size=100, mean_score=0.8),
    })
    writer = JsonFileWriter(str(policy_path))
    controller = PolicyController(UpdateRule())
    with caplog.at_level("ERROR"):
        await _refit_once(controller, reader, writer, policy_path, timedelta(hours=1))
    # Left untouched (not overwritten with a "fixed" policy).
    assert policy_path.read_text() == "{ this is not json"
    assert any("not valid json" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_refit_once_missing_file_is_noop(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    policy_path = tmp_path / "does-not-exist.json"
    reader = InMemoryStatsReader()
    writer = JsonFileWriter(str(policy_path))
    controller = PolicyController(UpdateRule())
    with caplog.at_level("WARNING"):
        await _refit_once(controller, reader, writer, policy_path, timedelta(hours=1))
    assert not policy_path.exists()  # we didn't create it
    assert any("missing" in record.message.lower() for record in caplog.records)
