-- ============================================================
-- FoodSafe India — Schema Additions (migration_010)
-- Run AFTER schema_migration_009.sql
-- Extends: `localities` (added in migration_009) beyond Mumbai to four
-- more major Indian metros already present as `districts` rows in
-- seed_demo.sql: Delhi, Bengaluru, Chennai, Pune.
--
-- No schema changes here — `localities` (table, indexes, grants) was
-- already created and granted to foodsafe_app in migration_009. This
-- migration is seed data only, same discipline as migration_009's
-- Mumbai seed: every row below is a real, well-known neighborhood with
-- its real India Post PIN code and an approximate real centroid
-- lat/long, sourced as public, checkable knowledge — not synthesized.
-- See docs/LOCALITY_DATA.md ("do not synthesize coordinates or
-- pincodes... a fabricated 'locality' is worse than no locality at
-- all") for why this matters and how to extend further.
--
-- Each block joins against the districts row already seeded in
-- seed_demo.sql for that city (name_canonical/state checked against
-- seed_demo.sql directly rather than assumed):
--   ('Pune',      'Maharashtra')
--   ('Delhi',     'Delhi')
--   ('Chennai',   'Tamil Nadu')
--   ('Bengaluru', 'Karnataka')
-- ============================================================

-- ------------------------------------------------------------
-- SEED: real Delhi localities
-- ------------------------------------------------------------
INSERT INTO localities (name_canonical, parent_district_id, pincodes, latitude, longitude)
SELECT v.name, d.id, v.pincodes, v.lat, v.lng
FROM (VALUES
    ('Connaught Place',   ARRAY['110001'], 28.6315, 77.2167),
    ('Karol Bagh',        ARRAY['110005'], 28.6519, 77.1909),
    ('Chandni Chowk',     ARRAY['110006'], 28.6506, 77.2303),
    ('Hauz Khas',         ARRAY['110016'], 28.5494, 77.2001),
    ('Saket',             ARRAY['110017'], 28.5245, 77.2066),
    ('Vasant Kunj',       ARRAY['110070'], 28.5200, 77.1590),
    ('Dwarka',            ARRAY['110075'], 28.5921, 77.0460),
    ('Rohini',            ARRAY['110085'], 28.7495, 77.0565),
    ('Lajpat Nagar',      ARRAY['110024'], 28.5677, 77.2432),
    ('Greater Kailash',   ARRAY['110048'], 28.5494, 77.2425),
    ('Rajouri Garden',    ARRAY['110027'], 28.6492, 77.1226),
    ('Pitampura',         ARRAY['110034'], 28.6980, 77.1315),
    ('Janakpuri',         ARRAY['110058'], 28.6219, 77.0878),
    ('Mayur Vihar',       ARRAY['110091'], 28.6096, 77.2953)
) AS v(name, pincodes, lat, lng)
JOIN districts d ON d.name_canonical = 'Delhi' AND d.state = 'Delhi'
ON CONFLICT (name_canonical, parent_district_id) DO NOTHING;

-- ------------------------------------------------------------
-- SEED: real Bengaluru localities
-- ------------------------------------------------------------
INSERT INTO localities (name_canonical, parent_district_id, pincodes, latitude, longitude)
SELECT v.name, d.id, v.pincodes, v.lat, v.lng
FROM (VALUES
    ('Koramangala',       ARRAY['560034'], 12.9352, 77.6245),
    ('Indiranagar',       ARRAY['560038'], 12.9719, 77.6412),
    ('Whitefield',        ARRAY['560066'], 12.9698, 77.7500),
    ('Jayanagar',         ARRAY['560041'], 12.9250, 77.5938),
    ('Malleshwaram',      ARRAY['560003'], 13.0035, 77.5709),
    ('Rajajinagar',       ARRAY['560010'], 12.9911, 77.5529),
    ('HSR Layout',        ARRAY['560102'], 12.9116, 77.6389),
    ('Electronic City',   ARRAY['560100'], 12.8452, 77.6602),
    ('Marathahalli',      ARRAY['560037'], 12.9569, 77.7011),
    ('Basavanagudi',      ARRAY['560004'], 12.9422, 77.5760),
    ('Yelahanka',         ARRAY['560064'], 13.1005, 77.5963),
    ('JP Nagar',          ARRAY['560078'], 12.9077, 77.5906),
    ('Banashankari',      ARRAY['560070'], 12.9250, 77.5667)
) AS v(name, pincodes, lat, lng)
JOIN districts d ON d.name_canonical = 'Bengaluru' AND d.state = 'Karnataka'
ON CONFLICT (name_canonical, parent_district_id) DO NOTHING;

-- ------------------------------------------------------------
-- SEED: real Chennai localities
-- ------------------------------------------------------------
INSERT INTO localities (name_canonical, parent_district_id, pincodes, latitude, longitude)
SELECT v.name, d.id, v.pincodes, v.lat, v.lng
FROM (VALUES
    ('T Nagar',           ARRAY['600017'], 13.0418, 80.2341),
    ('Anna Nagar',        ARRAY['600040'], 13.0850, 80.2101),
    ('Adyar',             ARRAY['600020'], 13.0012, 80.2565),
    ('Mylapore',          ARRAY['600004'], 13.0339, 80.2619),
    ('Velachery',         ARRAY['600042'], 12.9791, 80.2212),
    ('Nungambakkam',      ARRAY['600034'], 13.0569, 80.2425),
    ('Besant Nagar',      ARRAY['600090'], 13.0002, 80.2665),
    ('Egmore',            ARRAY['600008'], 13.0732, 80.2609),
    ('Guindy',            ARRAY['600032'], 13.0067, 80.2206),
    ('Tambaram',          ARRAY['600045'], 12.9249, 80.1000),
    ('Porur',             ARRAY['600116'], 13.0381, 80.1564),
    ('Kilpauk',           ARRAY['600010'], 13.0810, 80.2410),
    ('Perambur',          ARRAY['600011'], 13.1143, 80.2329)
) AS v(name, pincodes, lat, lng)
JOIN districts d ON d.name_canonical = 'Chennai' AND d.state = 'Tamil Nadu'
ON CONFLICT (name_canonical, parent_district_id) DO NOTHING;

-- ------------------------------------------------------------
-- SEED: real Pune localities
-- ------------------------------------------------------------
INSERT INTO localities (name_canonical, parent_district_id, pincodes, latitude, longitude)
SELECT v.name, d.id, v.pincodes, v.lat, v.lng
FROM (VALUES
    ('Koregaon Park',     ARRAY['411001'], 18.5362, 73.8938),
    ('Shivajinagar',      ARRAY['411005'], 18.5308, 73.8474),
    ('Kothrud',           ARRAY['411038'], 18.5074, 73.8077),
    ('Viman Nagar',       ARRAY['411014'], 18.5679, 73.9143),
    ('Aundh',             ARRAY['411007'], 18.5590, 73.8077),
    ('Baner',             ARRAY['411045'], 18.5590, 73.7868),
    ('Hadapsar',          ARRAY['411028'], 18.5089, 73.9260),
    ('Deccan Gymkhana',   ARRAY['411004'], 18.5162, 73.8412),
    ('Wakad',             ARRAY['411057'], 18.5978, 73.7645),
    ('Katraj',            ARRAY['411046'], 18.4575, 73.8595),
    ('Kondhwa',           ARRAY['411048'], 18.4667, 73.8901),
    ('Yerawada',          ARRAY['411006'], 18.5480, 73.8827),
    ('Sinhagad Road',     ARRAY['411041'], 18.4745, 73.8280)
) AS v(name, pincodes, lat, lng)
JOIN districts d ON d.name_canonical = 'Pune' AND d.state = 'Maharashtra'
ON CONFLICT (name_canonical, parent_district_id) DO NOTHING;
