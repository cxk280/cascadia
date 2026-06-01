-- Email verification (PLAN.md §9, 2026-06-01 follow-up): signup is not complete
-- until the user confirms via an emailed link. New accounts start UNVERIFIED
-- and cannot log in until verified — including the first (bootstrap admin)
-- account; there is no exception.

ALTER TABLE auth_users
    ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS auth_email_verifications (
    id            UUID PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES auth_users (user_id) ON DELETE CASCADE,
    -- Only the SHA-256 of the opaque verification token is stored (same posture
    -- as sessions); the raw token travels only in the emailed link, so a DB
    -- leak can't be replayed to verify an account.
    token_sha256  TEXT NOT NULL UNIQUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at    TIMESTAMPTZ NOT NULL,
    -- Set when the link is used. A non-null value means the token is spent
    -- (single-use).
    consumed_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS auth_email_verif_user_idx
    ON auth_email_verifications (user_id);
