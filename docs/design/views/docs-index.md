# Docs Index

> **Tier 4** · spec v0 · auto-approved 2026-05-18 · `docs-index.md`
> Public-facing.

## Purpose

The docs landing. Routes the visitor to the right deep-dive: getting started, architecture, methodology, benchmarks, comparison, API reference.

## Layout

```
[Top nav — same as landing]
──────────────────────────────────────────────────────────────────────────────
                              Documentation

  Getting started                  Architecture
  Install · Quick start            How Cascadia is built
  Configuration                    Hot path · Shadow · Learning loop

  Methodology                      Benchmarks
  Why eval reliability matters     Reproducible run results
  Judge ensemble · Calibration

  Comparison                       API Reference
  vs LiteLLM / Portkey / RouteLLM  Endpoints · Schemas · Examples

  Roadmap (anchor)                 Contributing
  What's coming next               How to PR
──────────────────────────────────────────────────────────────────────────────
[Footer]
```

## Sections

Two-column grid of doc-section cards, each with title + 1-line summary + link.

## Components

Doc card (icon + heading + summary), top nav, footer.

## States

Standard.

## Data

Static. Card list is hardcoded in the SSG.

## Interactions

Cards are click-anywhere; hover lifts subtle.

## Notes

- This is the canonical jumping-off point from the landing footer.
