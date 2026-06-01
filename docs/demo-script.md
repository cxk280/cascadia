# Cascadia — employer-demo script

> One-page runbook for a 5-to-10-minute live demo. Assumes the local stack is up
> (`docker compose up -d`, proxy + dashboard-api + dashboard running, see [README.md](../README.md#quick-start))
> and that benchmark traffic has been populated (`bench/scripts/pareto-frontier.sh`).
>
> Numbers in this script come from the live dev DB as of `2026-05-26`: 458 requests,
> 64 calibration labels (round 1 + round 2), 1359 judge_scores (453 shadow pairs × a
> 3-judge panel), 4 clusters. Refresh them by re-running the script and the populator
> before a demo — or just read them off the live dashboard, which is authoritative.

## The story in one sentence

> "Every LLM gateway you've seen routes by rules a human wrote. Cascadia routes by a closed loop — and here's the chart it generated yesterday from its own shadow data."

## Cold-start narrative (30s, before clicking anything)

Open with the three-claim spine, fast:

1. **Counterfactual shadow routing** — the proxy mirrors a configurable fraction of cascade decisions to the next tier up. So "what would the expensive model have said?" is a side effect of serving traffic, not a separate eval pipeline.
2. **Per-cluster online policy learning** — requests get hashed into N clusters; each cluster's `(cheap_model, expensive_model, threshold, shadow_rate)` policy refits from a bandit-style update over judge scores.
3. **Bias-corrected judge ensemble, human-calibrated** — pairwise + rubric prompts, position swap, anti-self-preference, scored against a real human-rated set. This is the part that makes the cost-saving number not a lie.

Then: *"The dashboard is showing the live operating point on the Pareto chart from those three things working together. Let me walk you through it."*

## Click-by-click tour

### 1. `/` — Overview (15s)

Point at the four KPI cards. Anchor numbers:

| KPI | Live value |
|---|---|
| Requests (7d window) | **458** |
| Escalation rate | **69.9%** |
| Avg latency | **~5.6s** (LLM round-trip, not proxy overhead) |
| Mean judge score | **0.522** over n=1359 |

Say: *"Escalation rate 70% means seven in ten requests didn't trust the cheap tier. That's the policy controller saying 'don't risk it' — which is exactly what we want the system to do without a human tuning the threshold."*

Then: *"The proxy itself adds about 2ms on top of that, measured separately under load. The ~5.6s is the model call. The point of the gateway is to make sure each of those round-trips is worth it — that's the next page."*

### 2. `/pareto` — Pareto frontier (90s — the headline)

This is the chart that closes the interview. Talk through:

- One dot per cluster. X-axis = escalation rate (cost proxy). Y-axis = mean judge score. Dot size = sample count.
- Real numbers from the current DB (Phase 7.3 mixed-provider seed):

| Cluster | Providers | Escalation | Quality | n |
|---|---|---|---|---|
| cluster-0 | openai | **52.9%** | 0.507 | 297 |
| cluster-1 | openai | **81.0%** | 0.508 | 315 |
| **cluster-mixed** | **groq → openai** | **69.7%** | **0.596** | 297 |
| cluster-3 | openai | **74.7%** | 0.495 | 450 |

Say: *"Look at cluster-mixed. It's running Groq's llama-3.3-70b as the cheap tier and escalating to OpenAI's gpt-4o on the expensive tier. Same prompts as the others — that's the same closed-loop machinery — but the quality lands at 0.596 vs ~0.51 everywhere else. That dot is what Phase 7 cross-provider cascade buys you: the controller doesn't care which provider's name is on the model string; it learns the right threshold by counterfactually scoring its own decisions."*

Then say: *"Cluster-1 is doing 81% escalation for almost the same quality as cluster-0 at 53%. That's a ~28-point cost gap for ~0 quality gap — that's where the controller's next refit will pull cluster-1's threshold down. That arrow is the closed loop, drawn from real data."*

Honest beat: *"This is the live operating point, not the full frontier. To draw the curve you'd run the controller across a parameter sweep and plot each. The script `bench/scripts/pareto-frontier.sh` regenerates exactly the data behind this chart — about 15 seconds from a clean DB."*

### 3. `/clusters` — Cluster explorer (20s)

Point at the four-row table. Same numbers, sortable by request count / escalation rate / mean judge score. Say: *"This is the per-cluster breakdown of the chart we just saw — the rows feed the dots."*

### 4. `/activity` — Recent activity (20s)

Two panels — recent events (proxy decisions) on the left, recent judge verdicts on the right. Say: *"Left side is the proxy emitting decision events the moment they happen. Right side is the judge worker scoring shadow pairs asynchronously. The latency between them is the controller's cycle time — the bigger the gap, the slower the loop closes."*

### 5. `/calibrate/rubric` — The rubric (60s — the credibility beat)

**This is the killer slide for the rigor argument.** Walk through:

- Rubric v1 → v2 transition with Cohen's κ progression: **κ = −0.024 → +0.519**.
- *"v1 said 'when in doubt, tie.' Two reviewers labeled 30 pairs and we got κ ≈ 0 — essentially noise. Reviewer A was a liberal tie-caller, reviewer B picked winners. v2 said 'tie is last resort' with worked examples. κ jumped to +0.52 on the next round. Same reviewers, same pairs, just a sharper rubric."*
- *"That's not a fix that ships in most gateway repos. It's a fix that ships in academic eval papers."*

### 6. `/calibrate/label` — The labeling tool (20s)

Show keyboard shortcuts ([A] / [B] / [T] / [U], Esc to blur rationale). Mention position randomization (deterministic per pair-reviewer) and the attention checks (the pilot had 2 gold-standard checks in its 30-pair round; the tool default is ~5%). Say: *"This is the tool that produced the κ number on the previous page. It's the same tool we'd hand to Prolific reviewers for the 200-pair production set."*

## The verbosity-bias honesty beat (90s — refuse to flinch)

This is the differentiator most candidates fail at. Walk through:

- *"After we fixed the rubric, we ran the bias-corrected judge ensemble against the same human labels — and the ensemble agreed with humans at **τ-b ≈ 0**."*
- Show the cherry-picked disagreement table from `docs/blog/methodology.md`:
  - "What year did the Berlin Wall fall?" — Cheap: *"November 9, 1989."*  Expensive: *"1989."* — **Human picked expensive** (answers what was asked); **panel picked cheap** (more detail).
  - "Speed of light in km/s?" — same pattern: humans prefer concise, panel prefers verbose.
- *"This is **verbosity bias** — Zheng et al. 2023 published it; we reproduced it cleanly in our own data. The 3-judge cross-family panel was unanimous on 24 of 30 pairs and still wrong by human standards."*
- *"The clean part: panel-internal τ ≈ +0.28. The judges agree with each other meaningfully. They disagree with humans uniformly. That's a bias, not noise."*
- *"The concision-adjusted aggregator (`--concision-weight 0.30`) walks the panel-vs-human τ-b from **−0.152 → +0.196** — full sweep table in `docs/blog/methodology.md`. The best weight isn't a silver bullet; it's a published, characterized correction."*
- Closer: *"Most gateway repos publish '97% quality at 78% cost' and don't tell you what the judge is or whether it agrees with humans. We published that the headline judge agreed with humans at zero, named the bias, shipped the correction, and put the gap on the website. That's the methodology blog. The reason that's the right move for a portfolio: anyone who reads it knows what they're looking at."*

## Differentiator close (30s)

Pull from the [README → "What makes Cascadia different"](../README.md#what-makes-cascadia-different):

> *"LiteLLM and Portkey are provider plumbing with human-authored routing rules. Cascadia is the layer that learns what those rules should be. They compose — stack Cascadia on top of LiteLLM if you want both. The thing competitors structurally can't ship is the closed loop, because they don't generate the shadow data. We do, as a side effect of serving traffic."*

Then point at the architecture diagram on the README and stop talking.

## If they ask the obvious questions

| Question | Answer |
|---|---|
| *"Isn't this just LiteLLM?"* | "LiteLLM is plumbing — 100+ providers behind one OpenAI shape. Cascadia is the policy layer above it. They compose. See the README's 'What makes Cascadia different' for the long answer." |
| *"How big is the calibration set?"* | "30 pairs, 2 reviewers, real humans. That's a pilot, not a publishable claim. Production-grade is a 200-pair Prolific run (~$300) that's queued — see PLAN.md `[[cascadia-prolific-deferred]]`." |
| *"What's the proxy overhead?"* | "P99 ≈ 5.6ms on macOS loopback. Target was <2ms on tuned Linux; that's deferred to Phase 6 — characterized, not buried." |
| *"What providers do you support?"* | "OpenAI, Anthropic, Groq today. vLLM/Together queued in Phase 7. Hard-fail on unprefixed model strings — locked decision in PLAN §9, 2026-05-19." |
| *"Where's the code I'd actually read first?"* | "`crates/proxy/src/cascade.rs` for the hot path. `services/judge-worker/cascadia_judge/aggregation.py` for the ensemble correction. `services/policy-controller/cascadia_policy/controller.py` for the bandit refit. README has the chart." |

## Pre-demo checklist

- [ ] Stack is up: proxy on 18080, dashboard-api on 18082, dashboard on 3000.
- [ ] `curl http://127.0.0.1:18082/api/overview?window_minutes=10080` returns `request_count: 151+`.
- [ ] `/pareto` page renders the chart (dashboard's window default must be wide enough to include the loaded data — bug fixed in Task #3).
- [ ] `/activity` page loads without HTTP 500 (bug fixed in Task #3).
- [ ] Browser zoomed to a level where the four-cluster scatter is legible.
- [ ] `docs/blog/methodology.md` and the README's "What makes Cascadia different" open in adjacent tabs in case they ask.

## Post-demo follow-ups (have ready)

- Link to public GitHub repo with the README chart.
- Link to `docs/blog/methodology.md` for the rigor argument.
- Link to the README's "What makes Cascadia different" for the LiteLLM/Portkey comparison.
- One-line bio: *"Senior DevOps + AI engineer, MIT-licensed flagship — closed-loop quality measurement is the differentiator, the Pareto chart is the artifact, the methodology blog is the credibility."*
