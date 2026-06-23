"""
FoodSafe India — Stage 2: Standardisation
RawRecord → StandardisedRecord

  - Contaminant names → canonical via fuzzy match
  - All values → PPB
  - State/district → Census 2021 canonical
  - Dates → ISO 8601
  - Ambiguous dates flagged for review
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import psycopg2
from rapidfuzz import process, fuzz   # pip install rapidfuzz

from pipeline.config import (
    CONTAMINANT_ALIASES,
    STATE_ALIASES,
    UNIT_TO_PPB,
    DATABASE_URL,
)
from pipeline.stage1_extract import RawRecord

logger = logging.getLogger(__name__)

# ============================================================
# OUTPUT DATA CLASS
# ============================================================

@dataclass
class StandardisedRecord:
    source_url:             str
    source_type:            str
    pdf_page:               Optional[int]

    commodity_name:         Optional[str]   # canonical or best-guess
    brand_name:             Optional[str]
    manufacturer_name:      Optional[str]
    contaminant_canonical:  Optional[str]   # e.g. "aflatoxin_b1"
    contaminant_match_score: float = 0.0   # 0-100 fuzzy match score

    raw_value_ppb:          Optional[float] = None
    legal_limit_ppb:        Optional[float] = None
    pass_fail:              Optional[bool]  = None  # True = passed

    test_date:              Optional[date]  = None
    date_ambiguous:         bool = False    # True = could be MM/DD or DD/MM

    state_canonical:        Optional[str]  = None
    district_id:            Optional[int]  = None   # FK into districts table
    district_name:          Optional[str]  = None
    mandi_id:               Optional[int]  = None

    lab_raw:                Optional[str]  = None
    lab_id:                 Optional[int]  = None   # FK into labs table

    page_ocr_confidence:    float = 1.0
    standardisation_errors: list[str] = field(default_factory=list)


# ============================================================
# CONTAMINANT STANDARDISER
# ============================================================

class ContaminantStandardiser:
    """
    Fuzzy-match raw contaminant strings to canonical names.
    Uses:
    1. Exact alias lookup (config.py CONTAMINANT_ALIASES)
    2. DB aliases[] lookup
    3. Rapidfuzz token_sort_ratio fallback
    """

    FUZZY_THRESHOLD = 80   # minimum acceptable score

    def __init__(self, db_conn=None):
        # Load all canonical names + aliases from DB if available
        self._canonical_to_aliases: dict[str, list[str]] = {}
        self._all_aliases: list[str] = []      # flat list for fuzzy search
        self._alias_to_canonical: dict[str, str] = dict(CONTAMINANT_ALIASES)

        if db_conn:
            self._load_from_db(db_conn)

    def _load_from_db(self, conn):
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT name_canonical, aliases FROM contaminants")
                for canonical, aliases in cur.fetchall():
                    self._canonical_to_aliases[canonical] = aliases or []
                    self._alias_to_canonical[canonical.lower()] = canonical
                    for alias in (aliases or []):
                        self._alias_to_canonical[alias.lower()] = canonical
            self._all_aliases = list(self._alias_to_canonical.keys())
            logger.info("Loaded %d contaminant aliases from DB", len(self._all_aliases))
        except Exception as e:
            logger.error("DB contaminant load failed: %s", e)

    def standardise(self, raw: str) -> tuple[Optional[str], float]:
        """Returns (canonical_name, confidence_score 0-100)."""
        if not raw:
            return None, 0.0

        normalised = raw.strip().lower()

        # Step 1: exact alias lookup
        if normalised in self._alias_to_canonical:
            return self._alias_to_canonical[normalised], 100.0

        # Step 2: fuzzy match against all known aliases
        if self._all_aliases:
            match, score, _ = process.extractOne(
                normalised,
                self._all_aliases,
                scorer=fuzz.token_sort_ratio,
            )
            if score >= self.FUZZY_THRESHOLD:
                return self._alias_to_canonical.get(match, match), float(score)

        # Step 3: no match
        logger.warning("No canonical match for contaminant: %r", raw)
        return None, 0.0


# ============================================================
# UNIT CONVERTER
# ============================================================

class UnitConverter:
    """Convert measured values to PPB (µg/kg)."""

    def convert(self, value_str: str, unit_str: str) -> Optional[float]:
        try:
            value = float(value_str.replace(",", "").strip())
        except (ValueError, AttributeError):
            return None

        unit_clean = unit_str.strip().lower()

        # Handle Unicode micro sign variants
        unit_clean = unit_clean.replace("µ", "u").replace("μ", "u")

        factor = UNIT_TO_PPB.get(unit_clean)
        if factor is None:
            # Try partial match
            for key, fac in UNIT_TO_PPB.items():
                if key in unit_clean or unit_clean in key:
                    factor = fac
                    break

        if factor is None:
            logger.warning("Unknown unit: %r — value not converted", unit_str)
            return None

        return value * factor


# ============================================================
# DATE STANDARDISER
# ============================================================

class DateStandardiser:
    """
    Parse messy date strings to ISO date.
    Flags ambiguous MM/DD vs DD/MM dates.
    """

    # Try these format strings in order
    FORMATS = [
        "%Y-%m-%d",
        "%d/%m/%Y", "%d-%m-%Y",
        "%d/%m/%y", "%d-%m-%y",
        "%d %B %Y", "%d %b %Y",
        "%B %d, %Y", "%b %d, %Y",
        "%m/%Y", "%B %Y",
    ]

    def standardise(self, raw: str) -> tuple[Optional[date], bool]:
        """Returns (iso_date, is_ambiguous)."""
        if not raw:
            return None, False

        raw = raw.strip()

        for fmt in self.FORMATS:
            try:
                dt = datetime.strptime(raw, fmt)
                ambiguous = self._check_ambiguous(raw)
                return dt.date(), ambiguous
            except ValueError:
                continue

        # Last resort: try dateparser library if installed
        try:
            import dateparser
            result = dateparser.parse(raw, settings={"PREFER_DAY_OF_MONTH": "first"})
            if result:
                return result.date(), True   # dateparser → always flag ambiguous
        except ImportError:
            pass

        logger.warning("Failed to parse date: %r", raw)
        return None, False

    @staticmethod
    def _check_ambiguous(raw: str) -> bool:
        """
        A date is ambiguous if it's MM/DD format where
        both interpretations are valid calendar dates.
        e.g. "03/04/2024" could be 3 Apr or 4 Mar.
        """
        m = re.match(r"^(\d{1,2})[\/\-](\d{1,2})[\/\-]", raw)
        if not m:
            return False
        a, b = int(m.group(1)), int(m.group(2))
        # Ambiguous if both could be a valid day or month
        return (1 <= a <= 12) and (1 <= b <= 12) and (a != b)


# ============================================================
# GEOGRAPHIC STANDARDISER
# ============================================================

class GeoStandardiser:
    """
    Normalise state names and resolve districts to Census 2021 IDs.
    """

    FUZZY_THRESHOLD = 75

    def __init__(self, db_conn=None):
        # district_name -> (id, canonical_name, state)
        self._district_map: dict[str, tuple[int, str, str]] = {}
        self._district_names: list[str] = []
        if db_conn:
            self._load_districts(db_conn)

    def _load_districts(self, conn):
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name_canonical, state, alternate_names
                    FROM districts
                """)
                for row in cur.fetchall():
                    did, name, state, alts = row
                    for variant in [name] + (alts or []):
                        key = variant.lower().strip()
                        self._district_map[key] = (did, name, state)
            self._district_names = list(self._district_map.keys())
            logger.info("Loaded %d district name variants from DB", len(self._district_names))
        except Exception as e:
            logger.error("District load failed: %s", e)

    def standardise_state(self, raw: str) -> Optional[str]:
        if not raw:
            return None
        key = raw.strip().lower()
        return STATE_ALIASES.get(key, raw.title())

    def resolve_district(
        self,
        raw_district: str,
        state_canonical: Optional[str],
    ) -> tuple[Optional[int], Optional[str]]:
        """Returns (district_id, district_canonical_name)."""
        if not raw_district:
            return None, None

        key = raw_district.strip().lower()

        # Exact match
        if key in self._district_map:
            did, name, _ = self._district_map[key]
            return did, name

        # Fuzzy match
        if self._district_names:
            match, score, _ = process.extractOne(
                key,
                self._district_names,
                scorer=fuzz.token_sort_ratio,
            )
            if score >= self.FUZZY_THRESHOLD:
                # If we know the state, verify the match is in that state
                did, name, matched_state = self._district_map[match]
                if state_canonical and matched_state != state_canonical:
                    # Wrong state — don't use fuzzy result
                    logger.warning(
                        "Fuzzy district match %r is in %s not %s",
                        name, matched_state, state_canonical
                    )
                    return None, raw_district
                return did, name

        return None, raw_district   # unresolved


