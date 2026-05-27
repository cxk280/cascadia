# Cascadia on Railway

Per-service Railway config. Each file points Railway at the corresponding Dockerfile under `deploy/docker/`.

## Service topology

| Railway service     | Image source                                            | Public domain? | Internal port |
| ------------------- | ------------------------------------------------------- | -------------- | ------------- |
| `postgres`          | Railway managed Postgres plugin (not a custom service)  | No             | 5432          |
| `proxy`             | `deploy/docker/proxy.Dockerfile`                        | Optional       | 8080          |
| `dashboard-api`     | `deploy/docker/dashboard-api.Dockerfile`                | **No**         | 8080          |
| `dashboard`         | `deploy/docker/dashboard.Dockerfile`                    | **Yes**        | 3000          |
| `judge-worker`      | `deploy/docker/judge-worker.Dockerfile`                 | No             | —             |
| `policy-controller` | `deploy/docker/policy-controller.Dockerfile`            | No             | —             |

`dashboard-api` deliberately stays on the Railway internal network. The dashboard reaches it via `CASCADIA_DASHBOARD_API_BASE=http://dashboard-api.railway.internal:8080`. No public ingress to the FastAPI surface, so the basic-auth gate in `dashboard/middleware.ts` is the only door to the calibration write paths.

## Provisioning order (per Phase 3 task #77)

```bash
# 1. New Railway project + Postgres
railway init cascadia-dev
railway add postgres

# 2. One service per Dockerfile. From the repo root:
for svc in proxy dashboard-api dashboard judge-worker policy-controller; do
    railway service create $svc
done

# 3. Restore data from local Postgres into Railway Postgres.
#    Get the Railway DSN from the dashboard or `railway variables --service postgres`.
LOCAL_DSN="postgres://cascadia:cascadia@localhost:5432/cascadia"
RAILWAY_DSN="$(railway variables --service postgres --json | jq -r '.DATABASE_URL')"
pg_dump --no-owner --no-acl "$LOCAL_DSN" | psql "$RAILWAY_DSN"

# 4. Set env vars per service (see env-vars.md in this dir).
```

## Env vars per service

See `env-vars.md` in this directory for the complete matrix. The two non-obvious entries from the Option-B correction:

- `dashboard.CASCADIA_CALIBRATE_USER=cascadia`
- `dashboard.CASCADIA_CALIBRATE_PASS=QVTD7Uyc9PXuOixZB_5s` (generated; rotate via the Railway UI any time)

There is **no** `CASCADIA_DEMO_MODE` anywhere — that Option-A toggle was abandoned.
