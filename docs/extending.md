# Extending Cascadia

Cascadia's hot path is opinionated (cascade routing → shadow eval → closed loop) but most of the *components* inside it are pluggable. This doc maps the extension points so you can configure or replace pieces without forking the core.

Scope: configuration changes and registry entries. If you're adding a *new upstream provider*, see [`adding-a-provider.md`](adding-a-provider.md) — that's a separate workflow.

## Quick map

| Want to customize… | Read |
|---|---|
| Which judge models / prompt variants run | [Judge ensemble](#judge-ensemble) |
| How verdicts are aggregated into a quality score | [Aggregator](#aggregator) |
| How the policy controller refits thresholds | [Policy controller](#policy-controller) |
| What requests get sampled for the calibration set | [Calibration sampler](#calibration-sampler) |
| Which upstream provider serves a cluster | [`adding-a-provider.md`](adding-a-provider.md) |

## Judge ensemble

The judge worker scores shadow pairs by fanning out to every registered judge over each pair. A "judge" is a `(judge_name, prompt_variant)` pair — e.g. `pairwise_preference_v1` is one judge, `rubric_v1` is another.

### Configuring which judges run

CLI flag: `--judges <name> [<name> ...]`. Without it, every registered judge runs. Example:

```bash
cascadia-judge-poll --judges pairwise_preference_v1 rubric_v1
```

This is the lever for a deploy that wants to drop the rubric judge or run a single judge for cost reasons. The aggregator handles missing variants gracefully — it just has fewer rows to average.

### Configuring which models the judges call

CLI flags `--model <model_id>` + `--provider <openai|anthropic|groq|xai>` select the LLM that backs every judge in that run. You typically run the orchestrator multiple times with different `--model` values and let the aggregator merge the results — that's how the cross-family panel (judge diversity) is assembled.

Example (cross-family panel — 3 judges × 2 models per judge):

```bash
cascadia-judge-poll --judges pairwise_preference_v1 --provider openai --model gpt-4o
cascadia-judge-poll --judges pairwise_preference_v1 --provider anthropic --model claude-haiku-4-5
cascadia-judge-poll --judges rubric_v1 --provider openai --model gpt-4o
# … etc
```

### Adding a new judge

A judge is a `Judge` subclass in `services/judge-worker/cascadia_judge/judges/`. The base class auto-registers subclasses by `name`, so adding a new judge is:

1. Create `services/judge-worker/cascadia_judge/judges/your_judge.py` with `class YourJudge(Judge): name = "your_v1"` etc.
2. Import it from `judges/__init__.py` so registration fires at import time.
3. Done — the poller picks it up automatically.

See `services/judge-worker/cascadia_judge/judges/pairwise.py` and `rubric.py` as worked examples.

### Adding a new prompt variant

Prompt variants live alongside the judge they belong to (the swapped-position variant of `pairwise_preference_v1` is implemented inside that judge as a registered variant). The same registry pattern applies.

## Aggregator

`services/judge-worker/cascadia_judge/aggregation.py::aggregate()` reduces N judge verdicts to a single `EnsembleScore` (score, confidence, position-bias, provenance) per shadow pair. (`EnsembleScore` is the result dataclass; `aggregate()` is the function you'd swap.)

### Tuning knobs

The one runtime knob is the concision weight, exposed as `--concision-weight` on the calibration CLIs `cascadia-judge-calibrate` and `cascadia-judge-llm-panel` (default 0.0). At the library level it's the `concision_weight` parameter of `aggregate()`.

The concision weight is a post-hoc correction for verbosity bias — see [methodology blog § Run 3](blog/methodology.md). Default is 0.0 (no correction); 0.30 is the value that walked the 30-pair pilot's panel-vs-human τ-b from −0.152 to +0.196.

The self-preference filter is **always on** — it's Step 1 of `aggregate()`, not a flag. It drops any judge verdict whose model name substring-matches either candidate model name (e.g. a `gpt-4o-mini` judge scoring a `gpt-4o-mini` candidate is dropped). Disabling it for an ablation means editing that step, not flipping a toggle.

### Replacing the aggregator entirely

The aggregator (`aggregate()` in `aggregation.py`) is pure (no I/O), so swapping it is a single import in the calibration CLIs and the poller. For most use cases the concision weight is the only operational lever you'd reach for; deeper changes (different bias corrections, a different fold strategy) mean replacing the function.

## Policy controller

`services/policy-controller/cascadia_policy/controller.py` holds the bandit-style per-cluster threshold refit. It's pure (no I/O): `PolicyController.refit()` takes the current policy + per-cluster `ClusterStats` and returns a new `PolicyTable`. The surrounding I/O lives next to it — `storage.py` reads judge_scores into stats, `writer.py` writes the new policy JSON atomically, and `cli.py` wires the loop together.

### Tuning knobs

Env vars (read in `cli.py`):

- `CASCADIA_REFIT_INTERVAL_SEC` — how often to refit, in seconds. Default 300. (Also settable via `--interval-seconds`.)
- `CASCADIA_LOOKBACK_MINUTES` — how far back to pull judge_scores per refit. Default 60. (Also `--lookback-minutes`.)

The refit math itself is parameterized by `UpdateRule` (in `controller.py`), exposed as CLI flags rather than env vars:

- `--step` — how much to move the threshold per step. Default 0.03.
- `--min-sample-size` — minimum judge_scores per cluster before a refit fires. Default 20.
- `--target` / `--margin` — the cheap-vs-expensive mean-score band that decides step direction. Defaults 0.5 / 0.05.

### Replacing the refit strategy

`PolicyController._refit_cluster(policy, stats) -> ClusterPolicy` is the per-cluster decision: it reads `stats.mean_score`, compares against the `UpdateRule` band, and steps the threshold. A custom strategy (UCB, Thompson sampling, contextual bandit) either swaps the `UpdateRule` dataclass for a richer one or overrides `_refit_cluster` in a `PolicyController` subclass. Because the class is pure, you can unit-test a new strategy without any DB.

If you're considering this: open an issue first. The bandit refit is intentionally simple because the closed-loop feedback signal it learns from is itself noisy (judge τ-b ≈ 0.5 at best). A more sophisticated refit overfits to judge noise.

## Calibration sampler

`services/judge-worker/cascadia_judge/calibration/sampler.py` picks which shadow pairs go into the calibration set.

### Tuning knobs (CLI flags)

- `--round 1` — uniform random over clusters with stratification.
- `--round 2+` — active learning: picks the highest-uncertainty pairs from the ensemble's scoring of the existing pool. Requires `--score-with-ensemble` — that's the flag that actually runs the ensemble over the candidate pool; without it there are no scores to be uncertain about, so the active-learning step is a no-op.
- `--size N` — total pairs to sample. Default 30.
- `--attention-check-rate 0.05` — fraction of pairs that are unambiguous gold-standard checks. Default 0.05.

### Custom selection strategies

`select_batch()` is the function to override if you want a different sampling distribution. The default round-2+ behavior uses ensemble confidence + position-bias as the uncertainty signal.

## When to upstream a customization

If you find yourself implementing something that other operators would obviously want — a new judge prompt variant, a new aggregator correction, a new refit strategy — open an issue with the use case. Cascadia is MIT-licensed so a private fork is fine, but the project will absorb judge / aggregator / refit *strategies* that are well-characterized and methodologically defensible. See [CONTRIBUTING.md](../CONTRIBUTING.md) for the PR shape.
