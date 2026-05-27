# Overview — Operator Home

> **Tier 1** · spec v0 · auto-approved 2026-05-18 · `overview.md`
> Inherits [Dashboard shell](dashboard-shell.md).

## Purpose

The first view the operator sees after login. Answers in three glances: *Is it working? Am I saving money? Is quality OK?* — then surfaces anything that needs attention.

## Layout

```
Breadcrumb: Overview                                       [Time range ▾] [Export]
──────────────────────────────────────────────────────────────────────────────────
┌──────────────────────────────────────────────────────────────────────────────┐
│  HEADLINE: "You saved $1,247 in the last 7 days." (large, accent.primary)    │
│  Sub: "At 97.4% of Sonnet-everywhere quality. P99 routing overhead 1.6ms."   │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────┬──────────┬──────────┬──────────┐
│ Savings  │ Quality  │ Traffic  │ Latency  │  ◀ KPI strip (4 cards)
│ 78.2% ↑3 │ 97.4% →  │ 142.3k → │ 1.6ms ↓  │
│ vs no-   │ vs Sonnet│ requests │ P99 over │
│ cascade  │ baseline │ /day     │ -head    │
└──────────┴──────────┴──────────┴──────────┘

┌──────────────────────────────────────────┬─────────────────────────────────┐
│ Pareto position (mini)                   │ Top clusters by traffic         │
│  ─ small Pareto frontier                 │  ┌──────────────────────────┐   │
│  ─ current point (dot)                   │  │ Code Q&A     38.1% · $$$ │   │
│  ─ "What if I moved this?" →             │  │ Math         22.4% · $$  │   │
│                                          │  │ Creative     14.0% · $$$ │   │
│                                          │  │ Simple chat   9.7% · $   │   │
│                                          │  │ + 14 more →               │   │
│                                          │  └──────────────────────────┘   │
└──────────────────────────────────────────┴─────────────────────────────────┘

┌──────────────────────────────────────────┬─────────────────────────────────┐
│ Recent activity (event feed, last 50)    │ Needs attention                 │
│  ▸ Policy controller refit (cluster #4)  │  ─ Calibration set drift +0.08  │
│  ▸ Quality regression detected ↓2.1%     │  ─ Anthropic key 6d to expiry   │
│  ▸ Sonnet escalation rate 12% → 14%      │  ─ Judge ensemble disagreement  │
│  ▸ Shadow batch completed (n=420)        │     spike on cluster #11        │
│  ▸ Provider Anthropic latency +14%       │                                 │
│  ▸ View all →                            │  View all alerts →              │
└──────────────────────────────────────────┴─────────────────────────────────┘
```

## Sections

1. **Headline savings card** — big number, calm presentation. The single most important fact on the page.
2. **KPI strip** — 4 cards: savings %, quality vs baseline, traffic volume, P99 latency. Each with a small trend indicator (↑/↓/→) and "vs baseline" microcopy.
3. **Pareto position mini** — links to full Pareto frontier explorer. Same chart visual as the landing, but smaller and showing live data.
4. **Top clusters by traffic** — top-5 clusters with traffic %, cost relative indicator ($/$$/$$$), link to clusters view.
5. **Recent activity** — event feed (policy updates, regressions, batches, provider events). Click any event to drill in.
6. **Needs attention** — surfaced alerts that aren't urgent enough to interrupt but the operator should know about.

## Components

From design system: dashboard shell, KPI card, mini-chart, event-row, alert-card, time-range picker, button.

## States

- **Empty (no traffic yet):** headline becomes "Awaiting your first request" with a code snippet showing the OpenAI base URL swap; KPI cards show "—".
- **Loading:** skeletons for all six cards.
- **Degraded:** if the proxy is unreachable, replace headline with "Cascadia API unreachable — showing cached data from 2m ago" + retry button.
- **Light mode:** standard token swap.

## Data

- KPIs: `savings_pct`, `quality_pct`, `traffic_24h`, `p99_latency_ms`, each with `delta` for trend.
- Pareto: same shape as the landing chart (array of model configs + current operating point).
- Recent activity: paginated event log; latest 50 here.
- Needs attention: 0..N alert objects (severity ≤ warning; critical alerts interrupt with a top-bar banner from the shell).

## Interactions

- Time range picker (default: 7 days; options: 24h, 7d, 30d, 90d, custom) re-renders all numbers.
- Click any KPI → drills into the corresponding deep view (Cost, Quality, Live traffic, Health).
- Click event in activity feed → opens contextual drawer with full event payload.
- Pareto mini "What if I moved this? →" deep-links to the full explorer with the slider pre-positioned.

## Notes

- The headline savings number must be **conservative** — calculated against shadow-eval data, not aspirational. The KPI strip's "vs baseline" microcopy is the rigorous claim.
- This is the screenshot that goes in the README under "What it looks like in production."
