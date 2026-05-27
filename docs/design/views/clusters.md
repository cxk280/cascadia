# Cluster Explorer

> **Tier 1** · spec v0 · auto-approved 2026-05-18 · `clusters.md`
> Inherits [Dashboard shell](dashboard-shell.md).

## Purpose

Lets the operator browse the semantic clusters Cascadia has discovered, understand what each one represents, and see how routing is performing per cluster. This is the "what is the AI doing?" view.

## Layout

```
Breadcrumb: Clusters                                        [Re-cluster] [Filter ▾]
──────────────────────────────────────────────────────────────────────────────────
┌─────────────────────────────────────────┬────────────────────────────────────┐
│ Cluster list                            │ Cluster detail (selected)          │
│ ┌─────────────────────────────────────┐ │                                    │
│ │ ●Code Q&A          38.1%  $0.31 ↑   │ │  Code Q&A                          │
│ │ ●Math              22.4%  $0.18 →   │ │  ─────────────                     │
│ │ ●Creative          14.0%  $1.42 ↑↑  │ │  54,212 requests · 38.1% of traffic│
│ │ ●Simple chat        9.7%  $0.04 →   │ │                                    │
│ │ ●Code completion    4.8%  $0.49 ↓   │ │  ┌───────────────────────────────┐│
│ │ ●Translation        3.1%  $0.22 →   │ │  │ Example prompts (5)           ││
│ │ ●Summarization      2.8%  $0.31 →   │ │  │ • "Why is my Rust closure…"   ││
│ │ ●Math word probs    2.0%  $0.18 ↑   │ │  │ • "Refactor this Python…"     ││
│ │ + 11 more…                          │ │  │ • "fix race condition in…"    ││
│ └─────────────────────────────────────┘ │  └───────────────────────────────┘│
│                                         │                                    │
│ ●= traffic share                        │  Routing policy                    │
│ $ = $/1k                                │  Tier 1: Haiku  Threshold: 0.74    │
│ ↑↓ = quality trend (7d)                 │  Tier 2: Sonnet  Escalation: 12%   │
│                                         │  Last refit: 4h ago                │
│                                         │  ┌──────────────────────────────┐  │
│                                         │  │ Edit routing policy →        │  │
│                                         │  └──────────────────────────────┘  │
│                                         │                                    │
│                                         │  Mini-charts row:                  │
│                                         │  • Traffic 24h sparkline           │
│                                         │  • Quality 7d                      │
│                                         │  • Cost 7d                         │
│                                         │  • Latency P99 7d                  │
│                                         │                                    │
│                                         │  Recent requests in this cluster → │
└─────────────────────────────────────────┴────────────────────────────────────┘
```

## Sections

1. **Cluster list (left)** — sortable, traffic-share dot, model micro-chip if there's a per-cluster override.
2. **Cluster detail (right)** — selected cluster's full profile.
3. **Example prompts** — 5 representative redacted prompt openings (full prompt requires drill-in). Lets the operator validate "yes, this is a code cluster."
4. **Routing policy summary** — tier 1/tier 2 models, escalation threshold, last refit. Link to edit.
5. **Mini-charts row** — traffic, quality, cost, latency sparklines.
6. **Recent requests** — link to Request detail filtered to this cluster.

## Components

Data table (cluster list), detail panel, prompt-example card, mini-chart, sparkline, breadcrumb-tag for "from Overview".

## States

- **Empty (no clusters yet):** "Clustering needs at least 1,000 requests to converge. Currently: 432." Shows progress bar to threshold.
- **Re-clustering:** banner above list: "Policy controller re-clustering — last seen distribution shown below." Disable Edit policy CTA during refit.
- **Disagreement / drift:** if a cluster's recent membership is drifting >threshold, show `accent.warn` chip on row.

## Data

- `clusters`: array of `{id, name, traffic_share, cost_per_1k, quality_pct, quality_delta_7d, last_refit, tier_1_model, tier_2_model, threshold, escalation_rate, sample_prompts: string[5]}`.
- Mini-chart series: time-bucketed metrics per cluster.

## Interactions

- Click cluster row → loads detail in right panel (no full page reload).
- "Re-cluster" top-action: opens modal explaining "Trigger an out-of-cycle re-clustering on the last 7d of traffic." Confirms before triggering.
- "Edit routing policy →" deep-links to Routing policy editor scoped to this cluster.
- Example prompts: click → opens request detail for that prompt (or anonymized sample if redaction is on).

## Notes

- Cluster names are auto-generated from the most common topical keywords + manually editable. Auto-name shows in `text.secondary`; if operator renamed, the manual name shows in `text.primary` and an "auto: original-name" chip appears.
- The example prompts visualisation is genuinely useful for AI/ML reviewers — most other tools hide the actual prompt distribution.
