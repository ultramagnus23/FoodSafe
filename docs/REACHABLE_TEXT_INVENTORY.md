# Reachable Indian food-safety text inventory

What is actually fetchable right now, without any auth/captcha bypass
(plain HTTP GET / page render, same as a normal visitor). Compiled
2026-07-04 via direct page fetches. Not exhaustive for state portals —
only Maharashtra was spot-checked; other states are an open item, not
covered here.

| Source | URL | Format | Approx. count | Date range | Structured or narrative | Food-safety enforcement relevant? |
|---|---|---|---|---|---|---|
| FSSAI food-testing listing | `fssai.gov.in/index.php?page=food-testing.php` | PDF listing page | ~150+ documents | Jan 2023 – Jul 2026 (bulk of dated items) | **Narrative** — ~100+ are press clippings (NDTV, Business Standard, The Hindu, etc.) reporting on food-safety news, not result tables. A handful of guidance docs (e.g. rice-fortification FAQ) are structured Q&A, not enforcement data. | Yes, but as unstructured news text only — this is the realistic target for the pipeline-generalization eval (§4), not a source of quantitative enforcement records. |
| FSSAI food-recall-archive | `fssai.gov.in/cms/food-recall-archive.php` | PDF listing | 6 documents | 2017 – 2026 (mostly 2017-18, one 2026 status doc) | **Narrative/administrative** — regulation text, guidelines, meeting minutes, an FBO-notification letter, an application-status PDF, a calendar. No recall records. | No — administrative documents only, confirms the earlier finding that this page has "no recall data." |
| FSSAI food-recall (pointer page) | `fssai.gov.in/cms/food-recall.php` | HTML + 1 PDF | 1 FAQ PDF | n/a | Narrative (procedure/FAQ) | No — explicitly a pointer to FoSCoS, which is blocked (401). No recall data itself. |
| FSSAI knowledge-hub direct links | `fssai.gov.in/knowledge-hub.php` | HTML + scattered PDFs | 3 directly linked (Citizen Charter, 2026 calendar, application-status doc) | 2025-26 | Narrative/administrative | No |
| **State Food Safety Index (SFSI)** | `fssai.gov.in/cms/foodsafetyindex.php` | PDF reports | **8 editions**, one "Report" + narrative "Write-up" per year for most, plus a separate "Parameters" doc for 2022-23 | **2018-19 through 2023-24** (6 annual cycles) | **Structured** — state-level composite rankings across 5 parameters (HR/institutional capacity, compliance, testing infrastructure/surveillance, training, consumer empowerment) | Not enforcement *records*, but the strongest real, structured, multi-year, state-level dataset found on the FSSAI site. Worth a dedicated line in Findings — this is what FSSAI *can* publish in structured form when it chooses to, which sharpens the contrast with the enforcement-data opacity rather than undermining it. |
| FoSCoS food-recall | `foscos.fssai.gov.in/food-recall` | N/A | 0 | n/a | N/A | **Blocked** — 401 + captcha headers on `commonapi`, confirmed and tracked by the weekly probe (§7). Not counted as "reachable." |
| Maharashtra FDA — NSQ Alerts | `fda.maharashtra.gov.in/1094/NSQ-Alerts` | Embedded HTML table (not downloadable) | 5 live entries as of 2026-06-23 | product mfg/expiry dates 2024–2028 (page "last updated" date, not a historical archive) | Structured (product/batch/mfg-expiry/manufacturer/defect) | **Out of scope** — this is drug quality-of-standard (NSQ) data, not food. Same regulator (FDA Maharashtra covers both food and drugs), so it's useful evidence that *a* state portal can and does publish structured regulatory tables — a genuine contrast point for the paper — but it isn't itself food-safety enforcement text and shouldn't be counted toward the food corpus. |

## What this means for §4 (the extraction eval)

The only realistic, in-scope, real-text corpus for a pipeline-generalization
eval is the **FSSAI food-testing news-clipping PDFs** (~150+ documents,
2023–2026) — narrative press coverage, not result tables. Running OCR+NER
against these will demonstrate the pipeline works end-to-end on real text,
but the expected extraction yield is low almost by construction (news
clippings don't contain structured contaminant/district/value fields to
extract) — this should be framed honestly as a negative/near-null result
consistent with the paper's core claim (§1, item 3: the barrier is the
data regime, not the tooling), not as a failed eval.

## Pipeline run against a real sample (2026-07-04)

