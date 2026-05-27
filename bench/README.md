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

### Future benchmarks

- `k6/cascade.js` — Phase 2: measures cost savings on a synthetic cascade workload.
- `quality.py` — Phase 3+: replays MT-Bench / HumanEval against the proxy, computes judge ensemble scores, writes `bench/out/report.html`.
