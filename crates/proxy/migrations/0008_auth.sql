-- Operator authentication: email + password accounts and server-side
-- opaque sessions for the Cascadia operator dashboard.
--
-- Context (PLAN.md §9, 2026-06-01): v1 shipped with no accounts. The
-- dashboard sat behind HTTP Basic Auth (the browser-native popup) and the
-- calibration flow used a cookie-only reviewer handle. This migration backs
-- first-class email/password auth so login becomes an integral part of the
-- app rather than a browser dialog. We deliberately rolled our own (no
-- OAuth, no NextAuth) with **server-side opaque sessions** rather than
-- JWTs: sessions are revocable on the spot, carry no signing-secret rotation
-- burden, and the token embeds no client-tamperable claims.
--
-- Like the calibration tables (0005), these live in the proxy's sqlx
-- migration set because the proxy owns schema and applies it at boot; the
-- FastAPI dashboard-api reads/writes them against the same Postgres.
--
-- UUIDs are generated application-side (Python `uuid.uuid4()`), matching the
-- calibration store's convention, so this migration needs no pgcrypto /
-- uuid-ossp extension.

CREATE TABLE IF NOT EXISTS auth_users (
    user_id        UUID PRIMARY KEY,
    -- Login identity. The app normalizes to lowercase before insert/lookup;
    -- the unique index below enforces case-insensitive uniqueness in the DB
    -- too, so a direct write can't sneak in a dup-by-case.
    email          TEXT NOT NULL,
    -- Argon2id PHC string (algorithm, params, salt, and hash, all encoded in
    -- the one string). We never store plaintext, and the verifier reads the
    -- params back out of this string — so a future parameter bump doesn't
    -- strand existing rows; they just get rehashed on next successful login.
    password_hash  TEXT NOT NULL,
    display_name   TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at  TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS auth_users_email_lower_key
    ON auth_users (LOWER(email));

CREATE TABLE IF NOT EXISTS auth_sessions (
    session_id     UUID PRIMARY KEY,
    user_id        UUID NOT NULL REFERENCES auth_users (user_id) ON DELETE CASCADE,
    -- We store ONLY the SHA-256 of the opaque session token, never the token
    -- itself. A DB leak therefore can't be replayed as a live session — an
    -- attacker would have to preimage SHA-256. The raw token lives only in
    -- the user's httpOnly cookie.
    token_sha256   TEXT NOT NULL UNIQUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at     TIMESTAMPTZ NOT NULL,
    last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Set when the user logs out (or an admin force-revokes). A non-null
    -- value means the session is dead regardless of expires_at.
    revoked_at     TIMESTAMPTZ,
    user_agent     TEXT
);

CREATE INDEX IF NOT EXISTS auth_sessions_user_id_idx ON auth_sessions (user_id);
CREATE INDEX IF NOT EXISTS auth_sessions_expires_at_idx ON auth_sessions (expires_at);
