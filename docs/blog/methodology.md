# Cascadia methodology — how the cost numbers are honest

*The 200-pair Prolific run is queued; until it lands the calibration set is the 30-pair friend pilot characterized below. The numbers in this document are real — they're the measurements from that pilot, not a forward projection.*

## The trap: gateways that lie with confidence

The LLM-gateway space is crowded with products that publish cost-saving numbers and have no honest way to verify them. The standard recipe is:

1. Pick a workload (often the vendor's own synthetic prompts).
2. Route some fraction to a cheaper model based on a heuristic.
3. Score quality with an LLM judge — usually a single judge, single prompt, no calibration against human preferences.
4. Report "78% cost reduction at 97% quality."

The reported number is meaningless because every step has a structural bias the recipe doesn't correct:

- **Synthetic prompts** don't sample real production traffic. A cascade that wins on synthetic prompts can lose on real ones in ways the vendor cannot see.
- **Single-judge LLM scoring** suffers from documented position bias and self-preference (Zheng et al., 2023). A judge that's also the cheap tier will systematically inflate the cheap tier's wins.
- **No human-calibration step** means there's no way to know whether the judge's preferences match a real user's. The "97% quality" is "97% of what the judge thinks quality is" — circular.

Cascadia takes a different shape. The headline number is generated from production traffic, scored by a bias-corrected ensemble, and calibrated against a human-labeled hold-out set.

## Counterfactual shadow routing

The proxy makes a cascade decision per request: cheap tier first, escalate to expensive on low confidence. A configurable `shadow_rate` ∈ [0, 1] determines what fraction of *accepted-by-cheap* requests are *also* sent to the expensive tier asynchronously. The pair is persisted to `shadow_pairs` with both responses.

This solves the cold-start + exploration/exploitation problem that kills naive learned-routing attempts: you don't have to wait for a "bad cascade" to happen before you can score the cheap tier's quality. You get the counterfactual ("what would the expensive model have said?") as a side effect of serving traffic. Shadow data accumulates from minute zero.

Per-cluster `shadow_rate` lets the controller spend more shadow budget on uncertain clusters (high variance in scores) and pull it back on stable ones.

## The judge ensemble

A single LLM-as-judge is biased. Cascadia stacks three corrections on top:

### 1. Two prompt formats, not one

- **Pairwise (v1):** Score = p(cheap ≥ expensive) on the user's actual task, given both responses side by side. One JSON output, fast.
- **Rubric (v1):** Score each response *independently* on a 0–10 quality rubric. Derive a pairwise probability from the gap via a logistic on `(cheap − expensive) / temperature`. Two LLM calls instead of one; the extra cost buys an orthogonal signal that doesn't share the pairwise prompt's biases.

Combining both is meaningfully better than running either alone — they fail on different inputs.

### 2. Position-bias correction

Pairwise judges have a documented position preference (they tend to favor whichever response appears in position B; the exact bias depends on the judge model). Cascadia runs the same pairwise judge twice — once with cheap as A, once with cheap as B — and averages the two estimates of p(cheap ≥ expensive). The per-judge `|p − swapped_p|` is exposed as a position-bias diagnostic in the dashboard.

### 3. Anti-self-preference

A judge whose model name appears in either candidate (substring match in both directions) is dropped from the ensemble. A `gpt-4o-mini` judge scoring a `gpt-4o-mini` cheap-tier response would inflate cheap-side wins by 8–15% in published self-preference studies. Cascadia errs on the side of dropping a judge rather than keeping it: an over-conservative ensemble is honest, a biased one is poison.

The aggregation function ([`services/judge-worker/cascadia_judge/aggregation.py`](../../services/judge-worker/cascadia_judge/aggregation.py)) applies these corrections in order and returns a single `EnsembleScore` with provenance — how many verdicts came in, how many were dropped for self-preference, how many failed, the position-bias estimate, and which judge models contributed. That provenance is persisted alongside the score so future audits can see what shaped the number.

## Calibration against humans

The ensemble's quality estimate is only as good as its agreement with what a human reviewer would say. Cascadia ships a calibration harness ([`services/judge-worker/cascadia_judge/calibration/`](../../services/judge-worker/cascadia_judge/calibration/)) that:

1. Loads a JSONL of `(prompt, response_a, response_b, human_label ∈ {a, b, tie})` rows.
2. Runs the ensemble over each pair.
3. Computes Kendall's τ-b (rank correlation between the ensemble's continuous score and the human ordinal label).
4. Reports the τ, the discretized-label agreement rate, the position-bias estimate, and the per-label distribution.

