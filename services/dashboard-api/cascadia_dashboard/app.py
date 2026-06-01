"""FastAPI surface. Thin — every route hands off to `Store`.

CORS is wired wide-open by default; production deployments should set
`CASCADIA_DASHBOARD_CORS_ORIGINS` to the dashboard's public URL.
"""

from __future__ import annotations

import asyncio
import os
import socket
from contextlib import asynccontextmanager
from datetime import timedelta
from importlib.metadata import PackageNotFoundError, version
from typing import AsyncIterator
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from cascadia_dashboard.auth import (
    AsyncpgAuthStore,
    AuthStore,
    attach_auth_routes,
)
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


def create_app(
    store: Store | None = None,
    calibration_store: CalibrationStore | None = None,
    auth_store: AuthStore | None = None,
    email_sender=None,
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
    attach_auth_routes(app, get_auth_store, email_sender=email_sender)

    return app


def _tcp_probe(host: str, port: int, timeout_s: float) -> None:
    with socket.create_connection((host, port), timeout=timeout_s):
        return None
