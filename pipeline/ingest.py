"""
FoodSafe India — Pipeline Orchestrator
Wires all 4 stages together + writes usable records to PostgreSQL.

Can be run:
  - Directly: python -m pipeline.ingest --source fssai
  - Via Airflow: import run_pipeline as the callable
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from contextlib import contextmanager
from datetime import date
from typing import Optional

import psycopg2
import psycopg2.extras

from pipeline.config import DATABASE_URL
from pipeline.stage1_extract import extract_pdf, RawRecord
from pipeline.stage2_standardise import standardise_batch, StandardisedRecord
from pipeline.stage3_and_4 import dedup_and_score, ScoredRecord
from pipeline.sources.fssai import run_fssai_scrape, DownloadedFile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("foodsafe.ingest")

# ============================================================
# DB CONNECTION
# ============================================================

@contextmanager
def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# COMMODITY / BRAND RESOLVERS (upsert helpers)
# ============================================================

def upsert_commodity(conn, name: str) -> Optional[int]:
    """Insert if not exists, return id."""
    if not name:
        return None
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO commodities (name_canonical, category)
            VALUES (%s, 'packaged')
            ON CONFLICT (name_canonical) DO NOTHING
            RETURNING id
        """, (name.lower().strip(),))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("SELECT id FROM commodities WHERE name_canonical = %s", (name.lower().strip(),))
        row = cur.fetchone()
        return row[0] if row else None


