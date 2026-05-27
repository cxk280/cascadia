# Architecture Page (Public)

> **Tier 3** · spec v0 · auto-approved 2026-05-18 · `architecture-public.md`
> Public-facing doc page. Same chrome as Landing/Methodology.

## Purpose

Deep-dive on how Cascadia is built, intended for engineers evaluating the project. Mirrors `PLAN.md §3` for the public.

## Layout

```
[Top nav — same as landing]
──────────────────────────────────────────────────────────────────────────────
                              Architecture
                                                                      [TOC]
                                                                     · Overview
The full diagram, the hot path, the learning loop, the data model.   · Hot path
                                                                     · Shadow
                                                                     · Learning
──────────────────────────────────────────────────────────────────────────────
1. Overview
   ─ full architecture diagram (same as PLAN.md §3 + interactive hover)
   ─ component table: name, language, role, link to source

2. The hot path
   ─ request flow with timing budget
   ─ why Rust (latency budget rationale)
   ─ classifier inference details (ONNX, BGE-small)

3. The shadow path
   ─ what counterfactual shadow routing means
   ─ shadow rate %, scheduling, cost trade-off

4. The learning loop
   ─ judge worker
   ─ policy controller (UCB-style updates)
   ─ hot-reload of policy

5. Data model
   ─ events, policies, judges-scores schema
   ─ retention windows
   ─ privacy considerations (redaction)

6. Deploy modes
   ─ docker-compose
   ─ Helm chart
   ─ scaling: where each component scales out, where it doesn't
──────────────────────────────────────────────────────────────────────────────
[Footer]
```

## Sections

(See layout.)

## Components

Same as Methodology: nav, sticky TOC, prose, code blocks, diagrams, footer.

## States

- Standard light/dark.
- Mobile: TOC collapses.

## Data

Static page. Numbers (timing budgets, scaling factors) hard-coded with last-updated.

## Interactions

- TOC links, smooth scroll.
- Diagram: hover any component → tooltip + link to "see this in the running dashboard" (deep-link to System health).
- Each "see source →" link goes to the GitHub directory for that component.

## Notes

- Sister page to the in-product Architecture link (which may be the same page rendered inside the dashboard shell).
