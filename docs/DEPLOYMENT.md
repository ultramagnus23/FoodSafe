# Deployment runbook

Written 2026-09-11, after the original Supabase project was confirmed **deleted**
(not paused): `afjyojgezahnqegezpsk.supabase.co` returns NXDOMAIN, and the
Session pooler answers `FATAL: (ENOTFOUND) tenant/user ... not found`. A paused
project still resolves DNS. Every scheduled ingest since 2026-07-04 had been
failing on this step.

Nothing here is recoverable by editing config — the project must be recreated.
The good news is that **no data is permanently lost**: the schema is in this repo
and every real record came from a public source that can be re-ingested. That has
been verified, not assumed (see [Verified before writing](#verified-before-writing)).

Steps marked **[you]** need a browser login and cannot be automated.
Steps marked **[cli]** are one command.

---

## 0. What you need

| Account | Purpose | Cost |
|---|---|---|
| Supabase | Postgres database | Free tier is enough |
| Render | FastAPI backend (`render.yaml` already targets it) | Free tier sleeps after inactivity |
| Vercel | Next.js frontend | Free tier |
| GitHub | Already connected (`ultramagnus23`) | — |

> **Free-tier warning.** The previous project was deleted for inactivity. If this
> deployment is meant to stay up for a demo or a paper submission, set a calendar
> reminder to touch it monthly, or pay for the smallest paid tier. The daily
> ingest workflow keeps the database active on its own — but only once step 6 is done.

---

## 1. Create the Supabase project **[you]**

1. Create a new project. Any region works; **ap-south-1 (Mumbai)** is closest.
2. Save the database password somewhere real — you cannot read it back later.
3. Go to **Project Settings → Database → Connection string → Session pooler**.

Copy the **Session pooler** URI. It looks like:

```
postgresql://postgres.<ref>:<password>@aws-1-ap-south-1.pooler.supabase.com:5432/postgres?sslmode=require
```

Two things that have bitten this project before:

- **Use the Session pooler host, not `db.<ref>.supabase.co`.** The direct host is
  IPv6-only and unreachable from most Indian ISPs and from GitHub Actions.
- **Keep `?sslmode=require`.** `api/db.py` verifies the certificate against the
  `certifi` bundle; TLS verification was previously disabled here and was fixed
  deliberately. Do not weaken it to get a connection working.

---

## 2. Build the schema **[cli]**

**Now automatic once step 6 is done:** `.github/workflows/ingest.yml` runs
`python -m scripts.bootstrap_db` as its first step, daily and on every
manual dispatch. It's idempotent (already-applied files report "skipped"
via Postgres's duplicate-object codes), so this also means any new
`schema_migration_*.sql` merged to `main` goes live automatically on the
next scheduled run — no more remembering to run this by hand after adding
a migration. This section is still the manual path for the very first
bootstrap, before the GitHub secret exists (step 6), or for running it
locally against a database you're pointing `DATABASE_URL` at directly:

```bash
export DATABASE_URL="<the Session pooler URI from step 1>"
python -m scripts.bootstrap_db
```

Applies `schema.sql`, then `schema_reference_districts.sql`, then all 13
`schema_migration_*.sql` files in numeric order (there is no `001`). Expect
**39 tables** and **73 localities**. Safe to re-run — already-applied files
report `present` rather than failing, so a run interrupted by a network drop can
simply be repeated.

The reference-districts file runs before the migrations for a reason worth
knowing, because it fails silently rather than loudly. Migrations 009 and 010
attach ~70 real localities (India Post pincodes and centroids) to districts by
name — Mumbai, Delhi, Bengaluru, Chennai, Pune. On a real-only database the
districts table holds whatever AGMARKNET returned that day, which on 2026-09-11
was 21 districts across Punjab, Kerala, Andhra Pradesh and elsewhere, with none
of those five cities. Every locality INSERT matched nothing and seeded **zero**
rows, with no error — taking `/v1/meta/localities`, the pincode resolution on
`POST /v1/reports`, and the report form's locality field down with it. Seeding
the five reference rows first fixes this in a single pass (verified: 73
localities, stable across three consecutive runs).

Those five rows are real reference geography — real districts, real centroids —
in the same category as the FSSAI lab directory. They assert that a place
exists, not that anything was measured there, and they add no record, no test
result and no risk score. A district with no records still aggregates to
nothing, which is exactly right.

Check without changing anything:

```bash
python -m scripts.bootstrap_db --check
```

---

## 3. Load real data **[cli]**

```bash
python -m pipeline.run_and_log openfda --limit 200
python -m pipeline.run_and_log agmarknet --limit 1000
python -m pipeline.run_and_log loksabha_qa
python -m pipeline.run_and_log fssai_annual_report
python -m pipeline.run_and_log fssai_labs
python -m models.aggregate
python -m models.disease_burden compute_all
```

`DATA_GOV_IN_KEY` improves AGMARKNET throughput but is not required.

### What you actually get, and the decision it forces

Measured on a clean database on 2026-09-11:

| Source | Result |
|---|---|
| openFDA | 119 records inserted (`--limit 200`) |
| AGMARKNET | 21 districts, 32 commodities |
| Lok Sabha Q&A | **350 rows** of real state-wise enforcement |
| FSSAI Annual Report | 3 fiscal years (2019-20 → 2021-22) |
| FSSAI labs | 215 inserted |
| `models.aggregate` | 119 brand rows, **0 district rows** |
| `models.disease_burden` | **0 estimates** (0 combinations even eligible) |

**A production database built only from real sources has an empty India risk map
and zero disease-burden estimates.** This is not a bug. openFDA records are US
geography, and no source in this pipeline publishes Indian district-level
contamination measurements — that is the central finding of the paper.

The populated risk map and the lead-in-chilli alert come from `seed_demo.sql`
and `pipeline/seed_enforcement.py`, which are **synthetic**. The locality layer
is not among them — those pincodes and centroids are real India Post data and
are loaded by step 2 on a real-only build.

### Decision: real-only (2026-09-11)

**This deployment loads no synthetic data.** `seed_demo.sql` and
`pipeline/seed_enforcement.py` are not run. Do not run them against the
production database.

The consequence is deliberate and must not be treated as a bug to fix later:
the district risk map has no risk markers, and the disease pages return no
estimates. The paper's central claim is that India publishes no accessible
district-level contamination data. An instance that demonstrates exactly that
is the honest artifact; one padded with synthetic records to look fuller would
undercut the argument it exists to support.

Verified on a real-only instance the same day: the UI states this rather than
implying safety. `components/ui/RiskBadge.tsx` renders "Insufficient data" in a
neutral colour and explicitly never renders a score when
`inference_type = insufficient_data`; `components/LeafletMap.tsx` gates marker
colour on `risk_score != null` and draws no-data districts in a distinct grey.
The map legend says so in as many words: *"Districts with no data are shown as
a distinct grey dashed marker, never as zero or low risk."*

**Demo the `/directory` page, not `/map`.** Under real-only, `/directory` is
the surface carrying real content — FSSAI Annual Report enforcement metrics for
three fiscal years (1,18,775 samples analysed in 2019-20, ₹56.28 crore in civil
penalties) and the Lok Sabha state-wise table. `/map` is legitimately, and
visibly, empty.

---

## 4. Deploy the API to Render **[you]**

**Blueprints are a paid feature — do not use `render.yaml` on the free plan.**
Create the service by hand instead; the settings below reproduce `render.yaml`
exactly, so that file stays useful as the reference for what to type (and for
a future paid plan).

**New → Web Service → connect this repo → branch `main`**, then:

| Setting | Value |
|---|---|
| Language / Runtime | `Python 3` |
| Root Directory | *(leave blank — `api/` is at the repo root)* |
| Build Command | `pip install -r requirements-api.txt` |
| Start Command | `uvicorn api.main:app --host 0.0.0.0 --port $PORT` |
| Instance Type | `Free` |
| Health Check Path | `/` |

Verified 2026-09-11 before writing this: `requirements-api.txt` resolves in a
clean virtualenv, and the app boots with **only** those dependencies, in
`ENVIRONMENT=production`, against the live Supabase database — TLS verified,
pool initialised, real data served on every `/v1/meta/*` endpoint. The build
and start commands above are the ones that were exercised.

Then set these environment variables (the manual path does **not** read
`render.yaml`, so every one of these must be entered by hand — including
`ENVIRONMENT` and `PYTHON_VERSION`, which the Blueprint would have supplied):

| Variable | Value |
|---|---|
| `DATABASE_URL` | the Session pooler URI from step 1, **including `?sslmode=require`** |
| `JWT_SECRET` | generate one, see below |
| `ENVIRONMENT` | `production` — **must be set manually** |
| `PYTHON_VERSION` | `3.11.9` — **must be set manually** |
| `FRONTEND_URL` | leave blank for now; set in step 5 |
| `SENTRY_DSN` | optional; omit to run without error tracking |

Generate a signing secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

**`JWT_SECRET` is mandatory in production.** The app refuses to boot with the
default key when `ENVIRONMENT=production` — verified 2026-09-11, it raises
`RuntimeError: JWT_SECRET is not set`. If Render shows a boot crash with that
message, the variable is missing, not broken.

Note the service URL Render gives you, e.g. `https://foodsafe-api.onrender.com`.

> Render's free tier sleeps after ~15 minutes idle; the first request then takes
> 30–50 seconds. For a live demo, hit the URL once a few minutes beforehand.

---

## 5. Deploy the frontend to Vercel **[you]**

**Set Root Directory to `frontend`.** This matters: the repo root also contains a
legacy single-file SPA (`index.html`), and the old root `vercel.json` used to
build *that* instead of the Next.js app. It has been renamed to
`vercel.legacy-static.json` so it can no longer be picked up by accident.
`frontend/vercel.json` now carries the correct Next.js config.

1. **New Project** → this repo → **Root Directory: `frontend`**.
2. Environment variables:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | the Render URL from step 4 |
| `NEXT_PUBLIC_SITE_URL` | your Vercel production URL |

`NEXT_PUBLIC_*` values are baked in **at build time** — changing them later
requires a redeploy, not just a settings save.

---

## 6. Close the loop **[you]**

1. Set `FRONTEND_URL` on Render to the Vercel production URL, then redeploy.
   CORS already allows `localhost:3000`, `foodsafe.in`, and any `*.vercel.app`
   preview by regex, so previews work without further configuration.
2. Add the database URL as a GitHub secret so the daily ingest resumes:

```bash
gh secret set DATABASE_URL --body "<the Session pooler URI>"
gh secret set DATA_GOV_IN_KEY --body "<optional AGMARKNET key>"
```

3. Trigger it once by hand to confirm it is green:

```bash
gh workflow run ingest.yml
gh run watch
```

---

## 7. Verify

```bash
API=https://<your-render-url>

curl -s $API/ | head -c 200                      # service alive
curl -s $API/openapi.json | grep -c '"/v1'       # expect ~53 routes
curl -s $API/v1/meta/districts | head -c 200     # real districts
curl -s $API/v1/meta/state-enforcement | head -c 200   # real Lok Sabha rows
```

Then in the browser:

- `/map` renders (empty of India district risk if you went real-only — expected)
- `/directory` lists labs, commissioners and national enforcement metrics
- `/search?q=rice` returns results carrying `real_count`
- Register an account, log in, and confirm `/account` loads

> The anonymous rate limit is **20 requests/day per IP**, held in memory
> (`api/main.py`). It resets on every deploy and is not shared across instances.
> A demo can exhaust it in a few page loads — **log in before demoing.** Making
> this limit persistent and shared is tracked as a known gap, not done here.

---

## Verified before writing

Checked against a live local instance on 2026-09-11 so this runbook is not
guesswork:

- `scripts/bootstrap_db.py` builds 39 tables from empty in one pass, twice,
  deterministically; re-running is clean and exits 0.
- All five real ingesters pull live data into a freshly bootstrapped database
  (counts in step 3).
- The API boots against that database and serves real data on every analytical
  endpoint.
- `pytest tests/` — 62 passed.
- `next build` — clean, 16 routes.
- Production guard confirmed: boot refused without `JWT_SECRET`.
- `.env` is gitignored and has never been committed.

## Still open after this deploy

- **Rotate the old database password.** It was shared in plaintext and is in the
  local `.env`. The old project is gone, so the credential is dead — but do not
  reuse that password on the new project.
- The in-memory rate limiter is per-instance and resets on deploy.
- `foodsafe_app` restricted role exists but is unused; the API connects as the
  database owner. Activating it needs staging validation — see `docs/RLS_ACTIVATION.md`.
- No district-level Indian contamination data exists to fill the map. That is the
  research problem, not a deployment task.
