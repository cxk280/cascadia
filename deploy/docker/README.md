# Cascadia Dockerfiles

Five multi-stage Dockerfiles, one per service. Build context is always the **repo root** (`cd cascadia/`); the Dockerfile path is relative.

| Service             | Dockerfile                                     | Default port | Base image (runtime)              |
| ------------------- | ---------------------------------------------- | ------------ | --------------------------------- |
| `proxy`             | `deploy/docker/proxy.Dockerfile`               | 8080         | `distroless/cc-debian12:nonroot`  |
| `dashboard-api`     | `deploy/docker/dashboard-api.Dockerfile`       | 8080         | `python:3.12-slim-bookworm`       |
| `dashboard`         | `deploy/docker/dashboard.Dockerfile`           | 3000         | `distroless/nodejs20-debian12:nonroot` |
| `judge-worker`      | `deploy/docker/judge-worker.Dockerfile`        | —            | `python:3.12-slim-bookworm`       |
| `policy-controller` | `deploy/docker/policy-controller.Dockerfile`   | —            | `python:3.12-slim-bookworm`       |

## Build all locally

```bash
cd /Users/christopherking/code/cascadia
for svc in proxy dashboard-api dashboard judge-worker policy-controller; do
    docker build -f deploy/docker/${svc}.Dockerfile -t cascadia-${svc}:dev .
done
```

## Required runtime env vars

### `proxy`
- `CASCADIA_LISTEN_ADDR` (default `0.0.0.0:8080`)
- `CASCADIA_DATABASE_URL` — Postgres DSN
- `CASCADIA_OPENAI_API_KEY` or `CASCADIA_ANTHROPIC_API_KEY` (at least one)
- `CASCADIA_POLICY_FILE` — path to the policy JSON file (shared with `policy-controller`)

### `dashboard-api`
- `CASCADIA_DATABASE_URL`
- `CASCADIA_DASHBOARD_CORS_ORIGINS` — comma-separated list of dashboard origins (e.g. the Railway dashboard URL)
- `CASCADIA_DASHBOARD_HOST` (default `0.0.0.0` inside the image)
- `CASCADIA_DASHBOARD_PORT` (default `8080` inside the image)

### `dashboard`
- `CASCADIA_DASHBOARD_API_BASE` — internal URL of `dashboard-api` (e.g. `http://dashboard-api.railway.internal:8080`)
- `CASCADIA_CALIBRATE_USER` — HTTP basic-auth user for the calibration gate (defaults to `cascadia`)
- `CASCADIA_CALIBRATE_PASS` — **required in production**; if unset the middleware returns 503

### `judge-worker`
- `CASCADIA_DATABASE_URL`
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY` — per the configured judge panel

### `policy-controller`
- `CASCADIA_DATABASE_URL`
- `CASCADIA_POLICY_FILE` — must match the proxy's `CASCADIA_POLICY_FILE`
- `CASCADIA_LOOKBACK_MINUTES` (default 60)
- `CASCADIA_REFIT_INTERVAL_SEC` (default 300)

## Notes on the calibration gate (Option B)

The basic-auth gate for `/calibrate` lives in **`dashboard/middleware.ts`** (Next.js Edge), not in `dashboard-api`. There is intentionally **no `CASCADIA_DEMO_MODE`** env var anywhere — that toggle was abandoned in favor of password auth.

The `dashboard-api` image therefore stays oblivious to the gate. On Railway, lock down the `dashboard-api` further by setting `CASCADIA_DASHBOARD_CORS_ORIGINS` to the dashboard's public URL and keeping the API service on the internal network (no public domain).
