"""
FoodSafe India — Scientific Evidence Ingester, second source (Europe PMC)

Real, no-API-key data source: the Europe PMC REST API
(https://www.ebi.ac.uk/europepmc/webservices/rest/search) — free, public,
covering PubMed/PMC plus additional preprint and patent literature, with
real DOIs, PMIDs, PMCIDs, abstracts, and — the reason this is a second
source rather than just more OpenAlex volume — a real per-work
`pubTypeList` (Systematic Review, Meta-Analysis, Randomized Controlled
Trial, Cohort Studies, Case Reports, ...). OpenAlex's own `type` field only
distinguishes review vs. not; this lets `study_design` be a real,
source-reported classification instead of that coarse split.

Cross-dedup: this connector shares research_sources
(schema_migration_015.sql, extended by schema_migration_016.sql) with
pipeline/sources/research_evidence.py (OpenAlex). A work already present
by DOI or PMID is never re-inserted — it is *enriched*: study_design is
filled in if it was still 'unclassified', pmcid is added if missing, and
'europepmc' is recorded in source_apis. If the richer classification
reveals a systematic review or meta-analysis that OpenAlex's coarser
'type' field missed, the existing contaminant_research_links row is
upgraded from evidence_level 'C' to 'B' — never invented, and only ever
upgraded, never downgraded (see docs/RESEARCH_EVIDENCE_INGESTION.md).

Run:
  python -m pipeline.sources.europepmc_evidence --limit 5
Idempotent: shares the same doi/pmid dedup as research_evidence.py.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import psycopg2

from pipeline.config import pg_connect
from pipeline.sources.research_evidence import build_search_term, extract_health_terms

logger = logging.getLogger("foodsafe.europepmc_evidence")

EUROPEPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
REQUEST_DELAY_S = 1.0

# Ordered most-specific-first: the first matching pubType wins, so a work
# tagged both "Review" and "Systematic Review" (Europe PMC often lists
# several) is classified by the more informative tag.
_STUDY_DESIGN_RULES: tuple[tuple[str, str], ...] = (
    ("systematic review", "systematic_review"),
    ("meta-analysis", "meta_analysis"),
    ("meta analysis", "meta_analysis"),
    ("randomized controlled trial", "randomized_trial"),
    ("controlled clinical trial", "randomized_trial"),
    ("cohort", "cohort"),
    ("case-control", "case_control"),
    ("case control", "case_control"),
    ("cross-sectional", "cross_sectional"),
    ("cross sectional", "cross_sectional"),
    ("observational study", "observational"),
    ("case reports", "case_report"),
    ("clinical trial", "clinical_trial"),
    ("comparative study", "comparative_study"),
    ("review", "review"),
    ("editorial", "commentary"),
    ("comment", "commentary"),
    ("letter", "commentary"),
)

_UPGRADE_TO_B = {"systematic_review", "meta_analysis"}

_TAG_RE = re.compile(r"<[^>]+>")


# ------------------------------------------------------------
# Pure parsing helpers (unit-testable without network)
# ------------------------------------------------------------

def strip_html(text: str | None) -> str:
    """Europe PMC's 'core' result type embeds markup as HTML entities (e.g.
    'B&lt;sub&gt;1&lt;/sub&gt;'), so entities must be unescaped *before*
    tag-stripping — otherwise the newly-revealed '<sub>' tags are never
    removed. A second, cheap tag-strip afterward also catches any literal
    (non-escaped) tags some records carry directly."""
    if not text:
        return ""
    return _TAG_RE.sub("", html.unescape(text)).strip()


def classify_study_design(pub_types: list[str] | None) -> str:
    """Rule-based mapping off Europe PMC's own pubTypeList — never a guess.
    Falls back to 'unclassified' when only a generic tag like 'Journal
    Article' is present."""
    if not pub_types:
        return "unclassified"
    lowered = [p.lower() for p in pub_types]
    for keyword, design in _STUDY_DESIGN_RULES:
        if any(keyword in p for p in lowered):
            return design
    return "unclassified"


def should_upgrade_to_b(study_design: str) -> bool:
    return study_design in _UPGRADE_TO_B


def merge_study_design(existing: str | None, new: str) -> str:
    """Keep an existing informative classification; only replace a missing
    or 'unclassified' one."""
    if existing and existing != "unclassified":
        return existing
    return new


# ------------------------------------------------------------
# HTTP
# ------------------------------------------------------------

def _fetch(search_term: str, page_size: int) -> list[dict]:
    params = urllib.parse.urlencode({
        "query": search_term,
        "format": "json",
        "pageSize": page_size,
        "resultType": "core",
    })
    url = f"{EUROPEPMC_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "FoodSafe-India/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return (data.get("resultList") or {}).get("result", [])
    except urllib.error.HTTPError as e:
        logger.warning("Europe PMC HTTP %s for query=%s", e.code, search_term)
        return []
    except Exception as e:  # noqa: BLE001
        logger.warning("Europe PMC fetch failed for query=%s: %s", search_term, e)
        return []


# ------------------------------------------------------------
# DB helpers
# ------------------------------------------------------------

def _load_contaminants(conn) -> list[tuple[int, str]]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name_canonical FROM contaminants ORDER BY id")
        return [(r[0], r[1]) for r in cur.fetchall()]


