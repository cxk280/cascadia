# Adding a new provider

Cascadia ships native support for OpenAI, Anthropic, Groq, and xAI. To use *another* provider — Mistral, DeepSeek, Together, Fireworks, Perplexity, vLLM, etc. — **start here.** The answer is usually a one-line config change, not a new code module.

## Decision tree

```
                ┌────────────────────────────────────────────────┐
                │ What is the provider's wire format?            │
                └─────────────────────┬──────────────────────────┘
                                      │
              ┌───────────────────────┴───────────────────────┐
              ▼                                               ▼
   OpenAI's /v1/chat/completions               Custom (Anthropic Messages,
   (Mistral, DeepSeek, Together,                Gemini generateContent,
    Fireworks, Perplexity, vLLM,                Bedrock native, etc.)
    most "OpenAI-compatible" hosts)
              │                                               │
              ▼                                               ▼
   ✅ NO CODE CHANGE.                             ⚠ Open an issue first.
   Override CASCADIA_OPENAI_BASE_URL              See "Adding a Provider
   and use `openai/<model>` in policy.            variant" below.
```

## Path A — Provider speaks OpenAI's chat-completions shape

This is the right path for ≥90% of "add provider X" requests. Mistral, DeepSeek, Together, Fireworks, Perplexity, and most vLLM / Ray-Serve / Together-style hosts all expose `POST /v1/chat/completions` with the OpenAI request and response shape verbatim. Cascadia's `Provider::OpenAI` adapter dials whatever URL you give it, sends the OpenAI-shape body, parses the OpenAI-shape response.

### ⚠ Operational constraint — read this before designing your clusters

**One proxy instance dials one base URL per adapter.** That means a single Cascadia process *cannot* run a Mistral cheap tier escalating to OpenAI's gpt-4o expensive tier — both tiers share the `CASCADIA_OPENAI_BASE_URL`. The cascade still works at the policy level (you can have `openai/mistral-small` cheap and `openai/gpt-4o` expensive in the same cluster), but only one of those URLs is reachable per proxy.

**Workarounds, in order of operational simplicity:**

