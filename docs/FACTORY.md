# The Cascadia feature factory

A repeatable process for taking a feature from spec → reviewable, tested, full-stack PR **in this repo's own style**. It treats a feature like a compiler pipeline: a fixed stage DAG, exemplar-grounded generation, verification gates run with the project's *real* tools, and a human approving the plan and merging the result.

This file is the **durable profile** — the codebase-specific knowledge a factory run needs so it doesn't re-derive the map every time. Update it when the structure, gates, or exemplars change.

> First worked example: the **dynamic provider registry** (PR `feat/provider-registry` → `v2`, 2026-06-09). Citations throughout point at it.

## 0. Before you start — read these

1. **[CLAUDE.md](../CLAUDE.md)** — the intentional patterns. Several things that look removable are load-bearing.
2. **[PLAN.md §9](../PLAN.md)** — the append-only decisions log, newest first. **Grep it before removing/refactoring anything.** If your feature conflicts with a §9 entry, surface the conflict and get explicit authorization; a reversal is a *new dated §9 entry linking back* (see the 2026-06-09 registry entry reversing the 2026-05-19 closed-enum decision).
3. **[SECURITY.md](../SECURITY.md)** — threat model + the intentional auth gaps (`/policy`, `/config`, `/providers` are public *by design* — config, not credentials).

## 1. Product profile — where things live

| Layer | Location | Notes |
|---|---|---|
| **Rust proxy** (hot path) | `crates/proxy/src/` | Config, routing, cascade, upstream adapters, handlers, events, metrics. Must not block on Postgres (`try_send`). |
| Proxy config / env | `config.rs` (`Config::from_env`) | Every `CASCADIA_*` var is read here or in `policy.rs`; add new ones to the recognized-var list in `lib.rs::log_recognized_env_vars`. |
| Routing policy | `policy.rs` (`PolicyTable`, `ClusterPolicy`) + `watcher.rs` (file + postgres hot-reload) | Boot- and reload-time validation lives here. |
| Upstream adapters | `upstream.rs` + `upstream/{openai_compat,anthropic}.rs` | Dispatch keys on `Wire`. New wire = new adapter mirroring `anthropic.rs`. |
| HTTP handlers / routes | `handlers/*.rs` + route table in `lib.rs::router` | Public vs `/v1/*` bearer-gated split is in `router`. |
| Event log | `events.rs` (struct + SQL insert) | Schema-coupled; widening a field touches the struct *and* the `.bind(...)` chain. |
| **Python services** (each its own `.venv`/`uv`) | `services/{judge-worker,policy-controller,dashboard-api}/` | The policy-controller mirrors `ClusterPolicy` in `cascadia_policy/types.py` — **keep it from drifting**. dashboard-api derives providers dynamically via `split_part(model,'/',1)` (no closed-set assumption). |
| **Dashboard** (Next.js) | `dashboard/` | `app/*` pages, `lib/api.ts` client (TS types mirror the Rust/Python structs). |
| Deploy | `.circleci/config.yml` (CI/CD), `deploy/{docker,helm,railway,compose}/` | Live on Railway; `main`→dev/staging/prod, `v2`→isolated preview env. |

## 2. The gates (run the *real* ones — "passes our gate" must mean "passes CI")

```bash
# Rust
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
# Python (per service)
cd services/<svc> && uv sync --extra dev && uv run pytest -q
# Dashboard
cd dashboard && npm ci && npm run typecheck && npm run build
# All-green wrapper
make verify
# CircleCI config changes
#   validate via the circleci-mcp config_helper (no local CLI installed)
```

A stage is **not done** until its applicable gates pass — run them, see them pass, before moving on.

## 3. Patterns → stage DAGs

Classify the feature, instantiate the DAG, topologically sort, generate in order. The DAG is a default — add/remove stages to fit the real change.

