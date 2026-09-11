-- ============================================================
-- FoodSafe India — reference district geography
--
-- Applied by scripts/bootstrap_db.py immediately AFTER schema.sql and BEFORE
-- the numbered migrations. It is not itself a numbered migration because its
-- whole purpose is to exist before migrations 009 and 010 run.
--
-- Why this file exists
-- -------------------
-- Migrations 009 and 010 seed ~70 real localities (India Post pincodes and
-- centroids) for five cities, each attached with a join like:
--
--     JOIN districts d ON d.name_canonical = 'Mumbai' AND d.state = 'Maharashtra'
--
-- Those joins were written against a database seeded by seed_demo.sql, which
-- creates those districts. On a database built from REAL sources only, the
-- districts table contains whatever AGMARKNET's API returned that day — on
-- 2026-09-11 that was 21 districts across Andhra Pradesh, Punjab, Kerala,
-- Odisha, Haryana and others, with none of these five cities present.
--
-- Every one of those locality INSERTs therefore matched nothing and silently
-- seeded ZERO rows. No error, no warning: /v1/meta/localities returned an
-- empty list, the pincode resolution on POST /v1/reports could never resolve
-- anything, and the report form's locality field was dead. Seeding these five
-- reference rows first makes the locality layer land in a single bootstrap
-- pass, independent of which districts AGMARKNET happened to return.
--
-- Why this is real data, not synthetic seed
-- ----------------------------------------
-- These are five real Indian districts with their real names, states and real
-- WGS84 centroids. This is reference geography — the same category as the
-- FSSAI notified-lab directory or the India Post pincodes these rows exist to
-- anchor. It asserts that a place exists; it asserts nothing about anything
-- measured there.
--
-- No enforcement record, test result, contamination value or risk score is
-- created here, and none is implied. The distinction this project turns on is
-- between real and fabricated MEASUREMENTS — see pipeline/seed_enforcement.py
-- for the synthetic kind, which a real-only deployment must not load. This
-- file adds none of that, and a district with no records still aggregates to
-- nothing, exactly as it should.
--
-- Re-runnable: ON CONFLICT DO NOTHING against the (name_canonical, state)
-- unique constraint.
-- ============================================================

INSERT INTO districts (name_canonical, state, alternate_names, latitude, longitude)
VALUES
    ('Mumbai',    'Maharashtra', ARRAY['Bombay', 'Greater Mumbai', 'Mumbai City'], 19.0760, 72.8777),
    ('Delhi',     'Delhi',       ARRAY['New Delhi', 'NCT of Delhi'],               28.6139, 77.2090),
    ('Bengaluru', 'Karnataka',   ARRAY['Bangalore', 'Bengaluru Urban'],            12.9716, 77.5946),
    ('Chennai',   'Tamil Nadu',  ARRAY['Madras'],                                  13.0827, 80.2707),
    ('Pune',      'Maharashtra', ARRAY['Poona'],                                   18.5204, 73.8567)
ON CONFLICT (name_canonical, state) DO NOTHING;
