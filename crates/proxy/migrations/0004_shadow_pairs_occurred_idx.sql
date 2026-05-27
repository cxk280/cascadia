-- The policy controller's refit query joins shadow_pairs to judge_scores and
-- filters on `shadow_pairs.occurred_at > $cutoff`. The Phase-2 schema only had
-- a partial index on (occurred_at) WHERE judged_at IS NULL — useful for the
-- poller, useless for the controller which targets *judged* rows. At Phase-6
-- traffic (~50 shadow pairs/sec, millions of rows/day) the controller's full
-- seq scan would dominate DB CPU. This unconditional index fixes it.

CREATE INDEX IF NOT EXISTS shadow_pairs_occurred_at_idx ON shadow_pairs (occurred_at);
