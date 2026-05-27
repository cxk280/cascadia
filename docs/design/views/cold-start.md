# Cold-start / Empty State

> **Tier 3** · spec v0 · auto-approved 2026-05-18 · `cold-start.md`
> Inherits [Dashboard shell](dashboard-shell.md).

## Purpose

What an operator sees right after installing Cascadia — no traffic, no clusters, no policy data. Should feel guided and confident, not broken.

## Layout

```
Breadcrumb: Overview                                                          
──────────────────────────────────────────────────────────────────────────────
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│   Welcome to Cascadia.                                                       │
│   You're seeing this view because no requests have hit the gateway yet.      │
│                                                                              │
│   ┌──────────────────────────────────────────────────────┐                   │
│   │ $ docker run -p 8080:8080 ghcr.io/.../cascadia        │ [copy]            │
│   └──────────────────────────────────────────────────────┘                   │
│                                                                              │
│   Or test with curl:                                                         │
│   ┌──────────────────────────────────────────────────────┐                   │
│   │ curl http://localhost:8080/v1/chat/completions \      │ [copy]            │
│   │   -d '{"model":"auto","messages":[{"role":"user",…   │                   │
│   └──────────────────────────────────────────────────────┘                   │
│                                                                              │
│   Setup checklist:                                                           │
│   ☑  Cascadia is running (verified at 14:22:18)                              │
│   ☐  At least one provider API key configured  →  Configure                 │
│   ☐  Starter policy loaded                       (auto on first request)     │
│   ☐  First request received                                                  │
│                                                                              │
│   Once requests start flowing this view will replace itself with your        │
│   Overview dashboard.                                                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Sections

1. **Welcome header** — calm, no marketing.
2. **Quick start snippets** — Docker + curl, copy-able.
3. **Setup checklist** — visible progress with done/todo states.
4. **What-happens-next** sentence.

## Components

Code block with copy, checklist row (icon + label + status), inline CTA link.

## States

- **Step 1 incomplete (Cascadia not reachable):** the first checklist row turns danger; everything below shows as blocked.
- **Step 2 incomplete:** Configure link is the primary CTA.
- **All steps complete except first request:** big animated arrow + "Waiting for your first request…" pulse.

## Data

- `setup_status`: `{reachable, providers_count, has_starter_policy, requests_count}`.
- Live websocket so the view replaces itself the moment the first request lands.

## Interactions

- Copy buttons for the snippets.
- Configure link → Models & providers, scrolled to Add provider.
- The view auto-transitions to Overview after the first request without a manual click (smooth crossfade).

## Notes

- "Auto-transition to Overview" is a small detail but important — operators should feel the system "wake up" the moment they hit it.
