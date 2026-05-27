# SOLID — judge-worker architecture orientation

> This file orients future Claude sessions (and human contributors) to the abstractions in `services/judge-worker/`. PLAN.md is still the project-wide source of truth; this file zooms in on the eval-plane architecture.

The judge-worker is built on the **SOLID Agent Swarms** pattern (slides: https://docker-agent-swarm-slides.netlify.app/). The deck's runtime story — Docker Swarm with mounted socket — is deliberately **not** adopted. Cascadia uses Helm/K8s; the executor *abstraction* is the load-bearing piece, not Swarm itself.

If you are about to add a judge, swap a provider, or wire the worker to Postgres, read this first.

---

## 1. What the abstractions are

```
                       JudgeOrchestrator (composition root)
                                   │
                ┌──────────────────┼───────────────────┐
                ▼                  ▼                   ▼
         JudgeRegistry      JudgeExecutor          LLMClient(s)
         (decorator-      (Protocol; current:    (ABC; current:
          based; auto-     AsyncioJudgeExecutor)  OpenAI / Groq /
          discovered)                              xAI / Anthropic
                ▼                                   + Fake / Scripted)
          BaseJudge ABC
                │
                ▼
        @register_judge classes
        (currently: PairwisePreferenceJudge)
```

| Layer                | File                                              | Role                                                                          |
| -------------------- | ------------------------------------------------- | ----------------------------------------------------------------------------- |
| LLM contract         | `cascadia_judge/llm/base.py`                      | `LLMClient` ABC. **One method:** `chat(system, messages, …) -> LLMResponse`.  |
| LLM adapters         | `cascadia_judge/llm/openai_compatible.py`         | `_OpenAICompatibleClient` base; `OpenAIClient` / `GroqClient` / `XAIClient` differ only in `BASE_URL` + `API_KEY_ENV`. |
| LLM adapter (split)  | `cascadia_judge/llm/anthropic.py`                 | `AnthropicClient` — separate because Messages API shape differs.              |
| LLM test doubles     | `cascadia_judge/llm/fake.py`, `…/scripted.py`     | `FakeLLMClient` (queue responses programmatically); `ScriptedLLMClient` (replay from JSON fixture, keyed by `(judge_name, request_id)`). |
| Judge contract       | `cascadia_judge/judges/base.py`                   | `BaseJudge` ABC + `JudgeRegistry` + `@register_judge` decorator. Provenance helper `_score_with_llm` computes `prompt_hash` and times the call. |
| Judge example        | `cascadia_judge/judges/pairwise_preference.py`    | `PairwisePreferenceJudge` — LLM-as-judge that scores P(cheap ≥ expensive).    |
| Executor             | `cascadia_judge/executor.py`                      | `JudgeExecutor` Protocol + `AsyncioJudgeExecutor` (asyncio.gather fan-out).   |
| Orchestrator         | `cascadia_judge/orchestrator.py`                  | Composition root. Holds registry + executor + `llm_factory`. **Imports zero provider code.** |
| CLI                  | `cascadia_judge/cli.py`                           | The edge. Wires concretes. `--fixture` runs offline; `--provider`+`--pair` runs live. |

---

## 2. Where SOLID actually shows up

- **S — Single responsibility.** A judge has one reason to change: how it scores a `ShadowPair`. `BaseJudge` carries `name / description / prompt_variant` class attrs and a single `judge()` method.
- **O — Open / Closed.** Adding a judge is one file with `@register_judge`. Orchestrator, executor, CLI stay untouched. The `judges/__init__.py` imports the package's judges for their decorator side effects; the registry has no hard-coded list.
- **L — Liskov.** `JudgeExecutor` is a `typing.Protocol`. `AsyncioJudgeExecutor` today; a future `NATSJudgeExecutor` or `RayJudgeExecutor` substitutes in without changing the orchestrator. Same applies to `LLMClient`: `FakeLLMClient`, `ScriptedLLMClient`, and the four live adapters are interchangeable.
- **I — Interface segregation.** `LLMClient.chat()` is one method. No streaming, embeddings, or vision in this contract — those would be separate ABCs if/when they're needed.
- **D — Dependency inversion.** `JudgeOrchestrator.__init__` takes abstract types only. The CLI is the only place that names `OpenAIClient` / `ScriptedLLMClient` / `AsyncioJudgeExecutor`. `grep "import openai\|import anthropic" cascadia_judge/` returns nothing.

---

## 3. Provenance envelope (extension beyond the deck)

Every `JudgeVerdict` carries:

| Field            | Source                                                                       |
| ---------------- | ---------------------------------------------------------------------------- |
| `prompt_hash`    | `sha256(model || prompt_variant || system || user)` — stable per call.       |
| `model`          | From the injected `LLMClient.model`.                                          |
| `provider`       | From the injected `LLMClient.provider`.                                       |
| `prompt_variant` | Class attr on the judge — e.g. `"pairwise/v1"`. Bumping it = a new variant.   |
| `elapsed_ms`     | Wall-clock around the LLM call + parse.                                       |
| `error`          | `None` on success, `"ExceptionName: message"` on parse/transport failure.    |
| `score`          | `JudgeScore(score, confidence, rationale)` — pydantic-validated 0..1.        |

This is the structured output Phase 5's calibration math will read directly. Don't drop fields from this envelope without updating Phase 5's plan in PLAN.md §4.

---

## 4. How to add a judge

```python
# cascadia_judge/judges/my_new_judge.py
from cascadia_judge.judges.base import BaseJudge, register_judge
from cascadia_judge.types import ShadowPair, JudgeVerdict

@register_judge
class MyNewJudge(BaseJudge):
    name = "my_new_judge_v1"
    description = "..."
    prompt_variant = "my_new/v1"

    async def judge(self, pair: ShadowPair) -> JudgeVerdict:
        system = "..."
        user = f"PROMPT: {pair.prompt}\n\nA: {pair.cheap_response}\n\nB: {pair.expensive_response}"
        return await self._score_with_llm(pair, system=system, user=user, parse=_parse)

def _parse(text: str) -> JudgeScore: ...
```

Then add the import to `cascadia_judge/judges/__init__.py`. The orchestrator, CLI, and tests **do not change**. If they need to change in order to add your judge, the abstractions are wrong — fix them, don't paper over.

`prompt_variant` is load-bearing: when you alter the prompt enough that scores from prior versions should not be pooled, bump the variant string (e.g. `pairwise/v1` → `pairwise/v2`).

---

## 5. How to add a provider

1. Subclass `_OpenAICompatibleClient` if the API is OpenAI-shaped — set `BASE_URL`, `API_KEY_ENV`, `provider`. Done.
2. Otherwise (Anthropic-style, Bedrock, Vertex, …), subclass `LLMClient` directly and implement `chat()`. Mirror `AnthropicClient` for the shape.
3. Register it in `cli.py`'s `_PROVIDER_CLIENTS` map.

**No SDK dependencies.** This is intentional. `httpx` is the only HTTP client. The deck's slide 14 demonstrated three providers in ~30 LOC by keeping it raw; we preserve that.

---

## 6. Tests

```bash
cd services/judge-worker
pip install -e ".[dev]"
pytest
```

- 13 tests; <0.3s wall-clock; **zero** API calls; **zero** network.
- `FakeLLMClient` for programmatic queueing (`test_pairwise_judge.py`, `test_orchestrator.py`).
- `ScriptedLLMClient` for fixture-replay (CLI smoke test via `tests/fixtures/pairwise_v1_basic.json`).
- Every new judge should land with at least: a happy-path parse test, a malformed-response test, and a prompt-hash-stability test. Use `FakeLLMClient` — don't burn API tokens in CI.

---

## 7. What is **not** here yet

- **Postgres consumer loop.** Phase 2 adds the `shadow_pairs` and `judge_scores` tables. When that lands, add a `cascadia_judge/storage/` module with two adapters (read shadow pairs, write verdicts) and a long-running poller. The orchestrator stays unchanged — the poller calls `orchestrator.evaluate(pair)` per row.
- **Judge ensemble (Phase 5).** Multiple registered judges already fan out in parallel; ensemble = registering 2–3 more `@register_judge` classes + a small aggregator that consumes a `list[JudgeVerdict]` and emits a single calibrated score. The aggregator is its own ABC when we get there.
- **Calibration set.** Human-rated examples land in a separate flow; the verdict envelope is the input to that calibration job.
- **Hot-path integration.** The judge worker is the eval plane. The Rust proxy in `crates/proxy/` is the hot path; it doesn't import any of this.

---

## 8. Deliberate non-adoptions from the source deck

These are choices, not omissions. Don't "fix" them without reading the rationale.

| Deck pattern                       | Cascadia choice                                                                              |
| ---------------------------------- | -------------------------------------------------------------------------------------------- |
| Docker Swarm + mounted socket      | **Skipped.** Cascadia ships Helm charts; the executor Protocol is the substitution surface. |
| `ThreadPoolAgentExecutor`          | Skipped in favor of `AsyncioJudgeExecutor` — judges are I/O-bound HTTP, async is the right primitive. |
| Tools / function-call loop          | Skipped — judges score, they don't call tools. `LLMClient.chat()` has no `tools` parameter.  |
| Parallel fan-out as the headline    | Kept for judges (ensemble of N judges over 1 pair). **Not** how the proxy escalates — that's Rust hot-path, sequential. |
| Provider SDK imports                | **Banned** in the package. Raw `httpx` only. CI greps for `import openai` etc.               |

---

## 9. Pointers

- Source deck (28 slides): https://docker-agent-swarm-slides.netlify.app/
- Project source of truth: `PLAN.md` at repo root.
- Decision log entry that scaffolded this: PLAN.md §9, `2026-05-19 — Judge-worker scaffolded early using SOLID Agent Swarms pattern`.
