# Methodology (Eval Methodology Explainer)

> **Tier 2** · spec v0 · auto-approved 2026-05-18 · `methodology.md`
> Public-facing doc page (not behind login). Linked from landing footer + dashboard help.

## Purpose

The credibility document. Explains how Cascadia judges LLM output quality, how the judges are calibrated against human ratings, and what the agreement numbers mean. This is the page technical reviewers who read papers will scrutinize.

## Layout

```
[Top nav — same as landing]
──────────────────────────────────────────────────────────────────────────────
                              Methodology
                                                                          [TOC]
                                                                         · Why
                                                                         · How
Cascadia's whole pitch rests on the claim that we can                    · Bias
judge LLM output quality cheaply and credibly.                           · Cal.
This page explains the methodology in full.                              · Limits
                                                                         · Repro
──────────────────────────────────────────────────────────────────────────────
1. Why eval reliability is everything
   ─ paragraph explaining the closed-loop dependency
   ─ example failure mode if judges are biased

2. The judge ensemble
   ─ diagram of 3-judge architecture
   ─ table: judge model, prompt variant, vote weight
   ─ rationale for ensemble (diversity vs single-judge)

3. Bias mitigation
   ─ position bias (A-vs-B order swap)
   ─ self-preference bias (no judge scores its own family unfiltered)
   ─ verbosity bias (length-normalized prompt)
   ─ format bias (mention by name + sample)

4. Human calibration
   ─ calibration set (200 examples, methodology)
   ─ headline: Kendall's τ = 0.74 (95% CI: 0.67–0.81)
   ─ chart: judge score vs human score (scatter + best-fit)

5. Limits & open problems
   ─ judge cost (real $)
   ─ judge drift (model updates over time)
   ─ generalization to long-context, multimodal

6. Reproduce
   ─ `make bench` walkthrough
   ─ link to GitHub `bench/` directory
──────────────────────────────────────────────────────────────────────────────
[Footer — same as landing]
```

## Sections

(See layout)

## Components

Top nav (shared with landing), TOC sidebar (sticky), prose with code blocks + tables + a scatter chart, diagram (judge architecture), footer.

## States

- **Default:** as drawn.
- **Mobile:** TOC collapses to a "Jump to" dropdown at the top.
- **Light mode:** standard token swap. Diagrams use color tokens not hardcoded.

## Data

Static page. No live data. Numbers (Kendall's τ, ensemble agreement) are hardcoded with last-updated date; updated when the calibration is re-run.

## Interactions

- TOC links: smooth scroll, sticky behavior.
- Scatter chart: hover any point shows the example prompt + scores.
- "Reproduce" section: copy-curl-style snippets for `make bench` invocations.

## Notes

- This page is what makes the credibility claim work. Without it, the headline cost-savings number is unfalsifiable.
- Pattern reference: the OpenAI evals docs page, Anthropic responsible-scaling-policy page, or similar serious technical reads — not a marketing page.
