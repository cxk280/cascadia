# Adding a new provider

Cascadia ships native support for OpenAI, Anthropic, Groq, and xAI, and a **dynamic provider registry** for everything else — HuggingFace, Together, Fireworks, OpenRouter, Mistral, DeepSeek, a local vLLM, your own gateway. Adding one of those is a **config change, not a code module**: name it in `CASCADIA_PROVIDERS`, give it a base URL + key, and use its prefix in your policy.

> **Why a registry?** Earlier Cascadia had a closed `Provider` enum and one base URL per adapter, so a single proxy couldn't run (say) a HuggingFace cheap tier escalating to an OpenAI expensive tier. The registry (PLAN.md §9, 2026-06-09) makes each provider its own entry with its own base URL + key, so mixed-provider cascades work in one process. The §9 hard-fail still holds: an unconfigured `provider/` prefix fails loudly at boot and on every policy hot-reload — it never silently mis-routes.

## Decision tree

```
              ┌────────────────────────────────────────────────┐
              │ What wire format does the provider speak?      │
              └─────────────────────┬──────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                            ▼
 OpenAI /v1/chat/completions  Anthropic /v1/messages     Something else
 (HuggingFace router,         (a private Claude-shape     (Gemini generateContent,
  Together, Fireworks,         host / proxy)               Bedrock native, …)
  vLLM, Mistral, …)
        │                           │                            │
        ▼                           ▼                            ▼
 ✅ Path A — registry entry,  ✅ Path A — registry entry,  ⚠ Path B — new `Wire`
   WIRE=openai (default).       WIRE=anthropic.              variant + adapter.
   NO CODE CHANGE.              NO CODE CHANGE.              Open an issue first.
```

The vast majority of "add provider X" requests are **Path A** — Cascadia already speaks both the OpenAI and Anthropic wire formats, and Path A picks one.

## Path A — add a named provider via the registry (no code change)

List the provider in `CASCADIA_PROVIDERS`, then configure it with three env vars (the name, uppercased with `-` → `_`, is the token):

```bash
export CASCADIA_PROVIDERS=hf                       # comma-separated for several
export CASCADIA_PROVIDER_HF_BASE_URL=https://router.huggingface.co   # required
export CASCADIA_PROVIDER_HF_API_KEY=hf_...         # omit to leave it unconfigured
export CASCADIA_PROVIDER_HF_WIRE=openai            # openai (default) | anthropic

cascadia-proxy
```

Then use the name as the `provider/` prefix in your policy. The model half may contain slashes (HuggingFace ids work verbatim):

```json
{
  "default_cluster": "default",
  "cluster_buckets": 4,
  "clusters": {
    "default": {
      "cheap_model":     "hf/meta-llama/Llama-3.3-70B-Instruct",
      "expensive_model": "openai/gpt-4o",
      "threshold": 0.7,
      "shadow_rate": 0.1
    }
  }
}
```

**Mixed-provider cascades now work in one proxy.** Because `hf` and `openai` are distinct registry entries with distinct base URLs + keys, the cheap tier dials the HuggingFace router and the expensive tier dials OpenAI — from the same process. (`events.provider` attributes each tier correctly, and `/clusters` shows `hf → openai`.)

- **`WIRE=openai`** (default) covers any host exposing `POST /v1/chat/completions` in OpenAI's shape: the HuggingFace router, Together, Fireworks, OpenRouter, Perplexity, vLLM/Ray-Serve, Mistral, DeepSeek, …
- **`WIRE=anthropic`** routes through the Anthropic Messages adapter (request/response + streaming translation) — for a private Claude-shape host or proxy.

### Quick alternative: repoint a built-in

If you just want one of the four built-ins to dial a different host (e.g. a self-hosted OpenAI-compatible endpoint), override its base URL instead of adding a registry entry:

```bash
export CASCADIA_OPENAI_API_KEY=<key>
export CASCADIA_OPENAI_BASE_URL=https://api.mistral.ai/v1
# policy: "cheap_model": "openai/mistral-small-latest"
```

This is simpler when you only need one extra host, but it consumes the `openai/` prefix — for *additional* providers alongside OpenAI, use a registry entry.

### Per-host safety check (OpenAI wire)

The OpenAI adapter refuses to dial known *non*-OpenAI-shape hosts (`api.anthropic.com`, `generativelanguage.googleapis.com`, `bedrock-runtime`) — it returns a 400 with a clear message before the network call, rather than a cryptic auth error. See `KNOWN_NON_OPENAI_HOSTS` in [`crates/proxy/src/upstream/openai_compat.rs`](../crates/proxy/src/upstream/openai_compat.rs). Your private host won't be on that list, so the request proceeds. If a provider speaks Anthropic's shape, give it `WIRE=anthropic` rather than pointing the OpenAI adapter at it.

