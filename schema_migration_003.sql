-- ============================================================
-- FoodSafe India — Schema Additions (migration_003)
-- Run AFTER schema.sql and schema_migration_002.sql
-- Adds: disease-burden layer (dose-response params, PAF estimates,
--       exposure alerts) + Codex/WHO benchmark columns.
--
-- Reuses existing tables instead of duplicating them:
--   - contaminants already has legal_limit_ppb_fssai/_codex + iarc_class,
--     so we extend it rather than creating a separate codex_limits table.
--   - icmr_consumption already covers commodity x state x age_group
--     dietary intake, so we extend it rather than creating a separate
--     dietary_consumption_by_state table.
-- ============================================================

-- ============================================================
-- 1. CODEX / WHO BENCHMARK COLUMNS ON contaminants
-- ============================================================

ALTER TABLE contaminants
    ADD COLUMN IF NOT EXISTS eu_limit_ppb            NUMERIC(12,4),
    ADD COLUMN IF NOT EXISTS who_jecfa_twi_ug_per_kg  NUMERIC(12,6),  -- Tolerable Weekly Intake, µg/kg bodyweight
    ADD COLUMN IF NOT EXISTS codex_doc_reference      TEXT,           -- e.g. "CXS 193-1995, Rev. 2019"
    ADD COLUMN IF NOT EXISTS codex_last_updated       DATE;

-- Seed benchmark values for the 8 seeded contaminants
UPDATE contaminants SET eu_limit_ppb = 2.0,   who_jecfa_twi_ug_per_kg = NULL,  codex_doc_reference = 'CXS 193-1995, Rev. 2019', codex_last_updated = '2019-01-01' WHERE name_canonical = 'aflatoxin_b1';
UPDATE contaminants SET eu_limit_ppb = 4.0,   who_jecfa_twi_ug_per_kg = NULL,  codex_doc_reference = 'CXS 193-1995, Rev. 2019', codex_last_updated = '2019-01-01' WHERE name_canonical = 'aflatoxin_total';
UPDATE contaminants SET eu_limit_ppb = 20.0,  who_jecfa_twi_ug_per_kg = 25.0,  codex_doc_reference = 'CXS 193-1995, Rev. 2019', codex_last_updated = '2019-01-01' WHERE name_canonical = 'lead';
UPDATE contaminants SET eu_limit_ppb = 50.0,  who_jecfa_twi_ug_per_kg = 2.5,   codex_doc_reference = 'CXS 193-1995, Rev. 2019', codex_last_updated = '2019-01-01' WHERE name_canonical = 'cadmium';
UPDATE contaminants SET eu_limit_ppb = 200.0, who_jecfa_twi_ug_per_kg = 15.0,  codex_doc_reference = 'CXS 193-1995, Rev. 2019', codex_last_updated = '2019-01-01' WHERE name_canonical = 'arsenic_inorganic';
UPDATE contaminants SET eu_limit_ppb = 10.0,  who_jecfa_twi_ug_per_kg = NULL,  codex_doc_reference = 'CXP 55-2004',            codex_last_updated = '2016-01-01' WHERE name_canonical = 'pesticide_chlorpyrifos';
UPDATE contaminants SET eu_limit_ppb = 2500.0,who_jecfa_twi_ug_per_kg = NULL,  codex_doc_reference = 'CXS 234-1999',          codex_last_updated = '2018-01-01' WHERE name_canonical = 'melamine';
UPDATE contaminants SET eu_limit_ppb = 5.0,   who_jecfa_twi_ug_per_kg = 0.12*7,codex_doc_reference = 'CXS 193-1995, Rev. 2019', codex_last_updated = '2019-01-01' WHERE name_canonical = 'ochratoxin_a';

-- Fumonisin B1 isn't in the seed contaminant list yet but is needed for the
-- oesophageal-cancer dose-response row below.
INSERT INTO contaminants (name_canonical, aliases, legal_limit_ppb_fssai, legal_limit_ppb_codex, eu_limit_ppb,
                           health_effect, iarc_class, processing_retention_factor, codex_doc_reference, codex_last_updated)
VALUES ('fumonisin_b1', ARRAY['FB1','fumonisin-B1','Fumonisin B1'], 2000.0, 2000.0, 1000.0,
        'Hepatotoxic, possibly carcinogenic (oesophageal)', '2B', '{"milling": 0.60}',
        'CXS 193-1995, Rev. 2019', '2019-01-01')
ON CONFLICT (name_canonical) DO NOTHING;

-- ============================================================
-- 2. dietary_consumption_by_state — extend icmr_consumption
-- ============================================================

ALTER TABLE icmr_consumption
    ADD COLUMN IF NOT EXISTS income_quintile          INT CHECK (income_quintile BETWEEN 1 AND 5),
    ADD COLUMN IF NOT EXISTS p95_consumption_g_per_day NUMERIC(10,3),
    ADD COLUMN IF NOT EXISTS p99_consumption_g_per_day NUMERIC(10,3);

-- ============================================================
-- 3. dose_response_params
-- ============================================================

