# Comparison Page

> **Tier 3** · spec v0 · auto-approved 2026-05-18 · `comparison.md`
> Public-facing.

## Purpose

Honest, sourced comparison vs LiteLLM, Portkey, RouteLLM, and raw OpenAI. Establishes where Cascadia is unique, and concedes where it's not.

## Layout

```
[Top nav]
──────────────────────────────────────────────────────────────────────────────
                            How Cascadia compares                Updated 2026-05-18

This page reflects each tool as of [DATE]. Corrections welcome via PR.

[ Comparison matrix — same as landing §4.7 but more detail ]

Capability                         Cascadia  LiteLLM  Portkey  RouteLLM  Raw
─────────────────────────────────  ────────  ───────  ───────  ────────  ───
OpenAI-compatible API              ✓         ✓        ✓        —         ✓
Multi-provider routing             ✓         ✓        ✓        ✓         —
Static cost-based routing          ✓         ✓        ✓        ~         —
Cascading inference                ✓         —        —        ~         —
Learned thresholds from prod       ✓         —        —        —         —
Counterfactual shadow eval         ✓         —        —        —         —
Per-cluster routing policy         ✓         —        —        ~         —
Self-hostable                      ✓         ✓        ✓        ✓         —
Open source license                MIT       MIT      AGPL     MIT       —
Production observability shipped   ✓         ~        ✓        —         —
…

Source notes:
  ✓ = full support
  ~ = partial / requires significant config
  — = not supported or vendor-specific

[ "Why we built our own" paragraphs ]
  ─ LiteLLM is the gold standard for "OpenAI-compatible gateway." We use…
  ─ Portkey has great observability. We don't compete on the ops side…
  ─ RouteLLM showed the cost/quality frontier is real. We…

When NOT to use Cascadia:
  ─ Single-model fixed-quality workload → just use that provider's SDK.
  ─ <1k requests / day → savings won't cover the operational complexity.
  ─ Hard quality SLA with humans-in-the-loop → use the SLA, not a router.
──────────────────────────────────────────────────────────────────────────────
[Footer]
```

## Sections

1. **Header + freshness disclaimer**
2. **Capability matrix**
3. **Per-competitor write-up** — honest, friendly. Cite their docs.
4. **When NOT to use Cascadia** — credibility move.

## Components

Comparison table, prose blocks, attribution links.

## States

Standard light/dark.

## Data

Hand-maintained from `docs/comparison-methodology.md`. Each cell has a source pin (hover to see).

## Interactions

- Hover a cell → tooltip with source / version date.
- "Source notes" expand panel.

## Notes

- "When NOT to use Cascadia" is the most-read paragraph on this page. Operators trust products that say no.
