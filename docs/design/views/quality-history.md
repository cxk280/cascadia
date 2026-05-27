# Quality History

> **Tier 2** · spec v0 · auto-approved 2026-05-18 · `quality-history.md`
> Inherits [Dashboard shell](dashboard-shell.md).

## Purpose

How is quality trending? Where did the last regression come from? The view answers both for an aggregate and per-cluster.

## Layout

```
Breadcrumb: Quality history                              [Time range ▾] [Per-cluster ☑]
──────────────────────────────────────────────────────────────────────────────────
┌─────────────────────────────────────────────────────────────────────────────┐
│  Quality over time (large line chart)                                       │
│  100%┤      ──────────────────                                              │
│   98%┤────                  ────                                            │
│   95%┤                          ────────                                    │
│      └────────────────────────────────────────                              │
│  Annotations: policy changes (▼), deploys (◆), alerts (●)                   │
└─────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────┬───────────────────────────────────────────┐
│ Regression detector            │ Recent regressions                        │
│  ─ Z-score band ±2σ            │  ─ 2d ago · Creative cluster · ↓2.1%      │
│  ─ Sustained-drop heuristic    │       cause: policy refit changed Tier 1  │
│                                │  ─ 4d ago · Code Q&A · ↓0.8% (recovered)  │
│                                │  ─ View all →                             │
└────────────────────────────────┴───────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  Per-cluster small multiples                                                │
│  [Code Q&A 7d]  [Math 7d]  [Creative 7d]  [Simple chat 7d]  [+14 more]      │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Sections

1. **Main quality chart** — line chart with policy-change annotations.
2. **Regression detector + recent regressions** — detection settings + log.
3. **Per-cluster small multiples** — sparkline per cluster, click to deep-dive.

## Components

Line chart, annotation glyphs, regression log row, small-multiples grid, sparkline.

## States

- **Empty (need more shadow data):** "Need at least 7 days of shadow data to render trends. Currently: 3d 12h."
- **Active regression:** banner above chart in `accent.danger` with link to drill in.
- **Loading:** skeleton chart.

## Data

- `quality_series`: `[{timestamp, quality_pct, sample_n}]` aggregate + per-cluster.
- `regressions`: `[{detected_at, cluster_id, magnitude, cause_link, status: active|recovered}]`.
- `policy_change_annotations`: timestamps + summaries for hover popover on chart.

## Interactions

- Hover chart → tooltip with date, quality %, sample size, any annotation.
- Click annotation glyph → context (policy diff, deploy info).
- Per-cluster sparkline click → filters main chart to that cluster.

## Notes

- The regression-detector logic should match what the policy controller uses to halt or rollback auto-tuning. The view exposes the same signal humans can audit.
