# Security Policy

## Reporting a vulnerability

Please email **chris@cking.me** with:
- A description of the vulnerability.
- Steps to reproduce.
- The version / commit SHA you observed it on.
- Optional: a suggested fix.

Please **do not** open a public GitHub issue for security findings. Give the maintainer at least 90 days to ship a fix before public disclosure.

## Scope

Cascadia is a self-hostable LLM gateway. The most security-sensitive surfaces are:

| Surface | Risk | Control |
|---|---|---|
| `/v1/chat/completions` on `cascadia-proxy` | Untrusted user prompts; provider API key exfiltration if responses leak request bodies | Audit log via `events`; never echoes API key |
| `cascadia-dashboard-api` (`/api/calibrate/*`) | Calibration labels are operator data; the `/calibrate` flow is gated by basic-auth in production | `CASCADIA_CALIBRATE_PASS` env var |
| Postgres `events.request_body` / `events.response_body` | Can contain user prompts and model output | Disabled by default (`CASCADIA_PERSIST_BODIES=false`) — opt-in |
| Postgres `shadow_pairs.prompt` / `cheap_response` / `expensive_response` | **Verbatim user prompt + both tier responses written every time a shadow route fires.** The judge worker reads these to score quality. | Persisted by default; redactable via `CASCADIA_REDACT_SHADOW_BODIES=true` (replaces text with `sha256:…` digests). Closed-loop quality scoring stops working when redacted — judge has nothing to compare. Trade-off must be explicit. |
| Policy file (`CASCADIA_POLICY_FILE`) | Path traversal / arbitrary read if mis-configured | Operator controls path; the proxy `read_to_string`s exactly the configured path |

### Data residency at a glance

If your environment cannot accept user prompts being written verbatim to
Postgres (regulated industries, GDPR/CCPA-flagged data), there are three
postures, ranked by restrictiveness:

1. **Full persistence** (default) — `shadow_pairs.{prompt,cheap_response,expensive_response}` written verbatim. The closed-loop judge ensemble works end-to-end. Suitable for first-party SaaS where the operator owns the data.
2. **Redacted shadow bodies** — set `CASCADIA_REDACT_SHADOW_BODIES=true`. Shadow pairs are still written but text columns contain `sha256:` digests instead of verbatim content. Metadata (cluster, models, timestamps, escalation outcome) is preserved. The judge worker can correlate decisions but cannot score them — the quality feedback loop is effectively disabled. Use for environments where you need cascade telemetry without storing user text.
3. **Shadow eval disabled** — set every cluster's `shadow_rate` to `0.0`. No `shadow_pairs` are written at all. The proxy still cascades, still escalates, still logs `events`, but the counterfactual signal is gone. Closest to "stateless gateway" mode.

Operators in regulated environments should pick a posture explicitly. The default is full persistence; document your choice in your deploy runbook.

The dashboard's [`/health` page](https://cascadia-dashboard-dev.up.railway.app/health) renders the current posture so an operator answering a DSAR can see at a glance what's stored without grepping env vars.

### GDPR / DSAR (data subject access requests)

**Cascadia does NOT carry user identity.** The proxy sees requests + responses but not who sent them; the only identifier in `events` is the per-request UUID. To fulfill an "access" or "erasure" request, the operator's *application layer* (the thing in front of Cascadia) must correlate user → request_id (via its own session/auth layer) and pass the list of `request_id`s into the recipe below.

The application layer is the right place for this anyway: it knows the auth model, the data-controller relationship, and the legal basis. Cascadia is the *processor*, not the controller.

**Where the request_id comes from.** Every successful `/v1/chat/completions` response (streaming + non-streaming) carries an `x-cascadia-request-id` header with the per-request UUID. The application layer should log this alongside its own user/session id at request time — that's the correlation table that lets you turn "Sara, user_id=12345" into the list of `request_id`s the recipe below consumes. There is no in-proxy correlation table because the proxy never sees user identity.

