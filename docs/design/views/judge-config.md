# Judge Configuration

> **Tier 2** · spec v0 · auto-approved 2026-05-18 · `judge-config.md`
> Inherits [Dashboard shell](dashboard-shell.md).

## Purpose

Configure the judge ensemble: which models judge, with which prompts, and how their votes combine. Tightly linked to the [Methodology page](methodology.md) which explains *why* this matters publicly.

## Layout

```
Breadcrumb: Judge configuration                               [Run calibration →]
──────────────────────────────────────────────────────────────────────────────────
┌──────────────────────────────────────────────────────────────────────────────┐
│ Ensemble: 3-judge default                                  [Switch ensemble ▾]│
│ Calibrated τ = 0.74 (95% CI 0.67–0.81) · last calibrated 6d ago               │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ Judge members                                                                │
│ ┌──────────────────┬─────────────────┬────────┬───────────────────────────┐ │
│ │ Model            │ Prompt variant  │ Weight │ Position-bias correction  │ │
│ ├──────────────────┼─────────────────┼────────┼───────────────────────────┤ │
│ │ Sonnet-3.7       │ pairwise/v2     │ 1.0    │ ☑ A/B swap each pair      │ │
│ │ GPT-4o           │ pairwise/v2     │ 1.0    │ ☑                          │ │
│ │ Gemini-1.5-Pro   │ pairwise/v1     │ 1.0    │ ☑                          │ │
│ │ [+ Add judge]                                                              │ │
│ └──────────────────┴─────────────────┴────────┴───────────────────────────┘ │
│                                                                              │
│ Vote combiner:  ( ) Majority  (●) Mean score  ( ) Weighted by τ vs human    │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────┬───────────────────────────────────┐
│ Cost per judgment                       │ Disagreement monitor              │
│  Sonnet     $0.012 avg                  │  Cluster #11: 0.41 (>0.30 alert)  │
│  GPT-4o     $0.014 avg                  │  Code Q&A: 0.18                   │
│  Gemini     $0.009 avg                  │  Math:      0.08                  │
│  Per call   $0.035 / shadow             │  Recent spike →                   │
└─────────────────────────────────────────┴───────────────────────────────────┘

[ Prompt library ]
  pairwise/v1 · pairwise/v2 · pointwise/v1 · …                       [Edit prompts]
```

## Sections

1. **Ensemble header** — current ensemble + calibrated τ.
2. **Judge members table** — model, prompt variant, weight, bias correction toggle.
3. **Vote combiner** — majority / mean / weighted.
4. **Cost monitor** — per-judge cost and total per-shadow-evaluation cost.
5. **Disagreement monitor** — clusters where the judges disagree often = flags for human attention.
6. **Prompt library** — list of named prompt variants used by judges.

## Components

Data table, dropdown, checkbox, radio group, KPI card, prompt-variant chip, edit prompts modal.

## States

- **Calibration stale:** if last calibration >30 days, banner in `accent.warn` "Recalibrate" CTA.
- **High disagreement:** if ensemble disagreement spikes, banner in `accent.warn` with link to disagreement detail.
- **Adding judge:** wizard with model picker (must be present in Models & providers), prompt variant select, weight, test-judgment preview.

## Data

- `ensemble`: `{members: [{model, prompt_id, weight, position_bias_correction}], combiner, calibration_tau, calibration_at}`.
- `disagreement_per_cluster`: `[{cluster_id, agreement_score, sample_n}]`.

## Interactions

- Edit prompts: opens editor with side-by-side preview of two responses being judged + the rendered prompt; saves new versioned variant.
- Test judgment: pick a sample request, run all judges with current config, see scores.

## Notes

- Prompts are versioned (pairwise/v1, pairwise/v2) — never edited in place. Changing a judge's prompt creates a new variant.
- Disagreement spikes are the early-warning signal for distribution shift — worth surfacing prominently.
