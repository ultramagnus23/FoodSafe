# FoodSafe India

## What the pipeline does

FoodSafe India pulls food-safety enforcement and recall data from public
sources (currently: real US FDA recalls via openFDA, real Indian
district/commodity data via AGMARKNET, plus best-effort FSSAI/local-news
sources that are honestly gated or thin — see Planned) into a Postgres
database. It then computes statistical risk scores — fail rate, Wilson
confidence interval — per district and per brand from whatever real
records exist.

## Validated: one real run, small slice

The pipeline has been run once, end to end, against real data. On
2026-07-27, `pipeline/run_and_log.py` was executed against a freshly
migrated local Postgres instance (the project's cloud database is
currently unreachable — see below) and:

- **21 real US FDA recall records** were fetched live from
  `accessdata.fda.gov` (no API key) and inserted.
- **10 real Indian districts** and **33 commodity rows** were fetched
  live from data.gov.in's AGMARKNET API and upserted.
- `models.aggregate` computed **11 district-level and 20 brand-level**
  risk scores from the resulting data.
- The FoSCoS-recall and local-news sources were also run against the
  same database; both completed without error and logged an honest
  zero-row result (a documented 401 auth gate and a day with no matching
  articles, respectively — not a crash).

This is a small slice, not a production-scale run — 21 records, one pass.
The full input, output, and run log are committed at
[`data/`](data/) and rendered at the deployed page below, so this claim
is checkable without running anything yourself.

**What "the DAGs" actually means here:** `pipeline/airflow_dags.py`
contains real Apache Airflow DAG definitions, but no Airflow instance has
ever been deployed for this project — those DAGs have never executed.
The orchestration that has actually run (in CI, and in the local
validation above) is `pipeline/run_and_log.py`, a plain Python script
invoked with `python -m pipeline.run_and_log <source> --limit N`.
**Recommendation: don't stand up Airflow for this project's current
scale.** One scheduler + one metadata database + one webserver is a lot
of infrastructure to run five short-lived ingest jobs a day; the existing
GitHub Actions cron (`.github/workflows/ingest.yml`) calling
`run_and_log.py` already does the job, is what's actually been exercised,
and is what this README's validated claim above is based on. This is a
recommendation, not a decision — `airflow_dags.py` is left in place,
unmodified, for whoever wants to make that call.

## What is deployed, and where

- **Static execution-record page:** [`site/`](site/) — a single static
  HTML page, no backend, no database, no auth, reading the committed
  JSON in `data/` to render the real run described above.
  <!-- DEPLOY_URL: fill in once `vercel --prod` has been run against site/ -->
  Not yet deployed to a public URL — the page is built and was verified
  locally (served and checked for console errors) but publishing it
  requires a Vercel login this environment doesn't have credentials for.
  Deploy command: `cd site && npx vercel --prod --yes`.
- **API (`api/`):** not confirmed deployed. `render.yaml` targets
  Render.com, but no live Render URL was found anywhere in this repo, and
  the database it would connect to is currently unreachable (see below) —
  so even if a Render service exists, it cannot be doing real work right
  now.
- **Next.js frontend (`frontend/`):** not confirmed deployed. No `.vercel`
  project link or live URL was found in this repo.
- **Cloud database:** the Supabase project this repo's `DATABASE_URL` is
  configured to use is currently unreachable —
  `psycopg2.OperationalError: ... FATAL: (ENOTFOUND) tenant/user ... not
  found`. Checking GitHub Actions history directly: **every scheduled run
  of the "Ingest food enforcement data" workflow since it was created
  (2026-07-04) has failed**, always on this database connection step.
  This needs a human with Supabase dashboard access to fix (recreate or
  unpause the project, update the `DATABASE_URL` secret) — it is not a
  code problem. Full detail in [`data/README.md`](data/README.md).

## Planned (not built yet)

- Publishing the static page above to a real URL (blocked on Vercel
  credentials, not code — see above).
- Restoring the cloud database connection and confirming the API/frontend
  are actually reachable somewhere live.
- Real Indian district- or locality-level enforcement/violation data.
  Nothing in this pipeline has one today — FSSAI/FoSCoS publish no open,
  structured feed (see `docs/FSSAI_INGESTION.md`), and the India-labeled
  rows historically seeded into this database
  (`pipeline/seed_enforcement.py`) are synthetic demo data, not real
  measurements.
- Running the pipeline on an actual schedule against a reachable
  database, so the "one real run" above becomes a continuously growing
  dataset instead of a single snapshot.
- Everything else this repo has code for but no verified live proof of —
  auth, search, alerts, admin panel, disputes, B2B API keys, disease
  burden modeling, and the rest of the `api/routes/` and `frontend/app/`
  surface. The code exists and has unit test coverage (`pytest tests/`,
  currently 62 passing), but "code exists and passes unit tests" is not
  the same claim as "this is running and reachable," and this README
  only makes the second kind of claim where it's been checked.

For the fuller technical inventory (data model, security posture, what
each module does) see `LAUNCH_CHECKLIST.md` and `docs/`.
