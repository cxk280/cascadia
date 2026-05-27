# Shadow Routing Config

> **Tier 3** · spec v0 · auto-approved 2026-05-18 · `shadow-routing.md`
> Inherits [Dashboard shell](dashboard-shell.md).

## Purpose

Controls the counterfactual shadow routing rate — what % of cascade decisions are mirrored to the higher tier for eval. Higher % = better learning signal, higher cost. Operators tune this here.

## Layout

```
Breadcrumb: Shadow routing                                       [Save] [Defaults]
──────────────────────────────────────────────────────────────────────────────────
┌──────────────────────────────────────────────────────────────────────────────┐
│ Global shadow rate                                                           │
│                                                                              │
│   ─────●─────────  5.0%                                                      │
│   0%                              25%                                        │
│                                                                              │
│   Projected shadow cost: $4.20 / day (≈ $126 / mo)                          │
│   Expected eval throughput: 1,420 judged pairs / day                         │
│   Confidence-band tightening: -23% (vs current rate)                         │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ Per-cluster overrides                                                        │
│  Cluster        Rate    Reasoning (optional)                                 │
│  Code Q&A       5.0%   inherit global                                        │
│  Creative       12.0%  drift suspected, more eval needed                     │
│  Math           5.0%   inherit                                               │
│  + add override                                                              │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ Schedule (optional)                                                          │
│  ☑ Off-peak boost: bump global to 15% between 02:00–06:00 UTC                │
│  ☐ Pause on weekends                                                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Sections

1. **Global rate slider with projections**
2. **Per-cluster overrides table**
3. **Schedule** — time-window rate overrides

## Components

Slider, projection card, data table, checkbox, schedule editor.

## States

- **Save pending**: dirty-state floating bar.
- **Cost over budget**: if projection exceeds operator-configured daily budget, slider clamps and shows warning.

## Data

- `global_rate`: float 0..1.
- `overrides`: `[{cluster_id, rate, reason}]`.
- `schedule`: time-windowed boosts / pauses.

## Interactions

- Slider drag: real-time projection update.
- Saving applies to next-decision; in-flight requests unaffected.

## Notes

- The "cost of evaluation" cap is the most common reason operators tune this. Make it cheap to ask "what if I doubled shadow?".
