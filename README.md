# Cascadia

[![CI](https://github.com/christopherking/cascadia/actions/workflows/ci.yml/badge.svg)](https://github.com/christopherking/cascadia/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Rust](https://img.shields.io/badge/rust-stable-orange.svg)](rust-toolchain.toml)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](services/judge-worker/pyproject.toml)

**A self-hostable, OpenAI-compatible LLM gateway that learns the cheapest model which still clears your quality bar — per request — using counterfactual evaluation on your own live traffic. No golden dataset, no separate eval rig.**

## In a nutshell

Cascadia does **per-cluster cascade routing**: every prompt is sorted into one of N clusters, served by that cluster's *cheap* tier, and escalated to the *expensive* tier only when a cheap-tier confidence signal drops below the cluster's threshold. You pay for the strong model exactly on the requests that need it.

The hard part is **setting those thresholds.** Cascadia runs a **closed feedback loop on live traffic**: a configurable `shadow_rate` of cheap-tier responses is mirrored to the expensive tier in the background, an LLM **judge ensemble** scores the pair ("would the expensive model have been meaningfully better?"), and a controller **refits each cluster's threshold** from that signal — automatically, no human in the loop. Quality is human-anchored: the judge is calibrated against human labels via Kendall's τ-b — a −1-to-+1 score for how often the judge and a human rank the same two answers in the same order (1 = always agree, 0 = coin-flip). Target is ≥ 0.7; the synthetic set hits 0.83, and the real human gate is pending a *Prolific run* (Prolific is a platform for paying vetted people to do small tasks — here, labeling enough answer pairs for a statistically real result). Judging is pairwise with position-swap debiasing.

The output is a **cost/quality Pareto frontier** per cluster — the curve of best-possible tradeoffs, where every point is "already optimal": you can't get cheaper without losing quality, or better without paying more. Cascadia fits it from the system's own shadow data and renders it live at `/pareto` — that frontier, not a marketing number, is the headline artifact.

> **MLOps stack, end-to-end:** Rust hot path · Python judge + policy-controller · Postgres event log · Next.js operator dashboard · FastAPI read-side · Helm · Prometheus + OpenTelemetry.

## What makes Cascadia different

Most gateways (LiteLLM, Portkey, OpenRouter) route on rules a human wrote and never tell you whether the rules are right. Cascadia *learns* the rules from a closed loop. They ask *"where does this request go?"*; Cascadia asks *"what's the cheapest model that still meets quality — and how do we know?"*

|  | LiteLLM / Portkey | Cascadia |
|---|---|---|
| Routing decisions | human-written rules | bandit refit from judge scores |
| Know the rules are right? | you don't | the Pareto chart, from shadow data |
| Quality measured? | cost-saved only | bias-corrected, human-calibrated judge ensemble |
| Adapts as models change | edit the YAML | refits automatically |

Three things competitors structurally don't do: **counterfactual shadow routing** (the "what would the expensive model have said?" signal falls out of serving traffic), **per-cluster online policy learning** (the [`policy-controller`](services/policy-controller/) refits because there's a closed loop to learn from), and a **bias-corrected, human-calibrated judge ensemble** (position-bias correction, anti-self-preference filtering, τ-b gating — academic-rigor evaluation, not a gateway feature).

**Provider breadth.** Cascadia natively speaks 4 providers (OpenAI / Anthropic / Groq / xAI). Any other OpenAI-shape host (Mistral, DeepSeek, Together, vLLM, your endpoint) is a one-env-var override — no code change. For everything else (Bedrock, Vertex, the LiteLLM 100+), **stack Cascadia on top of LiteLLM**: Cascadia decides the cascade, LiteLLM handles the N-provider plumbing. They're orthogonal and compose — Cascadia hands LiteLLM a resolved `(provider, model, request)`, LiteLLM handles auth/retries/quirks. (Cascadia has no retries or fallback chains by design — that's LiteLLM's lane.)

## Quick start

```bash
./scripts/quickstart.sh
```

One command: brings up Postgres, writes a starter policy, builds and starts the mock upstream + proxy, drives synthetic traffic to fill the Pareto data, and launches the dashboard-api + dashboard. It prints each step (and the policy knobs) as it runs; Ctrl-C tears it down. Proxy → `localhost:8080` (OpenAI-compatible at `/v1`); dashboard → `localhost:3000` (first visit → `/signup`). **Every port falls back to the next free one if it's already taken** (so it won't fight another dev server) — watch the startup lines for the resolved ports. That includes Postgres: if a *foreign* Postgres already owns `5432` (a common one is a Homebrew/Postgres.app install), the cascadia container is published on the next free host port instead, and the connection string follows. The dashboard is **precompiled** (`next build` + `next start`) so navigation is instant; set `DASHBOARD_MODE=dev` for the hot-reloading dev server while editing the UI. Override the preferred values (`CASCADIA_PG_PORT`, `CASCADIA_LISTEN_PORT`, `DASHBOARD_PORT`, `CASCADIA_DASHBOARD_PORT`, `CASCADIA_MOCK_PORT`), plus `CASCADIA_DATABASE_URL` (use your own DB outright), `CASCADIA_POLICY_FILE`, `QUICKSTART_TRAFFIC`, or `CASCADIA_AUTH_DISABLED`, via the environment.