CREATE TABLE IF NOT EXISTS dose_response_params (
    id                      SERIAL PRIMARY KEY,
    contaminant_id          INT REFERENCES contaminants(id),
    disease_icd10           TEXT NOT NULL,
    disease_name            TEXT NOT NULL,
    model_type              TEXT NOT NULL CHECK (model_type IN
                             ('linear_no_threshold','threshold','hazard_quotient')),
    slope_factor            NUMERIC(20,10),   -- linear: additional risk per µg/kg bw/day
    noael_ug_per_kg_day     NUMERIC(12,6),    -- threshold: NOAEL
    uncertainty_factor      INT,              -- threshold: UF applied to reach TDI
    tdi_ug_per_kg_day       NUMERIC(12,6),    -- tolerable daily intake
    relative_risk_at_twi    NUMERIC(8,4),
    evidence_grade          TEXT NOT NULL CHECK (evidence_grade IN
                             ('iarc_group_1','iarc_group_2a','iarc_group_2b','jecfa_established')),
    latency_years_min       INT,
    latency_years_max       INT,
    key_population          TEXT NOT NULL DEFAULT 'all'
                             CHECK (key_population IN ('children_0_5','pregnant','general_adult','all')),
    source_reference        TEXT,
    -- National-average baseline incidence, used as the PAF -> attributable-cases
    -- multiplier until district/state NCRP data is available (Task 10). This is
    -- a literature proxy (GLOBOCAN/ICMR national estimates), not a district value.
    background_incidence_per_100k NUMERIC(10,4),
    background_incidence_source   TEXT,
    UNIQUE (contaminant_id, disease_icd10, key_population)
);

INSERT INTO dose_response_params
    (contaminant_id, disease_icd10, disease_name, model_type, slope_factor, evidence_grade,
     latency_years_min, latency_years_max, key_population, source_reference)
SELECT c.id, v.icd10, v.disease_name, v.model_type, v.slope_factor, v.evidence_grade,
       v.lat_min, v.lat_max, v.key_pop, v.source_ref
FROM (VALUES
    ('aflatoxin_b1', 'C22.0', 'Hepatocellular carcinoma', 'linear_no_threshold', 0.0000072, 'iarc_group_1', 10, 30, 'general_adult', 'IARC Monograph Vol. 100F (2012); HBsAg-negative'),
    ('aflatoxin_b1', 'C22.0-HBsAg', 'Hepatocellular carcinoma (HBsAg+)', 'linear_no_threshold', 0.00026, 'iarc_group_1', 10, 30, 'general_adult', 'IARC Monograph Vol. 100F (2012); HBsAg-positive synergistic'),
    ('arsenic_inorganic', 'C67', 'Bladder cancer', 'linear_no_threshold', 0.0000005, 'iarc_group_1', 15, 40, 'general_adult', 'IARC Monograph Vol. 100C (2012)'),
    ('arsenic_inorganic', 'C44', 'Skin cancer', 'linear_no_threshold', 0.0000025, 'iarc_group_1', 15, 40, 'general_adult', 'IARC Monograph Vol. 100C (2012)'),
    ('fumonisin_b1', 'C15', 'Oesophageal cancer', 'linear_no_threshold', 0.0000002, 'iarc_group_2b', 10, 30, 'general_adult', 'IARC Monograph Vol. 82 (2002); slope under uncertainty')
) AS v(contaminant, icd10, disease_name, model_type, slope_factor, evidence_grade, lat_min, lat_max, key_pop, source_ref)
JOIN contaminants c ON c.name_canonical = v.contaminant
ON CONFLICT (contaminant_id, disease_icd10, key_population) DO NOTHING;

INSERT INTO dose_response_params
    (contaminant_id, disease_icd10, disease_name, model_type, noael_ug_per_kg_day, uncertainty_factor,
     tdi_ug_per_kg_day, evidence_grade, latency_years_min, latency_years_max, key_population, source_reference)
SELECT c.id, v.icd10, v.disease_name, 'threshold', v.noael::numeric, v.uf::int, v.tdi::numeric, v.evidence_grade,
       v.lat_min, v.lat_max, v.key_pop, v.source_ref
FROM (VALUES
    ('lead', 'F80-F89', 'Neurodevelopmental toxicity (children)', 0.0, NULL, 0.0, 'jecfa_established', 0, 5, 'children_0_5', 'JECFA 2011 — no identifiable threshold for children'),
    ('lead', 'I25', 'Cardiovascular disease (adults)', NULL, NULL, NULL, 'jecfa_established', 10, 30, 'general_adult', 'JECFA 2011 — linear above BLL 1 µg/dL, tracked via TWI fraction not slope factor'),
    ('cadmium', 'N15.9', 'Kidney tubular nephropathy', NULL, NULL, 0.357, 'jecfa_established', 15, 30, 'general_adult', 'JECFA TWI 2.5 µg/kg bw/week (2010), TDI = TWI/7'),
    ('ochratoxin_a', 'N28.9', 'Kidney disease', NULL, NULL, 0.0171, 'jecfa_established', 10, 25, 'general_adult', 'EFSA TWI 120 ng/kg bw/week, TDI = TWI/7')
) AS v(contaminant, icd10, disease_name, noael, uf, tdi, evidence_grade, lat_min, lat_max, key_pop, source_ref)
JOIN contaminants c ON c.name_canonical = v.contaminant
ON CONFLICT (contaminant_id, disease_icd10, key_population) DO NOTHING;

