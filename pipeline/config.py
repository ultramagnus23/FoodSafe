"""
FoodSafe India — Pipeline Configuration
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# Load .env (if present) so DATABASE_URL etc. work for pipeline runners too.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================================
# PATHS
# ============================================================

BASE_DIR   = Path(__file__).parent.parent
RAW_DIR    = BASE_DIR / "raw"          # local dev; prod → S3
PARSED_DIR = BASE_DIR / "parsed"

# ============================================================
# DATABASE
# ============================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://foodsafe_app:password@localhost:5432/foodsafe"
)


def pg_connect():
    """psycopg2 connection from DATABASE_URL, built from parsed components.

    libpq misparses the dotted Supabase pooler username (postgres.<ref>) when
    passed the raw URI, so we parse and pass keyword args. SSL is required for
    Supabase; honour an explicit sslmode=require too.
    """
    import psycopg2
    from urllib.parse import urlparse

    u = urlparse(DATABASE_URL)
    kwargs = dict(
        host=u.hostname,
        port=u.port or 5432,
        dbname=(u.path.lstrip("/") or "postgres"),
        user=u.username,
        password=u.password,
    )
    if "supabase.com" in (u.hostname or "") or "sslmode=require" in DATABASE_URL:
        kwargs["sslmode"] = "require"
    return psycopg2.connect(**kwargs)


# ============================================================
# AWS / S3
# ============================================================

S3_BUCKET        = os.environ.get("S3_BUCKET", "foodsafe-raw")
S3_REGION        = os.environ.get("AWS_REGION", "ap-south-1")
S3_RETENTION_DAYS = 365 * 7   # 7 years

# ============================================================
# OCR
# ============================================================

TEXTRACT_REGION          = "ap-south-1"
TESSERACT_CMD            = os.environ.get("TESSERACT_CMD", "tesseract")
OCR_MIN_CONFIDENCE       = 0.80   # below this → flag for review
TEXTRACT_FALLBACK        = True    # use Textract if Tesseract confidence low

# ============================================================
# CONFIDENCE SCORING (Section 4)
# ============================================================

CONFIDENCE_BASE          = 0.70
CONFIDENCE_MANUAL_VERIFY = +0.15
CONFIDENCE_TIER1_LAB     = +0.10
CONFIDENCE_TYPICAL_RANGE = +0.05
CONFIDENCE_LOW_OCR       = -0.10
CONFIDENCE_MIN_USABLE    = 0.75   # records below this are not used in models

# ============================================================
# RATE LIMITS
# ============================================================

FSSAI_SCRAPE_DELAY_S  = 2.0    # seconds between requests
AGMARKNET_DELAY_S     = 1.0
RSS_POLL_INTERVAL_MIN = 60

# ============================================================
# NER LABELS
# ============================================================

NER_LABELS = [
    "PRODUCT",
    "BRAND",
    "MANUFACTURER",
    "CONTAMINANT",
    "VALUE",
    "UNIT",
    "DATE",
    "STATE",
    "DISTRICT",
    "LAB_ID",
]

# ============================================================
# CONTAMINANT CANONICAL MAP (bootstrap — real version in DB)
# These are used before DB is available (e.g. first-run tests)
# ============================================================

CONTAMINANT_ALIASES: dict[str, str] = {
    "afb1":               "aflatoxin_b1",
    "aflatoxin b1":       "aflatoxin_b1",
    "aflatoxin-b1":       "aflatoxin_b1",
    "af b1":              "aflatoxin_b1",
    "total aflatoxin":    "aflatoxin_total",
    "aftotal":            "aflatoxin_total",
    "lead":               "lead",
    "pb":                 "lead",
    "lead (pb)":          "lead",
    "cadmium":            "cadmium",
    "cd":                 "cadmium",
    "arsenic":            "arsenic_inorganic",
    "inorganic arsenic":  "arsenic_inorganic",
    "ias":                "arsenic_inorganic",
    "chlorpyrifos":       "pesticide_chlorpyrifos",
    "lorsban":            "pesticide_chlorpyrifos",
    "melamine":           "melamine",
    "ochratoxin a":       "ochratoxin_a",
    "ota":                "ochratoxin_a",
    "ochratoxin-a":       "ochratoxin_a",
}

# ============================================================
# UNIT CONVERSION TO PPB
# ============================================================

UNIT_TO_PPB: dict[str, float] = {
    "ppb":      1.0,
    "µg/kg":    1.0,       # 1 µg/kg = 1 ppb
    "ug/kg":    1.0,
    "μg/kg":    1.0,
    "ppm":      1_000.0,
    "mg/kg":    1_000.0,
    "mg/l":     1_000.0,
    "µg/l":     1.0,
    "ug/l":     1.0,
    "ng/g":     1.0,       # 1 ng/g = 1 ppb
    "ng/kg":    0.001,
    "ppt":      0.001,
    "%":        10_000_000.0,
}

# ============================================================
# GEOGRAPHIC CANONICAL STATES
# ============================================================

STATE_ALIASES: dict[str, str] = {
    "mh":                       "Maharashtra",
    "maharashtra":              "Maharashtra",
    "dl":                       "Delhi",
    "delhi":                    "Delhi",
    "nct of delhi":             "Delhi",
    "up":                       "Uttar Pradesh",
    "uttar pradesh":            "Uttar Pradesh",
    "ka":                       "Karnataka",
    "karnataka":                "Karnataka",
    "tn":                       "Tamil Nadu",
    "tamil nadu":               "Tamil Nadu",
    "tamilnadu":                "Tamil Nadu",
    "wb":                       "West Bengal",
    "west bengal":              "West Bengal",
    "rj":                       "Rajasthan",
    "rajasthan":                "Rajasthan",
    "gj":                       "Gujarat",
    "gujarat":                  "Gujarat",
    "mp":                       "Madhya Pradesh",
    "madhya pradesh":           "Madhya Pradesh",
    "pb":                       "Punjab",
    "punjab":                   "Punjab",
    "hr":                       "Haryana",
    "haryana":                  "Haryana",
    "ap":                       "Andhra Pradesh",
    "andhra pradesh":           "Andhra Pradesh",
    "ts":                       "Telangana",
    "telangana":                "Telangana",
    "br":                       "Bihar",
    "bihar":                    "Bihar",
    "or":                       "Odisha",
    "odisha":                   "Odisha",
    "orissa":                   "Odisha",
    "as":                       "Assam",
    "assam":                    "Assam",
    "jh":                       "Jharkhand",
    "jharkhand":                "Jharkhand",
    "ct":                       "Chhattisgarh",
    "chhattisgarh":             "Chhattisgarh",
    "uk":                       "Uttarakhand",
    "uttarakhand":              "Uttarakhand",
    "hp":                       "Himachal Pradesh",
    "himachal pradesh":         "Himachal Pradesh",
    "jk":                       "Jammu and Kashmir",
    "jammu and kashmir":        "Jammu and Kashmir",
    "jammu & kashmir":          "Jammu and Kashmir",
    "kl":                       "Kerala",
    "kerala":                   "Kerala",
    "ga":                       "Goa",
    "goa":                      "Goa",
    "mn":                       "Manipur",
    "manipur":                  "Manipur",
    "ml":                       "Meghalaya",
    "meghalaya":                "Meghalaya",
    "nl":                       "Nagaland",
    "nagaland":                 "Nagaland",
    "sk":                       "Sikkim",
    "sikkim":                   "Sikkim",
    "tr":                       "Tripura",
    "tripura":                  "Tripura",
    "ar":                       "Arunachal Pradesh",
    "arunachal pradesh":        "Arunachal Pradesh",
    "mz":                       "Mizoram",
    "mizoram":                  "Mizoram",
}

# ============================================================
# TIER-1 LABS (ICAR / NABL accredited)
# Partial list — full list loaded from DB
# ============================================================

TIER1_LAB_KEYWORDS = [
    "ICAR", "NABL", "CFTRI", "NIN", "NIFTEM",
    "IARI", "IVRI", "NDRI", "FSSAI Referral",
    "Central Food Laboratory",
]
