# Locality-level geography — what exists and how to extend it

## What this adds

`schema_migration_009.sql` adds a `localities` table sitting below
`districts` — the first sub-district geography this schema has ever had.
Seeded with ~20 real Mumbai neighborhoods (Juhu, Vile Parle West/East,
Churchgate, Bandra, Andheri, Colaba, Dadar, Powai, Worli, Malad, Borivali,
Santacruz, Kurla, Ghatkopar, Chembur, Mulund), each linked to its real
India Post PIN code(s) and an approximate centroid lat/long.

`schema_migration_010.sql` extends the same seed to four more metros
already present as `districts` rows in `seed_demo.sql` — Delhi,
Bengaluru, Chennai, and Pune — each with ~13 real, well-known
neighborhoods (Connaught Place, Koramangala, T Nagar, Koregaon Park,
etc.), same sourcing discipline: real India Post PIN codes, real
approximate centroids, no schema changes (the table/indexes/grants from
migration_009 already cover it). As of migration_010, `localities` has
real coverage for five cities: Mumbai, Delhi, Bengaluru, Chennai, Pune.
Every other city with a `districts` row still has zero localities —
querying `GET /v1/meta/localities` for those returns an empty list, not
an error, which is the correct honest answer until they're seeded too.

`consumer_reports` and `enforcement_records` both got a nullable
`locality_id` FK. Nullable and additive on purpose — every row and query
that only ever knew a district keeps working unchanged; a `NULL
locality_id` just honestly means "we don't have finer detail for this
row," which is the truth for 100% of data ingested before this migration.

`POST /v1/reports` now accepts an optional `pincode` field. If it matches
a seeded locality, the report is tagged with that `locality_id` (and its
parent `district_id`, if one wasn't already given) — see
`api/routes/reports.py`. `GET /v1/meta/localities` lists localities,
optionally filtered by `district_id` or resolved by `pincode`.

## Why pincode, not a free-text "locality name" field

Asking a user to pick "Juhu" from a dropdown only works if Juhu is
already seeded — which most of India isn't yet. A 6-digit PIN code is
something almost anyone already knows, is unambiguous (unlike "Andheri,"
which spans both West and East with different codes), and is backed by a
real, free, open reference dataset (India Post's PIN code directory,
data.gov.in) that can be bulk-loaded later without asking anyone to type
anything new.

## What real data can land here right now

Nothing does automatically yet — this migration is schema capacity, not
a new data feed. Per `docs/FSSAI_INGESTION.md`, no Indian government
source publishes locality-level (or even reliably district-level)
enforcement data in the open today. The realistic near-term source is
crowdsourced `consumer_reports` with a pincode (already wired above) —
see the growth-plan artifact from this session for the fuller sourcing
strategy (FBO license search reachability, local-news NER, BMC RTI).

## Extending the seed to more cities / full India coverage

1. **Bulk path (recommended for scale):** India Post's PIN code directory
   on data.gov.in is a free, open, real dataset mapping every PIN code to
   its office name, taluk, district, and state. Load it once into a
   staging table, then `INSERT INTO localities (...) SELECT ... FROM
   staging JOIN districts ON name match`, deduplicating PIN-code groups
   that share an office name into one locality row (the raw directory has
   one row per post office, which is finer than most people mean by
   "locality" — e.g. Juhu is one office, one locality; some larger areas
   have multiple offices worth merging).
2. **Manual path (what migration_009 did for Mumbai and migration_010 did
   for Delhi/Bengaluru/Chennai/Pune):** for a specific city, hand-pick the
   well-known neighborhood names, look up their real PIN code(s) and
   centroid, and add a `VALUES (...)` block following the exact pattern
   used in those migrations — joined against the city's existing
   `districts` row by exact `name_canonical`/`state` (check
   `seed_demo.sql` for the spelling before writing the JOIN). Fine for a
   handful of cities; doesn't scale to all of India.
3. Either way, **do not synthesize coordinates or pincodes** — every row
   in `localities` should trace to a real, checkable source, the same
   discipline this project already applies to `enforcement_records`
   (`source_type`, `source_url`). A fabricated "locality" is worse than
   no locality at all, for the same reason a fabricated risk score would
   be.
