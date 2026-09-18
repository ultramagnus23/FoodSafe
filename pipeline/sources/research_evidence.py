"""
FoodSafe India — Scientific Evidence Ingester (OpenAlex)

Real, no-API-key data source: the OpenAlex works API
(https://api.openalex.org/works) — free, public, structured JSON metadata
for ~250M scholarly works, including real DOIs, titles, authors, journals,
abstracts, and OpenAlex's own concept tags.

What this connector does NOT do: it does not claim a contaminant was found
in any Indian sample. It only records that peer-reviewed literature exists
associating a contaminant already in `contaminants` with a disease/health
outcome somewhere. That is a citation layer, not a local measurement — see
docs/RESEARCH_EVIDENCE_INGESTION.md.

Evidence level is restricted to two values, both rule-based off fields
OpenAlex itself reports (never an AI judgment call):
  B — OpenAlex type == 'review'
  C — anything else with a DOI and a reconstructable abstract
A record without a DOI, without a title, or without an abstract is
skipped, not inserted with placeholder values.

Run:
  python -m pipeline.sources.research_evidence --limit 5
Idempotent: dedups research_sources on doi, and
contaminant_research_links on (contaminant_id, research_source_id).
"""

from __future__ import annotations

import argparse
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

import psycopg2

from pipeline.config import pg_connect

logger = logging.getLogger("foodsafe.research_evidence")

OPENALEX_URL = "https://api.openalex.org/works"
REQUEST_DELAY_S = 1.0


def build_search_term(canonical_contaminant_name: str) -> str:
    """Shared with pipeline/sources/europepmc_evidence.py so both connectors
    search for the same thing per contaminant."""
    return f"{canonical_contaminant_name.replace('_', ' ')} health disease toxicity"


# OpenAlex concept display names that count as a "health outcome" match.
# Deliberately a small, literal keyword filter over OpenAlex's own tags —
# not an invented taxonomy.
HEALTH_TERM_KEYWORDS = (
    "cancer", "carcinoma", "disease", "toxicity", "syndrome", "poisoning",
    "hepato", "nephro", "neuro", "immune", "mortality", "tumor", "tumour",
    "lesion", "genotoxic", "mutagen", "teratogen",
)


# ------------------------------------------------------------
# HTTP
# ------------------------------------------------------------

def _fetch(search_term: str, per_page: int) -> list[dict]:
    # per_page can legally go up to OpenAlex's documented max of 200; a
    # transient 429 (shared "polite pool" rate limit, not a per-caller quota)
    # is worth one retry rather than silently dropping an entire
    # contaminant's results for the run.
    params = urllib.parse.urlencode({
        "search": search_term,
        "filter": "has_doi:true",
        "per-page": per_page,
    })
    url = f"{OPENALEX_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "FoodSafe-India/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            return data.get("results", [])
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                logger.warning("OpenAlex 429 for search=%s, retrying in %ss", search_term, 5 * (attempt + 1))
                time.sleep(5 * (attempt + 1))
                continue
            logger.warning("OpenAlex HTTP %s for search=%s", e.code, search_term)
            return []
        except Exception as e:  # noqa: BLE001
            logger.warning("OpenAlex fetch failed for search=%s: %s", search_term, e)
            return []
    return []


# ------------------------------------------------------------
# Pure parsing helpers (unit-testable without network)
# ------------------------------------------------------------

def reconstruct_abstract(inverted_index: dict | None) -> str:
    """OpenAlex stores abstracts as {word: [positions]} to dodge publisher
    copyright on the assembled text. Rebuild the plain-text abstract, or
    return '' if none is available."""
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort(key=lambda p: p[0])
    return " ".join(word for _, word in positions)


def classify_evidence_level(work_type: str | None) -> str:
    """Rule-based, off a field OpenAlex reports directly — see module
    docstring for why only B/C are ever produced here."""
    return "B" if (work_type or "").lower() == "review" else "C"


def extract_health_terms(concepts: list[dict] | None) -> list[str]:
    if not concepts:
        return []
    matched = []
    for c in concepts:
        name = c.get("display_name") or ""
        if any(kw in name.lower() for kw in HEALTH_TERM_KEYWORDS):
            matched.append(name)
    return matched[:5]


def _clean_doi(raw: str | None) -> str | None:
    if not raw:
        return None
    return raw.replace("https://doi.org/", "").strip() or None


