#!/usr/bin/env python3
"""Re-seed Cascadia's Postgres with the mixed-provider demo data.

Produces 4 clusters (cluster-0, cluster-1, cluster-mixed, cluster-3),
~453 events, ~453 shadow_pairs, ~1359 judge_scores — matches what the
local demo DB carries. Idempotent: refuses to insert if events table is
non-empty.

Usage:
  # against the local dev Postgres:
  CASCADIA_DATABASE_URL=postgres://cascadia:cascadia@localhost:5432/cascadia \\
      services/dashboard-api/.venv/bin/python scripts/seed-dev-postgres.py

  # against Railway dev Postgres (DATABASE_URL is auto-injected):
  railway run --service Postgres-cKur --environment dev -- \\
      services/dashboard-api/.venv/bin/python scripts/seed-dev-postgres.py

Uses asyncpg (already installed in dashboard-api/judge-worker/policy-controller
venvs) so no extra dependency required.
"""
from __future__ import annotations

import asyncio
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

try:
    import asyncpg
except ImportError:
    print(
        "ERROR: asyncpg not installed. Run this through one of the service "
        "venvs, e.g. services/dashboard-api/.venv/bin/python.",
        file=sys.stderr,
    )
    sys.exit(2)


CLUSTERS = [
    # (cluster_id, cheap_model, expensive_model, n_requests, escalation_pct, base_quality)
    ("cluster-0",     "openai/gpt-4o-mini",           "openai/gpt-4o", 99,  55, 0.508),
    ("cluster-1",     "openai/gpt-4o-mini",           "openai/gpt-4o", 105, 80, 0.509),
    ("cluster-mixed", "groq/llama-3.3-70b-versatile", "openai/gpt-4o", 99,  70, 0.595),
    ("cluster-3",     "openai/gpt-4o-mini",           "openai/gpt-4o", 150, 62, 0.494),
]


async def main() -> int:
    # Prefer DATABASE_PUBLIC_URL when set — it's what Railway injects for
    # commands run locally via `railway run`. DATABASE_URL is the internal
    # `*.railway.internal` host that only resolves from inside Railway's
    # network and will fail with `gaierror` from a developer machine.
    db_url = (
        os.environ.get("CASCADIA_DATABASE_URL")
        or os.environ.get("DATABASE_PUBLIC_URL")
        or os.environ.get("DATABASE_URL")
    )
    if not db_url:
        print(
            "ERROR: CASCADIA_DATABASE_URL / DATABASE_PUBLIC_URL / DATABASE_URL "
            "must be set.",
            file=sys.stderr,
        )
        return 2

    rng = random.Random(20260520)
    now = datetime.now(timezone.utc)

    conn = await asyncpg.connect(db_url)
    try:
        # Migrations applied? Look for the events table.
        exists = await conn.fetchval("SELECT to_regclass('public.events')")
        if exists is None:
            print(
                "ERROR: 'events' table missing. Start the proxy at least once "
                "so sqlx migrations run, then re-run this seed.",
                file=sys.stderr,
            )
            return 3

        existing = await conn.fetchval("SELECT COUNT(*) FROM events")
        if existing > 0:
            print(f"events table already has {existing} rows. Refusing to double-seed.")
            return 0

        event_rows = []
        shadow_rows = []
        judge_rows = []

        for cluster_id, cheap, expensive, n, escalation_pct, base_q in CLUSTERS:
            for i in range(1, n + 1):
                request_id = uuid.uuid4()
                escalated = (i % 100) < escalation_pct
                final_model = expensive if escalated else cheap
                provider = final_model.split("/", 1)[0]
                occurred = now - timedelta(seconds=i + rng.randint(0, 30))
                event_rows.append((
                    request_id,
                    occurred,
                    "chat_completions",
                    provider,
                    final_model,
                    200,
                    1500 + rng.randint(0, 8000),
                    120 + rng.randint(0, 200),
                    60 + rng.randint(0, 100),
                    cluster_id,
                    escalated,
                ))
                pair_id = uuid.uuid4()
                shadow_rows.append((
                    pair_id,
                    request_id,
                    occurred,
                    cluster_id,
                    f"synthetic prompt for {cluster_id}",
                    cheap,
                    "cheap response text",
                    expensive,
                    "expensive response text",
                    now,
                ))
                for judge, variant, judge_provider in [
                    ("pairwise_preference_v1", "pairwise/v1", "anthropic"),
                    ("pairwise_preference_v1_swapped", "pairwise/v1#swapped", "anthropic"),
                    ("rubric_v1", "rubric/v1", "openai"),
                ]:
                    score = max(0.0, min(1.0, base_q + (rng.random() - 0.5) * 0.1))
                    judge_rows.append((
                        uuid.uuid4(),
                        pair_id,
                        judge,
                        variant,
                        judge,
                        judge_provider,
                        score,
                        0.9,
                        "bench-hash",
                        500,
                    ))

        print(
            f"inserting {len(event_rows)} events / "
            f"{len(shadow_rows)} shadow_pairs / {len(judge_rows)} judge_scores"
        )
        await conn.executemany(
            """
            INSERT INTO events (
                request_id, occurred_at, route, provider, model,
                upstream_status, elapsed_ms, prompt_tokens, completion_tokens,
                cluster_id, escalated
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            """,
            event_rows,
        )
        await conn.executemany(
            """
            INSERT INTO shadow_pairs (
                pair_id, request_id, occurred_at, cluster_id, prompt,
                cheap_model, cheap_response, expensive_model, expensive_response,
                judged_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            """,
            shadow_rows,
        )
        await conn.executemany(
            """
            INSERT INTO judge_scores (
                score_id, pair_id, judge_name, prompt_variant, model, provider,
                score, confidence, prompt_hash, elapsed_ms
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            """,
            judge_rows,
        )
        print("seed complete.")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
