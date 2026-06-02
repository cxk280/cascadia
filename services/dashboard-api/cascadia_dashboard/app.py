"""FastAPI surface. Thin — every route hands off to `Store`.

CORS is wired wide-open by default; production deployments should set
`CASCADIA_DASHBOARD_CORS_ORIGINS` to the dashboard's public URL.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import socket
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import AsyncIterator
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from cascadia_dashboard.auth import (
    AsyncpgAuthStore,
    AuthStore,
    DuplicateEmailError,
    attach_auth_routes,
)
from cascadia_dashboard.auth.security import hash_password
from cascadia_dashboard.calibrate import (
    AsyncpgCalibrationStore,
    CalibrationStore,
    attach_calibrate_routes,
)
from cascadia_dashboard.store import AsyncpgStore, Store
from cascadia_dashboard.types import (
    ClusterRow,
    EventRow,
    HealthResponse,
    Overview,
    ParetoPoint,
    RecentVerdict,
)


def _service_version() -> str:
    try:
        return version("cascadia-dashboard-api")
    except PackageNotFoundError:
        return "dev"


async def _seed_admin(auth_store: AuthStore) -> None:
    """Create a pre-verified admin from CASCADIA_SEED_ADMIN_EMAIL/_PASSWORD.

    **Demo-only.** This exists so the keyless demo has a known login without an
    email round-trip (the demo has no SMTP). It is hard-gated behind
    `CASCADIA_DEMO=true` so a hardcoded admin can NEVER be created in a real
    deployment — even if the seed env vars are present. Self-hosters onboard via
    real signup; they should not set CASCADIA_DEMO.

    No-op unless demo mode is on AND both seed vars are set. Idempotent.
    """
    log = logging.getLogger(__name__)
    demo_mode = (os.environ.get("CASCADIA_DEMO") or "").strip().lower() == "true"
    has_seed_vars = bool(
        os.environ.get("CASCADIA_SEED_ADMIN_EMAIL")
        or os.environ.get("CASCADIA_SEED_ADMIN_PASSWORD")
    )
    if not demo_mode:
        if has_seed_vars:
            log.warning(
                "[seed] CASCADIA_SEED_ADMIN_* is set but IGNORED: seeding a known "
                "admin is demo-only and requires CASCADIA_DEMO=true. Refusing to "
                "create a hardcoded account in a non-demo deployment."
            )
        return
    email = (os.environ.get("CASCADIA_SEED_ADMIN_EMAIL") or "").strip().lower()
    password = os.environ.get("CASCADIA_SEED_ADMIN_PASSWORD") or ""
    if not email or not password:
        return
    if await auth_store.get_user_by_email(email) is not None:
        return
    try:
        await auth_store.create_user(
            user_id=str(uuid.uuid4()),
            email=email,
            password_hash=hash_password(password),
            display_name="Demo Admin",
            role="admin",
            email_verified=True,
        )
        log.warning(
            "[seed] DEMO MODE: created pre-verified admin %r from "
            "CASCADIA_SEED_ADMIN_* — known credentials, demo use only.",
            email,
        )
    except DuplicateEmailError:
        pass  # raced with another worker; fine


# Per-cluster operating points for the demo's Pareto frontier. The live
# single-model-pair mock can't produce a genuine cost/quality TRADE-OFF — its
# "quality" (P(cheap >= expensive)) and "cost" (escalation rate) are the same
# underlying signal, so one corner dominates and the frontier collapses to a
# point. Real deployments get a spread because different clusters run different
# model pairs whose quality and cost vary independently. We reproduce that here
# by seeding clusters with DECOUPLED escalation + quality, chosen so cluster-0/1/2
# form a rising efficient frontier and cluster-3 is a (Pareto-dominated) point
# the controller would trim — exactly what the /pareto page is meant to show.
# (cluster, cheap_model, expensive_model, n, escalation_pct, base_quality)
_DEMO_FRONTIER = [
    ("cluster-0", "openai/gpt-4o-mini", "openai/gpt-4o", 100, 20, 0.46),
    ("cluster-1", "anthropic/claude-haiku-4-5", "anthropic/claude-sonnet-4-6", 100, 45, 0.53),
    ("cluster-2", "openai/gpt-4o-mini", "anthropic/claude-sonnet-4-6", 100, 72, 0.62),
    ("cluster-3", "anthropic/claude-haiku-4-5", "openai/gpt-4o", 100, 88, 0.55),
]


def _demo_seed_rows(now: datetime):
    """Build (events, shadow_pairs, judge_scores) rows for the demo frontier.

    Pure + deterministic (fixed RNG seed) so it's testable and reproducible.
    Mirrors the column layout the real judge poller writes, including
    shadow_pairs.ensemble_score (what /pareto and the controller read).
    """
    rng = random.Random(20260602)
    events, shadows, judges = [], [], []
    for cluster_id, cheap, expensive, n, esc_pct, base_q in _DEMO_FRONTIER:
        for i in range(1, n + 1):
            request_id = uuid.uuid4()
            escalated = i <= esc_pct  # exactly esc_pct of n=100 escalate
            final_model = expensive if escalated else cheap
            occurred = now - timedelta(seconds=i + rng.randint(0, 30))
            events.append((
                request_id, occurred, "chat_completions", final_model.split("/", 1)[0],
                final_model, 200, 1500 + rng.randint(0, 8000),
                120 + rng.randint(0, 200), 60 + rng.randint(0, 100), cluster_id, escalated,
            ))
            pair_id = uuid.uuid4()
            scores = []
            for judge, variant, jprov in [
                ("pairwise_preference_v1", "pairwise/v1", "anthropic"),
                ("pairwise_preference_v1_swapped", "pairwise/v1#swapped", "anthropic"),
                ("rubric_v1", "rubric/v1", "openai"),
            ]:
                s = max(0.0, min(1.0, base_q + (rng.random() - 0.5) * 0.08))
                scores.append(s)
                judges.append((uuid.uuid4(), pair_id, judge, variant, judge, jprov, s, 0.9, "demo-seed", 500))
            ensemble = sum(scores) / len(scores)
            shadows.append((
                pair_id, request_id, occurred, cluster_id, f"demo prompt for {cluster_id}",
                cheap, "cheap response", expensive, "expensive response", now, ensemble, 0.9,
            ))
    return events, shadows, judges


async def _seed_demo_data(pool) -> None:
    """Seed a representative Pareto frontier so the demo's /pareto page shows a
    real curve + working slider. Demo-only (CASCADIA_DEMO=true) and idempotent
    (skips if the events table already has rows). Never runs on a real deploy.
    """
    if (os.environ.get("CASCADIA_DEMO") or "").strip().lower() != "true":
        return
    log = logging.getLogger(__name__)
    existing = await pool.fetchval("SELECT count(*) FROM events")
    if existing:
        return  # already has data (seeded or live) — leave it
    events, shadows, judges = _demo_seed_rows(datetime.now(timezone.utc))
    await pool.executemany(
        "INSERT INTO events (request_id, occurred_at, route, provider, model, "
        "upstream_status, elapsed_ms, prompt_tokens, completion_tokens, cluster_id, escalated) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
        events,
    )
    await pool.executemany(
        "INSERT INTO shadow_pairs (pair_id, request_id, occurred_at, cluster_id, prompt, "
        "cheap_model, cheap_response, expensive_model, expensive_response, judged_at, "
        "ensemble_score, ensemble_confidence) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)",
        shadows,
    )
    await pool.executemany(
        "INSERT INTO judge_scores (score_id, pair_id, judge_name, prompt_variant, model, "
        "provider, score, confidence, prompt_hash, elapsed_ms) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
        judges,
    )
    log.warning(
        "[seed] DEMO MODE: seeded %d events across %d clusters for the Pareto "
        "frontier (demo data, not real traffic).",
        len(events), len(_DEMO_FRONTIER),
    )


def create_app(
    store: Store | None = None,
    calibration_store: CalibrationStore | None = None,
    auth_store: AuthStore | None = None,
    email_sender=None,
    signup_disabled: bool | None = None,
) -> FastAPI:
    """Factory. Pass `store` / `calibration_store` / `auth_store` to inject
    fakes in tests; in production we construct asyncpg-backed stores in the
    lifespan hook from `CASCADIA_DATABASE_URL`.
    """

    state: dict[str, object] = {
        "store": store,
        "calibration_store": calibration_store,
        "auth_store": auth_store,
    }

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owns_store = False
        owns_calibration_store = False
        if state["store"] is None:
            dsn = os.environ.get("CASCADIA_DATABASE_URL")
            if not dsn:
                raise RuntimeError(
                    "CASCADIA_DATABASE_URL must be set (or pass `store=` to create_app)"
                )
            asyncpg_store = await AsyncpgStore.connect(dsn)
            state["store"] = asyncpg_store
            owns_store = True
            # Share the asyncpg pool between the read-side and the
            # calibration write-side so we don't open two pools against
            # the same DB.
            if state["calibration_store"] is None:
                state["calibration_store"] = AsyncpgCalibrationStore(asyncpg_store._pool)  # type: ignore[attr-defined]
                owns_calibration_store = True
            # Auth shares the same pool as the read/calibration stores. No
            # separate ownership flag — it doesn't hold a pool of its own.
            if state["auth_store"] is None:
                state["auth_store"] = AsyncpgAuthStore(asyncpg_store._pool)  # type: ignore[attr-defined]
            # Demo-only: seed a representative Pareto frontier so /pareto shows a
            # real curve on first boot. Gated on CASCADIA_DEMO + empty events.
            await _seed_demo_data(asyncpg_store._pool)  # type: ignore[attr-defined]
        # Optional: seed a pre-verified admin from env. Used by the keyless demo
        # so a fresh stack has known login creds (no email round-trip). Hard-gated
        # behind CASCADIA_DEMO=true; idempotent (skips if the account exists).
        if state["auth_store"] is not None:
            await _seed_admin(state["auth_store"])  # type: ignore[arg-type]
        try:
            yield
        finally:
            if owns_store and state["store"] is not None:
                await state["store"].close()  # type: ignore[union-attr]
            # The calibration store shares the pool, so closing it would
            # double-close. Only close if we built a standalone one.
            if owns_calibration_store and state["calibration_store"] is not None:
                # No close needed — same pool as read store.
                pass

    app = FastAPI(
        title="Cascadia Dashboard API",
        version=_service_version(),
        lifespan=lifespan,
    )

    # CORS: closed by default. The dashboard-api accepts POST writes
    # (calibration label submissions, reviewer onboarding) so an open `*`
    # default would let any internet-facing webpage forge those calls
    # against a visitor's browser. Operators must opt in by setting
    # `CASCADIA_DASHBOARD_CORS_ORIGINS=https://your.host` (comma-separated
    # for multiple), or `CASCADIA_DASHBOARD_CORS_ORIGINS=*` to explicitly
    # restore wide-open behavior. Empty / unset = no cross-origin access.
    cors_raw = os.environ.get("CASCADIA_DASHBOARD_CORS_ORIGINS", "")
    origins = [o.strip() for o in cors_raw.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        # POST added in Phase-5-followup: the calibration labeling app
        # needs to submit reviewer + label rows.
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    def get_store() -> Store:
        s = state["store"]
        if s is None:
            raise RuntimeError("store not initialised — lifespan hook did not run")
        return s  # type: ignore[return-value]

    def get_calibration_store() -> CalibrationStore:
        s = state["calibration_store"]
        if s is None:
            raise RuntimeError("calibration_store not initialised")
        return s  # type: ignore[return-value]

    def get_auth_store() -> AuthStore:
        s = state["auth_store"]
        if s is None:
            raise RuntimeError("auth_store not initialised")
        return s  # type: ignore[return-value]

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="cascadia-dashboard-api",
            version=_service_version(),
        )

    @app.get("/api/proxy-reachable")
    async def proxy_reachable() -> dict[str, object]:
        """Probe the proxy and report status the dashboard can act on.

        - `reachable`: TCP probe to the proxy's listen address. Fast, no HTTP.
        - `readyz`: when reachable, an HTTP GET on /readyz to surface
           which readiness checks passed/failed. Lets the dashboard tell
           operators things like "proxy is up but Postgres isn't configured
           for event persistence" without needing two round-trips.
        """
        import httpx

        url = os.environ.get("CASCADIA_PROXY_URL", "http://127.0.0.1:8080")
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, _tcp_probe, host, port, 0.5
                ),
                timeout=1.0,
            )
        except (asyncio.TimeoutError, OSError) as exc:
            return {
                "reachable": False,
                "probed": f"{host}:{port}",
                "error": str(exc),
            }
        # Reachable; fetch /readyz for persistence + provider status.
        # Tight timeout: the dashboard hits this endpoint on every page load
        # (and the client banner polls it every 5s). A slow proxy must not
        # stall the dashboard SSR — better to report reachable-without-readyz
        # than to hang the page.
        try:
            async with httpx.AsyncClient(timeout=0.5) as client:
                resp = await client.get(f"{url.rstrip('/')}/readyz")
                if resp.status_code in (200, 503):
                    return {
                        "reachable": True,
                        "probed": f"{host}:{port}",
                        "readyz": resp.json(),
                    }
        except (httpx.HTTPError, ValueError):
            pass
        # Reachable but /readyz didn't respond cleanly — still report reachable.
        return {"reachable": True, "probed": f"{host}:{port}"}

    @app.get("/api/config")
    async def config_snapshot() -> dict[str, object]:
        """Return the proxy's current non-secret deployment config.

        Used by the dashboard's Data residency page to show operators what
        posture (full persistence / redacted / shadow-disabled) they're
        running in without grepping env vars.
        """
        import httpx

        url = os.environ.get("CASCADIA_PROXY_URL", "http://127.0.0.1:8080")
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                resp = await client.get(f"{url.rstrip('/')}/config")
                if resp.status_code == 200:
                    return resp.json()
                return {"error": f"proxy returned HTTP {resp.status_code}"}
        except (httpx.HTTPError, ValueError) as exc:
            return {"error": f"proxy /config unreachable: {exc}"}

    @app.get("/api/policy")
    async def policy() -> dict[str, object]:
        """Return the proxy's current in-memory policy table.

        Operators need to see the live threshold + shadow_rate per cluster
        without grepping a mounted file. The proxy serializes its
        PolicyTable at `/policy` (read-only, no auth — the table is config,
        not credentials). We forward that response with a short timeout so
        the dashboard SSR never stalls.
        """
        import httpx

        url = os.environ.get("CASCADIA_PROXY_URL", "http://127.0.0.1:8080")
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                resp = await client.get(f"{url.rstrip('/')}/policy")
                if resp.status_code == 200:
                    return resp.json()
                return {"error": f"proxy returned HTTP {resp.status_code}"}
        except (httpx.HTTPError, ValueError) as exc:
            return {"error": f"proxy /policy unreachable: {exc}"}

    @app.get("/api/overview", response_model=Overview)
    async def overview(
        window_minutes: int = Query(60, ge=1, le=24 * 60 * 7),
        store: Store = Depends(get_store),
    ) -> Overview:
        return await store.overview(window=timedelta(minutes=window_minutes))

    @app.get("/api/clusters", response_model=list[ClusterRow])
    async def clusters(
        window_minutes: int = Query(60, ge=1, le=24 * 60 * 7),
        store: Store = Depends(get_store),
    ) -> list[ClusterRow]:
        return list(await store.clusters(window=timedelta(minutes=window_minutes)))

    @app.get("/api/events/recent", response_model=list[EventRow])
    async def recent_events(
        limit: int = Query(50, ge=1, le=500),
        store: Store = Depends(get_store),
    ) -> list[EventRow]:
        return list(await store.recent_events(limit=limit))

    @app.get("/api/verdicts/recent", response_model=list[RecentVerdict])
    async def recent_verdicts(
        limit: int = Query(50, ge=1, le=500),
        store: Store = Depends(get_store),
    ) -> list[RecentVerdict]:
        return list(await store.recent_verdicts(limit=limit))

    @app.get("/api/pareto", response_model=list[ParetoPoint])
    async def pareto(
        window_minutes: int = Query(60, ge=1, le=24 * 60 * 7),
        store: Store = Depends(get_store),
    ) -> list[ParetoPoint]:
        return list(await store.pareto_points(window=timedelta(minutes=window_minutes)))

    attach_calibrate_routes(app, get_calibration_store)
    attach_auth_routes(
        app, get_auth_store, email_sender=email_sender, signup_disabled=signup_disabled
    )

    return app


def _tcp_probe(host: str, port: int, timeout_s: float) -> None:
    with socket.create_connection((host, port), timeout=timeout_s):
        return None
