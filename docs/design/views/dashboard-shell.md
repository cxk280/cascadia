# Dashboard Shell — Shared Layout

> **Shared spec** · v0 · auto-approved 2026-05-18 · `dashboard-shell.md`
> Not a view itself. Inherited by every operator-dashboard view (#09–#25).

## Purpose

Every dashboard view shares the same outer chrome. Speccing it once means each view spec can focus on its own content area, and the design language (nav, breadcrumbs, mode toggle) stays consistent.

## Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ TOP BAR  Cascadia · search…           Status · Mode · Help · User       │
├─────────┬───────────────────────────────────────────────────────────────┤
│         │  Breadcrumb · View                     [primary action]       │
│ SIDEBAR ├───────────────────────────────────────────────────────────────┤
│         │                                                               │
│ Live    │                                                               │
│  ●Over  │                                                               │
│  ·Traffic│                  CONTENT AREA                                │
│  ·Pareto│                  (per-view content lives here)                │
│  ·Clust │                                                               │
│  ·Quality│                                                              │
│  ·Cost  │                                                               │
│  ·Health│                                                               │
│         │                                                               │
│ Config  │                                                               │
│  ·Policy│                                                               │
│  ·Models│                                                               │
│  ·Shadow│                                                               │
│  ·Judges│                                                               │
│         │                                                               │
│ Meta    │                                                               │
│  ·Keys  │                                                               │
│  ·Settings                                                              │
│  ·Audit │                                                               │
└─────────┴───────────────────────────────────────────────────────────────┘
```

## Top bar

- Height: 56 px. Background `bg.surface`. Bottom border `border.subtle`.
- **Left:** Cascadia wordmark (JetBrains Mono 15px) · 24px gap · search input (placeholder: "Search requests, clusters, models…").
- **Right (ltr):** Live-status pill (●Live · ●Paused · ●Degraded) · mode toggle (Dark/Light icon) · help icon · user menu (avatar + caret).
- Search opens an omnibox modal (cmd-k) — separate component spec if needed.

## Sidebar

- Width: 240 px (collapses to 56 px icon-only). Background `bg.surface`. Right border `border.subtle`.
- Section headers in eyebrow style (`text.secondary`, ALL CAPS, 12 px): **LIVE**, **CONFIG**, **META**.
- Items: icon + label, 32 px row height, 8 px gap. Hover `bg.surface-2`. Active state: `accent.primary` 2 px left bar + `text.primary`.
- **LIVE** group: Overview, Live traffic, Pareto frontier, Clusters, Quality, Cost, Health.
- **CONFIG** group: Routing policy, Models & providers, Shadow routing, Judges, Calibration.
- **META** group: API keys, Settings, Audit log.
- Bottom: collapsed/expanded toggle + version badge (`v0.0.1-phase0`).

## Content area

- Breadcrumb row: 48 px tall. `text.secondary` "Section / View". Right side reserved for the view's primary action button (e.g., "Add cluster," "Export CSV").
- Below: full-width content with 32 px page padding on all sides.
- Max content width: 1440 px (wider than landing — operator screens, not marketing).

## States

- **Loading:** sidebar visible; content area shows skeletons matching the view's expected layout.
- **Degraded:** top-bar status pill turns `accent.warn`, click → System health view filtered to the failing component.
- **Disconnected:** thin banner above breadcrumb in `accent.danger` muted: "Lost connection to Cascadia API. Retrying…" with retry button.
- **Light mode:** mirrors all colors per the light-mode tokens; otherwise identical.

## Data needs

- Live status (proxy heartbeat + judge worker + policy controller).
- Unread count for Alerts (if any) — small dot badge on Health item.
- Build/version string for footer.

## Open questions

- Org switcher: does the v1 self-hosted single-org UI need an org switcher chip in the top bar? Recommend: yes as a stub for v2, today it's a placeholder showing "default-org" with a tooltip explaining single-org is current limit.
- Notification inbox vs Alerts page: keep them separate — inbox is a popover on the bell icon (not a full view), Alerts page is the full management view.
