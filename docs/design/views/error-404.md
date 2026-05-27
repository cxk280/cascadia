# 404 — Not Found

> **Tier 4** · spec v0 · auto-approved 2026-05-18 · `error-404.md`

## Purpose

Page-not-found state for both dashboard and public surfaces.

## Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│                    404                                                       │
│                    ─────                                                     │
│                    That page isn't here.                                     │
│                                                                              │
│                    The URL you followed doesn't match any                    │
│                    Cascadia route. Try one of these:                         │
│                                                                              │
│                    →  Overview                                               │
│                    →  Docs                                                   │
│                    →  Recent requests                                        │
│                                                                              │
│                    URL: /weird/path/typo                                     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Sections

- Big 404, calm tone.
- Three contextual suggestions (different lists for dashboard vs public).
- Show the offending URL.

## Components

H1, prose, link list.

## States

- Dashboard-shell variant: in-shell, sidebar still works.
- Public variant: with top nav and footer; no sidebar.

## Notes

- Keep the personality minimal. Avoid "Oops!" and ASCII pets.
