# Audit Log

> **Tier 4** · spec v0 · auto-approved 2026-05-18 · `audit-log.md`
> Inherits [Dashboard shell](dashboard-shell.md).

## Purpose

Append-only record of every config change Cascadia made (manual or automatic). Operators audit, reviewers verify.

## Layout

```
Breadcrumb: Audit log                                              [Filter…] [Export CSV]
──────────────────────────────────────────────────────────────────────────────────
┌──────────┬──────────────────┬──────────────────┬───────────────────────────┐ │
│ When     │ Actor            │ Change           │ Detail                    │ │
├──────────┼──────────────────┼──────────────────┼───────────────────────────┤ │
│ 14:22    │ policy-ctrl      │ policy.refit     │ 3 thresholds updated      │ │
│ 13:14    │ chris@cking.me   │ policy.override  │ Creative · threshold 0.62 │ │
│ 12:00    │ system           │ key.rotated      │ provider/anthropic        │ │
│ 09:32    │ chris@cking.me   │ rule.created     │ Calibration drift         │ │
│ 08:15    │ policy-ctrl      │ cluster.refit    │ 18 clusters re-fit         │ │
└──────────┴──────────────────┴──────────────────┴───────────────────────────┘
```

## Sections

1. **Filter row** — actor, action type, time range.
2. **Log table** — sortable by When (default desc).
3. **Drawer** — click row → full before/after diff.

## Components

Data table (virtualized), filter chip, drawer with JSON diff viewer.

## States

- Filtered empty: "No matching entries in this range."
- Loading skeleton.

## Data

- `audit_entries`: `[{ts, actor, action, target, before, after, ip?}]`.
- Append-only — UI never edits.

## Interactions

- Click row → JSON diff drawer.
- Export CSV honors current filter.

## Notes

- Even auto changes (policy controller refits) appear here with actor `policy-ctrl`. Symmetry with human edits is what makes the log useful.
