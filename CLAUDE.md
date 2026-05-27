# Cascadia — instructions for AI agents (Claude Code et al.)

If you're an AI agent that just landed in this repo: **read this file before editing anything.** It's the project-specific equivalent of your global CLAUDE.md, and it overrides defaults where the project has a strong opinion.

## Where to look up "why is X the way it is?"

- **[`PLAN.md` §9 Decisions log](PLAN.md)** — newest first, append-only. Every load-bearing architectural decision is here with the reasoning. If you're about to remove, refactor, or "improve" something, **grep §9 for the relevant terms first.** Several patterns that look removable are intentional and the reasoning is in the log.
- **[`DIFFERENTIATOR.md`](DIFFERENTIATOR.md)** — the positioning vs LiteLLM / Portkey. Read before suggesting features that belong in those projects.
- **[`USERS.md`](USERS.md)** — the persona catalog. Each persona's `Last tested` line records the iter findings + fixes, so you can see what's already been audited.
- **[`SECURITY.md`](SECURITY.md)** — threat model, data residency postures, GDPR / DSAR runbook, judge-prompt-injection mitigations. The intentional auth gaps (e.g. `/policy` unauthenticated by design) are documented here.

## Patterns that are intentional — don't "fix" without grepping §9 first

- **Hard-fail on unprefixed model strings.** `parse_model_id` rejects bare `gpt-4o`. The proxy refuses to boot with unprefixed values in env or policy. This is in PLAN.md §9 (2026-05-19 Phase 7 scoping) — silent provider routing is worse than a loud fail.
- **No retry logic, no fallback chains.** These belong in LiteLLM, not here. See DIFFERENTIATOR.md → composition story. If you find yourself adding `retry_on_5xx`, stop.
- **Tool-use bypass + streaming bypass on cascade.** Requests carrying `tools=[]` or `stream=true` skip escalation by design — mid-loop escalation diverges into incoherent state. Don't try to "make tool-use traffic escalate." See `crates/proxy/src/cascade.rs` doc comment.
- **Shadow_pairs are always persisted; redaction is opt-in.** Redacting verbatim user prompts is `CASCADIA_REDACT_SHADOW_BODIES=true`. The default is full persistence because the judge needs context to score. SECURITY.md documents the data-residency postures.
- **Anti-self-preference filter is substring-matched on model name.** Not a content filter. If you want a real content filter, that's a new feature — open an issue.
- **Aggregator's concision-weight default is 0.0.** The 0.30 value that helped the pilot's panel-vs-human τ-b is a *characterized* correction, not the default. Don't auto-apply it.
- **`/policy` and `/config` proxy endpoints are public by design.** They return configuration (no credentials). The dashboard uses them. Don't add auth to these specifically — gate at the cluster boundary if you want them private.
- **Proxy `/v1/*` is auth-gated via optional `CASCADIA_PROXY_BEARER_TOKEN`.** When unset, the proxy is open — appropriate for private-network deploys. Don't change the default to "always required" without thinking through the local-dev impact.

## When the user asks for "X" and X conflicts with §9

Don't silently obey. Explain the conflict, point at the §9 entry, and ask whether they want to revisit the decision. The §9 log is *append-only*, and if a decision is being reversed, that reversal belongs in §9 as a new dated entry that links back to the original.

Example phrasing: *"Adding retry logic on 5xx would conflict with the LiteLLM composition story documented in DIFFERENTIATOR.md and PLAN.md §9 (2026-05-19). Want me to add the retry anyway and document the reversal, or do you want me to confirm the composition story still applies?"*

## Project-specific commands

```bash
# Rust
cargo build --release
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings

# Python services (each has its own .venv)
cd services/judge-worker && uv sync && uv run pytest
cd services/policy-controller && uv sync && uv run pytest
cd services/dashboard-api && uv sync && uv run pytest

# Dashboard
cd dashboard && npm install && npm run dev
cd dashboard && npx tsc --noEmit
```

The `Makefile` at the repo root wraps the most-used recipes; see `make verify` for the all-green target.

## Persona testing protocol (when the user invokes one)

The user runs persona-based UX testing per `USERS.md`. Key rules:

- **Cap at 3 iterations per persona.** Don't spiral past the cap.
- **Test against the live dev URL** (`cascadia-dashboard-dev.up.railway.app`, `cascadia-proxy-dev.up.railway.app`), not localhost — that's what real users see.
- **Sub-agents log in-character.** When spawning a persona via the Agent tool, write the prompt so the agent's voice + frustration shows through, not a sanitized "as the user I tried X" report.
- **Engineers fix; personas complain.** The persona's job is to surface findings. Your job is to fix them — including nits.
- **Mark completion in `USERS.md`** when iterations close, with the date + a one-line per-finding summary.
- **Persona findings get surfaced in the main thread.** Don't bury them in a sub-agent transcript.

## Repo invariants worth knowing

- **The proxy's hot path must not block on Postgres.** `try_send` is the contract — events are dropped (with a warn log) before the proxy blocks. Don't change this without a §9 entry.
- **`events.request_body` / `response_body` default OFF** (`persist_bodies: false`). Turning them on is a privacy decision documented in SECURITY.md.
- **Policy hot-reload works only with `CASCADIA_POLICY_FILE`.** `CASCADIA_POLICY_JSON` (inline) requires a process restart. Both paths are valid; pick based on deploy target.
- **Live deploys:** the proxy + dashboard run on Railway in the `cascadia-dev` project, `dev` environment. URLs in README status header. Bearer token + calibrate password live in Railway env vars (not in this repo).

## When you're sure you want to commit something

The user explicitly opts in to commits. Don't `git commit` without that opt-in. Pre-commit hooks exist; don't `--no-verify` unless explicitly asked.
