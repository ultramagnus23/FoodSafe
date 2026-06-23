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

-- ---- Enforcement records (recent: 2024-2026 so the 24-month district window catches them) ----
-- Failures (pass_fail=FALSE) drive the /alerts ticker. raw_value/limit pairs are illustrative.
-- cols: test_date, lab_id, source_url, source_type, commodity_id, contaminant_id,
--       raw_value_ppb, legal_limit_ppb, pass_fail, state, district_id, brand_id,
--       confidence_score, is_duplicate
INSERT INTO enforcement_records
  (test_date, lab_id, source_url, source_type, commodity_id, contaminant_id,
   raw_value_ppb, legal_limit_ppb, pass_fail, state, district_id, brand_id,
   confidence_score, is_duplicate) VALUES
-- Rice / aflatoxin in Mumbai (matches the risk-report demo)
('2026-05-12', 1, 'https://fssai.gov.in/r/1', 'fssai', 1, 1,  45.2, 10.0, FALSE, 'Maharashtra', 1, NULL, 0.92, FALSE),
('2026-03-22', 1, 'https://fssai.gov.in/r/2', 'fssai', 1, 1,  12.1, 10.0, FALSE, 'Maharashtra', 1, NULL, 0.88, FALSE),
('2026-02-05', 2, 'https://fssai.gov.in/r/3', 'fssai', 1, 3,  88.0,100.0, TRUE,  'Maharashtra', 1, 1,    0.90, FALSE),
('2025-11-14', 3, 'https://fda.gov/r/4',      'usfda', 1, 6,   3.2, 20.0, TRUE,  'Maharashtra', 1, NULL, 0.81, FALSE),
-- Chilli / lead in Ahmedabad
('2026-06-01', 5, 'https://fssai.gov.in/r/5', 'fssai', 5, 3, 620.0,100.0, FALSE, 'Gujarat', 5, 5,    0.86, FALSE),
-- Milk / melamine in Noida
('2026-05-20', 4, 'https://fda.gov/r/6',      'usfda', 3, 7,3100.0,2500.0,FALSE, 'Uttar Pradesh', 8, 3, 0.84, FALSE),
-- Groundnut / aflatoxin_total in Lucknow
('2026-04-18', 4, 'https://fssai.gov.in/r/7', 'fssai', 4, 2,  88.0, 30.0, FALSE, 'Uttar Pradesh', 9, NULL, 0.89, FALSE),
-- Turmeric / lead in Chennai
('2026-05-30', 1, 'https://apeda.gov.in/r/8', 'apeda', 6, 3,1240.0,100.0, FALSE, 'Tamil Nadu', 10, 6,  0.83, FALSE),
-- Chilli / lead Delhi (MDH)
('2026-06-10', 3, 'https://fssai.gov.in/r/9', 'fssai', 5, 3, 410.0,100.0, FALSE, 'Delhi', 7, 5,        0.91, FALSE),
-- Rice clean tests for low-risk market-gap districts
('2026-04-02', 1, 'https://fssai.gov.in/r/10','fssai', 1, 1,   2.0, 10.0, TRUE,  'Tamil Nadu', 11, NULL, 0.90, FALSE),
('2026-03-15', 2, 'https://fssai.gov.in/r/11','fssai', 1, 1,   1.5, 10.0, TRUE,  'Karnataka',  12, NULL, 0.92, FALSE),
('2026-02-28', 1, 'https://fssai.gov.in/r/12','fssai', 1, 1,   3.1, 10.0, TRUE,  'Tamil Nadu', 11, NULL, 0.88, FALSE);

-- ---- agg_district_commodity_risk : RICE (commodity_id=1) for the /map heatmap ----
-- quarter '2026-Q2'. risk_score / n mirror plausible demo values.
INSERT INTO agg_district_commodity_risk
  (district_id, commodity_id, quarter, fail_rate, n_tests, risk_score, ci_lower, ci_upper, top_contaminants, model_version) VALUES
