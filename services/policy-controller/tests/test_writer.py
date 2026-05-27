"""Tests for the JSON writer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cascadia_policy.types import ClusterPolicy, PolicyTable
from cascadia_policy.writer import JsonFileWriter


def _table() -> PolicyTable:
    return PolicyTable(
        default_cluster="default",
        version="test-v1",
        cluster_buckets=2,
        clusters={
            "default": ClusterPolicy(
                cluster_id="default",
                cheap_model="a",
                expensive_model="b",
                threshold=0.7,
                shadow_rate=0.05,
            ),
        },
    )


@pytest.mark.asyncio
async def test_writes_valid_json(tmp_path: Path) -> None:
    target = tmp_path / "policy.json"
    writer = JsonFileWriter(target)
    await writer.write(_table())

    data = json.loads(target.read_text())
    assert data["default_cluster"] == "default"
    assert data["version"] == "test-v1"
    assert data["clusters"]["default"]["threshold"] == 0.7


@pytest.mark.asyncio
async def test_atomic_replace_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "policy.json"
    writer = JsonFileWriter(target)
    await writer.write(_table())

    # Mutate + rewrite
    t2 = _table()
    t2.clusters["default"].threshold = 0.42
    await writer.write(t2)

    data = json.loads(target.read_text())
    assert data["clusters"]["default"]["threshold"] == 0.42
    # And no stray .tmp files left behind.
    leftover = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert not leftover


@pytest.mark.asyncio
async def test_creates_parent_dir(tmp_path: Path) -> None:
    target = tmp_path / "subdir" / "policy.json"
    writer = JsonFileWriter(target)
    await writer.write(_table())
    assert target.exists()


@pytest.mark.asyncio
async def test_refuses_dangling_default_cluster(tmp_path: Path) -> None:
    # A policy whose default_cluster isn't a key in clusters would be rejected
    # by the proxy on reload. Catch it at write time instead of persisting a
    # broken policy.
    target = tmp_path / "policy.json"
    t = _table()
    t.default_cluster = "ghost"  # not present in clusters
    with pytest.raises(ValueError, match="default_cluster"):
        await JsonFileWriter(target).write(t)
    # Nothing written, and no orphaned temp file left behind.
    assert not target.exists()
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_no_tmp_left_when_replace_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # If os.replace fails (e.g. permissions), the temp file must be cleaned up
    # rather than orphaned in the policy directory.
    import os as _os

    target = tmp_path / "policy.json"

    def boom(src: str, dst: str) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(_os, "replace", boom)
    with pytest.raises(OSError, match="simulated replace failure"):
        await JsonFileWriter(target).write(_table())
    leftover = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert not leftover
