# cascadia-dashboard-api

Read-only HTTP API powering the Cascadia Next.js dashboard.

The proxy writes events, the judge worker writes scores, the policy
controller writes thresholds. This service only **reads** — it exposes
those tables as JSON for the dashboard.

## Endpoints

| Path | Purpose |
|---|---|
| `GET /api/health` | Liveness probe |
| `GET /api/overview?window_minutes=N` | Headline KPIs (request count, escalation rate, mean judge score, …) |
| `GET /api/clusters?window_minutes=N` | Per-cluster traffic + quality |
| `GET /api/events/recent?limit=N` | Last N proxy events |
| `GET /api/verdicts/recent?limit=N` | Last N judge verdicts joined with their pairs |
| `GET /api/pareto?window_minutes=N` | Per-cluster (escalation, quality) — the live operating point |

## Local dev

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# Requires the proxy's Postgres schema (migrations 0001–0004) to exist.
export CASCADIA_DATABASE_URL=postgres://cascadia:cascadia@localhost:5432/cascadia
cascadia-dashboard-api  # → http://127.0.0.1:18082/docs
```

## Testing

```bash
pytest -q  # runs against the in-memory store; no DB needed
```
