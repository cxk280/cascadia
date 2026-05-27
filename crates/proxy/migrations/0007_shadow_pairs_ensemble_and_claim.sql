-- Phase 8: close the online learning loop + make multi-replica polling safe.
--
-- These columns are written exclusively by the judge worker; the proxy only
-- ever INSERTs shadow_pairs (naming columns explicitly) so the new nullable
-- columns don't affect the proxy's insert path.

-- ensemble_score / ensemble_confidence: the judge worker now persists the
-- bias-corrected ensemble score (anti-self-preference + position-fold +
-- error-exclusion, per cascadia_judge.aggregation.aggregate) once per pair, so
-- the policy controller can tune thresholds on the SAME statistic the panel is
-- calibrated against — instead of a flat AVG over raw per-judge `judge_scores`
-- rows (which counted error rows as 0, double-counted position-swapped
-- siblings, and included self-preferring judges the ensemble would drop).
--
-- NULL until the pair is judged, and NULL when no judge produced a usable
-- signal for the pair (all errored / dropped). The controller filters
-- `ensemble_score IS NOT NULL`, so a no-signal pair is excluded rather than
-- dragging the mean toward a neutral 0.5.
ALTER TABLE shadow_pairs ADD COLUMN IF NOT EXISTS ensemble_score      DOUBLE PRECISION;
ALTER TABLE shadow_pairs ADD COLUMN IF NOT EXISTS ensemble_confidence DOUBLE PRECISION;

-- claimed_at: makes `FOR UPDATE SKIP LOCKED` actually effective across poller
-- replicas. fetch_pending claims rows (sets claimed_at) in the same statement
-- that selects them, so a second replica skips claimed-and-fresh rows instead
-- of re-judging them and double-paying for LLM calls. A claim older than the
-- worker's reclaim window is treated as stale (the worker that held it crashed)
-- and becomes eligible to be re-claimed. The poller releases the claim
-- explicitly on a processing failure so transient errors retry promptly.
ALTER TABLE shadow_pairs ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;
