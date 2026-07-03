-- ============================================================
-- FoodSafe India — Schema Additions (migration_004)
-- Run AFTER schema_migration_003.sql
-- Adds: admin/superuser flag, B2B API key extensions + usage log,
--       alert subscriptions (email channel only — WhatsApp intentionally
--       out of scope for this pass).
-- ============================================================

-- ============================================================
-- 1. ADMIN / SUPERUSER FLAG
-- ============================================================

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_superuser BOOLEAN NOT NULL DEFAULT FALSE;

-- ============================================================
-- 2. B2B API KEY MANAGEMENT — extend the existing api_keys table
-- (schema.sql already has id/user_id/key_hash/tier/rate_limit_per_day/
-- created_at/last_used/revoked_at; add the self-service-facing columns)
-- ============================================================

ALTER TABLE api_keys
    ADD COLUMN IF NOT EXISTS key_prefix TEXT,
    ADD COLUMN IF NOT EXISTS name       TEXT,
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS api_key_usage (
    id              BIGSERIAL   PRIMARY KEY,
    key_id          UUID        NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    endpoint        TEXT        NOT NULL,
    method          TEXT        NOT NULL,
    status_code     INT,
    response_ms     INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_key_usage_key_day
    ON api_key_usage (key_id, created_at DESC);

-- ============================================================
-- 3. ALERT SUBSCRIPTIONS (email channel only)
-- ============================================================

CREATE TABLE IF NOT EXISTS alert_subscriptions (
    id                  SERIAL      PRIMARY KEY,
    user_id             UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    district_id         INT         REFERENCES districts(id),      -- NULL = any district
    commodity_id        INT         REFERENCES commodities(id),    -- NULL = any commodity
    contaminant_id      INT         REFERENCES contaminants(id),   -- NULL = any contaminant
    alert_types         TEXT[]      NOT NULL DEFAULT '{twi_exceedance,codex_exceedance_fssai_compliant}',
    severity_threshold  TEXT        NOT NULL DEFAULT 'moderate'
                                     CHECK (severity_threshold IN ('moderate','high','critical')),
    active              BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_notified_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_alert_subscriptions_user ON alert_subscriptions (user_id);
CREATE INDEX IF NOT EXISTS idx_alert_subscriptions_active ON alert_subscriptions (active) WHERE active = TRUE;

-- ============================================================
-- 4. QUERY-PATTERN INDEXES (Task 11c — performance)
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_agg_district_commodity_map
    ON agg_district_commodity_risk (commodity_id, risk_score) WHERE risk_score IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_enforcement_records_timeline
    ON enforcement_records (district_id, commodity_id, test_date DESC);

CREATE INDEX IF NOT EXISTS idx_disease_burden_paf
    ON disease_burden_estimates (district_id, population_attributable_fraction DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_exposure_alerts_active_severity
    ON exposure_alerts (severity, last_seen DESC) WHERE active = TRUE;

-- ============================================================
-- 5. GRANTS
-- ============================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON
    api_key_usage, alert_subscriptions
    TO foodsafe_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO foodsafe_app;
