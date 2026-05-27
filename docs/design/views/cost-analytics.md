# Cost Analytics

> **Tier 2** · spec v0 · auto-approved 2026-05-18 · `cost-analytics.md`
> Inherits [Dashboard shell](dashboard-shell.md).

## Purpose

Where the dollars went and where they're going. Operators want to: (a) confirm savings, (b) understand spend distribution, (c) project monthly cost.

## Layout

```
Breadcrumb: Cost analytics                            [Time range ▾] [vs baseline ☑]
──────────────────────────────────────────────────────────────────────────────────
┌────────────┬────────────┬────────────┬────────────┐
│ Spend (7d) │ Saved (7d) │ Projected  │ Per request│
│ $384       │ $1,247     │ $1,650/mo  │ $0.0027    │
│ ↓18% wk    │ ↑23% wk    │ at current │ ↓26% q-o-q │
└────────────┴────────────┴────────────┴────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  Spend over time (stacked area: by model tier)                              │
│  $/day                                                                       │
│       ┌─ Haiku                                                              │
│       │── Sonnet                                                            │
│       │═══ Opus (shadow only)                                               │
│       │                                                                      │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────┬─────────────────────────────────┐
│ Breakdown by cluster                     │ Breakdown by API key            │
│  Code Q&A     $134   38.1%               │  sk_live_abc  $221  ↑           │
│  Math         $42    22.4%               │  sk_live_xyz  $142  →           │
│  Creative     $78    14.0% [highest $/k] │  + 3 more                       │
│  …                                       │                                 │
└──────────────────────────────────────────┴─────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ Counterfactual: what would this have cost on…                               │
│  Sonnet-everywhere baseline       $1,631                                    │
│  Haiku-everywhere (lossy)         $48                                       │
│  Static cascade (manual threshold) $542                                     │
│  Cascadia (learned)                $384  ← you                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Sections

1. **KPI strip** — spend, saved, projected, per-request.
2. **Spend over time** — stacked area by model tier.
3. **Breakdown by cluster + by API key** — tables.
4. **Counterfactual table** — what the same traffic would cost on alternate routing strategies (computed from shadow data).

## Components

KPI card, stacked area chart, breakdown table, counterfactual comparison block.

## States

- **Empty:** "Need 7 days of data for projections; showing observed spend only" + only KPI strip + observed chart.
- **Loading:** skeletons.
- **Negative savings (regression!):** banner in `accent.danger`: "Cascadia is currently more expensive than the static baseline. Click to investigate."

## Data

- `kpi`: `{spend_window, saved_window, projected_monthly, per_request_avg, deltas}`.
- `spend_series`: by tier, per day/hour.
- Breakdowns: cluster, API key, model.
- Counterfactuals: cost projections from shadow-data extrapolation.

## Interactions

- Time range picker.
- Toggle "vs baseline" on/off.
- Click cluster row → Clusters view filtered.
- Click API key row → API keys view.

## Notes

- The counterfactual table is the most credible savings claim — it shows what the same traffic actually would have cost elsewhere, not vendor-claimed numbers.
