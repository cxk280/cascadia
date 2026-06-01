# Dogfooding Cascadia — first non-synthetic user

> Resolves PLAN §8's open question ("is there a friendly real workload to be the first
> non-synthetic user?") and validates the two §7 criteria synthetic load can't:
> **cold-start convergence** (< 24h to stable routing) and **chaos resilience** (proxy
> keeps serving on last-known policy when the controller + judge are down).

This is the one task in `NEXT_STEPS.md` whose core action is **yours**: pointing your own
traffic at the live proxy. Everything else here — the config, what to watch, the chaos
drill — is built and ready.

## 1. Point real traffic at the proxy

Cascadia speaks the **OpenAI** chat-completions shape on the inbound side
(`POST /v1/chat/completions`). Any OpenAI-API client works by overriding three things:

```bash
export OPENAI_BASE_URL="http://localhost:8080/v1"
export OPENAI_API_KEY="<CASCADIA_PROXY_BEARER_TOKEN>"   # the proxy's bearer, not a provider key
# then call with model "auto" — the policy picks cheap-vs-expensive per cluster:
curl "$OPENAI_BASE_URL/chat/completions" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"auto","messages":[{"role":"user","content":"hello"}]}'
```

Works out of the box with: the OpenAI SDK (set `base_url` + `api_key`), `aider`
(`--openai-api-base`), Continue/Cursor custom-OpenAI providers, LangChain
(`ChatOpenAI(base_url=...)`), and any script you already point at OpenAI.

> **Claude Code caveat.** Claude Code talks the **Anthropic Messages** API
> (`/v1/messages`), which Cascadia does **not** expose inbound — Cascadia is
> OpenAI-inbound (it uses the Anthropic adapter only for the *upstream* leg). So you
> can't set `ANTHROPIC_BASE_URL=…cascadia…` and have Claude Code route through it
> directly. To dogfood Claude-Code-style coding traffic, point an OpenAI-API coding
> tool (aider, Continue, an OpenAI-SDK script) at Cascadia instead. (An Anthropic-shape
> inbound endpoint would be a real feature — open an issue if you want it.)

Keep `model: "auto"` so the cascade decides; a pinned `provider/model` bypasses routing.

## 2. Watch the loop close (cold-start convergence)

With real traffic flowing, watch the dashboard converge — the §7 target is **stable
routing within 24h**:

1. **Clusters form.** [`/clusters`](http://localhost:3000/clusters)
   — the hash classifier bins your prompts into real semantic categories. Early on the
   counts are lumpy; they stabilize as volume grows.
2. **Shadow pairs get scored.** The judge worker scores the shadowed pairs; `mean judge
   score` and `judge sample size` climb on [`/`](http://localhost:3000/).
3. **The controller refits.** Each refit moves the per-cluster `threshold` toward the
   cheapest tier that still clears your quality bar (it tunes on the bias-corrected
   `shadow_pairs.ensemble_score`, EC-O1).
4. **The Pareto points move.** On
   [`/pareto`](http://localhost:3000/pareto), drag the slider to
   project a cost for a target quality, and watch the back-test coverage rise as the
   points become a real frontier instead of a sparse scatter.

"Converged" = the refit stops materially moving thresholds between cycles and the
clusters are stable — the routing has learned your workload.

## 3. Run the chaos drill (resilience)

`bench/scripts/chaos-drill.sh` proves the §7 resilience claim: the proxy keeps serving on
its last-known policy with the controller **and** judge dead. It's free (mock upstream,
no keys) and deterministic:

```bash
# quick (~30s):
CASCADIA_DATABASE_URL=postgres://cascadia:cascadia@localhost:5432/cascadia \
  bench/scripts/chaos-drill.sh

# the real soak (one hour, as §7 specifies):
CHAOS_SECONDS=3600 CASCADIA_DATABASE_URL=… bench/scripts/chaos-drill.sh
```

It asserts: every request returns 200 during the outage, `/policy` is unchanged (served
from last-known, not refit), and shadow pairs queue up **unscored** (the judge is dead) —
then drain cleanly once the poller returns. The proxy never notices the side-cars are
down because the hot path never blocks on them (the `try_send` contract).

To run the drill against **live** traffic instead of the mock, stop the
`cascadia-judge-worker` and `cascadia-policy-controller` Railway services for the window
and confirm `cascadia-proxy` keeps serving real requests + that `/policy` holds steady.

## Acceptance (from NEXT_STEPS §5)

- [ ] Dashboard `/clusters` + `/pareto` show categories and points derived from **real**
      traffic (not the synthetic seed).
- [ ] Cold-start convergence demonstrated: thresholds stabilize within 24h of first
      traffic.
- [ ] Chaos drill green (local mock and/or live service-kill).
- [ ] Launch line earns its keep: *"this has been routing my own traffic for N weeks."*