### Inspecting the registry

`GET /providers` (public, no auth — configuration, not credentials) returns every configured provider with its name, wire, base URL, and a `configured` boolean (whether a key is set — never the key itself):

```json
{ "providers": [
  { "name": "anthropic", "wire": "anthropic", "base_url": "https://api.anthropic.com", "configured": true },
  { "name": "hf",        "wire": "openai",    "base_url": "https://router.huggingface.co", "configured": true },
  { "name": "openai",    "wire": "openai",    "base_url": "https://api.openai.com", "configured": true }
] }
```

### Helm chart equivalent

```yaml
config:
  providers: "hf"
  providerHfBaseUrl: https://router.huggingface.co
secrets:
  providerHfApiKey: hf_...
```

## Path B — a genuinely new wire format

Only needed when the provider speaks neither OpenAI's `/v1/chat/completions` nor Anthropic's `/v1/messages` — e.g. Gemini's `contents: [{role, parts}]` or Bedrock's per-model native shape. This is the rare case. **Open a GitHub issue first**, link PLAN.md §9 (`2026-05-19` for the hard-fail context, `2026-06-09` for the registry), and propose the new wire. The maintainer confirms it's worth the maintenance cost before you write code.

When approved, a new wire format touches:

| File | Change |
|---|---|
| `crates/proxy/src/config.rs` | Add a `Wire::<Name>` variant + `label()` arm + `Wire::parse()` arm. |
| `crates/proxy/src/upstream.rs` | Add a dispatch arm in `forward_chat()` and `forward_chat_stream()` keyed on the new `Wire`. |
| `crates/proxy/src/upstream/<name>.rs` | New adapter: translate OpenAI ChatCompletion request → provider request → OpenAI ChatCompletion response (+ streaming). Mirror `anthropic.rs`. |
| `crates/proxy/src/upstream/openai_compat.rs` | If relevant, add the provider's bare host to `KNOWN_NON_OPENAI_HOSTS`. |
| Tests | Unit tests for the adapter's request/response translation + an integration test against a mock emitting the new wire shape. `anthropic.rs`'s tests are the reference. |

Note this is a much smaller surface than before the registry: there's no enum variant, `FromStr` arm, `provider_credentials` arm, per-provider env wiring, or metrics-table edit — the registry handles naming, credentials, and routing; you only add the *wire translation*. Once the `Wire` exists, anyone can use it for any number of registry providers via `CASCADIA_PROVIDER_<NAME>_WIRE=<name>`.

### Streaming

A new wire adapter MUST also implement `forward_stream()` returning OpenAI `chat.completion.chunk` SSE frames. See `crates/proxy/src/upstream/anthropic.rs::AnthropicStreamTranslator` for translating typed events into OpenAI delta chunks.

## Naming and labels

- A provider's registry name (its `provider/` prefix) is lowercased and trimmed at parse time; the historical `x-ai` alias folds onto `xai`. Use it everywhere a string is needed — `events.provider`, Prometheus labels, log fields. Valid names are letters, digits, `-`, `_`.
- `Wire::label()` returns `openai` / `anthropic` for diagnostics. The wire is *how* a provider is dialed; the name is *who* it is.

## When in doubt

Open an issue. The 30-minute "is this a registry entry or a new wire?" conversation up front saves the maintainer rejecting 400 lines of code two weeks later. Almost always, it's a registry entry.

## "What if I need a provider neither Path A nor Path B covers?"

If the provider has a custom wire format AND nobody's willing to maintain a new `Wire` (Path B), **stack Cascadia on top of LiteLLM**. LiteLLM is the provider-plumbing layer (100+ APIs behind one OpenAI shape); Cascadia sits above it making cascade decisions:

```
client → Cascadia (cascade routing, policy learning, judge)
            ↓ OpenAI-compatible HTTPS
         LiteLLM (provider plumbing, retries, fallback, caching)
            ↓ N native wire formats
         OpenAI / Anthropic / Bedrock / Vertex / Cohere / Gemini / …
```

Add a registry entry (or override `CASCADIA_OPENAI_BASE_URL`) pointing at LiteLLM's proxy, use `<name>/<litellm-routable-model>` in your policy. You inherit LiteLLM's full provider list with Cascadia's closed-loop quality measurement on top. See the [README → "What makes Cascadia different"](../README.md#what-makes-cascadia-different) for the composition story.
