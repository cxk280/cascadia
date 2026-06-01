-- Postgres-backed policy distribution (controller -> proxy).
--
-- The closed-loop design (policy-controller refits thresholds, proxy
-- hot-reloads) was originally wired over a shared filesystem volume mounted
-- into both services (see deploy/compose/docker-compose.full.yml). That can't
-- exist on deploy targets where volumes are single-service (Railway). This
-- table is the cross-service rendezvous instead: the controller appends a new
-- row whenever a refit changes a threshold; the proxy polls the latest row and
-- hot-swaps its in-memory policy (crates/proxy/src/watcher.rs::spawn_pg).
--
-- Append-only, so the table doubles as a full audit trail of every policy
-- version the controller ever published. See PLAN.md §9 (2026-06-01).
CREATE TABLE IF NOT EXISTS policy_store (
    id         BIGSERIAL   PRIMARY KEY,
    version    TEXT        NOT NULL,
    body       JSONB       NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
