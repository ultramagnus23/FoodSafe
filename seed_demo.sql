-- ============================================================
-- FoodSafe India — Demo Seed Data
-- Run AFTER schema.sql and schema_migration_002.sql:
--   psql -d foodsafe -f seed_demo.sql
--
-- Purpose: stand in for the data the ingestion + nightly Airflow
-- aggregation would normally produce, so the API returns real
-- (non-empty) numbers for a local demo. NOT production data.
-- Commodity ids 1-10 and contaminant ids 1-8 come from schema.sql.
-- ============================================================

BEGIN;

-- ---- Districts (ids 1..12, insertion order matches the old frontend MOCK) ----
INSERT INTO districts (name_canonical, state, census_2021_code, water_quality_index, industrial_proximity_score, latitude, longitude) VALUES
('Mumbai',     'Maharashtra',   '2723', 52.0, 88.0, 19.07, 72.87),
('Pune',       'Maharashtra',   '2725', 64.0, 61.0, 18.52, 73.86),
('Nagpur',     'Maharashtra',   '2710', 58.0, 55.0, 21.14, 79.08),
('Nashik',     'Maharashtra',   '2718', 70.0, 44.0, 19.99, 73.79),
('Ahmedabad',  'Gujarat',       '2407', 49.0, 79.0, 23.02, 72.57),
('Surat',      'Gujarat',       '2425', 55.0, 72.0, 21.17, 72.83),
('Delhi',      'Delhi',         '0701', 41.0, 83.0, 28.70, 77.10),
('Noida',      'Uttar Pradesh', '0915', 47.0, 76.0, 28.53, 77.39),
('Lucknow',    'Uttar Pradesh', '0928', 54.0, 49.0, 26.84, 80.94),
('Chennai',    'Tamil Nadu',    '3302', 58.0, 67.0, 13.08, 80.27),
('Coimbatore', 'Tamil Nadu',    '3308', 71.0, 52.0, 11.01, 76.96),
('Bengaluru',  'Karnataka',     '2918', 62.0, 58.0, 12.97, 77.59);

-- ---- Brands (ids 1..6, order matches old frontend MOCK) ----
INSERT INTO brands (name_canonical, parent_company, product_categories, states_of_operation) VALUES
('India Gate', 'KRBL Ltd',          ARRAY['grain'],  ARRAY['Maharashtra','Delhi']),
('Fortune',    'Adani Wilmar',      ARRAY['oil'],    ARRAY['Gujarat','Maharashtra']),
('Amul',       'GCMMF',             ARRAY['dairy'],  ARRAY['Gujarat','Delhi','Maharashtra']),
('Haldiram''s','Haldiram Foods',    ARRAY['produce'],ARRAY['Delhi','Uttar Pradesh']),
('MDH',        'MDH Pvt Ltd',       ARRAY['spice'],  ARRAY['Delhi','Maharashtra']),
('Everest',    'Everest Food Products', ARRAY['spice'], ARRAY['Maharashtra','Gujarat']);

-- ---- Labs (ids 1..5; lab 5 is deliberately flagged for the fraud admin view) ----
INSERT INTO labs (name, tier, state, accreditation, reliability_score, pass_rate, deviation_z_score, flagged_suspicious, flag_reason, last_evaluated) VALUES
('CFTRI Mysuru',              1, 'Karnataka',   'ICAR/NABL', 0.940, 0.7600, -0.40, FALSE, NULL, NOW()),
('NABL Ref Lab Pune',         1, 'Maharashtra', 'NABL',      0.910, 0.7900, -0.20, FALSE, NULL, NOW()),
('ICAR Regional Lab Delhi',   1, 'Delhi',       'ICAR/NABL', 0.900, 0.8100,  0.05, FALSE, NULL, NOW()),
('State PH Lab Lucknow',      2, 'Uttar Pradesh','State',    0.760, 0.8800,  1.10, FALSE, NULL, NOW()),
('QuickTest Pvt Labs',        3, 'Gujarat',     'Private',   0.420, 0.9900,  3.20, TRUE,  'Benford p<0.01 and pass-rate 2.8σ above state mean', NOW());

-- NOTE: enforcement_records and the agg_* tables are NO LONGER seeded here.
--   * Raw demo records come from:   python -m pipeline.seed_enforcement
--     (a realistic volume the FSSAI OCR pipeline would otherwise produce).
--   * The agg_* risk tables are COMPUTED from those records by:
--                                  python -m models.aggregate
-- So the full demo setup is:
--   psql ... -f schema.sql -f schema_migration_002.sql -f seed_demo.sql
--   python -m pipeline.seed_enforcement      # raw demo enforcement records
--   python -m pipeline.sources.openfda       # real US FDA recalls (optional)
--   python -m models.aggregate               # compute district + brand risk

COMMIT;
