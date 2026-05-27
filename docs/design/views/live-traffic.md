# Live Traffic Stream

> **Tier 2** · spec v0 · auto-approved 2026-05-18 · `live-traffic.md`
> Inherits [Dashboard shell](dashboard-shell.md).

## Purpose

The real-time firehose. Each row is one request; new rows stream in at the top. Operators use it during incident triage, after policy changes (to confirm the new behavior), and just to "feel" their traffic.

## Layout

```
Breadcrumb: Live traffic                          [Filter…] [Pause ▶] [Export CSV]
──────────────────────────────────────────────────────────────────────────────────
┌─────────────────────────────────────────────────────────────────────────────┐
│ Filter chips: cluster ▾ · model ▾ · escalated only ☐ · errors only ☐ · …    │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────┬──────────┬──────────┬────────┬─────────┬────────────────────────┐
│ Time     │ Cluster  │ Route    │ Tokens │ Latency │ Prompt preview         │
├──────────┼──────────┼──────────┼────────┼─────────┼────────────────────────┤
│ ●14:22:03│ Code Q&A │ Haiku    │ 312/187│ 842ms   │ Why does this Rust …   │
│  14:22:01│ Math     │ Haiku    │ 88/41  │ 311ms   │ Solve: integral of …   │
│  14:22:00│ Creative │ Sonnet↑  │ 421/980│ 2.1s    │ Write a short story…   │
│  14:21:59│ Code Q&A │ Haiku    │ 256/142│ 712ms   │ How to dedupe…         │
│  14:21:57│ Simple   │ Haiku    │ 18/22  │ 188ms   │ what's the capital…    │
│  14:21:55│ Math     │ Haiku    │ 119/72 │ 401ms   │ Compute sin(45°)…      │
│  14:21:52│ Code Q&A │ Sonnet↑  │ 612/410│ 1.8s    │ Refactor this Python … │
│   …                                                                         │
└──────────┴──────────┴──────────┴────────┴─────────┴────────────────────────┘

Streaming · 142 req/min · oldest visible: 14:14:32                  [Load older]
```

## Sections

1. **Filter row** — chips for cluster, model, escalated/errors-only, time range (fixed at "live" by default).
2. **Stream table** — rows append at top, fade-in animation (300ms). Latest row gets a `accent.primary` dot.
3. **Stream footer** — current rate, oldest visible time, load-older button.

## Components

Filter chip, data table with virtualized rendering (handles 1000s of rows), streaming-row animation, status-dot.

## States

- **Paused:** play/pause flips to play; rate counter still increments but rows don't append; "Resume" CTA.
- **Filtered (no matches yet):** table empty + "Waiting for matching requests… (last match: 12m ago)".
- **Disconnected:** rows freeze; banner "Stream reconnecting…" with retry.
- **High volume:** if rate >500 req/min, automatic sampling kicks in; banner "Sampling 1 in 5 rows — pause to filter exhaustively."

## Data

- WebSocket stream of `{request_id, timestamp, cluster, route, escalated_bool, tier_1_model, tier_2_model, tokens_in, tokens_out, latency_ms, prompt_preview}`.
- Filter state in URL params for shareability.

## Interactions

- Click row → opens Request detail in a side drawer (no nav). Drawer has a "Pop out to full view" link.
- Filter chip: opens dropdown with options + apply/clear.
- Export CSV: exports the currently-filtered view (with a max-rows confirmation if filter is loose).
- Keyboard: `J/K` to navigate rows, `Enter` to open detail.

## Notes

- Streaming + virtualization is the tricky part — most tools choke at 1k req/min. Use react-virtualized or tanstack-virtual + a server-side sampling fallback.
- "Escalated" rows have an `↑` glyph in the Route column. Easy to scan visually.
