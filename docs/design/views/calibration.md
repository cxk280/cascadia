# Calibration Interface

> **Tier 2** · spec v0 · auto-approved 2026-05-18 · `calibration.md`
> Inherits [Dashboard shell](dashboard-shell.md).

## Purpose

Where humans rate model output pairs so we can calibrate the LLM-as-judge ensemble against human preference. This view is what makes the methodology page's "Kendall's τ = 0.74" number a fact rather than a hope.

## Layout

```
Breadcrumb: Calibration                                  Calibrated · τ = 0.74
──────────────────────────────────────────────────────────────────────────────────
┌─────────────────────────────────────────────────────────────────────────────┐
│ Pair 42 of 200 · cluster: Code Q&A                                          │
│ ─────────────────────────────────────                                       │
│                                                                              │
│  Prompt: How do I make a Python decorator that caches results?               │
│                                                                              │
│  ┌──────────────────────────────────┬──────────────────────────────────┐   │
│  │ Response A                       │ Response B                       │   │
│  │ A Python decorator can cache by  │ Use functools.lru_cache:         │   │
│  │ wrapping a function in a closure │                                  │   │
│  │ that holds a dict … (full)       │   @functools.lru_cache(maxsize=) │   │
│  │                                  │   def my_func(x):                │   │
│  │                                  │       …                          │   │
│  │                                  │ Or roll your own for finer …     │   │
│  └──────────────────────────────────┴──────────────────────────────────┘   │
│                                                                              │
│   Which is better?                                                           │
│   ( ) A much better   ( ) A slightly better   ( ) Tie                       │
│   ( ) B slightly better   ( ) B much better                                 │
│                                                                              │
│   Why? (optional, helps debug judges)                                       │
│   [_____________________________________________]                           │
│                                                                              │
│   [Skip]                                  [Submit & next →]                  │
└─────────────────────────────────────────────────────────────────────────────┘

Sidebar:
  Progress  ████████░░░░░░░░░░  42 / 200
  Agreement so far: 88% with current ensemble
```

## Sections

1. **Pair header** — index, total, cluster context.
2. **Prompt + paired responses** — A/B random order (no labels of which model).
3. **5-point preference picker** — much/slightly/tie symmetric scale.
4. **Optional reasoning** — text field for free-form notes.
5. **Sidebar progress** — pairs rated, running agreement vs ensemble.

## Components

Code/response viewer (preserves formatting), radio group (5-point), text input, progress bar, submit button.

## States

- **Empty (no calibration session active):** big CTA "Start a calibration session" with sampling options (cluster filter, count).
- **Mid-session:** as drawn.
- **Complete:** results page with full agreement breakdown + τ + chart.
- **Resume:** if a session was paused, top banner offers Resume.

## Data

- `session`: `{id, started_at, total_pairs, completed_pairs, cluster_filter}`.
- Per pair: `{prompt, response_a, response_b, ensemble_prediction, human_rating?, human_reasoning?}`.
- Final session: agreement matrix per judge.

## Interactions

- Hot keys: `1`-`5` for the rating; `Enter` to submit; `S` to skip; `R` for "reveal who said what" (after submit only).
- "Why?" field auto-saves draft per pair.
- Reveal post-submit: shows which model gave A vs B + the ensemble's prediction. Critical for the rater to learn what they're calibrating.

## Notes

- Random-order A/B is required for unbiased calibration. The view stores the order in the session, never shows it to the human until after submission.
- The calibrated τ feeds back into the methodology page numbers and the judge-config view.
