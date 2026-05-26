"""
FoodSafe India — Stage 3: Deduplication + Stage 4: Confidence Scoring
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

from pipeline.config import (
    CONFIDENCE_BASE,
    CONFIDENCE_MANUAL_VERIFY,
    CONFIDENCE_TIER1_LAB,
    CONFIDENCE_TYPICAL_RANGE,
    CONFIDENCE_LOW_OCR,
    CONFIDENCE_MIN_USABLE,
    OCR_MIN_CONFIDENCE,
    TIER1_LAB_KEYWORDS,
)
from pipeline.stage2_standardise import StandardisedRecord

logger = logging.getLogger(__name__)


# ============================================================
# STAGE 3 — DEDUPLICATION
# ============================================================

@dataclass
class DeduplicatedRecord:
    record: StandardisedRecord
    dedup_hash: str
    is_duplicate: bool
    duplicate_of_hash: Optional[str]


def _build_hash(rec: StandardisedRecord) -> str:
    """
    Hash on: date + lab_raw + commodity + contaminant + value + district
    Cross-source duplicates are flagged, not deleted.
    """
    components = "|".join([
        str(rec.test_date or ""),
        str(rec.lab_raw or ""),
        str(rec.commodity_name or "").lower().strip(),
        str(rec.contaminant_canonical or ""),
        str(round(rec.raw_value_ppb or 0.0, 3)),
        str(rec.district_id or rec.district_name or ""),
    ])
    return hashlib.sha256(components.encode()).hexdigest()


class Deduplicator:
    """
    Within-batch and cross-batch deduplication.

    Within-batch: uses an in-memory set.
    Cross-batch: checks the enforcement_records table for existing hash.
    """

    def __init__(self, db_conn=None):
        self._seen: set[str] = set()
        self._conn = db_conn

    def _hash_exists_in_db(self, h: str) -> bool:
        if not self._conn:
            return False
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM enforcement_records WHERE dedup_hash = %s LIMIT 1",
                    (h,)
                )
                return cur.fetchone() is not None
        except Exception as e:
            logger.error("Dedup DB check failed: %s", e)
            return False

    def process(self, records: list[StandardisedRecord]) -> list[DeduplicatedRecord]:
        out = []
        for rec in records:
            h = _build_hash(rec)

            in_memory_dup = h in self._seen
            in_db_dup     = (not in_memory_dup) and self._hash_exists_in_db(h)

            is_dup = in_memory_dup or in_db_dup
            dup_of = h if is_dup else None

            if not is_dup:
                self._seen.add(h)

            out.append(DeduplicatedRecord(
                record            = rec,
                dedup_hash        = h,
                is_duplicate      = is_dup,
                duplicate_of_hash = dup_of if is_dup else None,
            ))

        n_dups = sum(1 for r in out if r.is_duplicate)
        logger.info("Dedup: %d records, %d duplicates flagged", len(out), n_dups)
        return out


# ============================================================
# TYPICAL RANGE REFERENCE
# Used by Stage 4 to check if a value is plausible
# Extend this dict or move to DB as data grows
# ============================================================

# (contaminant_canonical, commodity_category) → (min_ppb, max_ppb)
# "typical" = what we've seen in real Indian enforcement data
TYPICAL_RANGES: dict[tuple[str, str], tuple[float, float]] = {
    ("aflatoxin_b1",    "grain"):   (0.1,   500.0),
    ("aflatoxin_b1",    "spice"):   (0.5,  1000.0),
    ("aflatoxin_b1",    "produce"): (0.1,   300.0),
    ("aflatoxin_total", "grain"):   (0.5,  2000.0),
    ("lead",            "dairy"):   (1.0,  1000.0),
    ("lead",            "produce"): (1.0,  2000.0),
    ("cadmium",         "grain"):   (1.0,   500.0),
    ("arsenic_inorganic","grain"):  (5.0,  2000.0),
    ("arsenic_inorganic","produce"): (1.0, 1000.0),
    ("pesticide_chlorpyrifos","produce"): (0.5, 500.0),
    ("melamine",        "dairy"):   (100.0, 100000.0),
    ("ochratoxin_a",    "grain"):   (0.1,   500.0),
}


def _is_in_typical_range(
    contaminant: Optional[str],
    commodity_category: Optional[str],
    value_ppb: Optional[float],
) -> bool:
    if not contaminant or value_ppb is None:
        return False

    # Try exact match first, then commodity-agnostic
    for cat in [commodity_category, None]:
        key = (contaminant, cat) if cat else None
        if key and key in TYPICAL_RANGES:
            lo, hi = TYPICAL_RANGES[key]
            return lo <= value_ppb <= hi

    return False


# ============================================================
# STAGE 4 — CONFIDENCE SCORING
# ============================================================

@dataclass
class ScoredRecord:
    record: StandardisedRecord
    dedup_hash: str
    is_duplicate: bool
    confidence_score: float   # 0.0 – 1.0
    confidence_breakdown: dict[str, float]
    is_usable: bool           # confidence >= CONFIDENCE_MIN_USABLE


class ConfidenceScorer:
    """
    Implements scoring from Section 4 of the spec.

    Base: 0.70
    +0.15 manually verified
    +0.10 tier-1 lab (ICAR / NABL)
    +0.05 value in typical range
    -0.10 OCR confidence < 0.80
    """

    def __init__(self, db_conn=None):
        self._conn = db_conn
        # Cache of lab_raw → tier
        self._lab_tier_cache: dict[str, int] = {}

    def _get_lab_tier(self, lab_raw: Optional[str]) -> Optional[int]:
        """Return 1, 2, or 3 (None = unknown)."""
        if not lab_raw:
            return None

        if lab_raw in self._lab_tier_cache:
            return self._lab_tier_cache[lab_raw]

        # Quick keyword check (Tier 1)
        for kw in TIER1_LAB_KEYWORDS:
            if kw.lower() in lab_raw.lower():
                self._lab_tier_cache[lab_raw] = 1
                return 1

        # DB lookup
        if self._conn:
            try:
                with self._conn.cursor() as cur:
                    cur.execute(
                        "SELECT tier FROM labs WHERE name ILIKE %s LIMIT 1",
                        (f"%{lab_raw}%",)
                    )
                    row = cur.fetchone()
                    if row:
                        self._lab_tier_cache[lab_raw] = row[0]
                        return row[0]
            except Exception as e:
                logger.error("Lab tier lookup failed: %s", e)

        self._lab_tier_cache[lab_raw] = None
        return None

    def score(
        self,
        deduped: DeduplicatedRecord,
        commodity_category: Optional[str] = None,
        manually_verified: bool = False,
    ) -> ScoredRecord:

        rec   = deduped.record
        score = CONFIDENCE_BASE
        breakdown: dict[str, float] = {"base": CONFIDENCE_BASE}

        # +0.15 manual verification
        if manually_verified:
            score += CONFIDENCE_MANUAL_VERIFY
            breakdown["manual_verify"] = CONFIDENCE_MANUAL_VERIFY

        # +0.10 tier-1 lab
        lab_tier = self._get_lab_tier(rec.lab_raw)
        if lab_tier == 1:
            score += CONFIDENCE_TIER1_LAB
            breakdown["tier1_lab"] = CONFIDENCE_TIER1_LAB

        # +0.05 value in typical range
        if _is_in_typical_range(rec.contaminant_canonical, commodity_category, rec.raw_value_ppb):
            score += CONFIDENCE_TYPICAL_RANGE
            breakdown["typical_range"] = CONFIDENCE_TYPICAL_RANGE

        # -0.10 low OCR confidence
        if rec.page_ocr_confidence < OCR_MIN_CONFIDENCE:
            score += CONFIDENCE_LOW_OCR   # negative
            breakdown["low_ocr"] = CONFIDENCE_LOW_OCR

        # Clamp to [0, 1]
        score = round(max(0.0, min(1.0, score)), 3)

        is_usable = score >= CONFIDENCE_MIN_USABLE

        if not is_usable:
            logger.info(
                "Record from %s scored %.3f — below usable threshold",
                rec.source_url, score
            )

        return ScoredRecord(
            record              = rec,
            dedup_hash          = deduped.dedup_hash,
            is_duplicate        = deduped.is_duplicate,
            confidence_score    = score,
            confidence_breakdown = breakdown,
            is_usable           = is_usable,
        )


# ============================================================
# COMMODITY CATEGORY RESOLVER
# (needed by ConfidenceScorer to check typical range)
# ============================================================

class CommodityCategoryResolver:
    """Map commodity_name → category using DB or heuristic."""

    HEURISTIC: dict[str, str] = {
        "rice":     "grain",  "wheat":    "grain",  "maize":    "grain",
        "groundnut":"produce","peanut":   "produce", "onion":   "produce",
        "milk":     "dairy",  "paneer":   "dairy",   "ghee":    "dairy",
        "chilli":   "spice",  "turmeric": "spice",   "cumin":   "spice",
        "mustard oil": "oil", "sunflower oil": "oil",
        "chicken":  "meat",   "mutton":   "meat",    "fish":    "seafood",
    }

    def __init__(self, db_conn=None):
        self._cache: dict[str, Optional[str]] = {}
        self._conn = db_conn

    def resolve(self, commodity_name: Optional[str]) -> Optional[str]:
        if not commodity_name:
            return None

        key = commodity_name.lower().strip()

        if key in self._cache:
            return self._cache[key]

        # Heuristic
        for kw, cat in self.HEURISTIC.items():
            if kw in key:
                self._cache[key] = cat
                return cat

        # DB
        if self._conn:
            try:
                with self._conn.cursor() as cur:
                    cur.execute(
                        "SELECT category FROM commodities WHERE name_canonical ILIKE %s "
                        "OR %s = ANY(aliases) LIMIT 1",
                        (f"%{key}%", commodity_name)
                    )
                    row = cur.fetchone()
                    if row:
                        self._cache[key] = row[0]
                        return row[0]
            except Exception as e:
                logger.error("Commodity category resolve failed: %s", e)

        self._cache[key] = None
        return None


# ============================================================
# COMBINED STAGE 3 + 4 RUNNER
# ============================================================

def dedup_and_score(
    records: list[StandardisedRecord],
    db_conn=None,
) -> list[ScoredRecord]:
    """
    Top-level function called by the Airflow DAG.
    Returns all records with scores; caller decides what to write.
    """
    deduplicator = Deduplicator(db_conn)
    scorer       = ConfidenceScorer(db_conn)
    cat_resolver = CommodityCategoryResolver(db_conn)

    deduped  = deduplicator.process(records)
    scored: list[ScoredRecord] = []

    for d in deduped:
        cat = cat_resolver.resolve(d.record.commodity_name)
        s   = scorer.score(d, commodity_category=cat)
        scored.append(s)

    usable    = sum(1 for s in scored if s.is_usable and not s.is_duplicate)
    duplicate = sum(1 for s in scored if s.is_duplicate)
    low_conf  = sum(1 for s in scored if not s.is_usable and not s.is_duplicate)

    logger.info(
        "Stage 3+4 complete: %d usable, %d duplicates, %d low-confidence",
        usable, duplicate, low_conf
    )

    return scored