# ============================================================
# PASS/FAIL NORMALISER
# ============================================================

def normalise_pass_fail(raw: Optional[str]) -> Optional[bool]:
    """Returns True = passed, False = failed, None = unknown."""
    if not raw:
        return None
    lower = raw.strip().lower()
    if any(w in lower for w in ["pass", "satisfactory", "conforming", "safe", "compliant"]):
        if "not" in lower or "un" in lower or "non" in lower or "fail" in lower:
            return False
        return True
    if any(w in lower for w in ["fail", "unsatisfactory", "non-conforming", "not safe"]):
        return False
    return None


# ============================================================
# LEGAL LIMIT LOOKUP
# ============================================================

class LegalLimitLookup:
    """Lookup FSSAI legal limit for a (contaminant, commodity) pair."""

    def __init__(self, db_conn=None):
        self._cache: dict[str, Optional[float]] = {}
        self._conn = db_conn

    def get(self, contaminant_canonical: str, commodity_name: Optional[str] = None) -> Optional[float]:
        key = f"{contaminant_canonical}:{commodity_name or '*'}"
        if key in self._cache:
            return self._cache[key]

        limit = None
        if self._conn:
            try:
                with self._conn.cursor() as cur:
                    cur.execute(
                        "SELECT legal_limit_ppb_fssai FROM contaminants WHERE name_canonical = %s",
                        (contaminant_canonical,)
                    )
                    row = cur.fetchone()
                    if row:
                        limit = float(row[0]) if row[0] is not None else None
            except Exception as e:
                logger.error("Legal limit lookup failed: %s", e)

        self._cache[key] = limit
        return limit