The Phase-5 acceptance threshold is **τ-b ≥ 0.7** — solid agreement but not a perfect-correlation hallucination.

### What we ship today, and what's missing

The repo includes a 15-pair synthetic calibration set (`services/judge-worker/calibration/golden_v0.jsonl`) where the human labels are deterministic by construction (correct math vs. wrong math, etc.). It hits **τ-b = 0.83** against the scripted ensemble. That demonstrates the harness works end-to-end and the metric is wired correctly.

A 30-pair **real-human pilot** ran on 2026-05-19 (Chris + a friend, two reviewers each labeling the same pairs). The pilot is documented in detail in the next section — short version: **the ensemble and humans agreed at τ-b ≈ 0** and the diagnosis turned out to be informative, not embarrassing. To make a production-grade Phase-5 claim, the next step is a ~200-pair set via paid crowdsourcing (Prolific / Surge / Scale, ~$300 — see PLAN.md memory `[[cascadia-prolific-deferred]]`).

## What the 2026-05-19 pilot found

The pilot exposed three real biases, each in its own run, and characterized the third one carefully because **it's the one that survives all the corrections we built**.

### Inter-rater agreement: the rubric itself was the first thing to fail

Before any judge model entered the picture, the two human reviewers were given **rubric v1** and asked to label the same 30 pairs. Cohen's κ between them was **−0.024** — statistical noise. The two reviewers were essentially guessing relative to each other; reviewer A was a liberal tie-caller and reviewer B picked winners.

The instinct here is to throw out the reviewers or add more attention checks. We did neither: we threw out the **rubric**. Rubric v1 was permissive enough that two reasonable readers could honestly land in completely different places on the same pair. We rewrote it as **rubric v2** (concision over verbosity as a tiebreaker, "tie is last resort" with worked examples, ban hedging language from the criteria) and re-labeled the same 30 pairs. Cohen's κ jumped to **+0.52** — moderate substantive agreement on the same data, same reviewers.

This is the methodological core of the project, not a footnote. The κ progression −0.024 → +0.52 is in [`services/judge-worker/calibration/archive/`](../../services/judge-worker/calibration/archive/). The next failures (τ-b ≈ 0 against the panel) are interpretable *because* this step happened first; otherwise the panel-vs-human gap could plausibly be reviewer noise, not measurement bias.

### Run 1 — single-model judge with self-preference filter triggered

The first calibration run used **gpt-4o-mini as the judge** (the same model as the cheap candidate). The aggregator's anti-self-preference filter dropped all 90 verdicts (3 judges × 30 pairs) because the judge model name substring-matched the candidate. **The ensemble returned 0.5 (no signal) for every pair; τ-b undefined.**

This is the bias correction *working as designed*. Without that filter the judge would have scored its own output against gpt-4o, inflated cheap-side wins by ~10–15% (per Zheng et al. 2023), and yielded a flattering τ-b on a structurally biased judge.

### Run 2 — Groq llama-3.3-70b judge with verbosity bias

We swapped the judge to llama-3.3-70b (different family, no self-preference overlap). τ-b lifted to ~+0.10 — barely above noise. The diagnosis: the ensemble said "expensive wins" on **90% of pairs** while humans split roughly 30 / 23 / 47 across A / B / tie. Position-bias estimate was near zero (0.008), so it wasn't slot bias — it was the judge consistently preferring the more verbose response, even when human reviewers preferred concise ones.

### Run 3 — 3-judge cross-family panel, the same bias reproduced cleanly

