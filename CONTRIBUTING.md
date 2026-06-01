# Contributing to Cascadia

Cascadia is MIT-licensed and welcomes contributions. This file is the short version of what an outside contributor needs to know.

## Before you open a PR

1. **Read [PLAN.md](PLAN.md) §9 (Decisions log).** The project has a strong opinion about *honest measurement* — quality numbers are calibrated against humans, biases are named not papered over. PRs that report cost-saved numbers without the corresponding quality calibration step won't land. See [docs/blog/methodology.md](docs/blog/methodology.md) for the framing.
2. **Read the [README → "What makes Cascadia different"](README.md#what-makes-cascadia-different).** Cascadia is the closed-loop quality-measurement layer, not the provider-plumbing layer. PRs that turn it into a LiteLLM/Portkey clone (retries, fallback chains, per-token cost tracking) will be redirected — those compose on top of Cascadia, they don't replace what it does.
3. **Open an issue first for non-trivial changes.** A 50-line refactor is fine to PR cold; a new phase of work or a contested architectural choice deserves a discussion thread first.

## Development setup

Prerequisites: [Rust stable](https://rustup.rs) (pinned by `rust-toolchain.toml`), Python 3.12, [`uv`](https://docs.astral.sh/uv/getting-started/installation/) (`pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`), Node 20+, Docker for Postgres. Copy `.env.example` → `.env` and fill in at least one provider key + `CASCADIA_DATABASE_URL` before running anything.

```bash
# Postgres for the proxy + dashboard-api
docker compose -f deploy/compose/docker-compose.yml up -d

# Rust workspace
cargo build --release
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings

# Python services — each has its own .venv
cd services/judge-worker     && uv sync && uv run pytest
cd services/policy-controller && uv sync && uv run pytest
cd services/dashboard-api     && uv sync && uv run pytest

# Dashboard
cd dashboard && npm install && npm run dev
```

CI runs all of the above on every PR — see [`.github/workflows/`](.github/workflows/).

## Where to start as a new contributor

- **First OSS PR?** Look for issues labeled [`good first issue`](https://github.com/cascadia-llm/cascadia/labels/good%20first%20issue). They're scoped to one file, one purpose, and won't require deep knowledge of the cascade-routing internals.
- **Want to extend a component (custom judge, aggregator strategy, policy refit)?** Read [`docs/extending.md`](docs/extending.md) before forking — most customizations are config changes, not source edits.
- **Adding a new upstream provider?** Read [`docs/adding-a-provider.md`](docs/adding-a-provider.md) FIRST. Most "add provider X" PRs become a one-line config change.

## What good PRs look like

- **One purpose per PR.** A new judge prompt is one PR. A docs typo is a different PR.
- **Tests at the layer of the change.** New translation logic in `crates/proxy/src/upstream/anthropic.rs`? Add unit tests in the same file. New aggregator behavior in `services/judge-worker/cascadia_judge/aggregation.py`? Add to `tests/test_aggregation.py`.
- **Don't bypass safety rails.** No `--no-verify` on git commits, no skipping clippy lints, no commenting-out failing tests. If a guard fires, fix the underlying issue.
- **Honor the §9 Decisions log.** Several patterns are intentional: hard-fail on unprefixed model strings, anti-self-preference filter drops judges by name, concision weight is post-hoc not learned. If you want to revisit one, open an issue and link the §9 entry first.

## Adding a new provider

**Read [`docs/adding-a-provider.md`](docs/adding-a-provider.md) FIRST.** Most "I want Cascadia to support X" PRs become one-line config changes, not a new adapter. Short version:

| If the provider… | Then… |
|---|---|
| …speaks the OpenAI `/v1/chat/completions` shape (Mistral, DeepSeek, Together, Fireworks, Perplexity, vLLM, …) | **No code change.** Set `CASCADIA_OPENAI_BASE_URL=https://api.mistral.ai/v1` (or wherever) and use `openai/<model-name>` in your policy. The OpenAI-compat adapter handles the wire format. |
| …has its own wire format (Gemini's `generativelanguage.googleapis.com`, Bedrock's native API) | A new `Provider` variant + `crates/proxy/src/upstream/<name>.rs` adapter is required. **Open an issue linking PLAN.md §9 (2026-05-19 — Phase 7 scoping) first** so the maintainer can confirm a new variant is the right move before you write 400 lines. |

The guard comment on the `Provider` enum in `crates/proxy/src/config.rs` and the `KNOWN_NON_OPENAI_HOSTS` list in `crates/proxy/src/upstream/openai_compat.rs` route you to the same decision in-code.

## What we won't accept

- **Retry logic, fallback chains, per-key load balancing.** These are LiteLLM's lane (and they do them well). Stack Cascadia on top of LiteLLM if you want both.
- **A new `Provider::*` variant for a provider that speaks OpenAI's chat-completions shape.** Mistral, DeepSeek, Together, Fireworks, Perplexity, vLLM all route through the OpenAI-compat adapter via a base URL override. PRs that add a new variant for one of these will be redirected to `docs/adding-a-provider.md`. See PLAN.md §9 (2026-05-19) for the hard-fail-on-unknown-providers rationale.
- **A new adapter for Bedrock or Vertex AI front-doors.** Both wrap providers we already support and the front-door wire shape is a stability liability. Configure a compatible base URL on the existing adapters and use IAM / WIF auth at the network layer.

## Code style

- **Rust:** stable toolchain (`rust-toolchain.toml` pins the version). `cargo fmt` + `cargo clippy -D warnings`. No unsafe without a `// SAFETY:` comment.
- **Python:** `ruff check` clean, type hints where the type is non-obvious. `from __future__ import annotations` at the top of new files.
- **TypeScript:** `tsc --noEmit` clean. We're on Next.js 14, server components by default; client components opt-in with `"use client"`.

## Commit messages

```
component: one-line summary in present tense

Optional body explaining *why* — the *what* is in the diff. Link the
issue or §9 decision this addresses.
```

Examples of `component`: `proxy`, `judge-worker`, `policy-controller`, `dashboard-api`, `dashboard`, `bench`, `docs`, `ci`.

## Security

Please don't open public issues for security findings. See [SECURITY.md](SECURITY.md) for the disclosure path.

## License

By contributing you agree your contribution is licensed under MIT — see [LICENSE](LICENSE).