def upsert_brand(conn, name: str) -> Optional[int]:
    if not name:
        return None
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO brands (name_canonical)
            VALUES (%s)
            ON CONFLICT (name_canonical) DO NOTHING
            RETURNING id
        """, (name.strip(),))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("SELECT id FROM brands WHERE name_canonical = %s", (name.strip(),))
        row = cur.fetchone()
        return row[0] if row else None


def resolve_contaminant_id(conn, canonical: str) -> Optional[int]:
    if not canonical:
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM contaminants WHERE name_canonical = %s", (canonical,))
        row = cur.fetchone()
        return row[0] if row else None


# ============================================================
# DB WRITER
# ============================================================

def write_records(conn, scored: list[ScoredRecord]) -> tuple[int, int]:
    """
    Write scored records to enforcement_records.
    Returns (inserted, skipped).
    All records are written (including duplicates and low-confidence),
    but is_duplicate and confidence_score are stored for downstream filtering.
    """
    inserted = 0
    skipped  = 0

    with conn.cursor() as cur:
        for s in scored:
            rec = s.record

            # Resolve FKs
            commodity_id  = upsert_commodity(conn, rec.commodity_name)
            contaminant_id = resolve_contaminant_id(conn, rec.contaminant_canonical)
            brand_id      = upsert_brand(conn, rec.brand_name)

            if commodity_id is None or contaminant_id is None:
                logger.debug(
                    "Skipping record — missing commodity_id (%s) or contaminant_id (%s)",
                    rec.commodity_name, rec.contaminant_canonical
                )
                skipped += 1
                continue

            try:
                cur.execute("""
                    INSERT INTO enforcement_records (
                        test_date, source_url, source_type, pdf_page,
                        commodity_id, contaminant_id,
                        raw_value_ppb, legal_limit_ppb, pass_fail,
                        state, district_id,
                        brand_id,
                        confidence_score, ocr_confidence,
                        dedup_hash, is_duplicate,
                        etl_version, parsed_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s,
                        %s, %s,
                        %s, %s,
                        %s, NOW()
                    )
                    ON CONFLICT DO NOTHING
                """, (
                    rec.test_date or date.today(),
                    rec.source_url,
                    rec.source_type,
                    rec.pdf_page,
                    commodity_id,
                    contaminant_id,
                    rec.raw_value_ppb,
                    rec.legal_limit_ppb,
                    rec.pass_fail,
                    rec.state_canonical,
                    rec.district_id,
                    brand_id,
                    s.confidence_score,
                    rec.page_ocr_confidence,
                    s.dedup_hash,
                    s.is_duplicate,
                    "1.0.0",
                ))
                if cur.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
            except psycopg2.Error as e:
                logger.error("Insert failed: %s | record: %s / %s", e, rec.commodity_name, rec.contaminant_canonical)
                conn.rollback()
                skipped += 1

    conn.commit()
    return inserted, skipped


# ============================================================
# MAIN PIPELINE
# ============================================================

def run_pipeline(
    source: str = "fssai",
    page_types: list[str] | None = None,
    use_s3: bool = False,
    max_pages: int = 10,
) -> dict:
    """
    Full pipeline run for a given source.

    Returns summary dict with counts.
    """
    logger.info("=== FoodSafe Pipeline START | source=%s ===", source)
    summary = {
        "source":     source,
        "files":      0,
        "raw":        0,
        "standardised": 0,
        "inserted":   0,
        "skipped":    0,
        "low_conf":   0,
        "duplicates": 0,
    }

    with get_db() as conn:

        # ---- Stage 0: Scrape ----
        if source == "fssai":
            downloaded = run_fssai_scrape(
                page_types=page_types,
                use_s3=use_s3,
                db_conn=conn,
                max_pages=max_pages,
            )
        else:
            logger.error("Unknown source: %s", source)
            return summary

        summary["files"] = len(downloaded)
        logger.info("Stage 0 complete: %d files to process", len(downloaded))

        # ---- Stage 1: Extract ----
        all_raw: list[RawRecord] = []
        for downloaded_file in downloaded:
            if not downloaded_file.local_path:
                continue
            try:
                raw_records = extract_pdf(
                    pdf_path    = downloaded_file.local_path,
                    source_url  = downloaded_file.pdf_link.url,
                    source_type = downloaded_file.pdf_link.source_type,
                )
                all_raw.extend(raw_records)
            except Exception as e:
                logger.error("Stage 1 failed for %s: %s", downloaded_file.local_path, e)

        summary["raw"] = len(all_raw)
        logger.info("Stage 1 complete: %d raw records", len(all_raw))

        if not all_raw:
            logger.warning("No raw records extracted — pipeline ending early")
            return summary

        # ---- Stage 2: Standardise ----
        standardised: list[StandardisedRecord] = standardise_batch(all_raw, conn)
        summary["standardised"] = len(standardised)
        logger.info("Stage 2 complete: %d standardised records", len(standardised))

        # ---- Stage 3 + 4: Dedup + Score ----
        scored: list[ScoredRecord] = dedup_and_score(standardised, conn)
        summary["duplicates"] = sum(1 for s in scored if s.is_duplicate)
        summary["low_conf"]   = sum(1 for s in scored if not s.is_usable and not s.is_duplicate)

        # ---- Write to DB ----
        inserted, skipped = write_records(conn, scored)
        summary["inserted"] = inserted
        summary["skipped"]  = skipped

    logger.info(
        "=== Pipeline DONE | files=%d raw=%d standardised=%d inserted=%d skipped=%d ===",
        summary["files"], summary["raw"], summary["standardised"],
        summary["inserted"], summary["skipped"],
    )
    return summary


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FoodSafe India Data Pipeline")
    parser.add_argument("--source",    default="fssai",  help="Data source (fssai)")
    parser.add_argument("--page-types", nargs="*",       help="FSSAI page types to scrape")
    parser.add_argument("--use-s3",    action="store_true", help="Upload raw PDFs to S3")
    parser.add_argument("--max-pages", type=int, default=5, help="Max pagination pages per listing")

    args = parser.parse_args()

    result = run_pipeline(
        source     = args.source,
        page_types = args.page_types,
        use_s3     = args.use_s3,
        max_pages  = args.max_pages,
    )
    print("\n=== SUMMARY ===")
    for k, v in result.items():
        print(f"  {k}: {v}")
