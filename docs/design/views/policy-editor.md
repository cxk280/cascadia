# Routing Policy Editor

> **Tier 1** · spec v0 · auto-approved 2026-05-18 · `policy-editor.md`
> Inherits [Dashboard shell](dashboard-shell.md).

## Purpose

The operator's control surface over routing decisions. Set per-cluster thresholds, override the auto-tuner, and review policy history. By default Cascadia auto-tunes; this view is for when an operator wants explicit control.

## Layout

```
Breadcrumb: Routing policy editor                         [Auto-tune: ON ▾] [Save]
──────────────────────────────────────────────────────────────────────────────────
┌──────────────────────────────────────────────────────────────────────────────┐
│  Mode banner                                                                 │
│  ● Auto-tune ON — Policy controller refits per-cluster thresholds every 6h.  │
│    Last refit: 4h 12m ago. Next: 1h 48m. [Pause auto-tune]                   │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ Per-cluster policy table                                                     │
│ ┌──────────────┬────────────┬────────────┬──────────┬──────────┬──────────┐ │
│ │ Cluster      │ Tier 1     │ Tier 2     │ Threshold│ Escal. % │ Locked?  │ │
│ ├──────────────┼────────────┼────────────┼──────────┼──────────┼──────────┤ │
│ │ Code Q&A     │ Haiku ▾    │ Sonnet ▾   │ ●─0.74   │ 12%      │ ☐        │ │
│ │ Math         │ Haiku ▾    │ Sonnet ▾   │ ●──0.81  │ 7%       │ ☐        │ │
│ │ Creative     │ Sonnet ▾   │ Opus ▾     │ ●─0.62   │ 32%      │ ☑ locked │ │
│ │ Simple chat  │ Haiku ▾    │ Sonnet ▾   │ ●───0.91 │ 2%       │ ☐        │ │
│ │ Code complete│ Haiku ▾    │ Sonnet ▾   │ ●──0.69  │ 18%      │ ☐        │ │
│ │ … 14 more    │            │            │          │          │          │ │
│ └──────────────┴────────────┴────────────┴──────────┴──────────┴──────────┘ │
│                                                                              │
│  Locked rows are excluded from auto-tune. Edit any cell to override.         │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ Policy history (timeline)                                                    │
│  ─── 4h 12m ago: Auto-tune refit · 3 thresholds updated · click to diff      │
│  ─── 10h ago: Manual override · Creative cluster · operator: chris@cking.me  │
│  ─── 1d 6h ago: Auto-tune refit · 7 thresholds updated                       │
│  ─── 2d ago: Policy v0.0.4 promoted from staging                             │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Sections

1. **Mode banner** — auto-tune on/off + status + next refit.
2. **Per-cluster policy table** — editable. Threshold cell is a mini-slider with numeric input.
3. **Policy history** — append-only log of policy changes. Click any entry → diff modal.

## Components

Toggle (mode banner), data table with editable cells, dropdown (model picker), mini-slider, checkbox, timeline list, diff modal.

## States

- **Auto-tune OFF:** banner turns `accent.warn`: "All thresholds frozen at current values. Cascadia is not learning. [Re-enable auto-tune]"
- **Pending change:** dirty rows show with `accent.warn` left border; floating "Save 3 changes / Discard" bar appears at bottom.
- **Conflict (auto-tune ran while you were editing):** modal "Auto-tune updated 2 thresholds while you were editing. Merge or override?"
- **Empty (no clusters yet):** disabled state matching the Clusters empty state.

## Data

- `policy`: array of `{cluster_id, tier_1_model, tier_2_model, threshold, escalation_rate, locked, last_modified, last_modified_by}`.
- `policy_history`: append-only events with full before/after policy snapshots.

## Interactions

- Threshold cell: drag mini-slider OR direct numeric entry. Real-time preview shows projected escalation rate on a tiny chart in the cell.
- Lock toggle: when checked, excludes that row from auto-tune.
- Save: opens confirmation showing diff + traffic projection ("This will increase Tier-2 calls by ~$8/day").
- Pause auto-tune: opens confirmation explaining the implication.

## Notes

- Confirmation modals must show the **expected cost/quality delta** from the projection model — operators should never apply policy changes without seeing what they're committing to.
- "Locked" rows are exempt from auto-tune but still get shadow-evaluated; the system can detect that a locked policy has drifted from optimal and surface an alert.