def _find_existing(conn, doi: str | None, pmid: str | None):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, study_design, source_apis FROM research_sources
               WHERE (doi IS NOT NULL AND doi = %s)
                  OR (pmid IS NOT NULL AND %s IS NOT NULL AND pmid = %s)
               LIMIT 1""",
            (doi, pmid, pmid),
        )
        return cur.fetchone()


def _enrich_existing(conn, source_id: int, existing_design: str | None, existing_apis: list[str],
                      new_design: str, pmcid: str | None) -> str:
    merged_design = merge_study_design(existing_design, new_design)
    apis = list(existing_apis or [])
    if "europepmc" not in apis:
        apis.append("europepmc")
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE research_sources
               SET study_design = %s, pmcid = COALESCE(pmcid, %s), source_apis = %s
               WHERE id = %s""",
            (merged_design, pmcid, apis, source_id),
        )
    return merged_design


def _insert_new(conn, work: dict, title: str, abstract: str, doi: str, pmid: str | None,
                 pmcid: str | None, study_design: str, fetched_query: str) -> int | None:
    journal = work.get("journalTitle") or (work.get("journalInfo") or {}).get("journal", {}).get("title")
    authors = [a.strip() for a in (work.get("authorString") or "").split(",") if a.strip()]
    landing_url = f"https://europepmc.org/article/{work.get('source', 'MED')}/{work.get('id', '')}"
    is_oa = (work.get("isOpenAccess") or "N") == "Y"

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO research_sources (
                    title, authors, journal, publication_year, doi, pmid, pmcid,
                    abstract, work_type, is_oa, landing_page_url, fetched_query,
                    study_design, source_apis
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (doi) DO NOTHING
                RETURNING id""",
            (
                title[:1000], authors, journal,
                int(work["pubYear"]) if str(work.get("pubYear") or "").isdigit() else None,
                doi, pmid, pmcid, abstract, "article", is_oa, landing_url, fetched_query,
                study_design, ["europepmc"],
            ),
        )
        row = cur.fetchone()
        return row[0] if row else None


def _link(conn, contaminant_id: int, source_id: int, evidence_level: str, health_terms: list[str]) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO contaminant_research_links (
                    contaminant_id, research_source_id, evidence_level, matched_health_terms
                ) VALUES (%s,%s,%s,%s)
                ON CONFLICT (contaminant_id, research_source_id) DO NOTHING
                RETURNING id""",
            (contaminant_id, source_id, evidence_level, health_terms),
        )
        linked = cur.fetchone() is not None
        if not linked and evidence_level == "B":
            # Already linked from an earlier OpenAlex-only pass at 'C' —
            # richer Europe PMC data now shows it's a systematic
            # review/meta-analysis. Upgrade only; never downgrade.
            cur.execute(
                """UPDATE contaminant_research_links SET evidence_level = 'B'
                   WHERE contaminant_id = %s AND research_source_id = %s AND evidence_level = 'C'""",
                (contaminant_id, source_id),
            )
        return linked


# ------------------------------------------------------------
# Main ingest
# ------------------------------------------------------------

def run(limit: int = 5) -> dict:
    """Fetch + cross-dedup + write real scientific-evidence links. Idempotent."""
    conn = pg_connect()
    summary = {
        "fetched": 0, "inserted": 0, "enriched": 0, "linked": 0, "upgraded_to_b": 0,
        "skipped_no_doi": 0, "skipped_no_abstract": 0, "skipped_dupe": 0,
    }
    try:
        contaminants = _load_contaminants(conn)
        for cid, canonical in contaminants:
            search_term = build_search_term(canonical)
            results = _fetch(search_term, page_size=limit)
            summary["fetched"] += len(results)

            for work in results:
                doi = (work.get("doi") or "").strip() or None
                pmid = (work.get("pmid") or "").strip() or None
                title = strip_html(work.get("title"))
                abstract = strip_html(work.get("abstractText"))

                if not doi:
                    summary["skipped_no_doi"] += 1
                    continue
                if not title or not abstract:
                    summary["skipped_no_abstract"] += 1
                    continue

                pub_types = (work.get("pubTypeList") or {}).get("pubType") or []
                study_design = classify_study_design(pub_types)
                pmcid = work.get("pmcid")

                try:
                    existing = _find_existing(conn, doi, pmid)
                    if existing:
                        source_id, existing_design, existing_apis = existing
                        merged_design = _enrich_existing(
                            conn, source_id, existing_design, existing_apis, study_design, pmcid
                        )
                        summary["enriched"] += 1
                        evidence_level = "B" if should_upgrade_to_b(merged_design) else "C"
                    else:
                        source_id = _insert_new(
                            conn, work, title, abstract, doi, pmid, pmcid, study_design, search_term
                        )
                        if source_id is None:
                            summary["skipped_dupe"] += 1
                            conn.rollback()
                            continue
                        summary["inserted"] += 1
                        evidence_level = "B" if should_upgrade_to_b(study_design) else "C"

                    mesh_headings = (work.get("meshHeadingList") or {}).get("meshHeading") or []
                    health_terms = extract_health_terms(
                        [{"display_name": h.get("descriptorName", "")} for h in mesh_headings]
                    )
                    was_new_link = _link(conn, cid, source_id, evidence_level, health_terms)
                    conn.commit()
                    if was_new_link:
                        summary["linked"] += 1
                    elif evidence_level == "B":
                        summary["upgraded_to_b"] += 1
                    else:
                        summary["skipped_dupe"] += 1
                except psycopg2.Error as e:
                    logger.error("upsert failed for doi=%s: %s", doi, e)
                    conn.rollback()

            time.sleep(REQUEST_DELAY_S)
    finally:
        conn.close()

    return summary


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    parser = argparse.ArgumentParser(description="Ingest real scientific-evidence links from Europe PMC")
    parser.add_argument("--limit", type=int, default=5, help="results per contaminant search term")
    args = parser.parse_args()

    summary = run(limit=args.limit)

    print("\n=== europepmc_evidence INGEST SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
