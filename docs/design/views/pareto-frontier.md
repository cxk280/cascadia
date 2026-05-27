# Pareto Frontier Explorer

> **Tier 1** · spec v0 · auto-approved 2026-05-18 · `pareto-frontier.md`
> Inherits [Dashboard shell](dashboard-shell.md).
> *This is the headline view of the whole product.* Treat with extra care.

## Purpose

Lets the operator explore the cost/quality tradeoff space their traffic actually lives in. Move a slider, see what would happen. This is where the "first LLM gateway that lets you navigate the Pareto frontier" claim is made tangible.

## Layout

```
Breadcrumb: Pareto frontier explorer                       [Cluster ▾] [Apply scenario]
──────────────────────────────────────────────────────────────────────────────────
┌──────────────────────────────────────────────────────────────────────────────┐
│                          PARETO FRONTIER CHART (large)                       │
│                                                                              │
│   Quality                                                                    │
│   100%┤                       ●Opus-everywhere                               │
│       │                  ●Sonnet-everywhere                                  │
│    98%┤              ◆ ◀── your current operating point (accent.primary)     │
│    97%┤              │  ◯ ←── target slider position (accent.warn dashed)    │
│    95%┤        ●GPT-4o                                                       │
│       │     ●Cascadia (learned)                                              │
│    90%┤         ●Static cascade                                              │
│       │ ●GPT-4o-mini                                                         │
│    80%┤●Haiku-everywhere                                                     │
│       │                                                                      │
│       └──────────────────────────────────────────────────── Cost ($/1k req)  │
│         $0.10    $0.30    $1.00     $3.00    $10.00    $30.00 (log scale)    │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────┬──────────────────────────────┐
│  Target quality slider                       │  Projected outcome           │
│  ─────●────────────────  98% of baseline      │                              │
│   80%                            100%        │  Cost: $0.42/1k (-12%)       │
│                                              │  Escalation rate: 18%        │
│  ☐ Apply per-cluster                          │  Risk: 1.2σ confidence       │
│  ☐ Pin to current operating point             │  ┌─────────────────────┐     │
│                                              │  │ Apply this policy   │     │
│                                              │  └─────────────────────┘     │
└──────────────────────────────────────────────┴──────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│  Per-cluster breakdown table                                                 │
│  ┌──────────────┬─────────┬──────────┬─────────┬──────────┬──────────────┐  │
│  │ Cluster      │ Traffic │ Cost/1k  │ Quality │ Threshold│ Pareto Δ     │  │
│  ├──────────────┼─────────┼──────────┼─────────┼──────────┼──────────────┤  │
│  │ Code Q&A     │ 38.1%   │ $0.31    │ 98.2%   │ 0.74     │ at frontier  │  │
│  │ Math         │ 22.4%   │ $0.18    │ 96.4%   │ 0.81     │ at frontier  │  │
│  │ Creative     │ 14.0%   │ $1.42    │ 98.9%   │ 0.62     │ +$0.14 above │  │
│  │ Simple chat  │  9.7%   │ $0.04    │ 99.1%   │ 0.91     │ at frontier  │  │
│  │ … 14 more    │   ─     │   ─      │   ─     │   ─      │     ─        │  │
│  └──────────────┴─────────┴──────────┴─────────┴──────────┴──────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Sections

1. **Pareto chart (large)** — primary visual. Points are model configurations the system has observed (including non-cascade baselines from synthetic comparison runs). Current operating point in `accent.primary`; target-slider position in `accent.warn` dashed circle.
2. **Slider + checkboxes** — drives the target-quality the operator wants to navigate toward.
3. **Projected outcome panel** — what happens if you apply: cost, escalation rate, risk band. Primary CTA: Apply this policy (opens confirmation modal).
4. **Per-cluster breakdown table** — for each cluster, current numbers + position relative to its own Pareto frontier. Cluster name links to Cluster explorer filtered to that cluster.

## Components

KPI strip (reused from Overview), Pareto chart (large variant), slider, checkbox group, projected-outcome card, data table with sortable headers, confirmation modal.

## States

- **Empty (insufficient shadow data):** Chart shows static reference points (vendor benchmarks) with a `text.muted` overlay: "Need 24h+ of shadow-routed traffic to plot your operating point. Currently: 4h." Slider disabled.
- **Loading:** chart skeleton with axis ticks present, dots animate in once data arrives (no layout shift).
- **Applying:** primary CTA enters loading state; chart shows both current and target points with arrow between.
- **Confidence too low:** if shadow sample for a target is <100, risk band shows in `accent.danger` and CTA is disabled with tooltip "Need more shadow data."

## Data

- `frontier_points`: array of `{config_id, name, cost_per_1k, quality_pct, traffic_pct_if_applied, sample_n, confidence_band}`.
- `current_operating_point`: same shape.
- `target_quality`: number 0..1, from slider.
- `clusters_breakdown`: array per cluster.

## Interactions

- Hovering a point: tooltip with config details, link to "show me requests this would route." 
- Slider drag: real-time recompute (debounced 100ms). Chart updates the dashed target circle.
- Apply per-cluster toggle: when on, instead of a single target, the operator gets per-row sliders in the breakdown table.
- Pin checkbox: locks the current operating point so target-slider movements compute deltas against the locked point, not the live one.
- Apply this policy CTA: confirmation modal with full diff vs current policy + "schedule for traffic ramp" toggle (apply over 1h vs immediately).

## Notes

- The chart's log-scale x-axis is non-negotiable — linear scale puts the entire interesting region on the left fifth and is unreadable.
- "Pareto Δ" column in the breakdown is the headline diagnostic: a cluster that isn't at its frontier is a tuning opportunity.
- This view's screenshot is the second most important after the landing chart. Spend Figma time on chart polish.
