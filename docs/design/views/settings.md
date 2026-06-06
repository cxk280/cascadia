# General Settings

> **Tier 4** · spec v0 · auto-approved 2026-05-18 · `settings.md`
> Inherits [Dashboard shell](dashboard-shell.md).

## Purpose

Org-level settings that don't live anywhere more specific.

## Layout

```
Breadcrumb: Settings                                                    [Save]
──────────────────────────────────────────────────────────────────────────────────
Sections (each is a collapsible group):

General
  Organization name       [Cascadia]
  Default time zone       UTC ▾
  Default time range       7d ▾

Data & retention
  Request log retention    30 days ▾
  Judge score retention    180 days ▾
  Redact prompts in UI     ☑ (recommended)

Telemetry
  Send anonymous usage     ☐ off  ●
  Send anonymous errors    ☑ on
  Read what we collect →

Danger zone
  Reset all clusters and policy        [Reset…]
  Wipe all stored events               [Wipe…]
  Export all data (JSON)               [Export]
```

## Sections

(See layout)

## Components

Form rows, dropdown, checkbox, danger button (with double-confirm modal).

## States

- Dirty-state floating Save bar.
- Danger actions require typed-confirmation.

## Data

- `org_settings`: arbitrary key/value blob persisted in DB.

## Interactions

- Each danger action has a 2-step confirmation (typed phrase).
- Export triggers download.

## Notes

- Retention is the most-tuned setting. Default 30 days for events is generous for a demo deployment; production users may go shorter for privacy.
