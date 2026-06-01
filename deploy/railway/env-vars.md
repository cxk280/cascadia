# Cascadia env vars per Railway service

This is the complete set of env vars to set in the Railway UI (or via `railway variables set --service <svc> KEY=VALUE`). Anything secret (API keys, the calibrate password) should be set via the Railway secret store, not committed.

Replace `<dashboard-url>` with the public Railway URL of the `dashboard` service after the first deploy.

## `proxy`

| Key                              | Value                                                            | Notes                              |
| -------------------------------- | ---------------------------------------------------------------- | ---------------------------------- |
| `CASCADIA_LISTEN_ADDR`           | `0.0.0.0:8080`                                                   |                                    |
| `CASCADIA_DATABASE_URL`          | `${{Postgres.DATABASE_URL}}`                                     | Railway reference                  |
| `CASCADIA_OPENAI_API_KEY`        | `sk-…`                                                           | secret                             |
| `CASCADIA_CHEAP_MODEL`           | `openai/gpt-4o-mini`                                             | Phase 7: `provider/` prefix REQUIRED — unprefixed strings hard-fail at boot. |
| `CASCADIA_EXPENSIVE_MODEL`       | `openai/gpt-4o`                                                  | Phase 7: `provider/` prefix REQUIRED.                                       |
| `CASCADIA_POLICY_FILE`           | `/policy/cascadia-policy.json`                                   | shared volume w/ policy-controller |
| `CASCADIA_CLUSTER_BUCKETS`       | `4`                                                              |                                    |
| `CASCADIA_LOG_JSON`              | `true`                                                           |                                    |

## `dashboard-api`

| Key                                  | Value                                  | Notes                              |
| ------------------------------------ | -------------------------------------- | ---------------------------------- |
| `CASCADIA_DATABASE_URL`              | `${{Postgres.DATABASE_URL}}`           | Railway reference                  |
| `CASCADIA_DASHBOARD_CORS_ORIGINS`    | `https://<dashboard-url>`              | tighten after first deploy         |
| `CASCADIA_DASHBOARD_HOST`            | `0.0.0.0`                              | image default                      |
| `CASCADIA_DASHBOARD_PORT`            | `8080`                                 | image default                      |

## `dashboard`

| Key                              | Value                                            | Notes                                       |
| -------------------------------- | ------------------------------------------------ | ------------------------------------------- |
| `CASCADIA_DASHBOARD_API_BASE`    | `http://dashboard-api.railway.internal:8080`     | Railway internal DNS                        |
| `CASCADIA_CALIBRATE_USER`        | `cascadia`                                       | Option-B basic-auth user                    |
| `CASCADIA_CALIBRATE_PASS`        | _(set in Railway only — never commit)_           | Option-B basic-auth pass; **secret**; set via the Railway UI / CLI |

**Do NOT** set `CASCADIA_DEMO_MODE`. The Option-A demo-mode toggle was abandoned in favor of the Next.js middleware basic-auth gate.

## `judge-worker`

| Key                       | Value                          | Notes               |
| ------------------------- | ------------------------------ | ------------------- |
| `CASCADIA_DATABASE_URL`   | `${{Postgres.DATABASE_URL}}`   | Railway reference   |
| `OPENAI_API_KEY`          | `sk-…`                         | secret (panel A)    |
| `ANTHROPIC_API_KEY`       | `sk-ant-…`                     | secret (panel B)    |
| `GROQ_API_KEY`            | `gsk_…`                        | secret (panel C)    |

The judge-worker's default entrypoint is `cascadia-judge-poll`; the panel config is passed as CLI args. On Railway, set the service's start command to e.g.:

```
cascadia-judge-poll --provider anthropic --model claude-haiku-4-5
```

(matching the panel that the sibling-agent Phase-1 run used).

## `policy-controller`

| Key                              | Value                          | Notes                              |
| -------------------------------- | ------------------------------ | ---------------------------------- |
| `CASCADIA_DATABASE_URL`          | `${{Postgres.DATABASE_URL}}`   | Railway reference                  |
| `CASCADIA_POLICY_FILE`           | `/policy/cascadia-policy.json` | shared volume w/ proxy             |
| `CASCADIA_LOOKBACK_MINUTES`      | `60`                           |                                    |
| `CASCADIA_REFIT_INTERVAL_SEC`    | `300`                          |                                    |
