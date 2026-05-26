-- ============================================================
-- FoodSafe India — PostgreSQL Schema
-- Run on PostgreSQL 15+
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";       -- fuzzy text search
CREATE EXTENSION IF NOT EXISTS "btree_gin";      -- GIN on scalar cols

-- ============================================================
-- LOOKUP / REFERENCE TABLES
-- ============================================================

CREATE TABLE commodities (
    id              SERIAL PRIMARY KEY,
    name_canonical  TEXT NOT NULL UNIQUE,
    category        TEXT NOT NULL CHECK (category IN ('dairy','grain','produce','meat','packaged','seafood','spice','oil')),
    aliases         TEXT[]      NOT NULL DEFAULT '{}',
    processing_types TEXT[]     NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE contaminants (
    id                          SERIAL PRIMARY KEY,
    name_canonical              TEXT NOT NULL UNIQUE,
    aliases                     TEXT[]      NOT NULL DEFAULT '{}',
    legal_limit_ppb_fssai       NUMERIC(12,4),
    legal_limit_ppb_codex       NUMERIC(12,4),
    health_effect               TEXT,
    iarc_class                  TEXT,   -- 1, 2A, 2B, 3
    -- per process type: {"boiling": 0.85, "roasting": 0.40, ...}
    processing_retention_factor JSONB   NOT NULL DEFAULT '{}',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE districts (
    id                          SERIAL PRIMARY KEY,
    name_canonical              TEXT NOT NULL,
    state                       TEXT NOT NULL,
    alternate_names             TEXT[]      NOT NULL DEFAULT '{}',
    census_2021_code            TEXT UNIQUE,
    water_quality_index         NUMERIC(5,2),   -- 0-100, higher = cleaner
    industrial_proximity_score  NUMERIC(5,2),   -- 0-100, higher = more industrial
    latitude                    NUMERIC(9,6),
    longitude                   NUMERIC(9,6),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (name_canonical, state)
);

CREATE TABLE mandis (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    district_id INT  NOT NULL REFERENCES districts(id),
    state       TEXT NOT NULL,
    agmarknet_id TEXT UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE brands (
    id                  SERIAL PRIMARY KEY,
    name_canonical      TEXT NOT NULL UNIQUE,
    parent_company      TEXT,
    product_categories  TEXT[]  NOT NULL DEFAULT '{}',
    states_of_operation TEXT[]  NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE labs (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    tier        INT  NOT NULL CHECK (tier IN (1, 2, 3)),  -- 1=ICAR/NABL, 2=state, 3=private
    state       TEXT,
    accreditation TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- CORE ENFORCEMENT RECORDS — PARTITIONED BY YEAR
-- ============================================================

CREATE TABLE enforcement_records (
    id              BIGSERIAL,
    test_date       DATE        NOT NULL,
    lab_id          INT         REFERENCES labs(id),
    source_url      TEXT,
    source_type     TEXT        NOT NULL CHECK (source_type IN ('fssai','usfda','efsa','apeda','state_health','agmarknet')),
    pdf_page        INT,
    commodity_id    INT         NOT NULL REFERENCES commodities(id),
    contaminant_id  INT         NOT NULL REFERENCES contaminants(id),
    raw_value_ppb   NUMERIC(16,6) NOT NULL,
    legal_limit_ppb NUMERIC(16,6),
    pass_fail       BOOLEAN,    -- TRUE = passed
    state           TEXT,
    district_id     INT         REFERENCES districts(id),
    mandi_id        INT         REFERENCES mandis(id),
    brand_id        INT         REFERENCES brands(id),
    confidence_score NUMERIC(4,3) NOT NULL CHECK (confidence_score BETWEEN 0 AND 1),
    ocr_confidence  NUMERIC(4,3),
    dedup_hash      TEXT,
    is_duplicate    BOOLEAN     NOT NULL DEFAULT FALSE,
    etl_version     TEXT,
    parsed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, test_date)
) PARTITION BY RANGE (test_date);

-- Annual partitions (extend as needed)
CREATE TABLE enforcement_records_2020 PARTITION OF enforcement_records
    FOR VALUES FROM ('2020-01-01') TO ('2021-01-01');
CREATE TABLE enforcement_records_2021 PARTITION OF enforcement_records
    FOR VALUES FROM ('2021-01-01') TO ('2022-01-01');
CREATE TABLE enforcement_records_2022 PARTITION OF enforcement_records
    FOR VALUES FROM ('2022-01-01') TO ('2023-01-01');
CREATE TABLE enforcement_records_2023 PARTITION OF enforcement_records
    FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');
CREATE TABLE enforcement_records_2024 PARTITION OF enforcement_records
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
CREATE TABLE enforcement_records_2025 PARTITION OF enforcement_records
    FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
CREATE TABLE enforcement_records_2026 PARTITION OF enforcement_records
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');

-- Indexes on enforcement_records
CREATE INDEX ON enforcement_records (test_date DESC);
CREATE INDEX ON enforcement_records (commodity_id, state);
CREATE INDEX ON enforcement_records (contaminant_id, district_id);
CREATE INDEX ON enforcement_records (brand_id) WHERE brand_id IS NOT NULL;
CREATE INDEX ON enforcement_records (confidence_score) WHERE confidence_score >= 0.75;
CREATE INDEX ON enforcement_records (dedup_hash);

-- ============================================================
-- SUPPLY CHAIN GRAPH
-- ============================================================

CREATE TABLE supply_chain_nodes (
    id          SERIAL PRIMARY KEY,
    node_type   TEXT NOT NULL CHECK (node_type IN ('farm','mandi','processor','warehouse','brand','retailer')),
    name        TEXT NOT NULL,
    district_id INT REFERENCES districts(id),
    commodity_id INT REFERENCES commodities(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE supply_chain_edges (
    id                  SERIAL PRIMARY KEY,
    source_node_id      INT NOT NULL REFERENCES supply_chain_nodes(id),
    target_node_id      INT NOT NULL REFERENCES supply_chain_nodes(id),
    process_type        TEXT,   -- "boiling", "milling", "pasteurisation", etc.
    retention_factor    NUMERIC(4,3),   -- 0.0 - 1.0, fraction of contaminant retained
    link_confidence     NUMERIC(4,3),   -- how well-established this supply link is
    source_url          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (source_node_id <> target_node_id)
);

CREATE INDEX ON supply_chain_edges (source_node_id);
CREATE INDEX ON supply_chain_edges (target_node_id);

-- ============================================================
-- AGGREGATION TABLES (refreshed nightly by Airflow)
-- ============================================================

CREATE TABLE agg_district_commodity_risk (
    district_id         INT  NOT NULL REFERENCES districts(id),
    commodity_id        INT  NOT NULL REFERENCES commodities(id),
    quarter             TEXT NOT NULL,  -- "2024-Q1"
    fail_rate           NUMERIC(6,4),
    n_tests             INT,
    risk_score          NUMERIC(6,2),
    ci_lower            NUMERIC(6,2),
    ci_upper            NUMERIC(6,2),
    top_contaminants    JSONB,          -- [{"name": "aflatoxin_b1", "fail_rate": 0.12}, ...]
    model_version       TEXT,
    last_updated        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (district_id, commodity_id, quarter)
);

CREATE TABLE agg_brand_safety_profile (
    brand_id        INT  NOT NULL REFERENCES brands(id),
    commodity_id    INT  NOT NULL REFERENCES commodities(id),
    n_tests         INT,
    n_failures      INT,
    avg_ppb         NUMERIC(16,6),
    risk_score      NUMERIC(6,2),
    ci_lower        NUMERIC(6,2),
    ci_upper        NUMERIC(6,2),
    inference_type  TEXT NOT NULL CHECK (inference_type IN ('direct_test','propagated','insufficient_data')),
    model_version   TEXT,
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (brand_id, commodity_id)
);

-- ============================================================
-- USERS & AUTH
-- ============================================================

CREATE TABLE users (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           TEXT        UNIQUE,
    phone           TEXT        UNIQUE,
    password_hash   TEXT,
    tier            TEXT        NOT NULL DEFAULT 'consumer_free'
                                CHECK (tier IN ('consumer_free','consumer_premium','fmcg','insurance')),
    home_district_id INT        REFERENCES districts(id),
    google_sub      TEXT        UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login      TIMESTAMPTZ,
    CONSTRAINT email_or_phone CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

CREATE TABLE api_keys (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash        TEXT        NOT NULL UNIQUE,
    tier            TEXT        NOT NULL,
    rate_limit_per_day INT      NOT NULL DEFAULT 100,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used       TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ
);

CREATE TABLE refresh_tokens (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT        NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at  TIMESTAMPTZ
);

-- ============================================================
-- AUDIT & DISPUTE
-- ============================================================

CREATE TABLE audit_log (
    id          BIGSERIAL   PRIMARY KEY,
    user_id     UUID        REFERENCES users(id),
    action      TEXT        NOT NULL,
    resource    TEXT        NOT NULL,
    ip_hash     TEXT,
    metadata    JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ON audit_log (user_id, created_at DESC);

CREATE TABLE brand_disputes (
    id                  SERIAL PRIMARY KEY,
    brand_id            INT  NOT NULL REFERENCES brands(id),
    enforcement_record_id BIGINT,     -- nullable: could dispute aggregated score
    submitted_by_email  TEXT NOT NULL,
    lab_evidence_url    TEXT,
    notes               TEXT,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','under_review','resolved_removed','resolved_kept','resolved_flagged')),
    submitted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at         TIMESTAMPTZ,
    resolver_notes      TEXT
);

-- ============================================================
-- RTI TRACKING
-- ============================================================

CREATE TABLE rti_requests (
    id              SERIAL PRIMARY KEY,
    source_type     TEXT NOT NULL,
    authority       TEXT NOT NULL,
    request_date    DATE NOT NULL,
    subject         TEXT NOT NULL,
    request_doc_url TEXT,
    response_date   DATE,
    response_doc_url TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','received','partial','appealed','rejected')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- SEED: CORE CONTAMINANTS
-- ============================================================

INSERT INTO contaminants (name_canonical, aliases, legal_limit_ppb_fssai, legal_limit_ppb_codex, health_effect, iarc_class, processing_retention_factor) VALUES
('aflatoxin_b1',        ARRAY['AFB1','aflatoxin-B1','Aflatoxin B1','af b1'],   10.0,   10.0,   'Hepatotoxic, carcinogenic',          '1',  '{"roasting": 0.40, "boiling": 0.85, "milling": 0.70}'),
('aflatoxin_total',     ARRAY['total aflatoxin','AFtotal'],                     30.0,   15.0,   'Hepatotoxic, carcinogenic',          '1',  '{"roasting": 0.40, "boiling": 0.85}'),
('lead',                ARRAY['Pb','lead (Pb)','plumbum'],                     100.0,  100.0,   'Neurotoxic',                         '2A', '{"washing": 0.60}'),
('cadmium',             ARRAY['Cd','cadmium (Cd)'],                             100.0,  200.0,   'Nephrotoxic, carcinogenic',          '1',  '{}'),
('arsenic_inorganic',   ARRAY['As','inorganic arsenic','iAs'],                  100.0,  300.0,   'Carcinogenic, vascular',             '1',  '{"cooking": 0.50}'),
('pesticide_chlorpyrifos', ARRAY['chlorpyrifos','Lorsban'],                      20.0,   20.0,   'Neurotoxic, endocrine disruptor',   '2A', '{"washing": 0.40, "cooking": 0.60}'),
('melamine',            ARRAY['melamine adulteration'],                        2500.0, 2500.0,   'Nephrotoxic (kidney stones)',        '3',  '{}'),
('ochratoxin_a',        ARRAY['OTA','ochratoxin-A'],                             10.0,   15.0,   'Nephrotoxic, possibly carcinogenic', '2B', '{"roasting": 0.70}');

-- ============================================================
-- SEED: CORE COMMODITIES
-- ============================================================

INSERT INTO commodities (name_canonical, category, aliases, processing_types) VALUES
('rice',        'grain',    ARRAY['paddy','basmati','non-basmati rice'],            ARRAY['milling','boiling','parboiling']),
('wheat',       'grain',    ARRAY['gehun','atta','maida','wheat flour'],            ARRAY['milling','baking','boiling']),
('milk',        'dairy',    ARRAY['cow milk','buffalo milk','toned milk'],          ARRAY['pasteurisation','UHT','boiling']),
('groundnut',   'produce',  ARRAY['peanut','moongphali','mungfali'],                ARRAY['roasting','boiling','oil_extraction']),
('chilli',      'spice',    ARRAY['red chilli','lal mirch','chilli powder'],        ARRAY['drying','grinding']),
('turmeric',    'spice',    ARRAY['haldi','curcuma longa'],                         ARRAY['drying','grinding']),
('mustard_oil', 'oil',      ARRAY['sarson ka tel','mustard oil'],                   ARRAY['cold_press','expeller']),
('onion',       'produce',  ARRAY['pyaaz','kanda'],                                 ARRAY['raw','cooking']),
('potato',      'produce',  ARRAY['aloo','batata'],                                 ARRAY['boiling','frying']),
('paneer',      'dairy',    ARRAY['cottage cheese','Indian cottage cheese'],        ARRAY['curdling','pressing']);

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY;

-- Users can only see their own row
CREATE POLICY users_self ON users
    USING (id = current_setting('app.user_id', TRUE)::UUID);

CREATE POLICY api_keys_own ON api_keys
    USING (user_id = current_setting('app.user_id', TRUE)::UUID);

-- Enforcement records are public-read (no RLS needed, but deny writes from app role)
-- Create a restricted app role
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'foodsafe_app') THEN
        CREATE ROLE foodsafe_app LOGIN;
    END IF;
END $$;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO foodsafe_app;
GRANT INSERT, UPDATE ON enforcement_records, audit_log, brand_disputes, rti_requests TO foodsafe_app;
GRANT INSERT, UPDATE, DELETE ON users, api_keys, refresh_tokens TO foodsafe_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO foodsafe_app;
