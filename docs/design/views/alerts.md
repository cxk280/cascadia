# Alerts & Incidents

> **Tier 3** · spec v0 · auto-approved 2026-05-18 · `alerts.md`
> Inherits [Dashboard shell](dashboard-shell.md).

## Purpose

The list of alert rules, their current state, and the incident log. Linked from System health's SLO burn callouts and the dashboard shell's degraded banner.

## Layout

```
Breadcrumb: Alerts & incidents                            [Active ▾] [Create rule]
──────────────────────────────────────────────────────────────────────────────────
Tabs:  [ Active  ·  All rules  ·  History  ]

Active
┌──────────────────────────────────────────────────────────────────────────────┐
│ ● Calibration drift               since 1d 4h    Watch                        │
│ ● Anthropic key expires            in 6 days      Warning                      │
│ ⚠ Ensemble disagreement spike      since 2h 14m   Investigating               │
│                                                                              │
│ Each row: severity dot, summary, since/duration, status pill                  │
└──────────────────────────────────────────────────────────────────────────────┘

All rules
┌──────────────────────────────────────────────────────────────────────────────┐
│ Rule                       Severity   Channel     Triggered (30d)  Enabled   │
│ Quality SLO burn          critical   slack-ops    1                ☑          │
│ Routing-overhead breach   critical   pagerduty    0                ☑          │
│ Calibration drift         warning    email        3                ☑          │
│ Anthropic key TTL         warning    slack-ops    1                ☑          │
│ Ensemble disagreement     warning    slack-ops    2                ☑          │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Sections

1. **Active tab** — currently-firing alerts.
2. **All rules tab** — manage rules.
3. **History tab** — past incidents with timeline.

## Components

Tab bar, alert row, rule row, severity dot, status pill, channel badge.

## States

- **Active empty:** "No active alerts. Last cleared 14h ago." (small green check)
- **Active critical:** automatic top-bar banner from shell + sound (toggleable).

## Data

- `active`: array of alert instances.
- `rules`: array of `{id, name, expression, severity, channels, enabled, triggered_count_30d}`.

## Interactions

- Click alert row → drawer with timeline, related events, runbook link.
- Create rule → wizard: pick metric, threshold, severity, channels.
- Acknowledge: marks an alert as seen but not cleared.

## Notes

- Channel integrations (Slack, PagerDuty, email) are out of scope for the mock but should be shown as wired-up.