INSERT INTO dose_response_params
    (contaminant_id, disease_icd10, disease_name, model_type, evidence_grade, key_population, source_reference)
SELECT c.id, 'T60.0', 'Pesticide residue hazard (sum-of-HQs)', 'hazard_quotient', 'jecfa_established', 'all',
       'JECFA/JMPR ADI-based hazard quotient approach'
FROM contaminants c WHERE c.name_canonical = 'pesticide_chlorpyrifos'
ON CONFLICT (contaminant_id, disease_icd10, key_population) DO NOTHING;

-- National-average background incidence (literature proxy pending NCRP data)
UPDATE dose_response_params SET background_incidence_per_100k = 2.5, background_incidence_source = 'GLOBOCAN 2020 India, liver cancer national estimate'  WHERE disease_icd10 = 'C22.0' AND key_population = 'general_adult';
UPDATE dose_response_params SET background_incidence_per_100k = 2.0, background_incidence_source = 'GLOBOCAN 2020 India, bladder cancer national estimate' WHERE disease_icd10 = 'C67';
UPDATE dose_response_params SET background_incidence_per_100k = 1.0, background_incidence_source = 'GLOBOCAN 2020 India, skin cancer national estimate'   WHERE disease_icd10 = 'C44';
UPDATE dose_response_params SET background_incidence_per_100k = 5.0, background_incidence_source = 'GLOBOCAN 2020 India, oesophageal cancer national estimate' WHERE disease_icd10 = 'C15';

-- ============================================================
-- 4. disease_burden_estimates
-- ============================================================

CREATE TABLE IF NOT EXISTS disease_burden_estimates (
    id                                  SERIAL PRIMARY KEY,
    district_id                         INT REFERENCES districts(id),
    commodity_id                        INT REFERENCES commodities(id),
    contaminant_id                      INT REFERENCES contaminants(id),
    disease_icd10                       TEXT NOT NULL,

    mean_exposure_ppb                   NUMERIC(12,4),
    mean_dietary_intake_ug_per_kg_per_day NUMERIC(12,6),
    p95_dietary_intake_ug_per_kg_per_day  NUMERIC(12,6),
    twi_exceedance_fraction             NUMERIC(5,4),

    population_attributable_fraction    NUMERIC(5,4),
    paf_lower_ci                        NUMERIC(5,4),
    paf_upper_ci                        NUMERIC(5,4),
    estimated_attributable_cases_per_100k NUMERIC(10,4),

    n_enforcement_records                INT,
    inference_type                       TEXT NOT NULL CHECK (inference_type IN ('direct','propagated','insufficient_data')),
    fssai_vs_codex_exceedance            BOOLEAN,
    model_version                        TEXT,
    computed_at                          TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (district_id, commodity_id, contaminant_id, disease_icd10)
);

CREATE INDEX IF NOT EXISTS idx_disease_burden_district ON disease_burden_estimates (district_id, contaminant_id);

-- ============================================================
-- 5. exposure_alerts
-- ============================================================

CREATE TABLE IF NOT EXISTS exposure_alerts (
    id                  SERIAL PRIMARY KEY,
    district_id         INT REFERENCES districts(id),
    contaminant_id       INT REFERENCES contaminants(id),
    commodity_id         INT REFERENCES commodities(id),
    alert_type           TEXT CHECK (alert_type IN ('twi_exceedance','codex_exceedance_fssai_compliant','trend_worsening')),
    severity              TEXT CHECK (severity IN ('moderate','high','critical')),
    mean_exposure_ppb     NUMERIC(12,4),
    codex_limit_ppb       NUMERIC(12,4),
    fssai_limit_ppb       NUMERIC(12,4),
    n_samples             INT,
    first_seen            DATE,
    last_seen             DATE,
    active                BOOLEAN DEFAULT TRUE,
    UNIQUE (district_id, contaminant_id, commodity_id, alert_type)
);

CREATE INDEX IF NOT EXISTS idx_exposure_alerts_active ON exposure_alerts (active, severity) WHERE active = TRUE;

-- ============================================================
-- 6. agg_district_commodity_risk — Codex benchmark columns
-- ============================================================

ALTER TABLE agg_district_commodity_risk
    ADD COLUMN IF NOT EXISTS codex_compliant_fraction NUMERIC(5,4),
    ADD COLUMN IF NOT EXISTS eu_compliant_fraction     NUMERIC(5,4),
    ADD COLUMN IF NOT EXISTS twi_exceedance_fraction    NUMERIC(5,4),
    ADD COLUMN IF NOT EXISTS fssai_vs_codex_flag        BOOLEAN;

-- ============================================================
-- 7. GRANTS
-- ============================================================

GRANT SELECT, INSERT, UPDATE ON
    dose_response_params, disease_burden_estimates, exposure_alerts
    TO foodsafe_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO foodsafe_app;
