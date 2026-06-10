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
- `/calibrate` — Judge-panel calibration (label pairs, edit the rubric)

## Architecture

```
app/         Next.js App Router — one folder per route
  overview/ pareto/ clusters/ activity/ health/   server components; fetch
             from dashboard-api at request time (dynamic = force-dynamic)
  login/ signup/ verify/ calibrate/   client screens
  api/       server-only route handlers (a thin BFF): proxy to dashboard-api
             + the proxy's /readyz, and set/clear the session cookie
components/  shared UI — Shell (nav frame), KpiCard, ParetoChart/Slider,
             AuthForm, and the live-status widgets (ProxyLivePip,
             ProxyReachabilityBanner)
lib/         api.ts (typed dashboard-api client) · auth.ts (session +
             upstream auth) · pareto-fit.ts (frontier math) · format.ts
             (display formatters) · proxy-status.ts (the /readyz probe shape)
```

**Data flow.** Browser → dashboard (Next.js) → `lib/api.ts` → `dashboard-api`
(FastAPI) → the proxy's Postgres. Most pages are server components marked
`dynamic = "force-dynamic"`, so each load reads fresh (dashboard-api isn't
reachable at build time). Nothing here writes — the proxy, judge worker, and
policy controller own all writes.

**Live status.** `ProxyLivePip` (header) and `ProxyReachabilityBanner` (per
page) client-poll `/api/proxy-reachable` every 2s — a route handler that TCP-
probes the proxy's `/readyz` — so "proxy down / draining / no-DB" surfaces
without a reload. Shared shape + helpers: `lib/proxy-status.ts`.

**Auth.** Email+password through the `app/api/auth/*` route handlers (a thin
BFF over dashboard-api) that set an HTTP-only session cookie; Next.js
middleware gates the app routes. Signup is double-opt-in (email verification).

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
