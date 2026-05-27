// k6 latency bench for Cascadia proxy overhead.
//
// Measures the latency Cascadia adds on top of an instant-response upstream.
// The Phase-1 acceptance criterion is P99 < 2 ms at 1k QPS — at that point
// the proxy is dominated by network I/O, not by routing or bookkeeping.
//
// How to run (from repo root):
//
//   # 1. Start the mock upstream (port 18081)
//   $ cargo run -p cascadia-mock-upstream --release &
//
//   # 2. Start the proxy pointed at the mock (port 18080)
//   $ CASCADIA_OPENAI_API_KEY=anything \
//     CASCADIA_OPENAI_BASE_URL=http://127.0.0.1:18081 \
//     CASCADIA_LISTEN_ADDR=127.0.0.1:18080 \
//     cargo run -p cascadia-proxy --release &
//
//   # 3. Run k6
//   $ k6 run bench/k6/proxy-overhead.js
//
// Tune RPS via env vars:
//   K6_RPS=1000 K6_DURATION=30s k6 run bench/k6/proxy-overhead.js

import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';

const targetRps = Number(__ENV.K6_RPS || 1000);
const duration  = __ENV.K6_DURATION || '30s';
const baseUrl   = __ENV.K6_BASE_URL || 'http://127.0.0.1:18080';

// Targets:
// - Production (tuned Linux + low-jitter NICs): P50<0.5ms, P95<1.5ms, P99<2ms
// - Local dev (macOS loopback, dev hardware): looser tail — see thresholds below.
// The proxy's routing overhead is bounded; the tail latency you see on a Mac
// is dominated by OS scheduling jitter, not by Cascadia's hot path.
export const options = {
  scenarios: {
    constant_rps: {
      executor: 'constant-arrival-rate',
      rate: targetRps,
      timeUnit: '1s',
      duration: duration,
      preAllocatedVUs: Math.max(200, Math.floor(targetRps / 2)),
      maxVUs:          Math.max(500, targetRps),
    },
  },
  thresholds: {
    // Local-dev gates. Override via env if you're on prod hardware.
    'http_req_duration{endpoint:chat}': [
      `p(50)<${__ENV.K6_P50_MS || 2}`,
      `p(95)<${__ENV.K6_P95_MS || 6}`,
      `p(99)<${__ENV.K6_P99_MS || 12}`,
    ],
    'checks': ['rate>0.99'],
  },
  noConnectionReuse: false,
  discardResponseBodies: true,
};

const body = JSON.stringify({
  model: 'gpt-4o-mini',
  messages: [{ role: 'user', content: 'hi' }],
});

const params = {
  headers: { 'Content-Type': 'application/json' },
  tags: { endpoint: 'chat' },
};

export default function () {
  const res = http.post(`${baseUrl}/v1/chat/completions`, body, params);
  check(res, {
    'status is 200': r => r.status === 200,
  });
}
