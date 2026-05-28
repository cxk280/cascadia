# Cascadia benchmarks

Reproducible scripts that produce the numbers in the README's headline chart.

## Latency: proxy overhead

`k6/proxy-overhead.js` measures the latency Cascadia adds on top of an instant-response upstream.
The Phase-1 acceptance criterion is **P99 < 2 ms at 1k QPS**.

### Setup

```bash
# Terminal 1 — start the instant-response mock upstream (port 18081)
$ cargo run -p cascadia-mock-upstream --release

# Terminal 2 — start the proxy, pointed at the mock (port 18080)
$ CASCADIA_OPENAI_API_KEY=anything \
  CASCADIA_OPENAI_BASE_URL=http://127.0.0.1:18081 \
  CASCADIA_LISTEN_ADDR=127.0.0.1:18080 \
  cargo run -p cascadia-proxy --release

# Terminal 3 — run k6
$ k6 run bench/k6/proxy-overhead.js
```

Tune via env vars: `K6_RPS=1000 K6_DURATION=30s K6_BASE_URL=http://127.0.0.1:18080`.

### What the thresholds enforce

```
http_req_duration{endpoint:chat}: p(50)<0.5ms  p(95)<1.5ms  p(99)<2ms
checks: rate>0.999
```

These thresholds are gates — k6 exits non-zero if any P/check fails.

## Quality / Pareto

Two scripts produce the README's per-cluster operating-point chart and the `/pareto`
dashboard view. Both write to `shadow_pairs.ensemble_score` — the same bias-corrected
signal the dashboard and policy controller read.

- **`scripts/multi-provider-pareto.sh`** — *synthetic, free.* Drives a mock upstream and
  **injects** constant per-cluster judge scores. Reproduces the demo chart in ~15s with
  no API keys. Use it for the deterministic README screenshot.

- **`scripts/mtbench-humaneval.sh`** — *real, paid.* Pulls the public MT-Bench (80) +
  HumanEval (164) prompt sets, drives them through the learned cascade against **real
  providers**, scores the shadow pairs with the **real bias-corrected judge ensemble**
  (the poller, which persists `ensemble_score`), refits the policy, and reports measured
  per-cluster operating points plus the §7 headline (cost reduction at quality). The
  best-tier-everywhere baseline is computed analytically (every request to the expensive
  tier is cost = 1.0), so there is no second paid arm. These are the honest numbers; they
  are **not** re-tuned to hit a round target. A fuller §7 three-arm served-response
  quality comparison is the documented next step on top of these operating points.

  ```bash
  # full run (spends real tokens):
  CASCADIA_OPENAI_API_KEY=sk-... CASCADIA_ANTHROPIC_API_KEY=sk-ant-... \
    bench/scripts/mtbench-humaneval.sh

  # cheap iteration smoke (20 + 20 prompts):
  MTBENCH_N=20 HUMANEVAL_N=20 CASCADIA_OPENAI_API_KEY=sk-... \
    bench/scripts/mtbench-humaneval.sh
  ```

  Requires the `judge-worker` and `policy-controller` venvs and a migrated Postgres.
  Outputs `/tmp/cascadia-mtbench-humaneval.json` (machine-readable points). An Anthropic
  key additionally enables the cross-provider mixed cluster (haiku cheap → gpt-4o expensive).

### Future benchmarks

- `k6/cascade.js` — Phase 2: measures cost savings on a synthetic cascade workload.
