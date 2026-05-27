# Prolific calibration runbook

> Operational playbook for upgrading the human-rated calibration set from the friend-pilot (n=30, 2 reviewers) to a defensible production-grade run (n=200, 4–5 reviewers). Estimated end-to-end: **half a day of setup work + ~24 hours of waiting** for reviewers to label, then ~30 minutes to aggregate and report.

## When to pull the trigger

Three triggers that should move this from deferred to active:

1. **Going public** — Show HN, r/MachineLearning, blog launch. The "n=200 human-rated" claim is what makes the methodology blog quoteable.
2. **Recruiter takeaway / system-design round** — having "I ran a 200-pair human-rated study against a cross-family panel and characterized verbosity bias at $X" is concrete, not hand-wavy.
3. **Phase 5 final acceptance close** — the README acceptance row currently ends with "needs the 200-pair Prolific run." Closing the loop requires this.

Pin `[[cascadia-prolific-deferred]]` in memory checks for these triggers automatically.

## Budget

| Item | Cost |
|---|---|
| Reviewer pay (200 pairs × 2 coverage × 30 sec × $12/hr) | $40 |
| Prolific platform fee (33%) | $13 |
| **2-coverage subtotal** | **~$55** |
| Step up to 5-coverage (5 reviewers per pair, much higher confidence) | ~$130 |
| Hosting for the labeling app (Vercel free tier suffices) | $0 |
| LLM panel re-run after labels land (gpt-3.5-turbo + groq + anthropic-haiku) | ~$0.10 |
| **Realistic total** | **$60–$200** depending on coverage |

Well above the $25 self-imposed ceiling, so it explicitly stays deferred until you make a budget call.

## Phase 0 — Required env vars (set ALL of these before going live)

> ⚠ **Reading this section is non-optional.** A deploy missing any of these either silently corrupts the dataset or costs you $300 with no usable data.

| Env var | Service | What it does | Failure mode if missing |
|---|---|---|---|
| `CASCADIA_CALIBRATE_PASS` | `cascadia-dashboard` | Basic-auth password gating the `/calibrate*` UI in production. | **CRITICAL.** Production hard-fails 503 if unset. Set it to a fresh `openssl rand -hex 12` value; share with reviewers via a secure channel. Note: enforced only in the Next.js middleware — the dashboard-api `/api/calibrate/*` endpoints themselves have no auth. If you expose the API URL publicly, anyone with that URL can POST labels bypassing the password. Deploy the API only on an internal hostname (Railway private network is fine) and gate the Next.js frontend with the password. |
| `CASCADIA_CALIBRATE_USER` | `cascadia-dashboard` | Basic-auth username paired with `CASCADIA_CALIBRATE_PASS`. | Optional; defaults to `cascadia`. Override only if you want a project-specific username for the study URL hint. |
| `CASCADIA_DASHBOARD_API_BASE` | `cascadia-dashboard` | Internal URL of the dashboard-api service. | Dashboard SSR fetches fail; pages show "Couldn't load…" errors. |
| `CASCADIA_DATABASE_URL` | `cascadia-dashboard-api`, judge-worker, policy-controller | Postgres connection string. | API + worker dead on startup. |
| `CASCADIA_RUBRIC_PATH` | `cascadia-dashboard-api` | Path to `rubric_v2.md` inside the container. Baked into the dashboard-api Dockerfile by default (`/app/calibration/rubric_v2.md`) — only override if you've mounted the rubric somewhere else. | `/api/calibrate/rubric` returns 503; labelers see a red error box. |
| `CASCADIA_PROXY_URL` | `cascadia-dashboard-api` | Internal URL of the proxy, used by `/api/policy` + `/api/config` + `/api/proxy-reachable`. | Dashboard data-residency / policy panels show "—" everywhere. |
| `CASCADIA_PROXY_BEARER_TOKEN` | `cascadia-proxy` | Bearer-token auth on `/v1/*`. Optional but strongly recommended for a publicly-reachable proxy. | If unset, anyone with the proxy URL can submit chat-completion requests and burn through your provider credits. |

## Phase 1 — Pre-flight (do once)

1. **Stand up enough shadow_pairs to sample from.** The friend pilot ran from 42 shadow_pairs; for an n=200 calibration set with cluster stratification + attention checks, sample from **~500+ shadow_pairs minimum, ~1000 ideal**. Drive varied traffic with `bench/scripts/pareto-frontier.sh 500` or by running the proxy as a real backend for whatever's nearby (your own Claude Code traffic, a friend's app, etc.). Wider prompt diversity = more informative calibration set.