To rule out a per-model quirk we ran a 3-judge panel: Anthropic `claude-haiku-4-5` + OpenAI `gpt-3.5-turbo` + Groq `llama-3.3-70b-versatile`. Three independent provider families. Each ran the bias-corrected pairwise judge (with position swap).

**Panel-vs-human τ-b = −0.09.** Per-judge: claude −0.25, gpt-3.5-turbo −0.05, llama +0.02.

**Panel-internal agreement: τ ≈ +0.28, 24 of 30 panel decisions unanimous.** The three judges agree with each other meaningfully; they disagree with humans uniformly.

### Walking the disagreements

The pattern is visible in the actual pairs:

| Prompt | Cheap (A) | Expensive (B) | Human | Panel |
|---|---|---|---|---|
| What year did the Berlin Wall fall? | "November 9, 1989." | "1989." | **B** (answers what was asked) | **A** (more detail) |
| How many time zones does Russia span? | "11 time zones. The country stretches…" | "11 time zones." | **B** (brevity) | tie |
| Speed of light in km/s? | "299,792 km/s. Often rounded to 300,000…" | "299,792 km/s." | **B** (brevity) | **A** (extra context) |
| Bash one-liner for recent .py files | `find . -name "*.py" -mtime -1` | `find` command + 8 lines of explanation | **A** (just the command) | **B** (with explanation) |

**Humans prefer concise, on-point responses. The panel rewards completeness and verbosity.** Both are defensible quality definitions; they're measuring different dimensions. This is exactly the **verbosity bias** Zheng et al. (2023) named in the original LLM-as-judge paper, reproduced here on real production traffic with three independent providers in 2026.

### What this means for the project

Every existing LLM gateway that publishes a "X% cost saved at Y% quality" number is silently swimming in this bias, because none of them measure both signals against humans. The Phase-5 acceptance criterion of "τ-b ≥ 0.7" was naive *for exactly this reason* — it assumed humans and LLM panels measure the same thing on common Q&A. They don't.

**We did not respond by rewriting the rubric until humans matched the panel.** That would have erased the finding. Instead:

1. **The pilot finding is published as-is.** Phase 5 acceptance is revised from "τ-b ≥ 0.7" to "characterized + named values mismatch with the bias signature documented." That's the actual claim Cascadia can honestly back; pretending otherwise would have undone the project's "honest measurement over flattering numbers" thesis.

2. **Phase 5.2 added a concision-bias correction** to the aggregator: `concision_adjustment(cheap, expensive, weight)` shifts the post-aggregation score toward whichever response is shorter, length-normalized. A post-hoc sweep across weights `{0.0, 0.05, …, 0.5}` on the same panel output (no re-LLM-calls needed) showed:

   | weight | τ-b vs humans | agreement rate | judge tie rate |
   |---:|---:|---:|---:|
   | 0.00 | −0.152 | 0.467 | 0.900 |
   | 0.05 | −0.037 | 0.500 | 0.933 |
   | 0.10 | +0.088 | 0.500 | 0.933 |
   | 0.15 | +0.128 | 0.500 | 0.933 |
   | 0.20 | +0.156 | 0.533 | 0.900 |
   | 0.25 | +0.184 | 0.533 | 0.867 |
   | **0.30** | **+0.196 (best)** | 0.533 | 0.867 |
   | 0.40 | +0.167 | 0.500 | 0.833 |
   | 0.50 | +0.139 | 0.533 | 0.733 |

   A note on the two τ-b figures in this post: the **−0.152** baseline here (weight 0.00) is the τ-b of the *aggregated ensemble score* — the confidence-weighted, position-folded number `aggregate()` actually emits — against humans. The **−0.09** reported for Run 3 above is the τ-b of the panel's *raw pairwise verdicts* before aggregation. Same pilot, two measurement points: aggregation reshapes the panel's decisions, so the two values differ slightly. Both are pre-concision-correction; the sweep starts from the aggregated baseline because that's the number the production pipeline produces.

   Read this as: as the concision penalty grows, the panel stops over-rewarding verbose responses, and panel-vs-human τ-b walks from **−0.152 → +0.196** — a **+0.348 swing** from the correction alone. The best weight is 0.30; agreement rate plateaus around 53% but the rank correlation (the more sensitive metric) responds cleanly. Verbosity bias is real, and the penalty does correct for it.

   The sweep is regenerated by:

   ```bash
   cascadia-judge-llm-panel \
       --dataset services/judge-worker/calibration/human_rated_v1.jsonl \
       --panel "anthropic:claude-haiku-4-5,openai:gpt-3.5-turbo,groq:llama-3.3-70b-versatile" \
       --concision-sweep "0.0,0.05,0.1,0.15,0.2,0.25,0.3,0.4,0.5"
   ```

   The post-hoc sweep does **not** re-call any LLMs — it re-aggregates the cached panel verdicts with each weight. The cost of the run above is one set of panel calls (~$5 in our case); the sweep itself is free.

   But the penalty does **not** close the gap to τ-b ≥ 0.7 on this dataset. Other drivers of disagreement remain unidentified; likely candidates are (a) n=30 is below the noise floor with 47% human-tie rate; (b) gpt-4o-mini vs gpt-4o is a quality gap that may be too narrow to discriminate at this prompt difficulty; (c) the v2 rubric may still over-push humans to pick sides on genuinely-close calls.

