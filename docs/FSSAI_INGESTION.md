# FSSAI ingestion — investigation & status

**TL;DR:** the OCR + extraction toolchain now works end-to-end, but FSSAI does
**not** publish district-level food-contamination test results as structured,
scrapable data. So this path cannot currently feed the India risk model. This
document records what was tried, what works, and exactly what remains.

## What the pipeline expects

`pipeline/sources/fssai.py` → `pipeline/stage1_extract.py` was designed to:
1. scrape FSSAI listing pages for links to **enforcement-report PDFs**,
2. OCR each PDF (Tesseract / Poppler) and run **NER** (spaCy) to pull
   product / brand / contaminant / value / unit / date / district,
3. standardise → dedup → confidence-score → `enforcement_records`.

This assumes FSSAI publishes **tabular enforcement PDFs**. That assumption no
longer holds.

## What I found (2026-06)

| Source | Status |
| --- | --- |
| `cms/enforcement-reports.php`, `recall-notices.php`, `lab-test-results.php`, `food-safety-mitra-reports.php` | **Dead** — all 302-redirect to the homepage. The site was restructured. |
| `cms/food-recall.php` | Reachable, but the recall list is **JS-rendered** (DataTables) — not in the static HTML and not PDFs. Recall entries are also **qualitative** (product / brand / reason / date), with **no contaminant ppb values**. |
| `cms/food-recall-archive.php` | Reachable, but exposes only admin PDFs (citizens' charter, application status), **no recall data**. |
| `index.php?page=food-testing.php` | Exposes ~hundreds of PDFs, but they are **news clippings** (`FSSAI_News_*`) and narrative documents — **not test-result tables**. |
| `knowledge-hub.php` (Annual Report, etc.) | JS-rendered; no static report PDFs. |

**Conclusion:** there is no open, structured feed of Indian district-level
contamination test data on the FSSAI site. The data that exists is either
JS-rendered and qualitative (recalls) or unstructured (news / narrative PDFs).

## What now works (this attempt)

- **OCR toolchain installed and verified:** Tesseract 5.5, Poppler 26, spaCy +
  `en_core_web_sm`, `pdfplumber`, `pdf2image`, `pytesseract`.
- **`extract_pdf` runs end-to-end on a real FSSAI PDF** — downloaded a live
  FSSAI PDF and ran `pipeline.stage1_extract.extract_pdf`; it processed the
  document and returned `RawRecord`s without error. Fields came back empty
  because (a) the test PDF was a news clipping, not a results table, and
  (b) no **trained** NER model is present (`stage1` falls back to "spaCy base +
  rules"). The path is functional; it just has nothing structured to extract.
- **`fssai.py` URLs modernised** to the current reachable pages so the scraper
  no longer points at dead endpoints.

## What remains to actually complete FSSAI ingestion

1. **A real structured source.** Options, in rough order of effort:
   - **RTI / bulk request** to FSSAI or state food-safety departments for raw
     surveillance datasets (the realistic route to real Indian test data).
   - **Headless browser** (Playwright) to render `food-recall.php` and capture
     the recall DataTable — this yields *qualitative* recall events (like the
     openFDA feed), not ppb values, and still has no district granularity.
   - State food-safety department portals (per-state, heterogeneous).
2. **A trained NER model** (`models/saved/` / the `Trained NER model not found`
   fallback) to extract entities from real enforcement PDFs, once such PDFs are
   sourced. Requires an annotated FSSAI corpus.
3. Only after 1–2 do `stage2/3/4` + `models/aggregate.py` produce real Indian
   district risk scores. Until then the heatmap runs on
   `pipeline/seed_enforcement.py` demo records (computed by the real
   aggregation) and the live feeds are openFDA (US recalls) + AGMARKNET
   (Indian geographic/commodity coverage).

## Reproducing the toolchain

```bash
# OS tools (Windows via scoop shown; apt on Linux)
scoop install tesseract poppler
# Python OCR/NLP deps (already in requirements.txt)
pip install pdfplumber pdf2image pytesseract Pillow spacy boto3
python -m spacy download en_core_web_sm
export TESSERACT_CMD="$(which tesseract)"   # if not on PATH
```
