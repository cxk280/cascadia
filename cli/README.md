# `cascadia` — one-command launcher

The friendly front door to [Cascadia](https://github.com/cxk280/cascadia), the
self-hostable LLM cascade gateway. Wraps Docker Compose so you don't have to.

```bash
npx cascadia demo      # keyless, zero-cost demo of the live closed loop
npx cascadia up        # self-host against real providers (BYO keys)
npx cascadia down      # stop + wipe        (--live | --all)
npx cascadia logs      # tail logs          (--live)
npx cascadia doctor    # preflight checks
```

## `demo` — see the product in one command

Only needs **Docker** (and Node, for `npx`). Brings up the whole stack —
proxy, dashboard, judge, controller, Postgres — pointed at an in-process **mock
upstream**, so there are **no API keys and no cost**. It then drives a little
traffic and opens a dashboard at `http://localhost:3000` (login gate disabled).

The closed loop is real: the judge scores shadow pairs and the policy controller
refits per-cluster thresholds every ~30s, which the proxy hot-reloads via its
Postgres policy store. Watch the Pareto chart and thresholds move on their own.

First run builds images from source (a few minutes); they're cached after.

Flags: `--no-build`, `--no-traffic`, `--traffic N`.

## `up` — self-host for real

Prompts for an OpenAI key (cascade tiers) and an Anthropic key (cross-family
judge), or reads them from the environment, and runs the same stack against real
providers. **This spends real API budget.** Keys are passed to the containers
in memory, not written to disk.

## How it finds the source

The launcher orchestrates the compose files + Dockerfiles in the Cascadia repo.
It uses, in order: `$CASCADIA_HOME` → a checkout it's running inside → a shallow
`git clone` into `~/.cascadia/checkout` (override the URL with `$CASCADIA_REPO`).

## Requirements

- Docker (with the Compose v2 plugin) and a running daemon
- Node ≥ 18
- git (only for the cold `npx` clone path)

Run `npx cascadia doctor` to verify all of the above.