1. **Stay within one OpenAI-compatible host.** Most realistic cascades are cheap-tier-vs-expensive-tier within one provider (gpt-4o-mini → gpt-4o, claude-haiku → claude-opus). No multi-host needed.
2. **Run two proxy instances** pointed at different `CASCADIA_OPENAI_BASE_URL`s; split traffic between them at your ingress layer by cluster. Each proxy makes its own cascade decision against its own base URL.
3. **Stack on LiteLLM.** Point `CASCADIA_OPENAI_BASE_URL` at a LiteLLM proxy; LiteLLM handles the N-provider dispatch underneath. See ["What if I need a provider neither Path A nor Path B covers?"](#what-if-i-need-a-provider-neither-path-a-nor-path-b-covers) below.
4. **Build a custom-wire-format provider** (Path B) — variants carry their own base URL, no sharing.

So:

```bash
# Provider keys + URLs come from env.
export CASCADIA_OPENAI_API_KEY=<mistral-key>
export CASCADIA_OPENAI_BASE_URL=https://api.mistral.ai/v1

cascadia-proxy
```

And in your policy file, use the `openai/` prefix:

```json
{
  "default_cluster": "default",
  "cluster_buckets": 4,
  "clusters": {
    "default": {
      "cheap_model":     "openai/mistral-small-latest",
      "expensive_model": "openai/mistral-large-latest",
      "threshold": 0.7,
      "shadow_rate": 0.1
    }
  }
}
```

That's it. The `openai/` prefix is selecting the *adapter*, not the upstream host — the host is wherever `CASCADIA_OPENAI_BASE_URL` points.

### Per-host safety check

The OpenAI adapter refuses to dial known *non*-OpenAI-shape hosts (`api.anthropic.com`, `generativelanguage.googleapis.com`, `bedrock-runtime`) — it returns a 400 with a clear "you've pointed me at the wrong place" message before the network call. See the `KNOWN_NON_OPENAI_HOSTS` list in [`crates/proxy/src/upstream/openai_compat.rs`](../crates/proxy/src/upstream/openai_compat.rs). Your private host won't be on that list, so the request proceeds.

### Helm chart equivalent

```yaml
config:
  openaiBaseUrl: https://api.mistral.ai/v1
secrets:
  openaiApiKey: <mistral-key>
```

## Path B — Provider has its own wire format

If the provider's request shape diverges from OpenAI's (Anthropic's `system: string` + content blocks, Gemini's `contents: [{role, parts}]`, Bedrock's per-model shape), you need a real adapter. **Open a GitHub issue first**, link PLAN.md §9 (`2026-05-19 — Phase 7 scoping`) for the hard-fail-on-unknown-providers context, and propose the variant. The maintainer will confirm the variant is worth the maintenance cost before you write code.

When approved, a new variant touches:

| File | Change |
|---|---|
| `crates/proxy/src/config.rs` | Add `Provider::<Name>` variant + `label()` arm + `FromStr` arm + `provider_credentials()` arm + env-var (`CASCADIA_<NAME>_API_KEY`, `CASCADIA_<NAME>_BASE_URL`). |
| `crates/proxy/src/model_id.rs` | Update the unknown-provider error message's "expected one of" list. |
| `crates/proxy/src/upstream.rs` | Add a dispatch arm in `forward_chat()` and `forward_chat_stream()`. |
| `crates/proxy/src/upstream/<name>.rs` | New adapter. Translate OpenAI ChatCompletion request → provider request → OpenAI ChatCompletion response. Mirror the structure of `anthropic.rs`. |
| `crates/proxy/src/upstream/openai_compat.rs` | Add the provider's bare host (`api.<name>.<tld>`) to `KNOWN_NON_OPENAI_HOSTS` so the OpenAI adapter refuses to be misconfigured at it. |
| `crates/proxy/src/metrics.rs` | Add the new label to the pre-touch table. |
| `deploy/helm/cascadia/templates/secret.yaml` + `values.yaml` | New `secrets.<name>ApiKey` field + Secret entry. |
| `deploy/helm/cascadia/templates/configmap.yaml` + `values.yaml` | New `config.<name>BaseUrl` field + ConfigMap entry. |
| Tests | Unit tests for the new adapter's request and response translation, plus an integration test against a mock that emits the new wire shape. Anthropic's tests in `crates/proxy/src/upstream/anthropic.rs` are the reference. |

### Streaming

The new adapter MUST also implement `forward_stream()` returning OpenAI `chat.completion.chunk` SSE frames. See `crates/proxy/src/upstream/anthropic.rs::AnthropicStreamTranslator` for a worked example of translating typed events into OpenAI delta chunks. The proxy doesn't ship streaming on a per-provider basis — it's all-or-nothing per adapter.

## Naming and labels

- `Provider::label()` returns the lowercase kebab-style name (`openai`, `anthropic`). Use it everywhere a string is needed — `events.provider` column, Prometheus labels, log fields. Stable identifier.
- The `provider/model` prefix is case-insensitive at parse time but stored as the canonical label. Don't introduce a new prefix that differs in case from the label.

## When in doubt

Open an issue. The 30-minute "should this be a base URL override or a new variant?" conversation up front saves the maintainer rejecting 400 lines of code two weeks later.

## "What if I need a provider neither Path A nor Path B covers?"

If the provider has a custom wire format AND nobody's willing to maintain a new variant (Path B), the answer is **stack Cascadia on top of LiteLLM**. LiteLLM is the provider-plumbing layer (100+ APIs behind one OpenAI shape); Cascadia sits above it making cascade decisions. Architecture:

```
client → Cascadia (cascade routing, policy learning, judge)
            ↓ OpenAI-compatible HTTPS
         LiteLLM (provider plumbing, retries, fallback, caching)
            ↓ N native wire formats
         OpenAI / Anthropic / Bedrock / Vertex / Cohere / Gemini / …
```

Point `CASCADIA_OPENAI_BASE_URL` at LiteLLM's proxy URL, use `openai/<litellm-routable-model>` in your policy. You inherit LiteLLM's full provider list with Cascadia's closed-loop quality measurement on top. See [DIFFERENTIATOR.md → The composition story](../DIFFERENTIATOR.md#the-composition-story-the-closer).
