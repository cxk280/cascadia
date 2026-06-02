"""The demo Pareto seed must produce a genuine (non-degenerate) frontier and
must never run outside demo mode."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cascadia_dashboard.app import _DEMO_FRONTIER, _demo_seed_rows, _seed_demo_data


def _per_cluster(events, shadows):
    esc, qual = {}, {}
    for ev in events:
        cid, escalated = ev[9], ev[10]
        esc.setdefault(cid, []).append(1 if escalated else 0)
    for sp in shadows:
        cid, ensemble = sp[3], sp[10]
        qual.setdefault(cid, []).append(ensemble)
    return {
        cid: (sum(esc[cid]) / len(esc[cid]), sum(qual[cid]) / len(qual[cid]))
        for cid in esc
    }


def _efficient(points: dict[str, tuple[float, float]]) -> set[str]:
    # Non-dominated: no other point has quality >= and cost <= (strictly better once).
    out = set()
    for cid, (cost, q) in points.items():
        dominated = any(
            other != cid
            and oq >= q
            and oc <= cost
            and (oq > q or oc < cost)
            for other, (oc, oq) in points.items()
        )
        if not dominated:
            out.add(cid)
    return out


def test_demo_seed_is_a_non_degenerate_frontier() -> None:
    events, shadows, judges = _demo_seed_rows(datetime.now(timezone.utc))
    assert len(events) == 100 * len(_DEMO_FRONTIER)
    assert len(judges) == 3 * len(shadows)  # 3 judge rows per pair

    pts = _per_cluster(events, shadows)
    eff = _efficient(pts)
    # The whole point of the seed: more than one efficient point, so a line
    # draws and the slider has a range to navigate.
    assert len(eff) >= 2, f"frontier collapsed to {eff}: {pts}"

    # Quality genuinely rises with cost along the efficient frontier (a real
    # trade-off, not one dominant corner).
    curve = sorted((pts[c][0], pts[c][1]) for c in eff)
    qualities = [q for _, q in curve]
    assert qualities == sorted(qualities), f"frontier not monotone: {curve}"

    # cluster-3 is intentionally Pareto-dominated (the "trim me" point).
    assert "cluster-3" not in eff


def test_seed_demo_data_noop_without_demo_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CASCADIA_DEMO", raising=False)

    class _ExplodingPool:
        async def fetchval(self, *a, **k):
            raise AssertionError("must not touch the DB when demo mode is off")

        async def executemany(self, *a, **k):
            raise AssertionError("must not insert when demo mode is off")

    import asyncio

    asyncio.run(_seed_demo_data(_ExplodingPool()))  # returns early, no error