2. **Verify the proxy is pointed at real, paired-but-distinct models.** Phase 7 is live: every cluster's `cheap_model` and `expensive_model` MUST carry a `provider/` prefix (e.g. `openai/gpt-4o-mini`, not the bare `gpt-4o-mini`) — the proxy hard-fails at boot on unprefixed values. Four providers ship native adapters: OpenAI, Anthropic, Groq, xAI. Cross-provider mixed-tier (e.g. `groq/llama-3.3-70b-versatile` cheap + `openai/gpt-4o` expensive) works today; see `bench/scripts/multi-provider-pareto.sh` for a worked example. Consider adding a few clusters where the cheap-vs-expensive quality gap is wide so the calibration set isn't dominated by close-call pairs.

   On Railway / Render / Fly (no writable volume), set `CASCADIA_POLICY_JSON` to inline JSON instead of `CASCADIA_POLICY_FILE`. The proxy accepts either — see `crates/proxy/src/policy.rs::from_env`.

3. **Sign up at Prolific** — <https://prolific.com> → Create researcher account → verify identity (passport/driver's license, ~24h turnaround on average, can be faster).

4. **Deposit funds** — Prolific requires pre-funding. Deposit ~$200 to start; unused funds stay on account.

## Phase 2 — Code changes to the labeling app (~30 min)

The `dashboard/app/calibrate/page.tsx` flow today asks users to type a reviewer_id and display_name. Prolific provides identifiers via URL params, so add a code path that uses them when present.

### Files to modify

- **`dashboard/app/calibrate/page.tsx`** — accept URL params `?PROLIFIC_PID=...&STUDY_ID=...&SESSION_ID=...`. When present, auto-onboard with `reviewer_id = PROLIFIC_PID` and `display_name = "Prolific:${PROLIFIC_PID}"`, then redirect straight to `/calibrate/label`. Skip the manual form.

- **`dashboard/app/calibrate/label/page.tsx`** — when the queue empties (the 🎉 screen), show the **Prolific completion code** instead. Prolific generates this code per-study; you'll configure it in step 3 below. Format: a fixed alphanumeric string the reviewer pastes back into Prolific to claim payment.

- **`services/dashboard-api/cascadia_dashboard/calibrate/routes.py`** — add `study_id` and `session_id` optional fields to `LabelSubmission`. Persist them in `calibration_labels` (small schema add: two `TEXT NULL` columns). Useful for filtering out test submissions vs. real ones.

- **Migration `0006_prolific_metadata.sql`** — `ALTER TABLE calibration_labels ADD COLUMN study_id TEXT, ADD COLUMN session_id TEXT;`

### Test it before going live

Test by visiting the labeling URL with synthetic params: `http://your-host/calibrate?PROLIFIC_PID=TEST123&STUDY_ID=test&SESSION_ID=test`. Confirm you skip onboarding, label one pair, and see the completion code at the end.

## Phase 3 — Configure the Prolific study (~20 min in their UI)

Field-by-field setup at <https://app.prolific.com/researcher/studies>:

| Field | Recommended value |
|---|---|
| **Study title** | "Compare pairs of AI responses (~50 min, $10)" |
| **Study description** | "You'll see ~100 pairs of AI-generated responses to the same question. For each pair, pick which response you'd prefer if asked the question for real. Position is randomized; no AI knowledge required. Full instructions inside." |
| **Study URL** | Your labeling app URL with Prolific's URL params placeholder. Prolific will substitute them per-participant. Example: `https://YOUR-DEPLOY.vercel.app/calibrate?PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}` |
| **Completion code** | Generate a random string (e.g. `CASCADIA-CALIB-XYZ123`). Display this on the 🎉 screen — reviewer pastes it into Prolific to claim payment. |
| **Estimated duration** | 50 minutes (200 pairs × 2 coverage / N reviewers — calculate per your coverage choice) |
| **Reward (pay)** | $10–$12 (≥ $12/hr equivalent. Prolific shows the per-hour rate live and warns if you go below platform minimum.) |
| **Number of participants** | 4 (for 200 pairs × 2 coverage, each labels 100; pair-routing is handled by the calibration_pending view server-side) |
| **Distribution** | Standard |

### Eligibility filters (Recruitment → Screening)

| Filter | Recommended |
|---|---|
| **First language** | English |
| **Country of residence** | US, UK, CA, AU, NZ (or wherever you want — wider pool is cheaper but adds variance) |
| **Minimum approval rate** | 95% |
| **Minimum prior studies completed** | 50 (filters out brand-new accounts) |
| **Age** | 18+ |
| **Technical background** | Optional — Prolific has a "experience with computer programming" filter; helpful if you want reviewers who can read code-related prompts |

### Pair distribution across reviewers

Prolific doesn't natively split work across participants — they each see the full study URL. Two ways to handle this:

- **Server-side routing (recommended):** the `calibration_pending` view already returns unlabeled pairs per reviewer. With Prolific PIDs as reviewer_ids, each new reviewer sees only pairs nobody-on-their-PID has labeled yet. With N reviewers and N≤2 coverage per pair, this works automatically — once a pair has 2 labels from different reviewers, it falls off everyone's queue.
- **Bounded queue:** add a `--max-per-reviewer 100` flag to the calibration pending view so each Prolific worker only sees ~100 pairs even if more are unlabeled. Prevents one fast reviewer eating the whole batch.

### Sample size math

For 200 pairs × 2 coverage = 400 total labels across N reviewers:

| Reviewers | Pairs each | Time each | Pay each | Total pay |
|---|---|---|---|---|
| 4 | 100 | 50 min | $10 | $40 |
| 8 | 50 | 25 min | $5 | $40 |
| 5 | 80 | 40 min | $8 | $40 |

Same total cost — pick based on how long you want to wait. More reviewers = faster (Prolific fills slots in minutes during peak hours), fewer reviewers = more consistent labeling style per reviewer.

## Phase 4 — Sample the calibration batch (5 min)

Once shadow_pairs is populated:

```bash
cd services/judge-worker && . .venv/bin/activate
cascadia-judge-sample-calibration \
    --round 1 --size 200 --attention-check-rate 0.05 \
    --database-url postgres://cascadia:cascadia@localhost:5432/cascadia
```

Verify:

```bash
docker exec cascadia-postgres psql -U cascadia -d cascadia -c \
  "SELECT cluster_id, COUNT(*) FROM calibration_pairs GROUP BY cluster_id;"
```

Should show ~190 real pairs across your clusters + ~10 attention checks.

## Phase 5 — Deploy the labeling app publicly (~30 min)

