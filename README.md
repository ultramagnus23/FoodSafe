# FoodSafe India

A public register of what can actually be known about food safety enforcement
in India — built on real data only, and honest about how little of it exists.
FSSAI publishes no programmatically accessible enforcement dataset; this
project ingests what *is* reachable, refuses to invent the rest, and treats the
gap itself as a finding (see [`docs/PAPER_SCOPING.md`](docs/PAPER_SCOPING.md)).

## Current state (checked 2026-09-19)

Each line says how it was verified. Where something is only reported, it says so.

- **Daily ingest** (`.github/workflows/ingest.yml`, GitHub Actions): scheduled
  runs succeeded every day 2026-09-12 → 2026-09-17. The 2026-09-18 scheduled run
  **failed** at the schema-sync step (a migration re-ran against rows written by
  a newer source; fixed the same day, `schema_migration_009/017`, and the sync
  step has passed against the production database since). Before that, every
  scheduled run since the workflow was created (2026-07-04) failed because the
  original Supabase project had been deleted — 6 successes and 71 failures in
  total (`gh run list`).
- **Database:** Supabase, recreated 2026-09-11 and **real-only** — no synthetic
  rows (`seed_demo.sql` / `pipeline/seed_enforcement.py` are not loaded in
  production).
- **Tests:** 192 passing (`pytest tests/`), CI green.
- **API and Next.js frontend:** *reported* live by the maintainer (Render +
  Vercel). No public URL is recorded in this repo and it has **not been
  independently verified**: `foodsafe-api.onrender.com` did not respond on
  2026-09-16 (the actual service name may differ), and `food-safe.vercel.app`
  serves a different app.
- **Static execution-record page** (GitHub Pages,
  [ultramagnus23.github.io/FoodSafe](https://ultramagnus23.github.io/FoodSafe/),
  HTTP 200 on 2026-09-19): a snapshot of one local validation run on 2026-07-27
  read from `data/` — historical, not live data.

### What real data is in the database

| Source | What it is | Status |
|---|---|---|
| openFDA food enforcement | US recalls (comparison baseline, ~119 rows on 2026-09-16, not re-counted) | real, converged |
| Lok Sabha — state enforcement | State/UT × year samples analysed, cases, convictions, licences cancelled (350 rows, job log 2026-09-18) | real |
| **Lok Sabha — state sampling outcomes** | State/UT × year samples analysed **vs found non-conforming**, 2013-14 → 2025-26 (539 rows from 16 strictly-validated tables, job log 2026-09-18) — [`docs/LOKSABHA_SAMPLING.md`](docs/LOKSABHA_SAMPLING.md) | real; the only source with a pass side |
| FSSAI Annual Report | national enforcement metrics, 3 fiscal years | real |
| FSSAI labs / commissioners | testing-lab (255) and state-commissioner directories | real directories |
| AGMARKNET | district/commodity reference geography | real but flaky: the API returned HTTP 400 in every run I checked (2026-09-16 → 09-18) |
| Local news (5 metros) | locality-tagged food-safety events | real but thin (~1 usable record per run) |
| OpenAlex + Europe PMC | ~1,860 peer-reviewed papers linking 9 contaminants to health outcomes (derived from run logs; `GET /v1/research/summary` gives the live count) | a citation layer — feeds no score |
| FoSCoS recalls | the regulator's recall portal | **gated**: see below |

**There is no district-level India risk data**, so the district risk map is
empty on purpose rather than filled with invented numbers.

### The access gate

`foscos.fssai.gov.in` refuses anonymous API access (401). The weekly CI probe
has failed every week since 2026-08-10; on 2026-09-18 the GitHub runner could
not connect at all (`ERR_CONNECTION_TIMED_OUT`, one reading), while a local check
the same day loaded the page but saw it render empty after its CSRF bootstrap
returned 401. So the page behaves differently by network, the cause of the CI
non-connection is **not established**, and the portal also varies with its daily
maintenance window. See the dated evidence and its limits in
[`docs/PAPER_SCOPING.md`](docs/PAPER_SCOPING.md) §5b and
[`docs/FSSAI_INGESTION.md`](docs/FSSAI_INGESTION.md). The RTI filed 2026-07-11
(FSSAI/R/E/26/00836) was answered as unable to provide the data directly.

## What the models do, and don't

- **Risk scores** (`models/aggregate.py`): a statistical aggregation (fail rate,
  Wilson interval) over enforcement records. With no real district-level
  records there is nothing to score, so none are shown.
- **Backtest on state sampling outcomes**
  ([`docs/BACKTEST_SAMPLING.md`](docs/BACKTEST_SAMPLING.md)): a state's
  non-conforming rate one year predicts the next far better than the national
  rate (average error 4.8 vs 13.2 percentage points), but **no model beat simply
  reusing last year's rate**, and the persistence may reflect where inspectors
  sample rather than food risk. It measures a testing rate, not food safety.
- **Disease-burden estimates**: a dose-response calculation
  (`models/disease_burden.py`), not a trained model; it produces nothing on the
  real-only database because there are no district-level measurements to feed it.
- The openFDA backtest is a published null result
  ([`docs/BACKTEST_REPORT.md`](docs/BACKTEST_REPORT.md)): every record is a
  recall, so there is no pass class.

## Orchestration

`pipeline/airflow_dags.py` contains Airflow DAG definitions, but no Airflow
instance has ever been deployed and those DAGs have never run. What actually
runs is `pipeline/run_and_log.py`
(`python -m pipeline.run_and_log <source> --limit N`), called from the GitHub
Actions cron. That is sufficient at this scale and Airflow is not recommended
here; the file is left in place for whoever wants to decide otherwise.
Failed steps (including `continue-on-error` ones whose green check hides a
failure) are meant to be reported to one rolling GitHub issue by
`scripts/ingest_alert.py`. The old alert steps never worked (their label didn't
exist); the replacement is unit-tested with a fake `gh` but has **not yet fired
in production**.

## Not done / open

- Rotate the Supabase database password and `JWT_SECRET` (both were pasted in
  chat). Confirm the real API and frontend URLs.
- Legal review of the disclaimer copy (`docs/PRE_LAUNCH_OPS.md`).
- Activate row-level security (scaffolding exists, deliberately not switched on:
  `docs/RLS_ACTIVATION.md`).
- Add the RTI reply letter to `docs/`; finish the Semantic Scholar leg of the
  novelty check (it was rate-limited).
- Not built: national year-by-year sampling tables (traps recorded in
  `docs/LOKSABHA_SAMPLING.md`), State Food Safety Index scores
  (`docs/REACHABLE_TEXT_INVENTORY.md`), any district-level real data.

For the technical inventory see [`LAUNCH_CHECKLIST.md`](LAUNCH_CHECKLIST.md) and
[`docs/`](docs/).
