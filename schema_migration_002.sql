-- ============================================================
-- FoodSafe India — Schema Additions (migration_002)
-- Run AFTER schema.sql
-- Adds: lab reliability, fraud flags, Benford's Law results,
--       brand dispute workflow, ICMR consumption data
-- ============================================================

-- ============================================================
-- 1. LAB RELIABILITY SCORING
-- ============================================================

ALTER TABLE labs
    ADD COLUMN IF NOT EXISTS reliability_score    NUMERIC(4,3) DEFAULT 0.700,
    ADD COLUMN IF NOT EXISTS pass_rate            NUMERIC(5,4),
    ADD COLUMN IF NOT EXISTS state_avg_pass_rate  NUMERIC(5,4),
    ADD COLUMN IF NOT EXISTS deviation_z_score    NUMERIC(6,3),   -- how far from state mean
    ADD COLUMN IF NOT EXISTS flagged_suspicious   BOOLEAN        NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS flag_reason          TEXT,
    ADD COLUMN IF NOT EXISTS last_evaluated       TIMESTAMPTZ;

-- Aggregated lab performance per commodity (for cross-validation)
CREATE TABLE IF NOT EXISTS lab_commodity_stats (
    lab_id          INT  NOT NULL REFERENCES labs(id),
    commodity_id    INT  NOT NULL REFERENCES commodities(id),
    quarter         TEXT NOT NULL,
    n_tests         INT  NOT NULL DEFAULT 0,
    n_failures      INT  NOT NULL DEFAULT 0,
    pass_rate       NUMERIC(5,4),
    avg_value_ppb   NUMERIC(16,6),
    std_value_ppb   NUMERIC(16,6),
    -- Benford's Law first-digit distribution
    benford_chi2    NUMERIC(10,4),   -- chi-squared statistic
    benford_p_value NUMERIC(8,6),    -- p < 0.05 → suspicious digit distribution
    benford_flagged BOOLEAN          NOT NULL DEFAULT FALSE,
    last_updated    TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    PRIMARY KEY (lab_id, commodity_id, quarter)
);

CREATE INDEX IF NOT EXISTS idx_lab_commodity_stats_flagged
    ON lab_commodity_stats (benford_flagged) WHERE benford_flagged = TRUE;

-- ============================================================
-- 2. FRAUD FLAGS ON ENFORCEMENT RECORDS
-- ============================================================

ALTER TABLE enforcement_records
    ADD COLUMN IF NOT EXISTS fraud_flags           JSONB    NOT NULL DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS fraud_score           NUMERIC(4,3) DEFAULT 0.0,
    ADD COLUMN IF NOT EXISTS geo_plausibility_ok   BOOLEAN  DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS value_is_round        BOOLEAN  DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS lab_flagged           BOOLEAN  DEFAULT FALSE;

-- Separate fraud audit table for full traceability
CREATE TABLE IF NOT EXISTS fraud_audit (
    id                  BIGSERIAL   PRIMARY KEY,
    enforcement_record_id BIGINT    NOT NULL,
    enforcement_date    DATE        NOT NULL,
    flag_type           TEXT        NOT NULL,  -- 'benford' | 'round_number' | 'geo_implausible' | 'lab_outlier' | 'value_cluster'
    flag_detail         TEXT,
    flag_score          NUMERIC(4,3) NOT NULL DEFAULT 0.0,
    auto_flagged        BOOLEAN     NOT NULL DEFAULT TRUE,
    reviewed_by         UUID        REFERENCES users(id),
    review_outcome      TEXT        CHECK (review_outcome IN ('confirmed_fraud','false_positive','needs_more_data')),
    reviewed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fraud_audit_record
    ON fraud_audit (enforcement_record_id, enforcement_date);
CREATE INDEX IF NOT EXISTS idx_fraud_audit_unreviewed
    ON fraud_audit (reviewed_at) WHERE reviewed_at IS NULL;

-- ============================================================
-- 3. BRAND DISPUTE WORKFLOW (replaces stub in schema.sql)
-- ============================================================

-- Drop old stub if it exists and recreate properly
DO $$ BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE tablename = 'brand_disputes') THEN
        -- Add missing columns to existing table
        ALTER TABLE brand_disputes
            ADD COLUMN IF NOT EXISTS commodity_id        INT  REFERENCES commodities(id),
            ADD COLUMN IF NOT EXISTS district_id         INT  REFERENCES districts(id),
            ADD COLUMN IF NOT EXISTS counter_lab_name    TEXT,
            ADD COLUMN IF NOT EXISTS counter_lab_accred  TEXT,
            ADD COLUMN IF NOT EXISTS counter_value_ppb   NUMERIC(16,6),
            ADD COLUMN IF NOT EXISTS counter_test_date   DATE,
            ADD COLUMN IF NOT EXISTS dispute_type        TEXT NOT NULL DEFAULT 'incorrect_data'
                                    CHECK (dispute_type IN ('incorrect_data','stale_data','wrong_brand','supply_chain_error','other')),
            ADD COLUMN IF NOT EXISTS internal_notes      TEXT,
            ADD COLUMN IF NOT EXISTS flagged_on_platform BOOLEAN NOT NULL DEFAULT FALSE;
    ELSE
        CREATE TABLE brand_disputes (
            id                      SERIAL      PRIMARY KEY,
            brand_id                INT         NOT NULL REFERENCES brands(id),
            commodity_id            INT         REFERENCES commodities(id),
            district_id             INT         REFERENCES districts(id),
            enforcement_record_id   BIGINT,
            submitted_by_email      TEXT        NOT NULL,
            dispute_type            TEXT        NOT NULL DEFAULT 'incorrect_data'
                                                CHECK (dispute_type IN ('incorrect_data','stale_data','wrong_brand','supply_chain_error','other')),
            lab_evidence_url        TEXT,
            counter_lab_name        TEXT,
            counter_lab_accred      TEXT,
            counter_value_ppb       NUMERIC(16,6),
            counter_test_date       DATE,
            notes                   TEXT,
            status                  TEXT        NOT NULL DEFAULT 'pending'
                                                CHECK (status IN ('pending','under_review','resolved_removed','resolved_kept','resolved_flagged')),
            flagged_on_platform     BOOLEAN     NOT NULL DEFAULT FALSE,
            internal_notes          TEXT,
            submitted_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved_at             TIMESTAMPTZ,
            resolver_notes          TEXT
        );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_disputes_brand ON brand_disputes (brand_id, status);