**Deletion recipe** (run against the proxy's Postgres; cascading FKs from `shadow_pairs` and `judge_scores` handle the rest):

```sql
-- Given a CSV of request_ids the application layer correlated to the user:
DELETE FROM judge_scores
 WHERE pair_id IN (
   SELECT pair_id FROM shadow_pairs WHERE request_id = ANY($1::uuid[])
 );
-- Calibration tables (only present if /calibrate has been used). The pairs
-- here are derivative: each row references a shadow_pair the operator
-- chose to score. Drop them before the parent shadow_pairs rows so the
-- foreign-key constraint stays satisfied.
DELETE FROM calibration_labels
 WHERE pair_id IN (
   SELECT pair_id FROM shadow_pairs WHERE request_id = ANY($1::uuid[])
 );
DELETE FROM calibration_pairs
 WHERE pair_id IN (
   SELECT pair_id FROM shadow_pairs WHERE request_id = ANY($1::uuid[])
 );
DELETE FROM shadow_pairs
 WHERE request_id = ANY($1::uuid[]);
DELETE FROM events
 WHERE request_id = ANY($1::uuid[]);
```

Note: `shadow_pairs.request_id` is denormalized from `events.request_id` (per migration `0003_drop_shadow_fk.sql` the FK was dropped so shadow pair persistence doesn't block on the events insert) — running all five DELETEs covers the cascade explicitly.

**Access (DSAR read) recipe:**

```sql
-- Same correlation step as above. Return everything Cascadia stores.
SELECT request_id, occurred_at, route, provider, model,
       request_body, response_body, cluster_id, escalated, tools_present
  FROM events WHERE request_id = ANY($1::uuid[]);

SELECT pair_id, request_id, occurred_at, cluster_id,
       prompt, cheap_model, cheap_response, expensive_model, expensive_response
  FROM shadow_pairs WHERE request_id = ANY($1::uuid[]);

SELECT js.*
  FROM judge_scores js
  JOIN shadow_pairs sp ON sp.pair_id = js.pair_id
 WHERE sp.request_id = ANY($1::uuid[]);
```

If `CASCADIA_PERSIST_BODIES=false` (default), the `events.request_body` / `events.response_body` columns will be `NULL`. If `CASCADIA_REDACT_SHADOW_BODIES=true`, the text columns in `shadow_pairs` are SHA-256 digests, not verbatim text — the access response should explain that those digests are not reversible.

**Retention:** Cascadia does not auto-expire rows. Operators in regulated environments should add a periodic job (`pg_cron` / `pg_partman` / a Kubernetes CronJob) appropriate to their retention policy. `shadow_pairs` grows faster than `events` whenever `shadow_rate > 0` and is the bigger storage liability; partition or expire it on a shorter schedule.

Sample retention job (30-day window — adjust to your regulatory regime):

```sql
DELETE FROM judge_scores
 WHERE occurred_at < NOW() - INTERVAL '30 days';
DELETE FROM calibration_labels
 WHERE created_at < NOW() - INTERVAL '30 days';
-- shadow_pairs occupies the most disk; consider a shorter window here.
DELETE FROM shadow_pairs
 WHERE occurred_at < NOW() - INTERVAL '14 days';
DELETE FROM events
 WHERE occurred_at < NOW() - INTERVAL '30 days';
```

PRs welcome adding a built-in retention setting; today it's BYO.

### AI-specific risks (out of scope today; documented for transparency)

These surfaces have not been hardened in v0 and operators should know:

- **Judge-prompt injection.** The judge LLMs receive `(prompt, response_a, response_b)` triples wrapped in a fixed instruction template. v0.0.1 added two layered defenses: (1) the system prompt now names "untrusted user-and-model content" and instructs the judge to ignore embedded instructions; (2) the inputs are wrapped in `<prompt>`, `<response_a>`, `<response_b>` XML-style tags so a malicious response that tries to impersonate a closing tag is treated as literal text; (3) the JSON-parse regex now anchors to the *trailing* JSON object so a smuggled `{"score": 1.0, ...}` earlier in the response can't win. None of these are bulletproof — sophisticated injections that mimic JSON-only output will still land. The anti-self-preference filter is orthogonal and only catches model-name matches. Treat judge scores as advisory under adversarial traffic.
- **Cheap-tier response injection.** A malicious cheap-tier provider could lace responses with content designed to inflate its own judge scores. Mitigated in part by cross-family judge panels (which converge despite injection attempts because they each parse the suspect text independently) + the layered defenses above, but not eliminated.
- **Prompt exfiltration via shadow eval.** The shadow_pair persistence path means *any* prompt that triggers a shadow route is stored alongside both tiers' responses. A jailbroken user prompt extracted from `shadow_pairs.prompt` could be replayed.

None of these are unique to Cascadia — they're inherent to LLM-as-judge pipelines — but they belong in the threat model.

### Operator authentication (dashboard)

The operator dashboard is gated by email + password auth (added 2026-06-01; see PLAN.md §9). Posture:

- **Passwords:** Argon2id (argon2-cffi), never stored or logged in plaintext; transparent rehash on login when params advance.
- **Sessions:** opaque 256-bit CSPRNG tokens, **not JWT**. Only the SHA-256 is persisted (`auth_sessions`); the raw token lives solely in an `httpOnly`, `SameSite=Lax`, `Secure`-in-production cookie. Sessions are revocable on the spot (logout, or admin) and expire at 30 days — a DB leak can't be replayed without preimaging SHA-256.
- **Email verification:** signup is double opt-in. Confirmation tokens are single-use, 24 h, and again stored only as SHA-256. The session is issued **after** verification, never at signup.
- **Roles:** `operator` / `admin` / `reviewer`, assigned server-side only (first account → admin; never taken from the request body). Middleware gates the calibration surface to admin/reviewer and confines reviewers to it. Validation is authoritative server-side and **fails closed** — an unreachable auth service denies access.
- **Account enumeration — deliberate tradeoffs.** Login is generic (`invalid email or password`) and spends a dummy Argon2 verify on unknown emails to equalize timing. Signup (`409 email exists`), the login *not-verified* `403`, and the verify endpoint *do* reveal that an address is registered — unavoidable for a product that refuses silent duplicate accounts and must tell users to check their inbox; `resend-verification` stays generic to limit it.
- **Transport:** the dashboard-api is server-to-server only (browser → Next.js route handlers → dashboard-api), same posture as the calibration write surface; the raw session/verification tokens never reach browser JS.

### Unauthenticated read endpoints (information disclosure by design)

The proxy exposes two read-only endpoints with no auth gate:

- `GET /policy` — the current in-memory policy table (cluster IDs, model strings, thresholds, shadow rates).
- `GET /config` — non-secret deployment config (data-residency posture, bearer-auth-enabled flag, policy version + cluster count).

Neither returns credentials, but together they reveal your cascade routing strategy to any unauthenticated caller — useful for an attacker designing escalation-bypass payloads. The endpoints are public because the dashboard-api uses them for operator-visible surfaces (the `/clusters` table's Threshold + Shadow rate columns, the `/health` page's data-residency block). If you need to gate them, run the proxy behind a private network and use only an ingress for `/v1/*` + the K8s probes.

### Pseudonymized calibration archive

`services/judge-worker/calibration/archive/` ships the labels from the 2026-05-19 pilot for audit purposes. Reviewer IDs were pseudonymized to `reviewer-a` / `reviewer-b` before public release; the original IDs were the project's first-name handles of the two participants. The pilot prompts themselves are generic factual/coding queries with no PII — see the methodology blog for the dataset description.

## Out of scope

- DoS / rate-limit bypass on a single deployment. Operators are expected to put a rate-limiter in front of the proxy.
- Issues in third-party dependencies that don't have a known exploit in our usage.
- Issues that require a malicious admin (e.g., someone with `CASCADIA_DATABASE_URL` access).

## Response

The maintainer will:
1. Confirm receipt within 7 days.
2. Triage and assign a severity within 14 days.
3. Ship a fix or document a workaround within 90 days for high-severity issues.
4. Credit you in the release notes (unless you'd prefer not to be named).
