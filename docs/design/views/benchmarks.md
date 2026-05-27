# Benchmarks Page

> **Tier 3** · spec v0 · auto-approved 2026-05-18 · `benchmarks.md`
> Public-facing.

## Purpose

The receipts. Reproducible benchmark numbers with operating point on a Pareto curve, plus the exact commands to reproduce them.

## Layout

```
[Top nav]
──────────────────────────────────────────────────────────────────────────────
                              Benchmarks v0.0.1                  Updated 2026-05-18

Headline:  78% cost reduction at 97% of Sonnet-quality on a 2,400-prompt blend.

[ Pareto chart — same as hero, larger and with multiple operating points ]

Methodology summary →  full methodology page

Run             | Cost / 1k | Quality (vs Sonnet) | Judge τ | Sample n
────────────────|───────────|---------------------|---------|---------
Sonnet-only      | $3.84      | 100.0%               | —        | 2400
Haiku-only       | $0.21      | 78.2%                | 0.74     | 2400
Static cascade   | $1.62      | 96.8%                | 0.74     | 2400
Cascadia (learned)│ $0.84      | 97.4%                | 0.74     | 2400

Reproduce:
  $ git clone …
  $ cd cascadia && make bench
  $ open bench/out/report.html

Per-benchmark breakdown (collapsible):
  ▸ MT-Bench (800)
  ▸ HumanEval (400)
  ▸ LMSys-Chat redacted sample (1200)

Hardware:
  m6a.2xlarge + 4 vCPU; provider calls geo-pinned us-east-1.
──────────────────────────────────────────────────────────────────────────────
[Footer]
```

## Sections

1. **Headline + Pareto chart**
2. **Run comparison table**
3. **Reproduction commands**
4. **Per-benchmark breakdowns**
5. **Hardware + provider notes**

## Components

Pareto chart (large), data table, code block, expandable accordion, footer note.

## States

- **Phase-0 banner:** at top: "Numbers below are *targets* until Phase-6 ships. Last measured run: pending."
- **After Phase-6:** banner switches to "Last measured run: <date> · n=…"

## Data

Static, generated from `bench/out/report.json`.

## Interactions

- Click any row in the comparison table → drill-down to per-benchmark page or `report.html`.
- Copy commands.

## Notes

- The Phase-0/Phase-6 banner is honesty-over-hype rule in action. Don't fake numbers.
