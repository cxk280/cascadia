# `cascadia` — one-command launcher

The friendly front door to [Cascadia](https://github.com/cxk280/cascadia), the
self-hostable LLM cascade gateway. Wraps Docker Compose so you don't have to.

```bash
npx cascadia-gateway demo      # keyless, zero-cost demo of the live closed loop
npx cascadia-gateway up        # self-host against real providers (BYO keys)
npx cascadia-gateway down      # stop + wipe        (--live | --all)
npx cascadia-gateway logs      # tail logs          (--live)
npx cascadia-gateway doctor    # preflight checks
```

## `demo` — see the product in one command

Only needs **Docker** (and Node, for `npx`). Brings up the whole stack —
proxy, dashboard, judge, controller, Postgres — pointed at an in-process **mock
upstream**, so there are **no API keys and no cost**. It then drives a little
traffic and opens a dashboard at `http://localhost:3000`. Log in with the demo
account **`foo@bar.com` / `admin123`** (seeded only in the demo — gated behind
`CASCADIA_DEMO=true`, so it can never exist in a real deployment).

The closed loop is real: the judge scores shadow pairs and the policy controller
refits per-cluster thresholds every ~30s, which the proxy hot-reloads via its
Postgres policy store. Watch the Pareto chart and thresholds move on their own.

First run **pulls six prebuilt images** from `ghcr.io/cxk280` (no git, no compile),
then starts instantly; cached after. The image tag is **tied to this package's
version** — `cascadia-gateway@x.y.z` pulls `vx.y.z` images — so you always know
exactly which images a launcher version runs. Override the source with
`CASCADIA_REGISTRY` (registry prefix, trailing slash) and `CASCADIA_TAG`.

Flags:
- `--build` — build images from source instead of pulling (needs git + a checkout).
- `--traffic N` / `--no-traffic` — drive (or skip) live mock traffic.

## `up` — self-host for real

Prompts for an OpenAI key (cascade tiers) and an Anthropic key (cross-family
judge), or reads them from the environment, and runs the same stack against real
providers. **This spends real API budget.** Keys are passed to the containers
in memory, not written to disk.

## How it finds the compose file

The default `demo` runs the demo compose file **bundled inside this package** and
pulls prebuilt images — no source tree required. The build-from-source paths
(`demo --build`, `up`) need the Cascadia repo, resolved in order: `$CASCADIA_HOME`
→ a checkout it's running inside → a shallow `git clone` into `~/.cascadia/checkout`
(override the URL with `$CASCADIA_REPO`).

## Requirements

- Docker (with the Compose v2 plugin) and a running daemon
- Node ≥ 18
- git — only for `demo --build` and `up` (building from source); **not** for the
  default pull-based demo

## Editions

The full closed loop is **MIT-licensed and free** — the cascade proxy, judge
ensemble, self-tuning controller, and dashboard all run and self-tune cost vs.
quality with no human in the loop. A future paid tier adds human-grounded
(Prolific) judge calibration; the open-source panel stays fully functional. See
the [main README](https://github.com/cxk280/cascadia#free-and-open-source--and-a-future-paid-tier).

Run `npx cascadia-gateway doctor` to verify all of the above.
