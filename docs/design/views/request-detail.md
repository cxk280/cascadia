# Request Detail / Drill-down

> **Tier 1** · spec v0 · auto-approved 2026-05-18 · `request-detail.md`
> Inherits [Dashboard shell](dashboard-shell.md).
> Typically reached via deep-link from Live traffic, Clusters, or Quality history.

## Purpose

The forensic view: one request, everything we know about it. Why did it route this way? What did each tier say? What did the judge think? This is the screen that wins ML systems engineers — being able to inspect a single decision end-to-end is rare in production tooling.

## Layout

```
Breadcrumb: Live traffic › Request r_8x2a3f9c                      [Copy curl] [Replay]
──────────────────────────────────────────────────────────────────────────────────
┌──────────────────────────────────────────────────────────────────────────────┐
│ Header strip                                                                 │
│   r_8x2a3f9c · 2026-05-18 14:22:03.412 · 1.4s end-to-end · API key sk_live_…│
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────┬─────────────────────────────────┐
│ Prompt                                   │ Decision pipeline               │
│ ─────────────────────────                │ ─────────────────────────       │
│ system: You are a helpful coding…        │ 1. Classify  (0.4ms)            │
│ user:   Why does this Rust closure       │    → cluster: Code Q&A (0.92)   │
│         capture `s` by move? …           │                                 │
│         [shown abridged · expand]        │ 2. Policy lookup (0.1ms)        │
│                                          │    → tier1: Haiku, threshold 0.74│
│                                          │                                 │
│                                          │ 3. Tier 1: Haiku  (842ms)       │
│                                          │    Confidence: 0.81 (> 0.74)    │
│                                          │    Tokens: 312 in · 187 out     │
│                                          │    Cost: $0.0004                │
│                                          │    ✓ Accepted (no escalation)   │
│                                          │                                 │
│                                          │ 4. Shadow eval (async, 1.2s)    │
│                                          │    Tier 2 (Sonnet) response →   │
│                                          │    Judge ensemble score: 0.94    │
│                                          │    Tier-1 score:           0.91 │
│                                          │    Δ = +0.03 (within band)      │
└──────────────────────────────────────────┴─────────────────────────────────┘

┌──────────────────────────────────────────┬─────────────────────────────────┐
│ Tier 1 response (returned)               │ Tier 2 response (shadow)         │
│ A Rust closure captures by move when…    │ Rust closures capture variables… │
│ [collapsible · diff toggle]              │ [collapsible · diff toggle]      │
└──────────────────────────────────────────┴─────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ Judge breakdown                                                              │
│ ┌──────────────────┬──────┬──────┬──────────────────────────────────┐         │
│ │ Judge            │ T1   │ T2   │ Comment (truncated)              │         │
│ ├──────────────────┼──────┼──────┼──────────────────────────────────┤         │
│ │ Sonnet-3.5 (A)   │ 0.92 │ 0.95 │ Both correct; T2 more detail …   │         │
│ │ GPT-4o (B)       │ 0.90 │ 0.94 │ T1 misses the move semantics nu… │         │
│ │ Gemini-1.5 (A)   │ 0.91 │ 0.94 │ Both correct…                    │         │
│ │ Ensemble (mean)  │ 0.91 │ 0.94 │                                  │         │
│ └──────────────────┴──────┴──────┴──────────────────────────────────┘         │
└──────────────────────────────────────────────────────────────────────────────┘

[Trace · OpenTelemetry] · [Counterfactual: what if threshold were 0.85?]
```

## Sections

1. **Header strip** — request ID, timestamp, total latency, source API key (masked).
2. **Prompt** — system + user messages, abridged with expand. Redaction-aware.
3. **Decision pipeline** — step-by-step what the proxy did, with timings and per-step output.
4. **Tier responses (paired)** — actual returned response + shadow response. Diff toggle highlights character-level differences.
5. **Judge breakdown** — per-judge scores with truncated reasoning; ensemble row.
6. **Footer actions** — open in trace viewer (OpenTelemetry), counterfactual scenario simulator.

## Components

Code block (prompt + responses), step-list, diff viewer, data table (judges), latency-bar mini-component, key/value chip, JSON viewer for the raw trace.

## States

- **No shadow available:** if this particular request wasn't shadow-routed, hide section 4–5 and show a banner "This request was not shadow-evaluated. To force-evaluate now, click here." (calls the eval API).
- **Judge in flight:** if eval is async-pending, show skeleton in judges table with "Waiting for ensemble (3/4 judges responded)…"
- **Redacted:** if PII redaction stripped the prompt, show the redaction summary instead of raw content + a "Why am I seeing this?" link to settings.
- **Replay:** clicking Replay opens a confirmation modal then re-issues the request, taking the user to the new request's detail.

## Data

- Full request payload (after redaction).
- Decision pipeline: array of `{step_name, duration_ms, output_summary, output_full}`.
- Tier responses: text + token counts + costs.
- Judge entries: per-judge scores + reasoning + ensemble agreement.

## Interactions

- Copy curl: places an equivalent `curl` command on clipboard for reproducing this exact request.
- Replay: re-runs with current policy; opens new detail page.
- Counterfactual: opens modal "If threshold for this cluster were X, this request would have…" with predicted route + estimated quality from shadow data.
- Trace viewer link: opens OpenTelemetry trace (likely in Jaeger/Tempo) for this request ID in a new tab.

## Notes

- Diff toggle on tier responses uses standard char-diff (green added / red removed). Useful for spotting "Tier 2 just adds caveats" patterns.
- This view's existence is what justifies the per-request event log retention (cost decision; see PLAN.md).
