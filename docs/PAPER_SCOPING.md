# Paper scoping doc (Phase 0)

Locked scoping decisions for the paper. Supersedes two prior scopes, both
abandoned for verified reasons — kept below for the record, not as live
options.

**History:**
1. Original plan: FSSAI district-level enforcement PDFs, Jan 2019–Dec 2024.
   Dead — FSSAI doesn't publish that corpus (see
   [FSSAI_INGESTION.md](FSSAI_INGESTION.md)): old report URLs 302-redirect
   to the homepage, and the PDFs that do exist are news clippings, not
   result tables.
2. First pivot: openFDA food enforcement as the empirical core, India as a
   case study. Also abandoned — independently verified that food/device
   recall NLP on FDA-adjacent text is a crowded, published lane (SemEval-2025
   Task 9's Food Hazard Detection Challenge: 6,644 expert-labeled recalls,
   active leaderboard, arXiv:2503.19800; DeviceBERT, arXiv:2406.05307;
   RecallRisk-BERT, arXiv:2606.27174; FORCE dataset, entity extraction
   including Location). A hazard/geography classifier on openFDA has no
   clean differentiator against this. See
   [PAPER_A_VS_B_MEMO.md](PAPER_A_VS_B_MEMO.md) for the full comparison.

**Committed scope (this document):** **Paper B** — a dated, evidence-backed
audit of what is programmatically extractable from India's food-safety
government infrastructure (FSSAI + FoSCoS), with a working, generalizable
OCR+NER extraction pipeline as proof the bottleneck is the data regime, not
the tooling. openFDA appears only as a comparative reference table (a
mature-regime baseline), not a modeling target.

**⚠ OPEN TODO — novelty claim NOT settled, do not lock into any paper
draft.** Two independent sweeps (general web search, then targeted
queries + direct abstract verification of the closest hits) found no
competing audit of FSSAI/FoSCoS accessibility. But the Semantic Scholar
API portion of the check is rate-limited (429s, no key) and was never
completed — see `PAPER_A_VS_B_MEMO.md` for the sweep history. **User is
running a manual Google Scholar / Semantic Scholar search themselves
before this claim is treated as settled.** This TODO stays open until
they confirm that's done; replace this note with the actual result at
that point, not before.

---

## 1. Core claims (what makes this citable)

1. **India has zero programmatically accessible enforcement/recall data
   today** — proven, not asserted. FSSAI enforcement-report URLs dead
   (302-redirect to homepage); "food-testing.php" PDFs are news clippings,
   not result tables; FoSCoS recalls are qualitative even when reachable
   (no ppb values, no district granularity).
2. **The access barrier is measurably tightening, not static.** Two dated
   checks on `foscos.fssai.gov.in`: 503-during-maintenance (initial
   investigation) → 401-with-`captcha`-response-headers (2026-07-04,
   confirmed via Playwright network interception — every call under
   `commonauth_readonly/commonapi/*` 401s, including an unrelated cosmetic
   dropdown endpoint, meaning FSSAI locked the whole surface, not just
   recalls). This longitudinal "it got harder between two checkpoints" data
   point is the paper's most original contribution.
3. **The barrier is not tooling.** `pipeline/stage1_extract.py`
   (Tesseract 5.5 + Poppler + spaCy) runs end-to-end on a real downloaded
   FSSAI PDF and returns empty fields — a validated negative result:
   nothing structured exists to extract, not a pipeline failure.
4. **Synthetic and real data are indistinguishable at the API/schema
   layer.** This repo's own `enforcement_records` table demonstrates it:
   1,683 `source_type='fssai'` rows are 100% synthetic
   (`pipeline/seed_enforcement.py`), detectable only by manually inspecting
   `source_url` for the `fssai.gov.in/demo/...` pattern — nothing in the
   schema flags it. Generalizes to a real warning for any dashboard/app
   built on scraped government data without provenance tracking.
5. **Comparative baseline:** openFDA — 27,563 real records, 2012–2026, 60
   states/territories, no API key required — vs. India's 0 real
   enforcement/recall records, presented as one table. No modeling
   contribution needed from openFDA; resist scope creep back toward a
   classifier.

## 2. Ethical/methodological boundary (state explicitly, it's a strength)

All findings above came from **read-only** requests — page loads, DOM
reads, network header inspection. No attempt was made to defeat the
FoSCoS captcha/auth gate, guess credentials, or otherwise bypass access
control. This boundary is itself worth a sentence in Methods: the audit
demonstrates what a good-faith, non-adversarial researcher can and cannot
reach.

