# System Health

> **Tier 1** · spec v0 · auto-approved 2026-05-18 · `system-health.md`
> Inherits [Dashboard shell](dashboard-shell.md).

## Purpose

The "is the plumbing OK?" view. Shows the health of each component (proxy, judges, controller, DB, queues), SLO burn-rate dashboards, and recent deploys. This is the screen DevOps reviewers will look at hardest.

## Layout

```
Breadcrumb: System health                                  [Restart subsystem ▾]
──────────────────────────────────────────────────────────────────────────────────
┌──────────────────────────────────────────────────────────────────────────────┐
│ Component status grid                                                        │
│  ┌──────────────┬──────────────┬──────────────┬──────────────┐               │
│  │ Proxy        │ Judge worker │ Policy ctrl  │ Postgres     │               │
│  │ ● Healthy    │ ● Healthy    │ ● Healthy    │ ● Healthy    │               │
│  │ 12 replicas  │ 4 replicas   │ 1 replica    │ 1 primary    │               │
│  │ p99 1.6ms    │ queue: 14    │ next: 1h48m  │ 23% conns    │               │
│  └──────────────┴──────────────┴──────────────┴──────────────┘               │
│  ┌──────────────┬──────────────┬──────────────┬──────────────┐               │
│  │ Redis        │ NATS         │ Embedder     │ Providers    │               │
│  │ ● Healthy    │ ● Healthy    │ ● Healthy    │ ● 1 degraded │               │
│  │ 28MB used    │ 0 backlog    │ 0.3ms p99    │ Anthropic ↑  │               │
│  └──────────────┴──────────────┴──────────────┴──────────────┘               │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────┬─────────────────────────────────┐
│ SLO burn-rate                            │ Recent deploys                  │
│  Routing-overhead SLO (P99 < 2ms)        │ ─ proxy v0.4.2  2h ago  ↗ chris │
│  ● 0.3 × budget (28d) · OK               │ ─ judge v0.4.1  6h ago  ↗ chris │
│                                          │ ─ ctrl v0.3.7   1d ago  ↗ chris │
│  Availability SLO (99.9%)                │                                 │
│  ● 0.1 × budget (28d) · OK               │ View change history →           │
│                                          │                                 │
│  Quality regression SLO (Δq > -0.03)     │                                 │
│  ⚠ 1.4 × budget (28d) · Watch            │                                 │
└──────────────────────────────────────────┴─────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ Latency observability                                                        │
│   Routing overhead (P50 / P95 / P99) line chart, last 24h                    │
│   End-to-end latency by tier (stacked area, last 24h)                        │
│   Provider latency comparison (bar chart, last 1h)                           │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Sections

1. **Component status grid** — 8 cards, one per major subsystem. Color dot for status, key metric for each.
2. **SLO burn-rate** — three SLOs Cascadia commits to: routing overhead, availability, quality regression. Show 28d budget consumption.
3. **Recent deploys** — last few deploys with operator + link to change history.
4. **Latency observability** — three charts: routing overhead, end-to-end by tier, provider latency comparison.

## Components

Status card, SLO burn-down indicator, deploy-item, line chart, stacked area chart, bar chart, status-dot.

## States

- **Degraded:** dot turns `accent.warn`; card border + status text turn warn; "View incident" link appears.
- **Down:** dot turns `accent.danger`; card has elevated style + automatic top-bar banner from shell.
- **SLO breach:** burn-rate row turns `accent.danger`; click → opens runbook in docs panel.
- **No data (just-started):** charts show skeleton with "Waiting for first metrics window (5m)…"

## Data

- Per-component: `{name, replicas, version, status: healthy|degraded|down, key_metric}`.
- SLO: `{name, definition, budget_consumed_pct, burn_rate, window}`.
- Deploys: `{component, version, deployed_at, deployed_by, link_to_commit}`.

## Interactions

- Click component card → opens drawer with: full metric set, recent logs (last 50 lines), restart button (with confirmation), open in Grafana link.
- SLO row click → opens detailed SLO breakdown view (line chart of burn rate over time + linked alerts).
- Deploy row click → opens diff view (commit range + changelog).

## Notes

- The SLO definitions live in the docs/methodology; this view links to them.
- The "Quality regression SLO" is unusual but important — it's what makes the closed-loop story credible. If learned policy ever causes quality to drop, this SLO catches it before users notice.
