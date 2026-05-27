-- Calibration set tables for the human-rated Phase-5 calibration set.
--
-- The Phase-5 acceptance criterion (Kendall's τ-b ≥ 0.7 between the judge
-- ensemble and humans) is currently demonstrated on a 15-pair synthetic
-- golden set. The production-grade version replaces that with ~200 pairs
-- sampled from real shadow_pairs, labeled by ≥2 reviewers each. These
-- tables back the active-learning sampler, the Next.js labeling app, and
-- the aggregator that emits canonical JSONL for the existing calibration
-- harness.
--
-- Why DB rather than JSONL files? Multi-reviewer overlap + position
-- randomization tracking + resume-support + inter-rater agreement queries
-- all want relational structure. Final canonical labels still export to
-- JSONL (the source of truth for the calibration harness) so the
-- reproducibility story stays intact.

CREATE TABLE IF NOT EXISTS calibration_reviewers (
    reviewer_id     TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    onboarded_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS calibration_pairs (
    pair_id                 UUID PRIMARY KEY,
    -- Source of the pair. Examples:
    --   "shadow_pairs:abcd-1234-..."  → sampled from a real proxy pair
    --   "synthetic:golden_v0:math-easy-a"
    --   "attention_check:obvious_b_wins:001"
    source                  TEXT NOT NULL,
    prompt                  TEXT NOT NULL,
    response_a              TEXT NOT NULL,
    response_b              TEXT NOT NULL,
    model_a                 TEXT,
    model_b                 TEXT,
    cluster_id              TEXT,
    -- Ensemble snapshot at sampling time. Round-1 (seed) pairs may have
    -- these NULL because no ensemble run happened yet. Round-2+ pairs
    -- record the values that drove the uncertainty sample so a later
    -- audit can see *why* this pair got picked.
    ensemble_score          DOUBLE PRECISION,
    ensemble_confidence     DOUBLE PRECISION,
    ensemble_position_bias  DOUBLE PRECISION,
    selection_round         INTEGER NOT NULL,
    selection_reason        TEXT NOT NULL,
    -- For attention-check pairs, this is the unambiguous correct label.
    -- A reviewer who picks the wrong answer here is flagged for review.
    -- NULL for ordinary pairs.
    attention_check_answer  TEXT CHECK (attention_check_answer IN ('a', 'b', 'tie')),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS calibration_pairs_source_idx ON calibration_pairs (source);
CREATE INDEX IF NOT EXISTS calibration_pairs_round_idx ON calibration_pairs (selection_round);

CREATE TABLE IF NOT EXISTS calibration_labels (
    label_id        UUID PRIMARY KEY,
    pair_id         UUID NOT NULL REFERENCES calibration_pairs(pair_id) ON DELETE CASCADE,
    reviewer_id     TEXT NOT NULL REFERENCES calibration_reviewers(reviewer_id),
    -- Position randomization. If TRUE, the reviewer saw response_b in slot A
    -- and response_a in slot B. The aggregator un-swaps `raw_label` when
    -- emitting the canonical JSONL.
    shown_swapped   BOOLEAN NOT NULL DEFAULT FALSE,
    raw_label       TEXT NOT NULL CHECK (raw_label IN ('a', 'b', 'tie', 'unknown')),
    rationale       TEXT,
    time_ms         INTEGER,
    rubric_version  TEXT NOT NULL,
    labeled_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- One label per (pair, reviewer). A reviewer who wants to re-label a
    -- pair (e.g. after re-reading the rubric) issues an UPSERT.
    UNIQUE (pair_id, reviewer_id)
);

CREATE INDEX IF NOT EXISTS calibration_labels_reviewer_idx ON calibration_labels (reviewer_id);

-- A reviewer's "pending queue" is just pairs without a label from this
-- reviewer. Pre-computing it as a view keeps the labeling-API SQL tight.
CREATE OR REPLACE VIEW calibration_pending AS
SELECT
    p.pair_id,
    p.source,
    p.prompt,
    p.response_a,
    p.response_b,
    p.model_a,
    p.model_b,
    p.cluster_id,
    p.selection_round,
    p.selection_reason,
    r.reviewer_id
  FROM calibration_pairs p
 CROSS JOIN calibration_reviewers r
  LEFT JOIN calibration_labels l
         ON l.pair_id = p.pair_id AND l.reviewer_id = r.reviewer_id
 WHERE l.label_id IS NULL
 ORDER BY p.selection_round ASC, p.created_at ASC;