(1, 1,'2026-Q2', 0.1480, 234, 72.40, 63.10, 81.70, '[{"name":"aflatoxin_b1","fail_rate":0.09},{"name":"lead","fail_rate":0.04},{"name":"pesticide_chlorpyrifos","fail_rate":0.015}]','rf_v1.2'),
(2, 1,'2026-Q2', 0.0700, 178, 41.00, 33.50, 48.50, '[{"name":"aflatoxin_b1","fail_rate":0.05},{"name":"lead","fail_rate":0.02}]','rf_v1.2'),
(3, 1,'2026-Q2', 0.1010,  92, 58.00, 47.20, 68.80, '[{"name":"aflatoxin_b1","fail_rate":0.07}]','rf_v1.2'),
(4, 1,'2026-Q2', 0.0550,  67, 35.00, 26.00, 44.00, '[{"name":"lead","fail_rate":0.03}]','rf_v1.2'),
(5, 1,'2026-Q2', 0.1120, 145, 63.00, 53.40, 72.60, '[{"name":"lead","fail_rate":0.08},{"name":"aflatoxin_b1","fail_rate":0.03}]','rf_v1.2'),
(6, 1,'2026-Q2', 0.0820,  98, 48.00, 38.90, 57.10, '[{"name":"lead","fail_rate":0.05}]','rf_v1.2'),
(7, 1,'2026-Q2', 0.1610, 312, 81.00, 73.20, 88.80, '[{"name":"aflatoxin_b1","fail_rate":0.11},{"name":"lead","fail_rate":0.05}]','rf_v1.2'),
(8, 1,'2026-Q2', 0.1190,  89, 67.00, 55.10, 78.90, '[{"name":"melamine","fail_rate":0.06},{"name":"aflatoxin_b1","fail_rate":0.05}]','rf_v1.2'),
(9, 1,'2026-Q2', 0.0930, 123, 54.00, 44.70, 63.30, '[{"name":"aflatoxin_total","fail_rate":0.06}]','rf_v1.2'),
(10,1,'2026-Q2', 0.0760, 201, 44.00, 36.10, 51.90, '[{"name":"lead","fail_rate":0.04}]','rf_v1.2'),
(11,1,'2026-Q2', 0.0220,  87, 18.00, 11.40, 24.60, '[{"name":"aflatoxin_b1","fail_rate":0.01}]','rf_v1.2'),
(12,1,'2026-Q2', 0.0190, 267, 16.00, 10.80, 21.20, '[{"name":"aflatoxin_b1","fail_rate":0.01}]','rf_v1.2');

-- A few non-rice rows so the risk-report commodity dropdown has real data
INSERT INTO agg_district_commodity_risk
  (district_id, commodity_id, quarter, fail_rate, n_tests, risk_score, ci_lower, ci_upper, top_contaminants, model_version) VALUES
(5, 5,'2026-Q2', 0.1900, 84, 76.00, 65.00, 87.00, '[{"name":"lead","fail_rate":0.19}]','rf_v1.2'),  -- Ahmedabad chilli
(7, 5,'2026-Q2', 0.1500, 96, 70.00, 60.00, 80.00, '[{"name":"lead","fail_rate":0.15}]','rf_v1.2'),  -- Delhi chilli
(8, 3,'2026-Q2', 0.1300, 54, 64.00, 51.00, 77.00, '[{"name":"melamine","fail_rate":0.13}]','rf_v1.2'),-- Noida milk
(11,3,'2026-Q2', 0.0210, 14, 12.00,  5.00, 19.00, '[{"name":"melamine","fail_rate":0.02}]','rf_v1.2');-- Coimbatore paneer-ish (low risk gap)

-- ---- agg_brand_safety_profile (ids match brands above) ----
INSERT INTO agg_brand_safety_profile
  (brand_id, commodity_id, n_tests, n_failures, avg_ppb, risk_score, ci_lower, ci_upper, inference_type, model_version) VALUES
(1, 1, 45, 4,   6.20, 28.00, 20.00, 36.00, 'direct_test',  'rf_v1.2'),  -- India Gate / rice
(2, 7, 32, 5,  18.40, 41.00, 31.00, 51.00, 'direct_test',  'rf_v1.2'),  -- Fortune / mustard_oil
(3, 3,178, 9,  21.00, 19.00, 14.00, 24.00, 'direct_test',  'rf_v1.2'),  -- Amul / milk
(4, 4,  0, 0,   NULL, 55.00, 38.00, 72.00, 'propagated',   'rf_v1.2'),  -- Haldiram's / groundnut (no direct test)
(5, 5, 23, 7,  88.00, 68.00, 55.00, 81.00, 'direct_test',  'rf_v1.2'),  -- MDH / chilli
(6, 6, 19, 5, 120.00, 62.00, 49.00, 75.00, 'direct_test',  'rf_v1.2');  -- Everest / turmeric

COMMIT;
