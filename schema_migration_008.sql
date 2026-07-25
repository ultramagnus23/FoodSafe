-- ============================================================
-- FoodSafe India — Schema Additions (migration_008)
-- Run AFTER schema_migration_007.sql
-- Adds: real RLS activation for `foodsafe_app` (H2.7 — security hardening).
--
-- Context: schema.sql enables RLS on users/api_keys/refresh_tokens keyed
-- on current_setting('app.user_id'), but that setting was never populated
-- anywhere in the app, and production has always connected as the DB
-- owner (which bypasses RLS regardless). So the RLS story in schema.sql's
-- comments has never actually been enforced. api/db.py now has a
-- `user_scoped(user_id)` helper that sets app.user_id via set_config(...,
-- is_local=true) inside a transaction for authenticated, already-user-
-- scoped routes (api/routes/user.py, api/routes/api_keys.py,
-- POST /v1/auth/refresh, /v1/auth/logout).
--
-- This migration closes two gaps found while wiring that up:
--   1. refresh_tokens has RLS ENABLED (schema.sql:315) but no POLICY was
--      ever created for it — under RLS, "enabled + no policy" means
--      default-deny for any non-owner role, so switching DATABASE_URL to
--      foodsafe_app without this would silently break login/refresh/
--      logout entirely (every refresh_tokens query would return 0 rows).
--   2. pipeline_runs and consumer_reports were added in migrations 005 and
--      007 without a matching GRANT block (unlike 002/003/004, which each
--      grant to foodsafe_app for the tables they add) — the app role
--      couldn't write to either table today if it weren't for the blanket
--      `GRANT SELECT ON ALL TABLES` plus the `GRANT INSERT, UPDATE ON
--      enforcement_records, audit_log, brand_disputes, rti_requests`
--      leaving these two out of the INSERT/UPDATE grant entirely.
--
-- IMPORTANT — activation is NOT automatic: this migration makes RLS
-- correct and safe to switch on, but production still connects as the DB
-- owner per docs/foodsafe-local-dev memory ("Run the API as the DB owner,
-- not foodsafe_app — the restricted role breaks login"). That reason no
-- longer applies to refresh_tokens after this migration, but before
-- flipping DATABASE_URL to a foodsafe_app connection string in any real
-- environment: (a) run the full auth flow (register/login/refresh/logout)
-- against it first, (b) confirm every other route that touches
-- users/api_keys/refresh_tokens goes through api/db.py's user_scoped()
-- helper or otherwise sets app.user_id, not a bare pool.acquire() — a
-- route that forgets to do so will simply see zero rows under RLS rather
-- than erroring, which is a silent-failure mode worth testing for
-- explicitly, not just assuming works.
-- ============================================================

-- Gap 1: refresh_tokens had RLS enabled with no policy.
-- (Postgres has no CREATE POLICY IF NOT EXISTS, hence the DO block.)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'refresh_tokens' AND policyname = 'refresh_tokens_own'
    ) THEN
        CREATE POLICY refresh_tokens_own ON refresh_tokens
            USING (user_id = current_setting('app.user_id', TRUE)::UUID);
    END IF;
END $$;

-- Gap 2: pipeline_runs / consumer_reports need the same INSERT/UPDATE
-- grant pattern every other migration already applies to the tables it
-- introduces.
GRANT SELECT, INSERT, UPDATE ON pipeline_runs, consumer_reports TO foodsafe_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO foodsafe_app;

-- ============================================================
-- Persisted rate limiting for unauthenticated public POST endpoints
-- (POST /v1/reports, POST /v1/disputes/submit). Previously these had no
-- dedicated limiter — only the global in-memory per-IP/day limiter in
-- api/main.py, which resets on every deploy and doesn't share state
-- across multiple instances. api_keys already has a persisted, DB-backed
-- limiter (api_key_usage) for machine clients; this gives the two public
-- human-facing submission endpoints the same durability.
-- ============================================================

CREATE TABLE IF NOT EXISTS public_submission_log (
    id          BIGSERIAL PRIMARY KEY,
    ip_hash     TEXT NOT NULL,   -- SHA-256 of client IP, never the raw IP
    endpoint    TEXT NOT NULL,   -- 'reports' | 'disputes'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_public_submission_log_lookup
    ON public_submission_log (ip_hash, endpoint, created_at DESC);

GRANT SELECT, INSERT ON public_submission_log TO foodsafe_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO foodsafe_app;