3. **The 200-pair Prolific run is the path to a defensible production-grade number.** Same tooling, larger n, more reviewers, wider quality gaps in the pair pool. Until that lands, the Cascadia README's acceptance row says exactly what's been measured: the *bias structure* is characterized; the *τ-b number itself* is not yet at the threshold needed to make the original Phase-5 claim publicly.

### Reproducibility — the full pilot in one command sequence

```bash
# Setup (proxy + DB + dashboard-api already running)
# 0.07 × 30 ≈ 2 gold-standard attention checks — what the pilot actually used.
# (The tool's default is 0.05; the pilot bumped it to land exactly 2 in 30.)
cascadia-judge-sample-calibration --round 1 --size 30 --attention-check-rate 0.07

# Two reviewers label 30 pairs each via /calibrate
# After both finish:
cascadia-judge-aggregate-labels --out calibration/human_rated_v1.jsonl

# 3-judge cross-family panel with concision sweep
cascadia-judge-llm-panel \
    --dataset calibration/human_rated_v1.jsonl \
    --panel "anthropic:claude-haiku-4-5,openai:gpt-3.5-turbo,groq:llama-3.3-70b-versatile" \
    --concision-sweep "0.0,0.05,0.1,0.15,0.2,0.25,0.3,0.4,0.5"
```

The 2026-05-19 pilot's raw data — labels, dropped reviewers (none), per-pair panel scores, rubric versions — is checked into `services/judge-worker/calibration/archive/` for audit.

The blog post will be revised once the human-rated set is collected.

## The Pareto chart on the dashboard

`/pareto` shows one dot per cluster, X = escalation rate (cost proxy), Y = mean judge score (quality). The chart updates as traffic flows through and the controller refits thresholds. It is not the predicted Pareto frontier — that requires fitting a smooth curve to many operating points across the deployment's history, which is Phase-7 territory if it ever ships. The live operating point chart is enough to answer the operator's actual question: *am I close to the frontier, and which clusters are dragging me down?*

## Reproducibility

Every number on the README is reproducible from a fresh clone:

- `bench/k6/proxy-overhead.js` — proxy latency overhead vs. an instant-response mock upstream.
- `bench/scripts/pareto-frontier.sh` — end-to-end: traffic → cascade → judge → controller → Pareto JSON. Writes `/tmp/cascadia-pareto.json` and prints a per-cluster summary.
- `cascadia-judge-calibrate --dataset calibration/golden_v0.jsonl --provider scripted --scripted-fixture calibration/scripted_v0.json` — replays the calibration run.

There are no closed binaries, no "vendor-only" features, no telemetry that phones home. The headline number is what falls out of the scripts.