The labeling app needs to be reachable from the open internet (Prolific reviewers won't VPN into your laptop).

> ⚠ **Set `CASCADIA_CALIBRATE_PASS` before the first public hit.** The Next.js middleware gates `/calibrate*` behind HTTP Basic Auth. In production the password is required; the middleware hard-fails 503 if unset. Generate with `openssl rand -hex 12`, set it on the dashboard service, and share it with reviewers via the Prolific study description (or a study attachment). Without this, any URL that gets posted to a public forum, indexed by a crawler, or shared by a confused reviewer becomes an open submission portal — and the labels that arrive count toward your dataset.
>
> The dashboard-api `/api/calibrate/*` endpoints have NO independent auth layer; the middleware is the only gate. Keep the API URL on an internal hostname (Railway private network is the default) so the only public surface is the Next.js frontend.

### Option A: Vercel (recommended, free tier)

```bash
cd dashboard
npx vercel --prod
```

Set environment variables in Vercel project settings:

- `CASCADIA_DASHBOARD_API_BASE=https://your-api-host`
- **`CASCADIA_CALIBRATE_PASS=$(openssl rand -hex 12)`** — production hard-fails without this.
- `CASCADIA_CALIBRATE_USER=cascadia` — optional, defaults to `cascadia`.

### Option B: ngrok (for testing only)

```bash
ngrok http 3000  # exposes your local Next.js
ngrok http 18082 # separate tunnel for the dashboard-api
```

Update `CASCADIA_DASHBOARD_API_BASE` in the Next.js process to point at the ngrok-tunneled API URL.

### Database access

The dashboard-api needs Postgres reachable from wherever it's deployed. For Vercel: stand up a managed Postgres (Neon free tier, Supabase, or RDS). Migrate the schema once. The proxy can keep writing to a local Postgres during the labeling window — just dump+restore at the end to sync data — or you can point everything at the managed DB from the start.

**Cheapest non-localhost option:** Neon (free tier, autosuspend), ~5 minutes to provision.

## Phase 6 — Launch the study (instant)

1. In Prolific UI: **Submit study for review.** Prolific moderates this within usually < 1 hour (they check the description for clarity and the study URL for accessibility).
2. Once approved, study goes live automatically. Recruits typically fill in 10–60 minutes during US/EU peak hours.
3. Reviewers click the link → land on `/calibrate?PROLIFIC_PID=...` → auto-onboard → label → submit completion code → Prolific marks them complete.

Monitor in real time:

```bash
watch -n 30 'docker exec cascadia-postgres psql -U cascadia -d cascadia -tA -c \
  "SELECT reviewer_id, COUNT(*) FROM calibration_labels GROUP BY reviewer_id ORDER BY COUNT(*) DESC;"'
```

## Phase 7 — Approve submissions (~10 min after each reviewer finishes)

For each completed submission, Prolific shows you the participant in the UI. Before clicking **Approve**:

1. Spot-check time-per-pair — if a reviewer averaged < 5 seconds per pair, they rushed. Reject with a polite reason.
2. Spot-check the attention-check pass rate via the dashboard-api:
   ```bash
   curl -s "http://your-api-host/api/calibrate/progress?reviewer_id=$PROLIFIC_PID" | python3 -m json.tool
   ```
   Reviewers with `n_attention_failed > 0` get auto-dropped by the aggregator at `--attention-failure-max 0` (recommended for paid reviewers). You can still approve their payment but their labels won't make it into the canonical set.

Prolific deducts pay automatically on approval. Rejections are subject to the platform's appeal process — be conservative; only reject for clear quality failures, not just "I disagree with their labels."

## Phase 8 — Aggregate + report (~10 min)

```bash
cd services/judge-worker && . .venv/bin/activate

# Tighter attention threshold for paid reviewers.
cascadia-judge-aggregate-labels \
    --database-url $CASCADIA_DATABASE_URL \
    --out calibration/human_rated_v1.jsonl \
    --attention-failure-max 0 \
    --min-reviewers 2

# Re-run the panel + sweep against the new larger set.
ANTHROPIC_API_KEY=... OPENAI_API_KEY=... GROQ_API_KEY=... \
  cascadia-judge-llm-panel \
    --dataset calibration/human_rated_v1.jsonl \
    --panel "anthropic:claude-haiku-4-5,openai:gpt-3.5-turbo,groq:llama-3.3-70b-versatile" \
    --concision-sweep "0.0,0.05,0.1,0.15,0.2,0.25,0.3,0.4,0.5" \
    --out /tmp/cascadia-panel-prolific.json
```

The aggregator output will include:
- Pairwise Cohen's κ across all reviewer pairs (with N=4–8 reviewers, this is meaningfully more stable than the n=2 friend pilot)
- Per-reviewer attention pass/fail counts
- Per-reviewer time-per-pair distribution
- Consensus / disagreement / excluded pair counts

The panel report will give you the τ-b at each concision weight. Compare to the friend pilot's `+0.20 (best)` — if the larger dataset moves the needle meaningfully, the verbosity-bias finding is robust. If τ-b crosses 0.7 with the wider quality-gap pair pool, congratulations, Phase 5 is closed.

## Phase 9 — Publish

1. **Update README acceptance row** — Phase 5 from ⚠ to ✅ (or stay ⚠ with the honest τ-b number from the bigger run, depending on outcome).
2. **Update methodology blog** — replace the "2026-05-19 pilot" section with the Prolific run's numbers, keep the friend-pilot as the "early findings that motivated the Prolific upgrade."
3. **Commit the canonical JSONL** — `services/judge-worker/calibration/human_rated_v1.jsonl` with the full Prolific labels (anonymized — the `reviewer_id` field already is, since Prolific PIDs are opaque).
4. **PLAN.md §9 decisions log entry** — append, don't rewrite. The friend pilot stays in the log; the Prolific run is the next chapter.

## Troubleshooting

| Problem | Fix |
|---|---|
| Reviewers can't submit completion code | Check that `?PROLIFIC_PID=...` reaches the labeling app. Look at the dashboard-api logs for the actual reviewer_id being onboarded. |
| Low completion rate (reviewers start but don't finish) | Study description unclear, or pay rate too low for the duration. Raise pay or shorten the batch per reviewer. |
| High attention-check failure rate (> 20%) | Rubric still ambiguous OR reviewers rushing OR the attention checks are too tricky. Re-read the rubric for ambiguity; tighten Prolific eligibility filters; consider rubric v3. |
| Cohen's κ < 0.4 with paid reviewers | The task is genuinely ambiguous OR your pair pool is too heavy on close-calls. Mix in wider-quality-gap pairs (e.g., gpt-3.5-turbo vs gpt-4o). |
| Prolific rejects the study at submission | Usually the URL isn't reachable from their crawler. Test with `curl -A "ProlificStudyChecker" $STUDY_URL` to verify. |
| Reviewer disputes a rejection | Prolific's appeal process kicks in. Be ready with the attention-check evidence + time-per-pair data. They side with the reviewer on ambiguous cases. |

## End-to-end timeline (honest)

| Phase | Wall time |
|---|---|
| 1. Pre-flight (drive traffic, sign up, verify ID) | 1–3 days (ID verification is the long pole) |
| 2. Code changes | 1 hour |
| 3. Configure study | 30 min |
| 4. Sample batch | 5 min |
| 5. Deploy app publicly | 30 min |
| 6. Launch + Prolific moderation | 1 hour after submission |
| 7. Reviewers complete | 4–24 hours after going live |
| 8. Approve + aggregate | 30 min |
| 9. Publish | 1 hour |
| **Total active researcher time** | **~5 hours** |
| **Total wall time** | **~2–4 days** (mostly waiting on ID verification + reviewer completion) |
