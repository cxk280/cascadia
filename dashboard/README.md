# cascadia-dashboard

Next.js 14 operator dashboard. Reads from `services/dashboard-api/` (which
in turn reads from the proxy's Postgres). The proxy, judge worker, and
policy controller all stay write-side; this is the only customer-facing
read surface.

## Pages

- `/` — Overview (KPIs)
- `/pareto` — Pareto frontier (live operating point)
- `/clusters` — Per-cluster table
- `/activity` — Tail of the event log + recent judge verdicts
- `/health` — Operator paging signals

## Local dev

```bash
# 1. Start the read-API (depends on the proxy's Postgres schema).
cd ../services/dashboard-api
. .venv/bin/activate
cascadia-dashboard-api  # → http://127.0.0.1:18082

# 2. Start the dashboard.
cd ../../dashboard
npm install
npm run dev  # → http://127.0.0.1:3000
```

If you point `CASCADIA_DASHBOARD_API_BASE` at a different URL, the
dashboard will use that instead of `http://127.0.0.1:18082`.
