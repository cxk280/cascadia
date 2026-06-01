-- Roles for operator-auth (PLAN.md §9, 2026-06-01 follow-up).
--
-- Three roles:
--   operator (default) - the daily-driver: dashboard + policy tuning.
--   admin              - operator + calibration/labeling + role management.
--   reviewer           - ONLY the calibration labeling surface, no dashboard.
--
-- Role is assigned server-side, never by the client: the FIRST account to sign
-- up becomes admin (bootstrap), everyone else is an operator, and an admin can
-- promote/demote via the admin-only set-role endpoint. Calibration is the
-- methodology owner's job, not a normal user's — this column is what enforces
-- that boundary (the sidebar already hides it; this makes it real).

ALTER TABLE auth_users
    ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'operator';

-- Constrain to the known roles. Wrapped so a re-run (e.g. after a manual
-- partial apply) doesn't error on the already-present constraint.
DO $$ BEGIN
    ALTER TABLE auth_users
        ADD CONSTRAINT auth_users_role_chk
        CHECK (role IN ('operator', 'admin', 'reviewer'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
