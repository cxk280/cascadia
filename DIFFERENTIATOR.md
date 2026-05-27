# How Cascadia is different from LiteLLM and Portkey

*Standalone reference. Linked from [README.md](README.md) and [PLAN.md §9 decisions log](PLAN.md). Update both when this changes.*

This is the question every recruiter and HN reader asks: *"Isn't this just LiteLLM?"* The answer below is the canonical one — README, methodology blog, and elevator pitch all derive from it.

> **TL;DR for the architect worried about provider breadth:** Cascadia natively supports 4 providers (OpenAI / Anthropic / Groq / xAI). For any other OpenAI-shape host (Mistral / DeepSeek / Together / Fireworks / Perplexity / vLLM / your private endpoint) you set one env var, no code change. For everything else — the LiteLLM 100+ list including Bedrock, Vertex, Cohere, the long tail — **stack Cascadia on top of LiteLLM**: Cascadia decides the cascade, LiteLLM handles the N-provider plumbing. See [The composition story](#the-composition-story-the-closer) below.

## The one-liner

LiteLLM and Portkey are **provider plumbing** with human-authored routing rules. Cascadia is the layer that **learns what those rules should be** — by counterfactually scoring its own cascade decisions on live traffic and refitting per-cluster thresholds from the closed loop.

They ask **"where does this request go?"**. Cascadia asks **"what's the cheapest model that still meets quality, and how do we know?"** — different problem, different solution.

## What each is optimizing

| | LiteLLM | Portkey | Cascadia |
|---|---|---|---|
| **Primary value** | Provider abstraction (100+ APIs behind one OpenAI shape) | Rule-based routing + hosted SaaS dashboard | Closed-loop quality measurement |
| **How routing decisions get made** | Human writes rules (round-robin, cost-tier, fallback chain) | Human writes conditional rules in YAML | Bandit refits per-cluster thresholds from judge scores |
| **How you know the rules are right** | You don't. You hope. | You don't. You hope. | The Pareto chart, generated from counterfactual shadow data |
| **Cost vs quality tradeoff** | Reports cost-saved; quality not measured | Same | Both. Bias-corrected human-calibrated judge ensemble; 30-pair pilot: κ v2 = +0.52 inter-rater; the τ-b ≥ 0.7 gate is queued behind the 200-pair Prolific run. See [methodology blog](docs/blog/methodology.md). |
| **Adaptation as models change** | Update the YAML | Update the YAML | Controller refits automatically; no human in the loop |

## The three load-bearing technical claims competitors structurally can't make

1. **Counterfactual shadow routing.** Cascadia's `shadow_rate` gives you "what would the expensive model have said?" as a side effect of serving traffic. LiteLLM and Portkey don't generate this signal because they don't have a use for it — they're routing, not evaluating.

2. **Per-cluster online policy learning.** The bandit-style refit in [`services/policy-controller/`](services/policy-controller/) exists because there's a closed loop to learn from. LiteLLM/Portkey require you to set the rule by hand and never tell you whether it's right. Cascadia tells you, and updates itself.

3. **Bias-corrected calibrated judge ensemble.** Position-bias correction, anti-self-preference filtering, human-rated Kendall's τ-b gating — this is academic-rigor evaluation methodology, not gateway-feature territory. Nobody in the gateway space ships this because nobody in the gateway space *measures quality honestly* — they report cost-saved-vs-always-using-expensive, which is always a flattering number when nobody checks the quality side.

## Where they win — honestly

This is the part that makes the differentiation credible in an interview. Refuse to flinch from it:

- **LiteLLM** has 100+ providers, retries, fallback chains, caching (response + semantic), key management, virtual keys. Battle-tested at scale, 30k+ stars on GitHub. If you want plumbing that just works, you use LiteLLM. Cascadia today supports **four providers** (OpenAI, Anthropic, Groq, xAI) with the OpenAI/Groq/xAI adapters sharing one code path and Anthropic getting full request/response translation including tool-use parity (Phase 7.1). No retry logic, no fallback chains — those are LiteLLM's lane (see the composition story below).

- **Portkey** has a polished hosted SaaS dashboard, prompt management, input/output guardrails. SaaS-grade UX, conditional routing rules expressed in clean YAML. Cascadia ships behind your firewall and the operator UI is admittedly less polished.

## The composition story (the closer)

You don't pick one. **You stack them.** LiteLLM handles the N-provider plumbing layer. Cascadia sits above it deciding which 2-tier cascade to use per cluster. The shadow data Cascadia generates feeds back a signal LiteLLM never had access to. They're **orthogonal** — one solves "how do I talk to N providers," the other solves "which provider should I be talking to for *this* request, and how do I know it's still the right one a month from now."

A realistic production architecture:

```
client → Cascadia (cascade decisions, policy learning, judge ensemble)
            ↓
         LiteLLM (provider plumbing, retries, fallback, caching)
            ↓
         OpenAI / Anthropic / Groq / vLLM / ...
```

Cascadia hands LiteLLM a fully-resolved `(provider, model, request)` triple per call; LiteLLM handles the auth, retries, and provider quirks; Cascadia receives back the response and the latency and emits the events that feed its closed loop.

## Defensibility — what if LiteLLM just adds cascade routing?

Plausible question. They might. Three reasons it doesn't collapse the differentiation:

1. **Eval methodology.** Phase 5's bias-corrected ensemble + human τ-b calibration is genuinely academic-rigor work that LiteLLM hasn't shown interest in. Their culture is *more features*, not *more honest measurement*. Even if they ship cascade routing, the quality signal will likely be a single-LLM-judge with no calibration story — easy for someone reading Cascadia's methodology blog to compare against directly.

2. **Design center.** Closed-loop policy *learning* (data-driven) versus config-driven routing rules is a different product philosophy. Adding it to LiteLLM isn't a feature — it's a different product wearing the same skin.

3. **Portfolio framing.** Cascadia's job as a portfolio project is the *methodology* — the rigorous evaluation, the closed loop, the honest acceptance gates. Even if every feature ends up commoditized in two years, the *story* of building it from scratch with academic rigor lives on the README, the blog, and the GitHub history. That's the artifact that opens MLOps interview conversations.

## The 30-second elevator pitch

> Existing LLM gateways route based on rules a human wrote. Cascadia routes based on a closed loop: every decision generates counterfactual shadow data, a bias-corrected judge ensemble scores it, and per-cluster thresholds refit automatically. The first gateway whose Pareto-frontier number is generated by the system itself, on live traffic, with academic-rigor evaluation methodology that's actually published. Same plumbing problem as LiteLLM, fundamentally different answer.

## Related reading

- [README.md](README.md) — Pareto chart + quick start.
- [PLAN.md §9 decisions log](PLAN.md) — full history of architectural decisions, including the differentiation framing locked on 2026-05-19.
- [docs/blog/methodology.md](docs/blog/methodology.md) — the eval methodology this argument rests on.
- LiteLLM repo: <https://github.com/BerriAI/litellm>
- Portkey: <https://portkey.ai>