**Live data, standalone (real providers, real cost).** `CASCADIA_LIVE=1 ./scripts/quickstart.sh` runs the same stack against a real cascade instead of the mock — Anthropic `claude-haiku-4-5` → `claude-sonnet-4-6` by default — with real traffic, a real multi-model **judge panel** scoring shadow pairs live, and the controller refitting on a loop. Needs `ANTHROPIC_API_KEY` (cascade) and `OPENAI_API_KEY` (cross-family judge — the panel must be a different family than the cascade). Live mode **clears the synthetic seed first** so the dashboard shows only live data; add **`QUICKSTART_TRAFFIC=0`** to start from an empty dashboard and drive your own traffic (handy on camera — watch the KPIs and Pareto chart fill in real time). Signup is **double opt-in** — it emails a confirmation link you must click to finish (with no SMTP configured, the link is printed to `/tmp/cascadia-dashboard-api.log`); the first confirmed account becomes **admin**, and calibration is admin/reviewer-only (operators consume the calibrated judge, they don't label). The same mode becomes a LiteLLM-stacked demo later by pointing `CASCADIA_OPENAI_BASE_URL` at LiteLLM — no code change.

**Deploying instead?** Kubernetes → [`deploy/helm/cascadia/`](deploy/helm/cascadia/README.md). Full container stack → `deploy/compose/docker-compose.full.yml`. Railway/Render/Fly → [PLAN.md §9 (2026-05-20)](PLAN.md).

## Use it from the OpenAI SDK

Point any OpenAI client's `base_url` at the proxy (note the trailing `/v1`); streaming, tool-use, `response_format`, and multi-turn all keep working.

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8080/v1", api_key="...")  # api_key = bearer token if CASCADIA_PROXY_BEARER_TOKEN is set
resp = client.chat.completions.create(
    model="gpt-4o-mini",                       # ignored — the policy decides which model serves
    messages=[{"role": "user", "content": "hi"}],
)
```

Responses carry `x-cascadia-served-model`, `x-cascadia-served-provider`, and `x-cascadia-escalated` so you can reconcile billing without parsing the body. (Tool-use and streaming requests always report `escalated: false` — the cascade bypasses escalation on both by design, so those clusters show 0% escalation; not a bug.)

If `CASCADIA_PROXY_BEARER_TOKEN` is set, every `/v1/*` call needs `Authorization: Bearer <token>` (pass it as `api_key`). Unset = open, for local dev and private networks.

**Adding a provider:** if it speaks OpenAI's `/v1/chat/completions`, no code change — override `CASCADIA_OPENAI_BASE_URL` and prefix the model `openai/` in your policy. Full recipe (incl. Anthropic and air-gapped notes) in [`docs/adding-a-provider.md`](docs/adding-a-provider.md); customizing the judge/aggregator/refit in [`docs/extending.md`](docs/extending.md).

## Tuning for cost

Two policy-file knobs drive cost; the dashboard's `/clusters` page shows both per-cluster with the current live value.

| Knob | What it is | Direction |
|---|---|---|
| `threshold` (0–1) | Cheap-tier confidence floor; cheap is accepted when `confidence ≥ threshold`, else escalate. | **Lower → more cheap accepted → less escalation → cheaper.** |
| `shadow_rate` (0–1) | Fraction of accepted-cheap responses mirrored to the expensive tier for scoring. | **Higher → more expensive-tier calls → more cost.** 0.05–0.10 is the sweet spot; 0.0 disables the loop (and quality scoring). |

The proxy hot-reloads `CASCADIA_POLICY_FILE` on change; confirm a change landed by reading the live values on `/clusters`.

## Operations

| Endpoint (`:8080`) | Purpose |
|---|---|
| `POST /v1/chat/completions` | OpenAI-compatible chat — the hot path |
| `GET /livez` / `GET /readyz` | liveness / readiness (DB pool + ≥1 provider). `/health` aliases `/readyz`. |
| `GET /metrics` | Prometheus exposition |
| `GET /policy` | read-only snapshot of the live policy table |

Unimplemented paths (`/v1/completions` legacy, `/v1/embeddings`, image/modality endpoints) return a 404 in an OpenAI-shape error envelope with a remediation hint — Cascadia is a *cascade-routing* gateway, not an everything-proxy.

**Metrics** are Cascadia-specific (not LiteLLM/Portkey conventions): `cascadia_proxy_requests_total{route,provider,status}` (counter, bounded cardinality) and `cascadia_proxy_request_duration_seconds{route,provider}` (histogram). Per-cluster escalation/tool-use rates live on the dashboard, not in Prometheus.

**Resilience:** the proxy traps SIGINT/SIGTERM and drains in-flight requests (`CASCADIA_SHUTDOWN_TIMEOUT_SECS`, default 30s). Killing the controller leaves the proxy serving on the last-known policy file; killing the judge-worker doesn't touch the hot path; if Postgres is down the hot path stays responsive and event-log writes degrade to best-effort (`/readyz` reports 503).

## Architecture

```mermaid
flowchart LR
    classDef hot fill:#0B3D2E,stroke:#5AE3D6,color:#E6E8EC,stroke-width:1px
    classDef store fill:#1A1F2C,stroke:#5AE3D6,color:#E6E8EC,stroke-width:1px
    classDef ctrl fill:#1A1F2C,stroke:#F5A05A,color:#E6E8EC,stroke-width:1px
    classDef ui fill:#1A1F2C,stroke:#9098A8,color:#E6E8EC,stroke-width:1px
    classDef client fill:#0B0E13,stroke:#9098A8,color:#E6E8EC,stroke-width:1px

    Client["Client app<br/>(OpenAI-compatible)"]:::client

    subgraph proxy ["Rust async proxy · hot path (P99 ~2 ms)"]
        direction TB
        Route["1. classify · 2. lookup · 3. call cheap<br/>4. escalate if low confidence<br/>5. shadow-route X% async · 6. emit event"]
    end
    class proxy hot

    subgraph providers ["Phase 7 upstreams (per-tier provider routing)"]
        direction LR
        OAI[OpenAI]:::ui
        ANT[Anthropic]:::ui
        GRQ[Groq]:::ui
        XAI[xAI]:::ui
        LL["LiteLLM (optional)<br/>stack here for 100+ providers"]:::ui
    end

    PG[("Postgres<br/>events · shadow_pairs<br/>judge_scores · calibration_*")]:::store
    JW["judge-worker (Python)<br/>LLM ensemble · bias correction · τ-b calibration"]:::ctrl
    PC["policy-controller (Python)<br/>bandit refit · per-cluster step<br/>atomic policy JSON write"]:::ctrl

    Client -->|HTTPS| Route
    Route --> OAI
    Route --> ANT
    Route --> GRQ
    Route --> XAI
    Route -.OpenAI-compat.-> LL
    Route -- "decision events + shadow pairs" --> PG
    PG -- "unjudged pairs" --> JW
    JW -- "judge_scores" --> PG
    PG -- "cluster stats" --> PC
    PC -- "hot-reload policy" --> Route

    DA["dashboard-api (FastAPI)"]:::ui
    UI["Next.js dashboard<br/>Overview · Pareto · Clusters<br/>Activity · Health · /calibrate"]:::ui

    PG --> DA --> UI
    UI -- "calibration labels" --> DA --> PG
```

```
cascadia/
├── crates/proxy/                  Rust async proxy — hot path
├── crates/mock-upstream/          instant-response mock for benches
├── services/judge-worker/         Python — LLM-as-judge ensemble + calibration
├── services/policy-controller/    Python — bandit-style threshold refit
├── services/dashboard-api/        Python (FastAPI) — read-side API
├── dashboard/                     Next.js 14 — operator UI (auth, Pareto, clusters…)
├── deploy/{compose,helm}/         local dev + Kubernetes
├── bench/                         reproducible benchmark scripts
└── docs/                          architecture, design specs, methodology
```

Full design history and the §9 decisions log: [PLAN.md](PLAN.md). Eval methodology: [docs/blog/methodology.md](docs/blog/methodology.md).

## Status

Phases 1–7 are shipped: the Rust proxy, 4-provider adapters with tool-use + streaming parity and a mixed-provider Pareto cluster, the judge ensemble, the bandit policy-controller (self-tunes from cold start), the dashboard, and the benchmark harness. ~70% expensive-tier reduction on a synthetic uncertain/confident mix; `bench/scripts/pareto-frontier.sh` reproduces the chart.

**Honest gap (Phase 5 calibration):** a 30-pair real-human pilot ran (Cohen's κ improved v1→v2 −0.02 → +0.52 after a rubric rewrite). The 3-judge panel reproduced **verbosity bias** (Zheng et al. 2023): panel-vs-human τ-b ≈ 0, lifted to ≈ +0.20 by a concision penalty. The original "τ-b ≥ 0.7" target was naive — humans and panels measure different dimensions of quality. A production-grade claim needs the ~200-pair Prolific run (~$300, deferred). Full diagnosis in the [methodology blog](docs/blog/methodology.md).

## Building the human-rated calibration set

The full toolchain ships in-repo — an active-learning sampler, the `/calibrate` labeling UI (position randomization + attention checks), an aggregator that emits canonical JSONL, and an LLM-panel backstop. The end-to-end runbook (sample → label → aggregate → compute τ-b) is in **[`docs/calibration.md`](docs/calibration.md)**.

## License

MIT — see [LICENSE](LICENSE). Productizes ideas from FrugalGPT (Chen et al. 2023), RouteLLM (Ong et al. 2024), AutoMix (Madaan et al. 2023), and LLM-as-a-Judge (Zheng et al. 2023). The closed feedback loop — counterfactual shadow eval driving routing policy without a hand-maintained golden set — is what Cascadia adds.