**Add-a-provider / cross-cutting backend** (the registry feature's shape):
`§9 entry + spec` → `config/data-layer` → `{upstream dispatch, policy validation}` → `python mirror (verify no drift)` → `{dashboard-api, dashboard}` → `property checks` → `docs`.

**Entity/CRUD + UI:** `data-layer` + `config` → `api` → `frontend` → `tests`.
**Integration / Workflow / Analytics:** decompose by the layers actually touched.

## 4. Exemplar registry (pattern on the repo's best current instance)

| Generating… | Exemplar to pattern on |
|---|---|
| A provider / upstream adapter | `crates/proxy/src/upstream/anthropic.rs` (request+response+streaming translation, full tests) |
| A public read-only endpoint | `crates/proxy/src/handlers/config.rs` → `providers.rs` |
| Config / env loading | `crates/proxy/src/config.rs::from_env` |
| Policy schema + validation | `crates/proxy/src/policy.rs` |
| Hot-reload plumbing | `crates/proxy/src/watcher.rs` (file + postgres) |
| Event-log field | `crates/proxy/src/events.rs` (struct + insert bind) |
| A dashboard page + API call | `dashboard/app/clusters/page.tsx` + `dashboard/lib/api.ts` |
| dashboard-api query | `services/dashboard-api/cascadia_dashboard/store.py` |

## 5. Verification ladder (cheapest first, stop at first failure)

`G1 parses → G2 fmt/clippy/typecheck → G3 contract (references only things that exist; matches upstream artifact) → G4 pattern conformance (matches the exemplar) → G5 functional + property checks → G6 integration → G7 security/compliance → G8 real CI`.

**Property checks** turn the spec's invariants into executable assertions. For the registry feature: an unprefixed model fails at parse; an *unconfigured* prefix fails at boot **and** on hot-reload (previous policy kept); `/providers` never serializes a key value; a configured custom provider with a slash-bearing model name validates. (See `model_id.rs`, `policy.rs`, `config.rs` test modules.)

**Repair loop:** on a gate failure, feed the *actual* failing output back into a regeneration of that stage. ~3 attempts, then escalate with full context (failing artifact + exact gate output + exemplar used).

## 6. Security/compliance (blocking where data is sensitive)

No secrets in the diff or in any endpoint payload (the `/providers` endpoint reports `configured: bool`, never the key). Public-by-design endpoints stay public; don't add auth to `/policy`,`/config`,`/providers` (gate at the cluster boundary). Schema/migrations additive + reversible. This operationalizes policy — it doesn't replace human security sign-off.

## 7. The reviewable PR

- **Feature branch off `v2`** (never push to `v2` directly), **PR into `v2`** for human review/approval. `v2` accumulates the feature set; it merges to `main` + a major npm bump (a `v*` tag) only when complete. The `main`-gated live envs are never touched by in-progress work.
- Clean, conventional commits — **one per logical stage** is a good default.
- PR description: what + why, per-stage rationale with **exemplar citations**, the gate results (real command output), and a **confidence map** routing review — tag first-try-green files "spot-check" and repaired/sensitive/schema-touching files "review closely."

## 8. Repo-specific tripwires (learned the hard way)

- **§9 conflict protocol is mandatory** — don't silently obey a request that contradicts a §9 entry; surface it, get authorization, write a reversal entry.
- **Hot-reload paths double the validation surface** — anything validated at boot must also be validated in `watcher.rs` (file *and* postgres), keeping the previous good policy on a bad reload.
- **`events.rs` is schema-coupled** — widening a field touches the struct, the SQL column list, *and* the `.bind(...)` chain (and `insert_event` takes `&Event`, so bind borrows: `.bind(e.field.as_str())`).
- **Keep the Python `types.py` mirror in lockstep** with `ClusterPolicy`.
- **Dynamic env vars** (`CASCADIA_PROVIDER_<NAME>_*`) need a prefix-match exception in `lib.rs::log_recognized_env_vars`, or the proxy warns they're unrecognized.
- **Don't tag `v*` before release** — the CircleCI tag filter triggers image publish; tags are the release path.