## 3. Structure guidelines

| Section | Content | Notes |
|---|---|---|
| Introduction | Frame as civic-tech/data-infrastructure transparency, not ML. Stake: apps, journalism, and research built on Indian food-safety data are building on data that doesn't programmatically exist. | AI can draft from bullets; you rewrite the stakes paragraph |
| Related work | Open-government-data accessibility literature (not food-recall NLP — that's the lane we're avoiding, cite it only to explain why we're not in it) | AI drafts summaries, you verify every claim |
| Methodology | The audit protocol itself: URL-by-URL enumeration, dated checks, network-level diagnostics (Playwright interception), explicit no-bypass boundary (§2) | You write — this is the paper's methodological contribution |
| Findings | Source × status × evidence × date table from `FSSAI_INGESTION.md`; the 503→401 changelog with header evidence; the synthetic-vs-real schema-indistinguishability finding | AI drafts from your logged evidence, you verify every claim against the actual dated files |
| Pipeline-generalization | Small extraction eval on whatever real Indian text is reachable (news-clipping PDFs, annual reports) — replaces the original 200-record hand-labeled eval, scaled to what's honestly available | You build this — needs real judgment on what "reachable" text exists |
| Comparative section | openFDA/AGMARKNET table only — real numbers already in hand, no new modeling | AI drafts from numbers, you check every one |
| Recommendations | What FSSAI would need to publish (structured feed, district-level results, stable URLs) + the RTI route as a researcher workaround | You write — this is what COMPASS/AI4SG reviewers want most |
| Limitations | Search-visibility of the novelty claim (2 queries ≠ exhaustive), single-country audit, two time points ≠ continuous monitoring, no IAA (no structured-data eval to double-label) | You review personally, no generic hedges |
| Ethics/broader impact | The no-bypass boundary (§2) as a stated methodological ethic, not just a disclaimer | You write |
| Dataset/artifact release | Release the diagnostic scripts + dated response captures + pipeline, not a "dataset" in the traditional sense — the citable object is the evidence trail | AI drafts license/access boilerplate |

## 4. Venue

arXiv **cs.CY** primary. COMPASS/AI4SG workshop as a compressed 4–6 page
extract — this scope fits their brief (civic-tech transparency, Global
South data infrastructure) better than a US-only hazard classifier would.

## 5. Timeline (~6–8 weeks)

- Week 1: finalize the audit writeup + comparative table (mostly already
  logged in `FSSAI_INGESTION.md` and this session's diagnostic).
- Weeks 2–3: small extraction-tooling eval on real reachable Indian text.
- Weeks 4–7: writing/revision (argument-heavy — this is where most of the
  real time goes, not data processing).

## 5b. Status update 2026-09-19 — one claim to qualify, and what the evidence does and doesn't support

**Claim 1 needs a qualifier before it is written as "zero".** It is true of
FSSAI's *own* channels. It is not true of government as a whole: State/UT
annual counts of samples analysed / found non-conforming (2013-14 → 2025-26)
and enforcement counts are disclosed to Parliament and are reachable through
sansad.in's unauthenticated JSON search API plus the answers' PDFs. Recovering
them was costly: of 70 candidate tables in 124 answers, 54 were rejected for
extraction defects (rows fused, misaligned by one state, garbled names, merged
headers), leaving 16 tables / 539 state-year rows with uneven coverage
(`docs/LOKSABHA_SAMPLING.md`). Suggested framing: the regulator publishes
nothing machine-readable; the same aggregates leak through a parliamentary PDF
channel at State/UT-year granularity only — no district, brand, product or lab
level — at high extraction cost. That strengthens the argument, but the
absolute "zero programmatically accessible" wording should go.

**Claim 2 (tightening): what the probe log actually contains.**
`docs/foscos_access_log.jsonl` has 12 entries, 2026-07-04 → 2026-09-14. It is
**not** a clean time series:
* Six valid readings (2026-07-04 → 08-03): recall API 401, dropdown API 401,
  CSRF-token endpoint 200.
* Six failures (every weekly run from 2026-08-10): `Page.inner_text: Timeout`.
  Because of a probe flaw these recorded null endpoint data even though the
  responses had been observed (fixed 2026-09-19; entries now also record vantage
  point, body length, console errors, failed requests and HTTP errors).
* One local diagnostic on 2026-09-18, outside the maintenance window: the CSRF
  bootstrap returned **401** to an anonymous visitor, the app's own unauthorised
  handler then threw (`TypeError: Cannot read properties of undefined (reading
  'filter')`), and the body rendered empty. A later local run **inside** the
  daily 23:30–03:00 IST maintenance window saw 503s and CSRF 200.
* **First CI-side reading with the improved probe** (2026-09-18 21:40 UTC, GitHub
  Actions runner, outside the maintenance window): the page request itself failed
  with `net::ERR_CONNECTION_TIMED_OUT` — no document, no API calls, no console
  errors. That matches the six failed weekly probes (which timed out reading a
  body that never arrived) and means the CI failures are a **network-level
  non-connection from the runner**, not the app-level CSRF 401 seen locally. Two
  vantage points, two different behaviours: from a local network the page loads
  and its CSRF bootstrap is refused; from GitHub's runner nothing connects.
* **Same symptom, different error text, 2026-09-19 (three GitHub runner readings:
  09:26, 10:26 and 11:40 UTC, all outside the maintenance window):** `page.goto`
  did not raise `net::ERR_*` but hit its 60 s timeout, and the document then
  navigated while being read ("execution context was destroyed"). The 11:40 run,
  with added diagnostics, recorded the tab's final URL: **`chrome-error://chromewebdata/`**
  — Chromium's own connection-error page — with no recall-API or CSRF response
  seen. So this is the same network-level non-connection as 2026-09-18, reported
  through a timeout instead of `ERR_CONNECTION_TIMED_OUT`, not a third portal
  behaviour. Until that was known the scraper (correctly) treated it as
  unclassifiable, raised, and the alerter opened its first production issue
  (#8); it is now classified `unreachable` (an expected outcome, with the URL kept
  in the log). Still one vantage point — the runner — and still no cause
  established for why it cannot connect.
* What is still NOT established: *why* the runner cannot connect (an IP/geography
  block of GitHub's ranges, an outage, or something else) — it is **one** reading,
  and July's CI probes did connect. Do not assert a cause; repeat readings are
  needed. The observation that matters for the paper is that the same public page
  behaves differently by network, and that from July to September CI went from
  "connects, refused (401)" to "cannot connect".

**Other dated observations (2026-09-18, one reading each):** the State Food
Safety Index page moved from `/cms/foodsafetyindex.php` to `/food-safety-index`
and the old URL now returns HTTP 200 with a "Page Not Found" screen (a soft
404 a status-code check would miss); `fssai.gov.in/robots.txt` returns the
site's HTML shell rather than a robots file; ICMR-NCDIR's cancer-registry data
is registry-level with interactive charts and no API/CSV (not district-level).

**Open items, updated:** #1 running but see above; #2 partly done — arXiv API
queries for FSSAI/FoSCoS and for "data accessibility" + India + "food safety"
returned 0 results, Semantic Scholar was rate-limited so that leg is
**incomplete**; #3 done — RTI filed 2026-07-11 (FSSAI/R/E/26/00836) and
answered as unable to provide the data directly (per repo code comments; the
reply letter itself is not in the repo, add it under `docs/`); #4 done
(`docs/REACHABLE_TEXT_INVENTORY.md`).

## 6. Open items before writing starts

1. ~~Set up a recurring probe of the FoSCoS endpoints.~~ **Done
   2026-07-04** — `scripts/probe_foscos.py` + `.github/workflows/
   foscos-probe.yml` (weekly, Mondays 12:00 UTC, read-only, no bypass
   attempted). Appends one JSON line per run to
   `docs/foscos_access_log.jsonl` (status + relevant headers for the
   recall API, an unrelated cosmetic dropdown endpoint, and the CSRF-token
   endpoint — tracking the unrelated endpoint is what let us tell the
   whole `commonapi` surface was locked, not just recalls). First entry
   confirms the same 401+captcha-headers state as the 2026-07-04 manual
   diagnostic. Needs several weeks to accumulate before it's a usable time
   series for the Findings section — start writing that section late.
2. **Second novelty sweep** via Google Scholar / Semantic Scholar, not just
   general web search, before fully committing to the "nobody has audited
   this" claim in the paper's own words.
3. **Decide on filing an RTI request** to FSSAI/state food-safety
   departments now — even a pending or rejected RTI is a usable data point
   for the Findings/Recommendations sections.
4. **Identify what real Indian text is actually reachable** for the
   pipeline-generalization eval (news-clipping PDFs already downloaded
   during `stage1_extract` testing, annual reports, FoSCoS DOM before the
   401 if any cached snapshot exists) — inventory this before committing to
   an eval size.
