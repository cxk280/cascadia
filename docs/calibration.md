# Building the human-rated calibration set

How to collect the human labels that the judge ensemble is calibrated against. The full toolchain ships in-repo: an **active-learning sampler** that picks the most informative pairs from `shadow_pairs`, the **`/calibrate` labeling app** (position randomization + attention checks), an **aggregator** that turns raw labels into the canonical JSONL the calibration harness consumes, and an **LLM-panel backstop** for when extending the human set is too expensive.

Context: a 30-pair real-human pilot ran on 2026-05-19 (Cohen's κ progressed v1 → v2 from −0.024 → +0.52 between two reviewers — the rubric iteration itself is the load-bearing finding; see [blog/methodology.md](blog/methodology.md)). The 15-pair synthetic golden set hits τ-b = 0.83 against the scripted ensemble and confirms the harness is wired correctly; a real claim against humans needs ~200 production pairs labeled by ≥2 reviewers each.

## How active learning picks pairs

Round 1 is stratified-random across clusters (no ensemble signal yet → no way to rank). Round 2+ scores the unlabeled pool with the judge ensemble and ranks by:

```
uncertainty = 0.5·(1 − confidence)              ← judges hedged
            + 0.3·(1 − 2·|score − 0.5|)         ← score near tie
            + 0.2·position_bias_estimate        ← judges disagree with themselves
```

Each round labels the highest-uncertainty pairs first (within cluster stratification) — the pairs where the ensemble is most uncertain are the most informative for humans to correct.

## Running it end-to-end

```bash
# Pre-req: proxy + Postgres up; you've driven enough traffic that
# shadow_pairs has rows (`bench/scripts/pareto-frontier.sh` will do).

# 1. Pull a round-1 seed batch into calibration_pairs (sampled + ~5% attention checks)
$ cd services/judge-worker && . .venv/bin/activate
$ cascadia-judge-sample-calibration --round 1 --size 30 \
    --attention-check-rate 0.05 \
    --database-url postgres://cascadia:cascadia@localhost:5432/cascadia

# 2. Bring up the dashboard-api (write surface for labels)
$ cd services/dashboard-api && . .venv/bin/activate
$ CASCADIA_DATABASE_URL=postgres://cascadia:cascadia@localhost:5432/cascadia \
  cascadia-dashboard-api &                        # → http://127.0.0.1:18082

# 3. Bring up the dashboard (the labeling UI lives at /calibrate)
$ cd dashboard && npm install && npm run dev      # → http://localhost:3000/calibrate

# 4. Each reviewer opens /calibrate, picks a short reviewer_id (e.g. "chris"),
#    reads /calibrate/rubric, and starts labeling. Keyboard shortcuts:
#    [A] = slot A wins · [B] = slot B wins · [T] = tie · [U] = unknown
#    Esc inside the rationale field re-enables shortcuts.

# 5. After a round wraps, run round 2 with the ensemble in the loop:
$ cascadia-judge-sample-calibration --round 2 --size 30 \
    --score-with-ensemble --ensemble-provider openai \
    --ensemble-model gpt-4o-mini  # or fake / scripted for offline test

# 6. Aggregate raw labels → canonical JSONL the existing harness consumes:
$ cascadia-judge-aggregate-labels --out calibration/human_rated_v1.jsonl
# stdout shows the quality report (Cohen's κ, per-reviewer attention pass/fail,
# consensus/disagreement counts). The JSONL is the artifact you check into the repo.

# 7. Compute τ-b of the current ensemble against the new human-rated set:
$ cascadia-judge-calibrate --dataset calibration/human_rated_v1.jsonl \
    --provider openai --model gpt-4o-mini --tau-min 0.7
```

## LLM-panel backstop

When you need to extend the calibration set beyond the budget for human reviewers, run a panel of 3 top-tier models (none in the judge ensemble) over the same pairs and use their unanimous agreements as a synthetic gold standard. Estimated cost: ~$5 for 200 pairs × 3 models with position-swap.

```bash
$ ANTHROPIC_API_KEY=… OPENAI_API_KEY=… GROQ_API_KEY=… \
  cascadia-judge-llm-panel \
    --dataset calibration/human_rated_v1.jsonl \
    --panel anthropic:claude-opus-4-7,openai:gpt-4o,groq:llama-3.3-70b \
    --tau-min 0.7
```

The panel report includes panel-vs-human τ, per-model-vs-human τ, and cross-model agreement — if any panel model is an outlier, swap it out.

## Quality controls baked in

- **Position randomization** — server decides per (pair, reviewer) whether to swap slot A/B; the reviewer never sees it. Deterministic per pair so a browser refresh doesn't flip the order mid-label.
- **Attention checks** — ~5% of pairs are obvious-by-construction (response A is gibberish, etc.). Reviewers above the failure threshold are dropped from the canonical aggregation but their labels stay in the DB for audit.
- **Inter-rater agreement** — Cohen's κ is computed pairwise across reviewers on overlapping pairs and reported alongside the dataset. κ < 0.5 means the rubric is ambiguous or the reviewers are confused — both are findings to publish.
- **Rubric versioning** — every label records the `rubric_version` it was given under, so a future audit can answer "which rubric were they using?"

## What's deferred

The current scope is **Chris + 1 friend** (no money spent). Scaling to a publishable claim means crowdsourcing through Prolific / Surge / Scale (~$300–700 for 200 pairs × 2 reviewers) — the labeling tool, schema, and aggregator already support it; only the reviewer pool grows. The [methodology blog](blog/methodology.md) frames this honestly until then.