CREATE INDEX IF NOT EXISTS idx_disputes_pending ON brand_disputes (status) WHERE status = 'pending';

-- ============================================================
-- 4. ICMR DIETARY CONSUMPTION DATA
-- ============================================================

CREATE TABLE IF NOT EXISTS icmr_consumption (
    id              SERIAL      PRIMARY KEY,
    commodity_id    INT         NOT NULL REFERENCES commodities(id),
    state           TEXT,           -- NULL = national average
    age_group       TEXT        NOT NULL DEFAULT 'adult'
                                CHECK (age_group IN ('child_1_3','child_4_6','child_7_9','adolescent','adult','elderly','pregnant')),
    sex             TEXT        NOT NULL DEFAULT 'all'
                                CHECK (sex IN ('male','female','all')),
    grams_per_day   NUMERIC(8,2) NOT NULL,
    kcal_per_day    NUMERIC(8,2),
    source_year     INT         NOT NULL DEFAULT 2020,
    source_doc      TEXT,           -- e.g. "ICMR-NIN Dietary Guidelines 2020"
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (commodity_id, state, age_group, sex, source_year)
);

CREATE INDEX IF NOT EXISTS idx_icmr_commodity ON icmr_consumption (commodity_id, state);

-- Seed national adult averages from ICMR-NIN 2020 (grams/day)
-- Source: Dietary Guidelines for Indians, ICMR-NIN 2020
INSERT INTO icmr_consumption (commodity_id, state, age_group, sex, grams_per_day, source_doc)
SELECT c.id, NULL, 'adult', 'all', vals.gpd, 'ICMR-NIN Dietary Guidelines 2020'
FROM (VALUES
    ('rice',         250.0),
    ('wheat',        200.0),
    ('milk',         300.0),
    ('groundnut',     15.0),
    ('chilli',         8.0),
    ('turmeric',       2.5),
    ('mustard_oil',   15.0),
    ('onion',         50.0),
    ('potato',        80.0),
    ('paneer',        25.0)
) AS vals(name, gpd)
JOIN commodities c ON c.name_canonical = vals.name
ON CONFLICT DO NOTHING;

-- ============================================================
-- 5. AGGREGATION TABLE UPDATES
-- Add fraud summary to district risk agg
-- ============================================================

ALTER TABLE agg_district_commodity_risk
    ADD COLUMN IF NOT EXISTS fraud_flagged_count  INT     DEFAULT 0,
    ADD COLUMN IF NOT EXISTS lab_reliability_avg  NUMERIC(4,3);

ALTER TABLE agg_brand_safety_profile
    ADD COLUMN IF NOT EXISTS dispute_count        INT     DEFAULT 0,
    ADD COLUMN IF NOT EXISTS under_dispute        BOOLEAN DEFAULT FALSE;

-- ============================================================
-- 6. GRANTS (extend existing foodsafe_app role)
-- ============================================================

GRANT SELECT, INSERT, UPDATE ON
    lab_commodity_stats, fraud_audit, brand_disputes, icmr_consumption
    TO foodsafe_app;
GRANT SELECT ON labs TO foodsafe_app;
GRANT UPDATE ON labs TO foodsafe_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO foodsafe_app;
