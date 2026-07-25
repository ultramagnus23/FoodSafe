# Pre-launch ops checklist

Two items on `LAUNCH_CHECKLIST.md` aren't code — confirming secrets are
set on each platform, and getting the disclaimer copy legally reviewed.
Neither can be verified or performed from inside this repo. This doc
exists so "confirm secrets are set" is a checklist you can actually run
through, not a vague reminder.

## Secrets to confirm are set (not just present locally in `.env`)

Derived from `render.yaml`, `.github/workflows/*.yml`, and
`frontend/.env.example` — the exact names each platform expects.

**Render** (`render.yaml`, the API service):
| Secret | Used by | Notes |
|---|---|---|
| `DATABASE_URL` | `api/db.py` | Supabase session-pooler connection string (`host=aws-1-<region>.pooler.supabase.com port=5432 ... sslmode=require`), not the direct IPv6-only host. |
| `JWT_SECRET` | `api/auth_utils.py` | As of this branch, the API now **refuses to start** in production without this set — see the fail-fast check added in `api/auth_utils.py`. |
| `FRONTEND_URL` | `api/main.py` CORS allowlist | Set to the production frontend domain. |
| `SENTRY_DSN` | `api/main.py` | Optional — leave unset to run without error tracking, or create a Sentry project and set it now that the wiring exists. |

**GitHub Actions** (`.github/workflows/ingest.yml`):
| Secret | Used by | Notes |
|---|---|---|
| `DATABASE_URL` | every ingest step | Same value as Render's, so ingested rows land in the same DB the API reads from. |
| `DATA_GOV_IN_KEY` | AGMARKNET ingest | Free key from data.gov.in; step is `continue-on-error` if missing. |
| `RESEND_API_KEY` | alert-subscription emails | Step is `continue-on-error` if missing — a no-op, not a failure, per the existing comment in the workflow. |

**Vercel** (frontend):
| Secret | Used by | Notes |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `frontend/lib/api/client.ts` | Point this at the Render API's public URL. Build-time env var (Next.js), not a runtime secret — set it in the Vercel project's environment variables. |
| `NEXT_PUBLIC_SITE_URL` | `frontend/app/sitemap.ts` | Production domain, for absolute sitemap URLs. |

None of the above values are readable from this repo (`.env` is
gitignored and wasn't inspected to write this doc) — this is a checklist
of *names* to go confirm in each platform's dashboard, not a report of
what's currently set.

## Legal review of disclaimer language

This is not something to implement in code — `LAUNCH_CHECKLIST.md` flags
it because the platform makes statistical claims about named brands and
places based on OCR-extracted government data, and current copy hasn't
been reviewed by counsel. Get an actual lawyer to review the exact
wording before wide release. Disclaimer strings currently live in:
`frontend/components/ui/DisclaimerBanner.tsx`, the `DISCLAIMER` constant
in `api/auth.py`, and per-response `disclaimer` fields returned by
`api/other_routes.py` and `api/routes/{compare,disease,risk,trends,widget}.py`
— surfaced in `frontend/components/TrendChart.tsx` and the
`alerts`/`compare`/`district/[id]`/`embed/district/[id]`/`methodology`/
`search` pages. That's the full surface to hand to counsel; I can't
perform or substitute for the review itself.
