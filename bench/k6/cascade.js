// k6 cascade bench. Fires a mix of "easy", "long", and "uncertain" prompts
// so the Phase-2 cascade exercises both paths (cheap-only and escalate).
// After the run, query Postgres with bench/scripts/cascade-report.sh for the
// per-model cost report.
//
// Setup:
//   # Postgres + mock + proxy (see bench/README.md)
//   $ k6 run bench/k6/cascade.js

import http from 'k6/http';
import { check } from 'k6';
import { SharedArray } from 'k6/data';

const baseUrl  = __ENV.K6_BASE_URL || 'http://127.0.0.1:18080';
const duration = __ENV.K6_DURATION || '20s';
const rps      = Number(__ENV.K6_RPS || 50);

export const options = {
  scenarios: {
    cascade: {
      executor: 'constant-arrival-rate',
      rate: rps,
      timeUnit: '1s',
      duration: duration,
      preAllocatedVUs: 50,
      maxVUs: 200,
    },
  },
  thresholds: {
    'checks': ['rate>0.99'],
  },
};

const prompts = new SharedArray('prompts', () => [
  // Easy → confident short cheap response → cheap-only path.
  'What is 2 + 2?',
  'Capital of Norway?',
  'Define photosynthesis briefly.',
  // Long → padded but confident → cheap-only path most of the time.
  'Give me a long but confident explanation of how TCP congestion control works.',
  'Provide a long technical summary of the CAP theorem.',
  // Uncertain → hedge-heavy response → cascade escalates.
  'Answer this uncertain edge case about Postgres MVCC.',
  'What is the uncertain behavior when you do X under Y?',
  'Explain this uncertain interaction in distributed systems.',
]);

export default function () {
  const prompt = prompts[Math.floor(Math.random() * prompts.length)];
  const body = JSON.stringify({
    model: 'gpt-4o-mini',
    messages: [{ role: 'user', content: prompt }],
  });
  const res = http.post(`${baseUrl}/v1/chat/completions`, body, {
    headers: { 'Content-Type': 'application/json' },
    tags: { endpoint: 'cascade' },
  });
  check(res, { 'status is 200': r => r.status === 200 });
}
