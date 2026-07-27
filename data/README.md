# Committed pipeline output — proof of execution

These files are a real snapshot from actually running the pipeline, so a
visitor can see genuine output without setting anything up. Generated
2026-07-27 by running `pipeline/run_and_log.py` against a local Postgres
instance (schema.sql + all 10 migrations applied fresh), because — see
"Why local, not the deployed Supabase DB" below — the project's actual
cloud database is currently unreachable.

## What each file is

| File | Source | What it is |
|---|---|---|
| `sample_ingest_openfda.json` | `pipeline/sources/openfda.py` | 21 real US FDA food-recall records, fetched live from `accessdata.fda.gov` (no API key, no auth) and inserted into `enforcement_records`. Every `source_url` in this file is a real, dereferenceable FDA recall page. |
| `sample_ingest_agmarknet_districts.json` | `pipeline/sources/agmarknet.py` | 10 real Indian districts, fetched live from data.gov.in's AGMARKNET commodity-price API and upserted into `districts`. Geographic reference data, not enforcement records — AGMARKNET doesn't carry safety/violation data (documented in the source file itself). |
| `sample_ingest_new_commodities.json` | openFDA + AGMARKNET combined | 33 commodity rows either source's ingest run upserted from real product-description text (openFDA) or real AGMARKNET commodity names. Not exclusively one source — the raw product-description entries (long, verbatim FDA recall text) are openFDA's; the short clean names are AGMARKNET's. |
| `sample_aggregation_district_risk.json` | `models.aggregate` | Computed district × commodity risk scores (Wilson CI, fail-rate) — real math run over whatever `enforcement_records` existed at the time (see caveat below). |
| `sample_aggregation_brand_risk.json` | `models.aggregate` | Same, aggregated by brand × commodity. |
| `sample_pipeline_runs_log.json` | `pipeline_runs` table | The actual `pipeline_runs` rows this session's execution logged — real timestamps, real row counts, real statuses (`success` / `expected_failure`), written by the same code path production ingestion uses (`pipeline/run_and_log.py`). |

## Honest caveat on the aggregation files

The local database used to produce `sample_aggregation_*.json` was not
empty before this run — it already held 10 old placeholder rows from an
earlier, pre-this-architecture dev session (`source_url` pattern
`fssai.gov.in/r/N`, `apeda.gov.in/r/N` — sequential fake IDs, not real
data, not even matching the current synthetic-seed pattern documented in
`pipeline/seed_enforcement.py`). `models.aggregate` legitimately computes
over whatever rows exist — that's how it's designed to work — so those
10 old rows are mixed into these two aggregation files alongside the 21
real openFDA rows ingested this session. They are not deleted or hidden;
flagging this here so the aggregation numbers aren't mistaken for 100%
real-data-derived. The ingest files above (`sample_ingest_*.json`) are
NOT affected by this — those are filtered to genuinely real rows only.

## Why local, not the deployed Supabase DB

The project's actual cloud database (referenced by the `DATABASE_URL`
secret in GitHub Actions and this repo's local `.env`) is currently
**unreachable**:

```
psycopg2.OperationalError: connection to server at
"aws-1-ap-south-1.pooler.supabase.com" ... failed: FATAL:
(ENOTFOUND) tenant/user postgres.afjyojgezahnqegezpsk not found
```

This is not a transient blip. Checking the GitHub Actions run history
(`gh run list --workflow="Ingest food enforcement data"`) directly:
**every scheduled run since the workflow's creation on 2026-07-04 — 24
out of 24 checked — has failed**, always on this exact database
connection step, completing in 17-24 seconds each time (too fast to have
done any real ingestion work). The earliest failure (2026-07-04) was a
different, related error — `password authentication failed` — meaning
the workflow's `DATABASE_URL` secret has never successfully connected to
this Supabase project, from the very first run. The most likely
explanation is that the referenced Supabase project has been paused
(free-tier auto-pause after inactivity) or deleted, and the GitHub
secret was never updated to match a working project. This needs a human
with Supabase dashboard access — recreating or unpausing the project and
updating the `DATABASE_URL` secret in both GitHub Actions and Render.

To produce a real result without that access, this session applied
`schema.sql` + `schema_migration_002.sql` through `schema_migration_010.sql`
to a local Postgres instance (already present from earlier dev sessions,
`~/scoop/apps/postgresql`, port 5433) and ran the actual pipeline
entrypoints against it — the same code, unmodified, that GitHub Actions
runs, just pointed at a database that exists. This proves the pipeline
logic itself works end to end; it does not resurrect the cloud
deployment, which is a separate, non-code, infra fix.

## Reproducing this

```bash
# Start a local Postgres and load the schema (adjust host/port to yours)
psql -h 127.0.0.1 -p 5433 -U postgres -d foodsafe -f schema.sql
for n in 002 003 004 005 006 007 008 009 010; do
  psql -h 127.0.0.1 -p 5433 -U postgres -d foodsafe -f schema_migration_$n.sql
done

# Run real ingestion against it
export DATABASE_URL="postgresql://postgres@127.0.0.1:5433/foodsafe"
python -m pipeline.run_and_log openfda --limit 15
python -m pipeline.run_and_log agmarknet --limit 20
python -m models.aggregate
```

`fssai_recall` and `local_news` were also run this session against the
same local DB — both completed without error and logged an
`expected_failure` / thin-yield result to `pipeline_runs` (0 rows each:
`fssai_recall` hit the documented FoSCoS 401 gate, `local_news` found 0
food-safety-relevant articles in that day's pull, both matching
previously documented, honest behavior — see `docs/FSSAI_INGESTION.md`
and `docs/LOCAL_NEWS_INGESTION.md`). Their output isn't included here
since there was nothing to include; the `pipeline_runs` log entries for
both attempts are in `sample_pipeline_runs_log.json` as proof they ran.
