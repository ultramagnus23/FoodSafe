# FoodSafe India

An open, evidence-first food-safety platform for India, built on public records
only. It compares India's legal limits with the EU, Codex and the US; links the
contamination found in food to the diseases its hazards cause (with sources);
gives country, state and packaged-food nutrition context; and is honest about how
little Indian testing data is public (see [`docs/PAPER_SCOPING.md`](docs/PAPER_SCOPING.md)).

**Public portal:** [ultramagnus23.github.io/FoodSafe](https://ultramagnus23.github.io/FoodSafe/)
(rebuilt daily from the production database). **Platform structure, models,
findings and limits:** [`docs/PLATFORM.md`](docs/PLATFORM.md).

## What was added on 2026-10-03

| Area | What | Docs |
|---|---|---|
| Standards | ~56,000 legal limits from FSSAI (CTR compendium v IX), the EU (pesticide MRLs + Reg. 2023/915), Codex (CXLs + CXS 193) and the US (40 CFR 180); India-vs-world comparison of ~1,700 food–hazard pairs | [`docs/STANDARDS.md`](docs/STANDARDS.md) |
| Hazard → health | IARC groups for 1,128 agents; 52 curated hazards with cited outcomes; ADI/ARfD/TDI values | [`docs/HAZARD_KB.md`](docs/HAZARD_KB.md) |
| ML | hazard-category text classifier trained on 15,210 EU notifications, tested on 6,934 later ones: accuracy 0.918, macro-F1 0.777 | [`docs/MODEL_HAZARD_CLASSIFIER.md`](docs/MODEL_HAZARD_CLASSIFIER.md) |
| Health | disease classification of every RASFF finding; health-outcome profiles per origin country; safe-intake calculator | `models/health_*.py`, `models/safe_intake.py` |
| Places | RASFF for every origin country; WHO food-safety capacity + global foodborne burden; World Bank nutrition indicators; Indian state profiles | `country_indicators.py`, `api/routes/places.py` |
| Nutrition | ~21,000 packaged foods sold in India (Open Food Facts) with UK front-of-pack traffic lights | `off_india.py`, `models/nutrition.py` |
| API | `/v1/standards`, `/v1/hazards`, `/v1/classify`, `/v1/health`, `/v1/countries`, `/v1/global`, `/v1/nutrition`, `/v1/places`; `/v1/rasff` takes `origin` | `api/routes/` |

## Current state (checked 2026-09-19; additions above dated 2026-10-03)

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
- **Tests:** 536 passing on 2026-10-03 (`pytest tests/`).
- **Standards, knowledge base, countries, packaged foods in production:** the
  2026-10-03 run of `standards.yml` (run 37091692036, job logs) loaded 56,619
  legal limits (FSSAI 1,573; EU 35,351 MRLs + 403 contaminant levels; Codex
  6,490 + 134; US 12,668), 789 hazard→outcome links, 39,172 country indicator
  values, 10,494 WHO burden rows and 21,188 packaged foods, and recomputed 1,711
  India-vs-world comparisons (India above the EU in 831) — the same counts as the
  local verification. Whole run: 9 minutes.
- **API and Next.js frontend:** *reported* live by the maintainer (Render +
  Vercel). No public URL is recorded in this repo and it has **not been
  independently verified**: `foodsafe-api.onrender.com` did not respond on
  2026-09-16 (the actual service name may differ), and `food-safe.vercel.app`
  serves a different app.
- **Public portal** (GitHub Pages,
  [ultramagnus23.github.io/FoodSafe](https://ultramagnus23.github.io/FoodSafe/)):
  since 2026-10-03 a live portal rebuilt daily from production by
  `.github/workflows/deploy-pages.yml`; checked in a browser on 2026-10-03 after
  the production loads (standards, hazards, safe intake, countries, burden,
  states, nutrition, sources render; no console errors). The July 2026 execution
  record moved to [`record.html`](https://ultramagnus23.github.io/FoodSafe/record.html).

### What real data is in the database

| Source | What it is | Status |
|---|---|---|
| openFDA food enforcement | US recalls (comparison baseline, ~119 rows on 2026-09-16, not re-counted) | real, converged |
| Lok Sabha — state enforcement | State/UT × year samples analysed, cases, convictions, licences cancelled (350 rows, job log 2026-09-18) | real |
| **Lok Sabha — state sampling outcomes** | State/UT × year samples analysed **vs found non-conforming**, 2013-14 → 2025-26 (539 rows from 16 strictly-validated tables, job log 2026-09-18) — [`docs/LOKSABHA_SAMPLING.md`](docs/LOKSABHA_SAMPLING.md) | real; the only source with a pass side |
| **Lok Sabha — pesticide residues (MPRNL)** | National commodity × period counts of samples analysed **vs above the FSSAI residue limit**, 2012-13 → 2018-19 (73 rows from 6 answers; production run 2026-09-19 inserted the same 73 as the local check, job log) — [`docs/LOKSABHA_PESTICIDE.md`](docs/LOKSABHA_PESTICIDE.md) | real contamination test results with a pass side, national grain only; 8 of 16 multiply-reported cells disagree between an early and later vintage |
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
  rate (average error 4.8 vs 13.1 percentage points), but **no model beat simply
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
exist); the replacement is unit-tested with a fake `gh` and **fired for real on
2026-09-19** (issue #8: the FoSCoS scraper could not classify a failed page load,
which turned out to be the runner's usual non-connection — see
`docs/PAPER_SCOPING.md` §5b; issue #8 can be closed once the next run is clean).

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