# ============================================================
# STAGE 2 PIPELINE
# ============================================================

class Standardiser:
    """
    Applies all standardisation steps to a RawRecord,
    producing a StandardisedRecord ready for Stage 3.
    """

    def __init__(self, db_conn=None):
        self.contaminant = ContaminantStandardiser(db_conn)
        self.unit        = UnitConverter()
        self.date        = DateStandardiser()
        self.geo         = GeoStandardiser(db_conn)
        self.legal       = LegalLimitLookup(db_conn)

    def standardise(self, raw: RawRecord) -> StandardisedRecord:
        errors: list[str] = []

        # ---- Contaminant ----
        cont_raw = raw.contaminant.value if raw.contaminant else None
        cont_canonical, cont_score = self.contaminant.standardise(cont_raw or "")
        if cont_raw and not cont_canonical:
            errors.append(f"Unresolved contaminant: {cont_raw!r}")

        # ---- Value in PPB ----
        ppb: Optional[float] = None
        if raw.value and raw.unit:
            ppb = self.unit.convert(raw.value.value, raw.unit.value)
            if ppb is None:
                errors.append(f"Unit conversion failed: {raw.value.value} {raw.unit.value}")

        # ---- Legal limit ----
        legal_limit: Optional[float] = None
        if cont_canonical:
            legal_limit = self.legal.get(cont_canonical)

        # ---- Pass/Fail (infer from value vs limit if not stated) ----
        pf = normalise_pass_fail(raw.pass_fail.value if raw.pass_fail else None)
        if pf is None and ppb is not None and legal_limit is not None:
            pf = ppb <= legal_limit

        # ---- Date ----
        test_date, date_ambiguous = self.date.standardise(
            raw.date.value if raw.date else ""
        )
        if raw.date and not test_date:
            errors.append(f"Could not parse date: {raw.date.value!r}")

        # ---- Geography ----
        state_canonical = self.geo.standardise_state(
            raw.state.value if raw.state else None
        )
        district_id, district_name = self.geo.resolve_district(
            raw.district.value if raw.district else None,
            state_canonical,
        )

        return StandardisedRecord(
            source_url              = raw.source_url,
            source_type             = raw.source_type,
            pdf_page                = raw.pdf_page,
            commodity_name          = raw.product_name.value if raw.product_name else None,
            brand_name              = raw.brand.value if raw.brand else None,
            manufacturer_name       = raw.manufacturer.value if raw.manufacturer else None,
            contaminant_canonical   = cont_canonical,
            contaminant_match_score = cont_score,
            raw_value_ppb           = ppb,
            legal_limit_ppb         = legal_limit,
            pass_fail               = pf,
            test_date               = test_date,
            date_ambiguous          = date_ambiguous,
            state_canonical         = state_canonical,
            district_id             = district_id,
            district_name           = district_name,
            lab_raw                 = raw.lab_id.value if raw.lab_id else None,
            page_ocr_confidence     = raw.page_ocr_confidence,
            standardisation_errors  = errors,
        )


def standardise_batch(
    records: list[RawRecord],
    db_conn=None,
) -> list[StandardisedRecord]:
    """Top-level function for Airflow task."""
    std = Standardiser(db_conn)
    results = []
    for rec in records:
        try:
            results.append(std.standardise(rec))
        except Exception as e:
            logger.error("Standardisation error on record from %s: %s", rec.source_url, e)
    return results
