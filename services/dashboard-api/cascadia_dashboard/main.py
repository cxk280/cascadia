"""`cascadia-dashboard-api` entrypoint — runs uvicorn against `create_app()`."""

from __future__ import annotations

import os

import uvicorn

from cascadia_dashboard.app import create_app


def main() -> None:
    # Host: bind 0.0.0.0 when running in a container/PaaS, 127.0.0.1 locally.
    # Port resolution (12-factor + Railway/Render/Heroku friendly):
    #   1. CASCADIA_DASHBOARD_PORT — explicit override
    #   2. PORT — common platform convention
    #   3. 18082 — local dev default
    host = os.environ.get("CASCADIA_DASHBOARD_HOST", "127.0.0.1")
    port = int(
        os.environ.get("CASCADIA_DASHBOARD_PORT")
        or os.environ.get("PORT")
        or "18082"
    )
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    main()
