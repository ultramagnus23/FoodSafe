# Paper A vs. Paper B — decision memo (2026-07-04)

Written after independently verifying the prior-work claim that killed the
openFDA pivot. `PAPER_SCOPING.md` is **not** updated further pending this
decision.

## Independent verification of prior work (confirmed, not taken on faith)

- **SemEval-2025 Task 9, Food Hazard Detection Challenge** (arXiv:2503.19800,
  site: food-hazard-detection-semeval-2025.github.io) — real. 6,644
  expert-labeled food-recall announcements, coarse+fine hazard/product
  category classification, active leaderboard, multiple published team
  systems (e.g. BrightCookies, arXiv:2504.20703), public GitHub solutions.
- **DeviceBERT** (arXiv:2406.05307) — real. NER for device/component
  terminology in FDA device-recall summaries, BioBERT-based.
- **RecallRisk-BERT** (arXiv:2606.27174) — real. Multi-task BERT (text +
  structured fields) predicting recall severity + root-cause category from
  FDA device-recall narratives.
- **FORCE dataset** — real (referenced in arXiv:2506.18185). 8,100 news
  articles + FDA press releases, sentence + entity-level annotation
  (Org/Product/Cause/Disease/Count/**Location**) for recall & outbreak
  extraction.

Conclusion: food/device recall hazard-classification and entity-extraction
on FDA-adjacent text, including geography extraction (FORCE already does
Location), is an active, published, leaderboard-driven space. The openFDA
pivot's proposed contribution (hazard/product NER + `distribution_pattern`
state parsing + recall-likelihood modeling) does not have a clean claim
against this — it would read as a smaller, less rigorously benchmarked
version of work that already exists with public leaderboards.

Additional check: searched for prior work specifically auditing Indian
food-safety data accessibility (FSSAI/FoSCoS) — found none. The gap claim
for Option B survives this search (not exhaustive, but no hit after two
targeted queries).

## Paper A — openFDA hazard/recall-risk model

| | |
|---|---|
| **Novel claim** | Unclear. Would need a differentiator against SemEval-2025 Task 9 (same task, larger published baseline set) and RecallRisk-BERT (same triage framing, applied to device not food recalls but structurally identical). The one piece not directly duplicated — `distribution_pattern` free-text → state-list parsing, feeding a state-level recall-rate model with an inspection-intensity confound covariate — is real but narrow, and reads as an *extension* of an existing benchmark rather than a new contribution. No confident answer to "why would a reviewer accept this over just extending SemEval's task." |
| **Data: real vs. needs work** | Fully real today — 27,563 openFDA records, no acquisition risk, ready for Phase 1 immediately. |
| **Rough timeline** | Technically fits 9–11 weeks. Publishability is the actual risk, not schedule. |
| **Verdict** | Fine as a class project / portfolio piece. Not recommended as the paper without a sharper differentiator that doesn't yet exist. |

## Paper B — India data-accessibility audit (openFDA/AGMARKNET as comparative reference only)

| | |
|---|---|
| **Novel claim** | A dated, methodical, evidence-backed audit of what's programmatically extractable from Indian food-safety government infrastructure: FSSAI's enforcement-report URLs dead (302→homepage), FoSCoS's access model measurably tightening (503-maintenance → 401-with-captcha-headers between two dated checks, captured via network-level diagnostic), synthetic-vs-real data indistinguishable via API response shape unless you inspect `source_url` patterns. Paired with a working, generalizable OCR+NER pipeline (Tesseract+Poppler+spaCy) validated end-to-end against a real downloaded FSSAI PDF — demonstrating the tooling works, the target corpus just isn't there yet. No competing paper found on this specific ground. |
| **Data: real vs. needs work** | The audit itself is 100% real and already substantially written (`docs/FSSAI_INGESTION.md`, today's 401 diagnostic). openFDA/AGMARKNET slot in only as a comparative "what a mature open-data regime looks like" table — no new modeling contribution needed from them, just real numbers already in hand (27,563 records, 60 states, vs. India's 0 real enforcement records / access barriers documented). Still open: whatever real Indian text *is* reachable (news-clipping PDFs, annual reports, FoSCoS DOM before the 401) should get a small extraction-tooling eval to show the pipeline generalizes past openFDA's already-structured JSON. |
| **Rough timeline** | Shorter than Paper A in some ways (no need to build/tune a competitive classifier against an active leaderboard) but the audit narrative and comparative table need careful, non-generic writing — this is argument-heavy, not numbers-heavy. Roughly 6–8 weeks: ~1 week finalizing the audit writeup + comparative table, ~2 weeks on the small extraction-tooling eval against real reachable Indian text, ~3–4 weeks writing/revision, matches COMPASS/AI4SG's typical cycle better than a 9–11 week ML-benchmark paper would. |
| **Verdict** | Recommended. Undersaturated ground, fits cs.CY / COMPASS/AI4SG's actual interest (civic-tech transparency, Global South government-data infrastructure) better than a US hazard classifier would, and the receipts already exist in this repo. |

## Recommendation

**Paper B**, openFDA/AGMARKNET relegated to a comparative table, no further modeling work needed on them beyond what's already ingested. Waiting on your pick before touching `PAPER_SCOPING.md` again.