def _clean_pmid(ids: dict) -> str | None:
    raw = (ids or {}).get("pmid")
    if not raw:
        return None
    return raw.rstrip("/").rsplit("/", 1)[-1]


# ------------------------------------------------------------
# DB helpers
# ------------------------------------------------------------

def _load_contaminants(conn) -> list[tuple[int, str]]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name_canonical FROM contaminants ORDER BY id")
        return [(r[0], r[1]) for r in cur.fetchall()]


def _upsert_source(conn, work: dict, fetched_query: str) -> tuple[int | None, bool]:
    """Insert a research_sources row if new. Returns (id, was_new)."""
    title = (work.get("title") or "").strip()
    doi = _clean_doi(work.get("doi"))
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    landing_url = (
        (work.get("primary_location") or {}).get("landing_page_url")
        or work.get("id")
    )
    if not title or not doi or not abstract or not landing_url:
        return None, False

    openalex_id = work.get("id")
    journal = ((work.get("primary_location") or {}).get("source") or {}).get("display_name")
    authors = [
        a["author"]["display_name"]
        for a in (work.get("authorships") or [])
        if a.get("author", {}).get("display_name")
    ]
    open_access = work.get("open_access") or {}

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM research_sources WHERE doi = %s", (doi,))
        row = cur.fetchone()
        if row:
            return row[0], False

        work_type = work.get("type")
        # OpenAlex's 'type' only distinguishes review vs. not — a coarser
        # study_design than europepmc_evidence.py can report from real
        # pubType tags, but still a real, source-reported value, not a guess.
        study_design = "review" if (work_type or "").lower() == "review" else "unclassified"

        cur.execute(
            """INSERT INTO research_sources (
                    title, authors, journal, publication_year, doi, openalex_id,
                    pmid, abstract, work_type, oa_status, is_oa, landing_page_url,
                    fetched_query, study_design, source_apis
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (doi) DO NOTHING
                RETURNING id""",
            (
                title[:1000], authors, journal, work.get("publication_year"),
                doi, openalex_id, _clean_pmid(work.get("ids") or {}), abstract,
                work_type, open_access.get("oa_status"),
                open_access.get("is_oa"), landing_url, fetched_query,
                study_design, ["openalex"],
            ),
        )
        row = cur.fetchone()
        if row:
            return row[0], True

        cur.execute("SELECT id FROM research_sources WHERE doi = %s", (doi,))
        row = cur.fetchone()
        return (row[0], False) if row else (None, False)


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
        return cur.fetchone() is not None


# ------------------------------------------------------------
# Main ingest
# ------------------------------------------------------------

def run(limit: int = 5) -> dict:
    """Fetch + map + write real scientific-evidence links. Idempotent."""
    conn = pg_connect()
    # NB: pipeline.run_and_log._rows_ingested() reads "inserted" first (falling
    # back to "fetched"/"scraped"), so "inserted" here is new research_sources
    # rows this run — the meaningful "did anything real land" count, not the
    # raw number of API results seen.
    summary = {
        "fetched": 0, "inserted": 0, "linked": 0,
        "skipped_no_doi": 0, "skipped_no_abstract": 0, "skipped_dupe": 0,
    }
    try:
        contaminants = _load_contaminants(conn)
        for cid, canonical in contaminants:
            search_term = build_search_term(canonical)
            results = _fetch(search_term, per_page=limit)
            summary["fetched"] += len(results)

            for work in results:
                doi = _clean_doi(work.get("doi"))
                abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
                if not doi:
                    summary["skipped_no_doi"] += 1
                    continue
                if not abstract:
                    summary["skipped_no_abstract"] += 1
                    continue

                try:
                    source_id, was_new = _upsert_source(conn, work, search_term)
                    if source_id is None:
                        summary["skipped_no_abstract"] += 1
                        conn.rollback()
                        continue
                    if was_new:
                        summary["inserted"] += 1

                    evidence_level = classify_evidence_level(work.get("type"))
                    health_terms = extract_health_terms(work.get("concepts"))
                    linked = _link(conn, cid, source_id, evidence_level, health_terms)
                    conn.commit()
                    if linked:
                        summary["linked"] += 1
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
    parser = argparse.ArgumentParser(description="Ingest real scientific-evidence links from OpenAlex")
    parser.add_argument("--limit", type=int, default=5, help="results per contaminant search term")
    args = parser.parse_args()

    summary = run(limit=args.limit)

    print("\n=== research_evidence INGEST SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
