# `docs/` index

Project docs. The root [README.md](../README.md) is the entry point for everything user-facing; this directory carries the longer-form material that doesn't fit on the landing page.

## How-to

| File | When you'd read it |
|---|---|
| [`adding-a-provider.md`](adding-a-provider.md) | You want Cascadia to support a new upstream (Mistral, DeepSeek, Together, …). Start here — most requests are a one-line `CASCADIA_OPENAI_BASE_URL` override, not a new adapter. |
| [`demo-script.md`](demo-script.md) | You're showing the dashboard live to a recruiter / hiring manager. One-page runbook, ~10-minute walkthrough. |
| [`prolific-runbook.md`](prolific-runbook.md) | You're scaling the human-rated calibration set via Prolific (200-pair production run). |

## Methodology / blog

| File | What it's about |
|---|---|
| [`blog/methodology.md`](blog/methodology.md) | Why judge ensembles bias toward verbose answers (panel-vs-human τ-b ≈ 0), how Cascadia detects and reports the gap, why honesty-over-hype is the differentiator. |

## Design specs

| File | Surface |
|---|---|
| [`design/VIEWS.md`](design/VIEWS.md) | Inventory of dashboard views — page-by-page wireframes and acceptance criteria. |
| [`design/landing-hero-spec.md`](design/landing-hero-spec.md) | Landing page design system reference (used by the in-repo Figma file). |
| [`design/views/`](design/views/) | Per-view design notes (alerts, API keys, architecture diagram, audit log, benchmarks, etc.). |

## Where everything else lives

- **Project state and decisions log** → [`../PLAN.md`](../PLAN.md) (root). Newest entries at the top of §9.
- **Differentiator vs LiteLLM / Portkey / RouteLLM** → [`../DIFFERENTIATOR.md`](../DIFFERENTIATOR.md).
- **Security policy + data-residency postures** → [`../SECURITY.md`](../SECURITY.md).
- **Persona test catalog** → [`../USERS.md`](../USERS.md).
- **Helm chart docs** → [`../deploy/helm/cascadia/README.md`](../deploy/helm/cascadia/README.md).
- **Contributing** → [`../CONTRIBUTING.md`](../CONTRIBUTING.md).