Ran `pipeline.stage1_extract.extract_pdf` against a spread sample of 15
real PDFs pulled directly from the food-testing listing (2,532 unique PDF
links confirmed on that one page via direct HTML fetch, spanning
2018–2026 per filename dates; the earlier "~150+" estimate undercounted —
2,532 is the real number).

- 6/15 failed with a Tesseract `TESSDATA_PREFIX` environment error
  (intermittent — same env, not a per-file issue) — a fixable
  reproducibility bug, not a data finding. Needs `TESSDATA_PREFIX` set
  explicitly before a full run.
- 9/15 succeeded, yielding **277 `RawRecord` objects** (0–95 per
  document).
- Checked every field on every one of the 277 records, not just the
  first per file: **zero non-null hits** on `product_name`, `brand`,
  `manufacturer`, `contaminant`, `value`, `unit`, `date`, `state`,
  `district`, `pass_fail`. The only field with hits was `lab_id` (40
  hits) — inspected the actual values and they are raw leftover OCR
  text lines from the article body (e.g. `"MUMBAI: Food safety and
  hygiene is of paramount importance..."`), not lab identifiers. This is
  a fallback/bucket artifact in the extraction rules, not real signal.

**Real usable structured records for a hand-labeled P/R/F1 eval: 0.**
This is well below any threshold for a meaningful quantitative
extraction-eval table — not "small," actually zero. Confirms the
document volume (2,532) was never the constraint; the content type is.
Recommend reframing §4 as a qualitative case study (documenting *why*
the pipeline returns 277 empty-shell records rather than 0 records with
real content — itself informative about how the extraction rules
over-fire on narrative text) rather than a quantitative eval table with
per-field P/R/F1. Flagging for your decision before any hand-labeling
starts, per your instruction.

## Update 2026-09-18 — State Food Safety Index re-checked

**The SFSI page moved and the old URL soft-404s.** The row above
(`fssai.gov.in/cms/foodsafetyindex.php`, reachable 2026-07-04) now renders a
"Page Not Found" screen while still returning HTTP 200 — a client-rendered
SPA, so a status-code check alone would call it healthy. The page now lives
at `fssai.gov.in/food-safety-index`. `fssai.gov.in/robots.txt` likewise
returns the SPA's HTML shell rather than a real robots file, so the site
publishes no machine-readable crawl policy. Both are additional data points
for the paper's "the access surface is unstable" claim (one observation each,
not a time series). The page sits behind an F5 `/TSbd/` bot-defence script;
this project reads public pages as a normal headless visitor and does not
attempt to evade it (same posture as the FoSCoS probe).

Documents on the new page (sizes from HEAD requests):

| Edition | File | Size | Extractable? |
|---|---|---|---|
| 2018-19 | `sfsi1819.pdf` | 0.34 MB | **No** — one page, zero text layer (scanned image); would need OCR |
| 2019-20 | `Report_State_Food_Safety_Index_08_06_2020.pdf` | 0.13 MB | Yes — 3 tables, 5 scores + total per state |
| 2020-21 | `Report_SFSI_20_09_2021.pdf` | 0.18 MB | Yes — tables split across pages 2-4 |
| 2021-22 | `Report_SFSI_06_06_2022.pdf` | 0.08 MB | Yes — tables split across pages 2-4 |
| 2022-23 | `Report_SFSI_080623.pdf` | 36 MB | Not attempted (size; same call as the annual-report manifest) |
| 2023-24 | write-up 0.37 MB / full report 40 MB | | Write-up has the full ranking table (6 scores + total) |

Extraction is messy (rotated header text, `None`-padded merged cells, tables
spanning pages, differing column counts per edition) — the same trap that
silently corrupted the 2018-19 annual-report parse. Any SFSI parser should
accept a row only if the component scores sum to the printed total
(verified by hand on Gujarat 2019-20: 17+24+16.5+4.75+16 = 78.25; Kerala
2023-24: 6.25+17+31+4+7.5+8 = 73.75) and count/log rejected rows instead of
guessing. **Not built yet** — SFSI is state *capacity* data (staffing,
compliance, testing infrastructure), not enforcement outcomes, so it was
ranked below extending the Lok Sabha state-wise enforcement tables.

## Open items not covered here

- Only Maharashtra was spot-checked for state-level content. Other major
  states (Delhi, Gujarat, Tamil Nadu, Karnataka, UP) are unchecked — worth
  a follow-up pass if the paper wants a broader state-portal comparison,
  but not required for the core FSSAI/FoSCoS audit.
- The SFSI reports themselves haven't been downloaded/parsed yet — only
  confirmed reachable and enumerated by year/title.
