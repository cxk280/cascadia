# 500 — Unrecoverable Error

> **Tier 4** · spec v0 · auto-approved 2026-05-18 · `error-500.md`

## Purpose

Catch-all for unrecoverable errors. Gives the operator an incident ID to file a report with, plus links to logs.

## Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│                    500                                                       │
│                    ─────                                                     │
│                    Cascadia hit an unrecoverable error.                      │
│                                                                              │
│                    Incident: incident-014af3                                 │
│                    Component: dashboard-api                                  │
│                    [Copy incident ID]                                        │
│                                                                              │
│                    What to do:                                               │
│                      → Try again. Some errors are transient.                 │
│                      → File a report on GitHub  (includes incident ID)       │
│                      → Open System health                                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Sections

- Big 500.
- Incident ID + component.
- Action list.

## Components

H1, prose, code-block (for the incident ID), link list, GitHub-issue prefill link.

## States

- If proxy is reachable but dashboard-api failed: link to System health (the proxy can still answer).
- If proxy unreachable: link to local logs path with copy-able tail command.

## Data

- `incident_id`: assigned by the server.
- `failing_component`: known after the error.
- Optional stack trace shown only if `?debug=1`.

## Interactions

- Copy incident ID.
- File a report: opens GitHub new-issue with title prefilled `[incident-014af3] dashboard-api 500`.

## Notes

- Show the incident ID prominently — it's the one piece of state worth reporting.
