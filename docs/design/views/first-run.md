# First-run Setup Wizard

> **Tier 3** · spec v0 · auto-approved 2026-05-18 · `first-run.md`
> Inherits [Dashboard shell](dashboard-shell.md) but in a modal/blocking variant.

## Purpose

One-time guided setup after installation. Captures the few decisions the system can't reasonably default (which providers, which starter policy variant) and gets the operator to first request fast.

## Layout

```
Modal (blocks the rest of the UI)
┌──────────────────────────────────────────────────────────────────────────┐
│  Cascadia setup · Step 2 of 4                                            │
│  ────────────────────────────────                                        │
│                                                                          │
│  ●─●─○─○                                                                 │
│  Welcome  Providers  Policy  Done                                        │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ Add at least one provider                                          │ │
│  │                                                                    │ │
│  │  Anthropic                                                         │ │
│  │  API key: [_____________________________________]  [test]          │ │
│  │  ✓ Verified at 14:22:14                                            │ │
│  │                                                                    │ │
│  │  + Add OpenAI / Bedrock / vLLM / Ollama …                          │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  [Back]                                              [Skip] [Continue →] │
└──────────────────────────────────────────────────────────────────────────┘
```

## Sections

1. **Step 1 — Welcome:** brand + one-paragraph "here's what's about to happen."
2. **Step 2 — Providers:** add at least one provider with key + connection test.
3. **Step 3 — Starter policy:** pick from presets (Balanced / Cheapest / Quality-first) with explanatory copy + Pareto preview.
4. **Step 4 — Done:** here's a curl command, [Take me to Cascadia →].

## Components

Modal shell, stepper, form input, button, code block.

## States

- **Skipped:** every step is skippable; skipping all leaves the operator on Cold-start.
- **Resumable:** if the operator closes mid-wizard, a Resume Setup card appears on Cold-start.

## Data

- Same as Models & providers data + a `setup_complete` flag.

## Interactions

- Each step has its own continue/back buttons.
- Step 2 must have at least one verified provider before Continue activates.
- Step 3 starter policy preview swaps a small Pareto chart to the right of the radio group.

## Notes

- This wizard is non-essential — operator can do everything from individual views — but it improves first-impression dramatically. Worth the build.
