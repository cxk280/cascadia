-- Initial schema for the Cascadia event log.
--
-- Every request through /v1/chat/completions becomes a row here. Phase 2 adds
-- shadow_pairs (one row per counterfactual shadow eval) and judge_scores
-- (one row per ensemble member's evaluation of a shadow pair). For now,
-- events is the single source of truth.

CREATE TABLE IF NOT EXISTS events (
    request_id          UUID PRIMARY KEY,
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    route               TEXT NOT NULL,
    provider            TEXT NOT NULL,
    model               TEXT NOT NULL,
    -- HTTP status returned by upstream provider (NULL if Cascadia rejected before calling upstream).
    upstream_status     SMALLINT,
    -- Total handler latency in ms (proxy-classify + upstream call + bookkeeping).
    elapsed_ms          INTEGER NOT NULL,
    -- Token counts pulled from upstream response. NULL when response didn't include `usage`.
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    -- Optional verbatim request/response bodies. Only persisted when
    -- CASCADIA_PERSIST_BODIES=true. Off by default for privacy + storage cost.
    request_body        JSONB,
    response_body       JSONB,
    -- Cascadia error code (e.g. `bad_request`, `upstream_status`, `provider_unconfigured`).
    -- NULL on success.
    error_code          TEXT
);

CREATE INDEX IF NOT EXISTS events_occurred_at_idx ON events (occurred_at DESC);
CREATE INDEX IF NOT EXISTS events_model_idx       ON events (model);
CREATE INDEX IF NOT EXISTS events_status_idx      ON events (upstream_status);
CREATE INDEX IF NOT EXISTS events_provider_idx    ON events (provider);
