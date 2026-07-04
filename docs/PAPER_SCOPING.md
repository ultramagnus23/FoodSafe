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
mature-regime baseline), not a modeling target. Searched independently for
prior work auditing FSSAI/FoSCoS accessibility specifically — found none;
this gap claim currently stands.

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
