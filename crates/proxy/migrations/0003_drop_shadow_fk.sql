-- Drop the FK constraint shadow_pairs.request_id → events.request_id.
--
-- Why: the proxy's writer task drains a single mpsc channel in submission order.
-- The chat handler intentionally queues the shadow_pair (from inside cascade)
-- BEFORE the event row (which it needs the cascade outcome to construct). With
-- the FK in place, the shadow_pair insert would fail with a referential
-- violation, since the events row hasn't been committed yet.
--
-- The constraint isn't load-bearing for analytics — JOIN queries on
-- request_id work fine without it, and the proxy is the only writer of both
-- tables so orphan rows are not a realistic worry.

ALTER TABLE shadow_pairs DROP CONSTRAINT IF EXISTS shadow_pairs_request_id_fkey;
