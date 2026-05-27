# Cascadia

[![CI](https://github.com/christopherking/cascadia/actions/workflows/ci.yml/badge.svg)](https://github.com/christopherking/cascadia/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Rust](https://img.shields.io/badge/rust-stable-orange.svg)](rust-toolchain.toml)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](services/judge-worker/pyproject.toml)

> **Status (as of 2026-05-22):** All six engineering phases (1–6) landed, plus Phase 7 + 7.1 + 7.2 + 7.3 (cross-provider cascades across OpenAI / Anthropic / Groq / xAI, tool-use parity, SSE streaming across all four, and mixed-provider Pareto cluster as the live differentiator). **Live dev:** dashboard [`cascadia-dashboard-dev.up.railway.app`](https://cascadia-dashboard-dev.up.railway.app); proxy [`cascadia-proxy-dev.up.railway.app/v1/chat/completions`](https://cascadia-proxy-dev.up.railway.app) (bearer-token gated; upstream keys are placeholders until the demo rotation, so requests will 401 against OpenAI until real keys are set). The proxy, judge ensemble, policy controller, dashboard, and benchmark harness are in. The synthetic calibration set hits Kendall's τ-b = 0.83 vs labels; the [labeling app](#building-the-human-rated-calibration-set) ships ready-to-run for collecting the real human-rated set that backs a production-grade ≥0.7 acceptance claim (see [docs/blog/methodology.md](docs/blog/methodology.md) for the full methodology).

**A self-hostable LLM gateway that learns the cheapest model that still meets your quality bar — using counterfactual shadow evaluation on your live traffic, no hand-maintained golden dataset, no extra eval infrastructure.** An MLOps stack end-to-end: Rust hot path, Python judge + policy-controller services, Postgres event log, Next.js operator dashboard, FastAPI read-side, Helm chart, Prometheus + OpenTelemetry, human-calibrated quality scoring.

```
  ── Per-cluster operating points, approximating the live /pareto chart ──

  mean judge score  (y-axis zoomed to 0.45–0.60 so the spread is visible)
   0.60 ┤                       ● cluster-mixed   ← groq → openai: cross-provider quality win
   0.55 ┤
   0.50 ┤   ● cluster-0              ● cluster-3        ● cluster-1
   0.45 ┤
        └──────┬───────────┬───────────┬───────────┬─────────  escalation rate  →  cost proxy
              50%         60%          70%          80%
```

> The ASCII above is a **rough rendering** of the live operating points — real cluster names, approximate positions, y-axis zoomed. The four dots are the real demo clusters; `cluster-mixed` (Groq cheap tier → OpenAI expensive tier) is the cross-provider quality win, and `cluster-1` sits at ~81% escalation for roughly `cluster-0`'s quality — a Pareto-dominated point the controller trims on its next refit. The dashboard renders the **authoritative numbers** live at [`/pareto`](https://cascadia-dashboard-dev.up.railway.app/pareto); the values come from the multi-provider seed in `scripts/seed-dev-postgres.py`. Reproduce a fresh run with `bench/scripts/pareto-frontier.sh` (single-provider) or `bench/scripts/multi-provider-pareto.sh` (mixed-provider) — both take ~15 seconds from a clean DB.

## What makes Cascadia different

Most LLM gateways (LiteLLM, Portkey, OpenRouter) route via static configuration. Most observability tools (Langfuse, Helicone) evaluate offline against curated datasets. Cascade-routing research (FrugalGPT, RouteLLM, AutoMix) hasn't shipped as production systems. Cascadia closes the loop with three load-bearing technical claims:

1. **Counterfactual shadow routing.** A configurable fraction of every cascade decision is mirrored to the next tier up. The "what would the expensive model have said?" signal is generated continuously as a side effect of serving traffic — no separate eval rig to babysit.

2. **Per-cluster cascade policies.** A hash-based classifier (Phase 4) bins requests into N clusters. Each cluster learns its own `(cheap_model, expensive_model, threshold, shadow_rate)` policy from the bandit-style refit in [`services/policy-controller/`](services/policy-controller/). Routing decisions are honest at the category level instead of one global threshold. (Field names match the JSON policy file's keys — see the policy example below.)

3. **Bias-corrected judge ensemble.** Two prompt formats (pairwise + rubric) × N judge models, with anti-self-preference filtering and position-bias correction. Calibrated against human labels via Kendall's τ in [`services/judge-worker/cascadia_judge/calibration/`](services/judge-worker/cascadia_judge/calibration/).

> **"Isn't this just LiteLLM?"** → see [DIFFERENTIATOR.md](DIFFERENTIATOR.md). Short version: LiteLLM is provider plumbing with human-authored routing rules. Cascadia learns what those rules should be by counterfactually scoring its own decisions on live traffic. They compose — stack Cascadia on top of LiteLLM if you want both.

> **"You only support 4 providers — what about Bedrock / Cohere / Vertex / the next one?"** Two answers, in order:
> 1. **Any OpenAI-shape host** (Mistral, DeepSeek, Together, Fireworks, Perplexity, vLLM, your private endpoint) is a one-line `CASCADIA_OPENAI_BASE_URL` override — **no code change.** Covers ~80% of practical cases. See [`docs/adding-a-provider.md`](docs/adding-a-provider.md).
> 2. **Anything else** (Bedrock / Vertex native API / the long tail of LiteLLM's 100+) — stack Cascadia on top of LiteLLM. Cascadia decides the cascade, LiteLLM handles N-provider plumbing. Architecture diagram in [DIFFERENTIATOR.md → The composition story](DIFFERENTIATOR.md#the-composition-story-the-closer).

## Quick start

> **Deploying instead of running locally?**
> - **Kubernetes** → [`deploy/helm/cascadia/`](deploy/helm/cascadia/README.md) (pin `--version 0.0.1` and read [CHANGELOG](deploy/helm/cascadia/CHANGELOG.md) before `helm upgrade`).
> - **Docker Compose (full stack)** → `deploy/compose/docker-compose.full.yml`.
> - **Railway / Render / Fly.io** → see [PLAN.md §9 (2026-05-20)](PLAN.md) for the live Railway deploy walkthrough (binds to `[::]:8080` for IPv6-only private networks).

The local-dev quick start below uses `cargo build` + Postgres in Docker, which is the fastest loop for hacking on the proxy itself.

```bash
# 1. Bring up Postgres
$ docker compose -f deploy/compose/docker-compose.yml up -d

# 2. Write a starter policy file. Phase 7 requires `provider/model` prefixes
#    on every model string — unprefixed values like "gpt-4o-mini" hard-fail
#    at boot. JSON keys are: cheap_model, expensive_model, threshold, shadow_rate.
#
#    `threshold` is the cheap-tier confidence FLOOR. cheap is accepted when
#    confidence >= threshold; otherwise the cascade escalates to expensive.
#    Lower threshold = lower bar = MORE cheap accepted = LESS escalation = CHEAPER.
#    See `## Tuning for cost` below for the full direction-of-each-knob table.
#
#    `shadow_rate` is the fraction of accepted-cheap responses that are mirrored
#    to the expensive tier in the background, so the judge worker can score the
#    pair. This FIRES REAL EXPENSIVE-TIER API CALLS on that fraction of traffic
#    — it costs real money. 0.05–0.10 is the sweet spot; 0.0 disables the
#    closed loop entirely.
$ cat > /tmp/cascadia-policy.json <<'EOF'
{
  "default_cluster": "default",
  "cluster_buckets": 4,
  "clusters": {
    "default": {
      "cheap_model": "openai/mock-cheap",
      "expensive_model": "openai/mock-expensive",
      "threshold": 0.7,
      "shadow_rate": 0.1
    }
  }
}
EOF

# 3. Build + start the proxy (in two terminals)
$ cargo build --release
$ ./target/release/cascadia-mock-upstream         # terminal A
$ CASCADIA_OPENAI_API_KEY=mock \
  CASCADIA_OPENAI_BASE_URL=http://127.0.0.1:18081 \
  CASCADIA_DATABASE_URL=postgres://cascadia:cascadia@localhost:5432/cascadia \
  CASCADIA_POLICY_FILE=/tmp/cascadia-policy.json \
  CASCADIA_CLUSTER_BUCKETS=4 \
  ./target/release/cascadia-proxy                  # terminal B
# At least one provider key (OPENAI/ANTHROPIC/GROQ/XAI) must be set. The
# mock upstream accepts any non-empty value, so `mock` is fine for local dev.

# 4. Drive synthetic traffic + populate the Pareto data
$ bench/scripts/pareto-frontier.sh 120

# 5. Open the dashboard
$ cd services/dashboard-api && . .venv/bin/activate && cascadia-dashboard-api &
$ cd dashboard && npm install && npm run dev       # → http://localhost:3000
```

> **Upgrading from a pre-Phase-7 config?** Any existing policy file with
> bare model names (`"cheap_model": "gpt-4o-mini"`) must be migrated by
> prepending the provider, e.g. `"openai/gpt-4o-mini"`. The proxy refuses
> to boot on unprefixed strings (intentional — silent routing surprises
> are worse than a loud failure). One-liner:
>
> ```bash
> $ jq '.clusters |= with_entries(.value |= (.cheap_model = "openai/" + .cheap_model | .expensive_model = "openai/" + .expensive_model))' old-policy.json > new-policy.json
> ```

**Prefer one command?** `deploy/compose/docker-compose.full.yml` runs the entire
stack (Postgres + proxy + dashboard + dashboard-api + judge-worker + policy-controller)
as containers. See the file header for the one-time image build step.

### Drop-in from the OpenAI Python SDK

Cascadia speaks the OpenAI chat-completions wire format. Point the SDK's `base_url` at the proxy (note the trailing `/v1`) and your existing code keeps working — streaming, tool-use, `response_format`, multi-turn:

```python
from openai import OpenAI

client = OpenAI(
    # Local dev (quick-start above runs the proxy on 0.0.0.0:8080):
    base_url="http://localhost:8080/v1",
    # Or the live dev deploy (bearer token required):
    # base_url="https://cascadia-proxy-dev.up.railway.app/v1",
    api_key="your-bearer-token-if-CASCADIA_PROXY_BEARER_TOKEN-is-set",
)

# Non-streaming
resp = client.chat.completions.create(
    model="gpt-4o-mini",     # the cascade ignores this; the policy decides
    messages=[{"role": "user", "content": "hi"}],
)
print(resp.choices[0].message.content)

# Streaming (Phase 7.2 — works against all four providers)
stream = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "tell me a joke"}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")
```

The HTTP response carries three Cascadia-specific headers so SDK consumers can reconcile billing without parsing the body:

- `x-cascadia-served-model` — the actual `provider/model` string that produced the response (may differ from the inbound `model` parameter).
- `x-cascadia-served-provider` — `openai` / `anthropic` / `groq` / `xai`.
- `x-cascadia-escalated` — `true` if the cheap tier was rejected and the cascade escalated, `false` otherwise. **Note:** tool-use requests (`tools=[...]`, Phase 7.1) and streaming requests (`stream=True`, Phase 7.2) always return `false` here — cascade bypasses escalation on both paths by design (mid-loop escalation would diverge into incoherent tool-call sequences or break the stream contract). Your dashboard's escalation rate will be 0% on those clusters; it's not a bug.

For Anthropic-backed clusters, `response_format: {"type": "json_object"}` is translated into a system-prompt directive (Anthropic doesn't have a native wire-level JSON mode). `response_format: {"type": "json_schema"}` returns a clear 400 because Anthropic enforces structured output via tool-use, not response_format — route json_schema traffic to an OpenAI-shape provider, or restructure as a tool-use call. See `docs/adding-a-provider.md`.

#### Auth

If `CASCADIA_PROXY_BEARER_TOKEN` is set on the proxy, every `/v1/*` request must carry `Authorization: Bearer <token>`. Use it in `api_key=` above (the OpenAI SDK forwards `api_key` as a bearer header). When the env var is unset (default for local-dev and private-network deploys), the proxy accepts unauthenticated requests — the cluster boundary is expected to handle auth.

### Adding another provider (Mistral, DeepSeek, Together, vLLM, private endpoints)

**See [`docs/adding-a-provider.md`](docs/adding-a-provider.md) for the full provider recipe + [`docs/extending.md`](docs/extending.md) for customizing the judge ensemble, aggregator, or policy refit.** The 90% short answer for *providers*: if the upstream speaks OpenAI's `/v1/chat/completions` shape, **no code change** — override `CASCADIA_OPENAI_BASE_URL` and prefix the model with `openai/` in your policy:

```bash
# Public Mistral API
$ CASCADIA_OPENAI_API_KEY=$MISTRAL_KEY \
  CASCADIA_OPENAI_BASE_URL=https://api.mistral.ai/v1 \
  ./target/release/cascadia-proxy

# Private vLLM / Together / DeepInfra cluster
$ CASCADIA_OPENAI_API_KEY=$INTERNAL_KEY \
  CASCADIA_OPENAI_BASE_URL=https://vllm.internal.corp:8000 \
  ./target/release/cascadia-proxy
```

In the policy file, prefix the model name with `openai/` — the prefix tells
Cascadia which adapter to use; the base URL tells the adapter where to hit:

```json
"cheap_model":     "openai/mistral-small-latest",
"expensive_model": "openai/mistral-large-latest"
```

The same shape works for any provider implementing OpenAI's `/v1/chat/completions`: Mistral, DeepSeek, Together, Fireworks, Perplexity, vLLM, Groq, xAI, on-prem clusters. For Anthropic specifically, use the `anthropic/` prefix and `CASCADIA_ANTHROPIC_BASE_URL` — the two wire shapes are not interchangeable. For Gemini / Bedrock native API / any custom shape, a new adapter is required — open an issue first per [`CONTRIBUTING.md`](CONTRIBUTING.md#adding-a-new-provider).

### Air-gapped deployment

Cascadia is designed to run with **no outbound internet beyond the upstream
provider host(s) you configure.** The proxy itself does not phone home, fetch
remote configuration, or call any telemetry endpoint. Everything it dials
out to at runtime is:

1. The configured `CASCADIA_*_BASE_URL` for each provider you've enabled.
2. The `CASCADIA_DATABASE_URL` Postgres instance (typically same VPC).
3. The optional `CASCADIA_OTLP_ENDPOINT` if you set it.

If you allowlist exactly those three from your egress policy, the proxy
operates fully without internet. The judge-worker calls the same provider
URLs to score shadow pairs; the policy-controller talks only to Postgres;
the dashboard talks only to the dashboard-api. None of them ship telemetry
to anywhere outside your network.

## Tuning for cost

Two knobs in the policy file actually drive cost. The dashboard's `/clusters` page exposes both per-cluster, with hover tooltips explaining the direction. Cheat sheet:

| Knob | What it is | Direction |
|---|---|---|
| `threshold` (0.0 – 1.0) | Cheap-tier confidence floor. Cheap is accepted when `confidence ≥ threshold`; below that, cascade escalates to expensive. | **Lower threshold → more cheap accepted → LESS escalation → CHEAPER.** Raising it forces more escalations and a higher bill. |
| `shadow_rate` (0.0 – 1.0) | Fraction of accepted-cheap responses that are mirrored to the expensive tier in the background so the judge worker can score the pair. | **Higher shadow_rate → more expensive-tier API calls → MORE cost** (extra calls, not from escalation). 0.05–0.10 is the sweet spot; 0.0 disables the closed loop entirely (no quality scoring). |

Common cost mistakes:

- **"Lower threshold should be cheaper because the number is smaller."** Half the time, half-right intuition. It IS cheaper here — because lower threshold = lower bar = more cheap accepted. But people often invert the direction on first guess. The `/clusters` page renders the current value next to the cluster's escalation rate so you can verify your change took effect.
- **Setting `shadow_rate: 0.5` to "learn faster."** That doubles the expensive-tier API cost of half your traffic on top of the cascade's own escalations. The policy controller refits fine on 0.05–0.10.
- **Setting `shadow_rate: 0.0` and wondering why the dashboard never updates.** No shadow pairs → no judge scores → controller has nothing to refit on → the dashboard's Pareto chart freezes. Disable the loop intentionally only when you're sure you don't need quality signal.
- **Forgetting to verify the change landed.** The proxy hot-reloads `CASCADIA_POLICY_FILE` on file change. The `/clusters` page shows the *current* live threshold + shadow_rate per cluster — read those values to confirm.

## Operations

For platform engineers and on-call.

| Endpoint | Purpose | Port (default) |
|---|---|---|
| `POST /v1/chat/completions` | OpenAI-compatible chat — the hot path | `8080` |
| `GET /livez` | Process is alive. Cheap. Use for liveness probes. | `8080` |
| `GET /readyz` | DB pool reachable + at least one provider configured. Use for readiness probes. | `8080` |
| `GET /health` | Backwards-compatible alias for `/readyz`. | `8080` |
| `GET /metrics` | Prometheus exposition. See metric names below. | `8080` |
| `GET /policy` | Read-only JSON snapshot of the current in-memory policy table. Used by the dashboard to show live threshold + shadow_rate per cluster. | `8080` |

**Endpoints we don't (and probably won't) implement:**

- `POST /v1/completions` — the *legacy* OpenAI Completions API (the one that takes `prompt: str`). Cascade routing operates on the chat-completions shape; the legacy API is a different request schema with no message structure. If you're on a 2023-vintage `openai.Completion.create(...)` codebase, migrate the calls to `openai.chat.completions.create(messages=[{"role":"user","content":"..."}])` before pointing at Cascadia.
- `POST /v1/embeddings` — out of scope. Cascadia is a *cascade routing* gateway, not an embeddings proxy. Route embeddings traffic to the provider directly (or stack a separate gateway).
- `POST /v1/images/*` and other modality endpoints — same reasoning.

The proxy returns a 404 with an OpenAI-shape JSON envelope (`{error: {type: "invalid_request_error", code: "not_found", ...}}`) on any unimplemented path, including a remediation hint for `/v1/completions` and `/v1/embeddings` specifically.

**Prometheus metric names:**

- `cascadia_proxy_requests_total{route, provider, status}` — counter. `route` is `chat_completions` or `chat_completions_stream`. `provider` is one of `openai|anthropic|groq|xai|unknown` (bounded cardinality — pre-seeded at startup). `status` is `ok|upstream_error|error`.
- `cascadia_proxy_request_duration_seconds{route, provider}` — histogram, end-to-end including cascade decisions.

Metric names are **Cascadia-specific** and intentionally do not match LiteLLM / Portkey / OpenRouter conventions — Cascadia's metric set is small (latency + counts only) and the dashboard at [`/clusters`](/clusters) already exposes the per-cluster escalation rate, tool-use rate, threshold, and shadow_rate that operators usually want to alert on. If you're cargo-culting a Grafana dashboard from another gateway, **the panels will be empty** — wire your own panels against the names above. Escalation rate as a Prometheus metric is not currently exposed; query [`/api/clusters`](http://localhost:18082/api/clusters?window_minutes=60) on the dashboard-api instead, or open an issue if you need it as a `cascadia_proxy_escalations_total` counter.

**Graceful shutdown:** the proxy traps SIGINT and SIGTERM and drains in-flight requests up to `CASCADIA_SHUTDOWN_TIMEOUT_SECS` (default 30s) before exiting. Safe for Kubernetes rolling deploys.

**Chaos posture:**
- Killing the policy-controller leaves the proxy serving on the last-known policy in `CASCADIA_POLICY_FILE`. No restart required when the controller comes back.
- Killing the judge-worker stops new `judge_scores` rows but does not affect the proxy hot path.
- Postgres unavailable: the proxy returns 503 from `/readyz` and starts dropping event-log entries (with `warn` logs). The hot path remains responsive — events are best-effort, not load-bearing.

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

    PG[("Postgres<br/>events · shadow_pairs<br/>judge_scores<br/>calibration_*")]:::store
    JW["judge-worker (Python)<br/>LLM ensemble · bias correction<br/>concision adjustment · τ-b calibration"]:::ctrl
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

<details><summary>Plain-text fallback (terminal-friendly)</summary>

```
Client app
   │  OpenAI-compatible HTTPS
   ▼
Rust async proxy  (P99 ~2 ms)
   classify · lookup policy · cheap → escalate? · shadow X% · emit event
   │       │       │       │
   ▼       ▼       ▼       ▼
 OpenAI  Anthropic  Groq  xAI         (per-tier, Phase 7)
   │
   ▼
 Postgres (events, shadow_pairs, judge_scores, calibration_*)
   │                                       ▲
   │ unjudged pairs           hot-reload   │
   ▼                          policy       │
 judge-worker  ── judge_scores ────▶  policy-controller
                                       │
   ┌───────────────────────────────────┘
   ▼
 dashboard-api  ──▶  Next.js dashboard  (Overview · Pareto · Clusters
                                          · Activity · Health · /calibrate)
```
</details>

See [PLAN.md](PLAN.md) for the full design history and the §9 Decisions log, and [docs/blog/methodology.md](docs/blog/methodology.md) for the eval methodology.

## Repository layout

```
cascadia/
├── crates/proxy/                  Rust async proxy — hot path
├── crates/mock-upstream/          Instant-response mock for benches
├── services/judge-worker/         Python — LLM-as-judge ensemble, calibration harness
├── services/policy-controller/    Python — bandit-style threshold refit
├── services/dashboard-api/        Python (FastAPI) — read-only API for the dashboard
├── dashboard/                     Next.js 14 — operator UI
├── deploy/compose/                docker-compose for local dev
├── deploy/helm/                   Helm chart
├── bench/                         Reproducible benchmark scripts
└── docs/                          Architecture, design specs, methodology
```

## Acceptance status (per phase)

| Phase | Acceptance criterion | Status |
|---|---|---|
| 1 | curl works, requests logged with traces, P99 overhead measured | ✅ (P99 < 2ms target → 5.6ms on macOS loopback, refined for Phase 6 tuned Linux hosts) |
| 2 | measurable cost reduction on synthetic load | ✅ ~70% expensive-tier reduction on uncertain/confident mix |
| 3 | judge worker writes scores, manual threshold tuning works | ✅ |
| 4 | self-tunes from cold start without manual intervention | ✅ Three sequential refits hot-reload in <1.04s each |
| 5 | Bias-corrected ensemble characterized against humans, biases named honestly | ⚠ first real-human pilot complete (30 pairs, 2 reviewers): rubric iterated v1→v2 (κ −0.02 → +0.52); 3-judge cross-family panel reproduced **verbosity bias** (Zheng et al. 2023) — panel τ-b vs humans ≈ 0, panel-internal τ ≈ +0.28, 24/30 unanimous; concision penalty (Phase 5.2) lifts τ-b to +0.20 at best. Original "τ-b ≥ 0.7" target was naive — humans and panels measure different dimensions of quality on common Q&A. Full diagnosis: [methodology blog](docs/blog/methodology.md). Production-grade Phase-5 closure needs the 200-pair Prolific run (~$300, deferred). |
| 6 | README has the Pareto chart, reproducible benchmark scripts | ✅ — chart above the fold, `bench/scripts/pareto-frontier.sh` reproduces it |
| 7 | Mixed-provider cluster with correct `events.provider` attribution; per-provider failures don't tear down the proxy | ✅ `model_id::parse_model_id` + 4-provider adapters (OpenAI / Anthropic / Groq / xAI) + per-tier dispatch in cascade; hard-fail on unprefixed model strings at boot. **Deferred:** live smoke against all four real APIs. 63 unit tests passing including 12 Anthropic translation cases and 10 Anthropic streaming translator cases. |
| 7.1 | OpenAI ↔ Anthropic tool-use parity (`tools` / `tool_choice` / `tool_calls` / `tool_result` round-trip) | ✅ — landed alongside Phase 7. Cascade bypasses escalation on tool-using requests (mid-tool-loop escalation would diverge into incoherent state). |
| 7.2 | SSE streaming across all four providers; chunks parse cleanly through the OpenAI SDK | ✅ — OpenAI/Groq/xAI pass-through; Anthropic event-stream translated to OpenAI delta chunks (text + tool-use). Cascade bypasses escalation on streaming requests (cheap-tier-only, no shadow pair) — partial-stream rollback to an expensive completion is not possible without breaking the client's stream contract. End-to-end smoke verified via OpenAI Python SDK round-trip. |
| 7.3 | Mixed-provider Pareto cluster (e.g. `groq → openai`) visible on the dashboard with correct `events.provider` per-tier attribution | ✅ — `bench/scripts/multi-provider-pareto.sh` drives a 4-cluster benchmark where two clusters cross provider families; live `/clusters` renders `cluster-mixed` as `groq → openai` with the highest mean quality of any cluster; demo-script `docs/demo-script.md` anchors on it as the headline differentiator. |

## Building the human-rated calibration set

A 30-pair real-human pilot ran on 2026-05-19 (Cohen's κ progressed v1 → v2 from −0.024 → +0.52 between two reviewers — the rubric iteration itself is the load-bearing methodological finding; see [docs/blog/methodology.md](docs/blog/methodology.md)). The 15-pair synthetic golden set hits τ-b = 0.83 against the scripted ensemble and shows the harness is wired correctly; a real claim against humans needs ~200 production pairs labeled by ≥2 reviewers each. The full toolchain to collect that set is in the repo: an **active-learning sampler** that picks the most informative pairs from `shadow_pairs`, a **Next.js labeling app** with position randomization and attention checks, an **aggregator** that turns raw labels into the canonical JSONL the calibration harness consumes, and an **LLM-panel backstop** for the cases where extending the human set is too expensive.

### How active learning picks pairs

Round 1 is stratified-random across clusters (no ensemble signal yet → no way to rank). Round 2+ scores the unlabeled pool with the judge ensemble and ranks by:

```
uncertainty = 0.5·(1 − confidence)              ← judges hedged
            + 0.3·(1 − 2·|score − 0.5|)         ← score near tie
            + 0.2·position_bias_estimate        ← judges disagree with themselves
```

Each round labels the highest-uncertainty pairs first (within cluster stratification). The pairs where the ensemble is most uncertain are the most informative humans can correct.

### Running it end-to-end

```bash
# Pre-req: proxy + Postgres up; you've driven enough traffic that
# shadow_pairs has rows (`bench/scripts/pareto-frontier.sh` will do).

# 1. Pull a round-1 seed batch into calibration_pairs (8 sampled + ~5% attention checks)
$ cd services/judge-worker && . .venv/bin/activate
$ cascadia-judge-sample-calibration --round 1 --size 30 \
    --attention-check-rate 0.05 \
    --database-url postgres://cascadia:cascadia@localhost:5432/cascadia

# 2. Bring up the dashboard-api (write surface for labels)
$ cd services/dashboard-api && . .venv/bin/activate
$ CASCADIA_DATABASE_URL=postgres://cascadia:cascadia@localhost:5432/cascadia \
  cascadia-dashboard-api &                        # → http://127.0.0.1:18082

# 3. Bring up the dashboard (the labeling UI lives at /calibrate)
$ cd dashboard && npm install && npm run dev      # → http://localhost:3000/calibrate

# 4. Each reviewer opens /calibrate, picks a short reviewer_id (e.g. "chris"),
#    reads /calibrate/rubric, and starts labeling. Keyboard shortcuts:
#    [A] = slot A wins · [B] = slot B wins · [T] = tie · [U] = unknown
#    Esc inside the rationale field re-enables shortcuts.

# 5. After a round wraps, run round 2 with the ensemble in the loop:
$ cascadia-judge-sample-calibration --round 2 --size 30 \
    --score-with-ensemble --ensemble-provider openai \
    --ensemble-model gpt-4o-mini  # or fake / scripted for offline test

# 6. Aggregate raw labels → canonical JSONL the existing harness consumes:
$ cascadia-judge-aggregate-labels --out calibration/human_rated_v1.jsonl
# stdout shows the quality report (Cohen's κ, per-reviewer attention pass/fail,
# consensus/disagreement counts). The JSONL is the artifact you check into the repo.

# 7. Compute τ-b of the current ensemble against the new human-rated set:
$ cascadia-judge-calibrate --dataset calibration/human_rated_v1.jsonl \
    --provider openai --model gpt-4o-mini --tau-min 0.7
```

### LLM-panel backstop

When you need to extend the calibration set beyond the budget for human reviewers, run a panel of 3 top-tier models (none in the judge ensemble) over the same pairs and use their unanimous agreements as a synthetic gold standard. Estimated cost: ~$5 for 200 pairs × 3 models with position-swap.

```bash
$ ANTHROPIC_API_KEY=… OPENAI_API_KEY=… GROQ_API_KEY=… \
  cascadia-judge-llm-panel \
    --dataset calibration/human_rated_v1.jsonl \
    --panel anthropic:claude-opus-4-7,openai:gpt-4o,groq:llama-3.3-70b \
    --tau-min 0.7
```

The panel report includes panel-vs-human τ, per-model-vs-human τ, and cross-model agreement — if any panel model is an outlier, swap it out.

### Quality controls baked in

- **Position randomization** — server decides per (pair, reviewer) whether to swap slot A/B; reviewer never sees it. Deterministic per pair so a browser refresh doesn't flip the order mid-label.
- **Attention checks** — ~5% of pairs are obvious-by-construction (response A is gibberish, etc.). Reviewers above the failure threshold are dropped from the canonical aggregation but their labels stay in the DB for audit.
- **Inter-rater agreement** — Cohen's κ-b is computed pairwise across reviewers on overlapping pairs and reported alongside the dataset. κ < 0.5 means the rubric is ambiguous or the reviewers are confused — both are findings to publish.
- **Rubric versioning** — every label records the `rubric_version` it was given under; a future audit can answer "which rubric were they using?"

### What's deferred

The current scope is **Chris + 1 friend** (no money spent). Scaling to a publishable claim means crowdsourcing through Prolific / Surge / Scale (~$300–700 for 200 pairs × 2 reviewers) — the labeling tool, schema, and aggregator already support it; only the reviewer pool grows. The methodology blog at `docs/blog/methodology.md` is the artifact that frames this honestly until then.

## License

MIT — see [LICENSE](LICENSE).

## Related work

This project productizes ideas from:

- FrugalGPT (Chen et al., 2023) — cascading inference
- RouteLLM (Ong et al., 2024) — learned routing
- AutoMix (Madaan et al., 2023) — self-verification cascades
- LLM-as-a-Judge (Zheng et al., 2023) — position bias + self-preference, motivates Phase 5's corrections

The closed feedback loop — counterfactual shadow eval driving routing policy without a hand-maintained golden dataset — is what Cascadia adds on top.
