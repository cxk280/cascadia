-- Phase 2: cascade routing + shadow eval.

-- Two new columns on `events` so we can answer cost/quality questions later
-- without joining shadow_pairs every time.
ALTER TABLE events ADD COLUMN IF NOT EXISTS cluster_id TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS escalated  BOOLEAN;
CREATE INDEX IF NOT EXISTS events_cluster_idx ON events (cluster_id);

--
-- shadow_pairs holds the counterfactual: cheap-tier response paired with the
-- expensive-tier response for the same prompt. The judge worker reads these,
-- scores them, and writes one row per ensemble member into judge_scores.
--
-- The proxy only ever INSERTs into shadow_pairs (with judged_at = NULL).
-- The judge worker UPDATEs judged_at when it finishes scoring a pair.

CREATE TABLE IF NOT EXISTS shadow_pairs (
    pair_id            UUID PRIMARY KEY,
    -- The event that originally triggered this shadow. Cheap-tier metadata
    -- (route, provider, latency, …) lives on the events row.
    request_id         UUID NOT NULL REFERENCES events(request_id) ON DELETE CASCADE,
    occurred_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cluster_id         TEXT NOT NULL,
    prompt             TEXT NOT NULL,
    cheap_model        TEXT NOT NULL,
    cheap_response     TEXT NOT NULL,
    expensive_model    TEXT NOT NULL,
    expensive_response TEXT NOT NULL,
    -- NULL until the judge worker has processed this pair. The poller filters
    -- on `judged_at IS NULL`; the partial index makes that an index-only scan.
    judged_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS shadow_pairs_unjudged_idx
    ON shadow_pairs (occurred_at)
    WHERE judged_at IS NULL;
CREATE INDEX IF NOT EXISTS shadow_pairs_cluster_idx ON shadow_pairs (cluster_id);
CREATE INDEX IF NOT EXISTS shadow_pairs_request_idx ON shadow_pairs (request_id);

CREATE TABLE IF NOT EXISTS judge_scores (
    score_id        UUID PRIMARY KEY,
    pair_id         UUID NOT NULL REFERENCES shadow_pairs(pair_id) ON DELETE CASCADE,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    judge_name      TEXT NOT NULL,
    prompt_variant  TEXT NOT NULL,
    -- Judge's underlying LLM (e.g. anthropic / sonnet-3.5). Lets us slice by
    -- judge family during calibration.
    model           TEXT NOT NULL,
    provider        TEXT NOT NULL,
    -- 0.0..1.0 — probability cheap response is ≥ expensive in quality. Phase 5
    -- ensemble combiner reads this column directly.
    score           DOUBLE PRECISION NOT NULL,
    confidence      DOUBLE PRECISION,
    rationale       TEXT,
    -- sha256(model || prompt_variant || system || user). Used to detect drift
    -- and to dedupe re-scores after a judge prompt bump.
    prompt_hash     TEXT NOT NULL,
    elapsed_ms      INTEGER NOT NULL,
    -- NULL on success; "ExceptionName: message" on parse/transport failure.
    error           TEXT,

    -- A pair shouldn't be scored more than once by the same (judge, variant).
    -- If a judge variant bumps to v2, a second row is legitimate.
    UNIQUE (pair_id, judge_name, prompt_variant)
);

CREATE INDEX IF NOT EXISTS judge_scores_pair_idx ON judge_scores (pair_id);
CREATE INDEX IF NOT EXISTS judge_scores_judge_idx ON judge_scores (judge_name, prompt_variant);
CREATE INDEX IF NOT EXISTS judge_scores_occurred_idx ON judge_scores (occurred_at DESC);
