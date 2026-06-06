# cascadia-policy-controller

Periodic batch job that reads recent judge_scores from Postgres, refits the
per-cluster cascade threshold, and writes a policy JSON that the Rust proxy
picks up via its file watcher.

```bash
$ pip install -e .
$ CASCADIA_DATABASE_URL=postgres://… \
  CASCADIA_POLICY_FILE=/etc/cascadia/policy.json \
  cascadia-policy-controller --once
```

The controller's update rule is intentionally crude (one knob, threshold; one
step size; bounded range). Phase 5 swaps it for a richer UCB-style update
that also learns shadow_rate and per-model preferences.

## Why a separate service

The Rust proxy needs to stay on the hot path. Policy reasoning happens here,
out of process, on a periodic cadence (cron / k8s CronJob / `--loop`).

## Design (substitution surfaces)

- `storage.py` is the substitution surface for reading shadow data. Today
  it's asyncpg; tomorrow it could be a BigQuery exporter or a S3 snapshot
  reader. The controller never imports asyncpg directly.
- `writer.py` is the substitution surface for emitting policies. Today a JSON
  file; tomorrow a Consul KV or a Postgres "policy" table the proxy reads on
  startup.
- `controller.py` is pure logic — no I/O. Easy to unit-test.
- `cli.py` is the only place that wires concrete implementations.
