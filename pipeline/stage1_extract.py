"""
FoodSafe India — Stage 1: Extraction
PDF → OCR → NER → structured dict per enforcement record

Handles:
  - Tesseract OCR (primary)
  - AWS Textract (fallback for low-confidence pages)
  - spaCy NER for entity extraction
  - RSS / JSON feeds parsed directly
"""

from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import boto3
import pytesseract
import spacy
from PIL import Image
from pdf2image import convert_from_path, convert_from_bytes

from pipeline.config import (
    OCR_MIN_CONFIDENCE,
    TEXTRACT_FALLBACK,
    TEXTRACT_REGION,
    TESSERACT_CMD,
)

logger = logging.getLogger(__name__)

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class RawField:
    """A single extracted field with its OCR confidence."""
    value: str
    confidence: float   # 0.0 – 1.0
    source: str         # "tesseract" | "textract" | "json" | "rss"

@dataclass
class RawRecord:
    """
    Output of Stage 1 for a single enforcement record.
    All values are raw strings — normalisation happens in Stage 2.
    """
    source_url:     str
    source_type:    str             # "fssai" | "usfda" | "efsa" | ...
    pdf_page:       Optional[int]   = None
    product_name:   Optional[RawField] = None
    brand:          Optional[RawField] = None
    manufacturer:   Optional[RawField] = None
    contaminant:    Optional[RawField] = None
    value:          Optional[RawField] = None
    unit:           Optional[RawField] = None
    date:           Optional[RawField] = None
    state:          Optional[RawField] = None
    district:       Optional[RawField] = None
    lab_id:         Optional[RawField] = None
    pass_fail:      Optional[RawField] = None   # raw "pass"/"fail"/"P"/"F" string
    page_ocr_confidence: float = 1.0            # mean word confidence for the page
    extraction_errors: list[str] = field(default_factory=list)


# ============================================================
# OCR LAYER
# ============================================================

class TesseractOCR:
    """Extract text + per-word confidence from a PIL image."""

    def __call__(self, image: Image.Image) -> tuple[str, float]:
        """Returns (full_text, mean_confidence 0-1)."""
        data = pytesseract.image_to_data(
            image,
            lang="eng+hin",
            output_type=pytesseract.Output.DICT,
            config="--psm 6",   # assume uniform block of text
        )
        confidences = [
            c / 100.0
            for c in data["conf"]
            if isinstance(c, (int, float)) and c >= 0
        ]
        mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
        text = pytesseract.image_to_string(image, lang="eng+hin", config="--psm 6")
        return text, mean_conf


class TextractOCR:
    """AWS Textract fallback for scanned / low-confidence pages."""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client("textract", region_name=TEXTRACT_REGION)
        return self._client

    def __call__(self, image: Image.Image) -> tuple[str, float]:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        buf.seek(0)
        response = self.client.detect_document_text(Document={"Bytes": buf.read()})

        lines, confidences = [], []
        for block in response.get("Blocks", []):
            if block["BlockType"] == "LINE":
                lines.append(block.get("Text", ""))
                confidences.append(block.get("Confidence", 0) / 100.0)

        text = "\n".join(lines)
        mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return text, mean_conf


# ============================================================
# NER MODEL
# ============================================================

class FSSAINERExtractor:
    """
    spaCy-based NER for FSSAI enforcement PDFs.

    In production: fine-tune a spaCy model on annotated FSSAI PDFs.
    This version uses rule-based patterns as a bootstrap.
    Replace nlp = spacy.load("en_core_web_sm") with your trained model.
    """

    # Contaminant keyword patterns
    CONTAMINANT_PATTERN = re.compile(
        r"(?:aflatoxin[\s\-]?[bBgG]?[12]?|aflatoxin total|lead|cadmium|arsenic|"
        r"chlorpyrifos|melamine|ochratoxin[\s\-]?[aA]|pesticide|heavy metal|"
        r"coliform|salmonella|e\.?\s*coli)",
        re.IGNORECASE,
    )

    # Value + unit patterns
    VALUE_UNIT_PATTERN = re.compile(
        r"(\d+(?:\.\d+)?)\s*"
        r"(ppb|ppm|µg/kg|ug/kg|μg/kg|mg/kg|ng/g|ng/kg|ppt|%|µg/l|ug/l)",
        re.IGNORECASE,
    )

    # Pass/Fail patterns
    PASS_FAIL_PATTERN = re.compile(
        r"\b(pass(?:ed)?|fail(?:ed)?|satisfactory|unsatisfactory|"
        r"conforming|non[\s\-]?conforming|not\s+safe|safe)\b",
        re.IGNORECASE,
    )

    # Date patterns (DD/MM/YYYY, DD-MM-YYYY, Month YYYY, YYYY-MM-DD)
    DATE_PATTERN = re.compile(
        r"\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\d{4}[\/\-]\d{2}[\/\-]\d{2}|"
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,]+\d{4})\b",
        re.IGNORECASE,
    )

    # Indian states (abbreviated regex — config.py has full alias map)
    STATE_PATTERN = re.compile(
        r"\b(Maharashtra|Delhi|Uttar Pradesh|Karnataka|Tamil Nadu|West Bengal|"
        r"Gujarat|Rajasthan|Madhya Pradesh|Punjab|Haryana|Bihar|Odisha|Kerala|"
        r"Telangana|Andhra Pradesh|Assam|Jharkhand|Chhattisgarh|Uttarakhand|"
        r"Himachal Pradesh|Goa|Jammu and Kashmir)\b",
        re.IGNORECASE,
    )

    # Lab ID pattern: alphanumeric codes like "FSSAI/LAB/2023/001234"
    LAB_ID_PATTERN = re.compile(
        r"\b(?:FSSAI|NABL|ICAR|LAB)[\/\-]?[A-Z0-9]{4,20}\b",
        re.IGNORECASE,
    )

    def __init__(self):
        try:
            self.nlp = spacy.load("en_foodsafe_ner")   # trained model
            logger.info("Loaded trained FoodSafe NER model")
        except OSError:
            self.nlp = spacy.load("en_core_web_sm")    # fallback
            logger.warning("Trained NER model not found — using spaCy base + rules")

    def extract(self, text: str, ocr_confidence: float, source: str = "tesseract") -> dict[str, Optional[RawField]]:
        """Run NER + regex on text, return dict of RawField values."""
        doc = self.nlp(text)

        result: dict[str, Optional[RawField]] = {
            "product_name": None,
            "brand":        None,
            "manufacturer": None,
            "contaminant":  None,
            "value":        None,
            "unit":         None,
            "date":         None,
            "state":        None,
            "district":     None,
            "lab_id":       None,
            "pass_fail":    None,
        }

        def rf(val: str) -> RawField:
            return RawField(value=val.strip(), confidence=ocr_confidence, source=source)

        # ---- spaCy entities ----
        for ent in doc.ents:
            if ent.label_ == "PRODUCT" and result["product_name"] is None:
                result["product_name"] = rf(ent.text)
            elif ent.label_ == "ORG" and result["brand"] is None:
                result["brand"] = rf(ent.text)
            elif ent.label_ == "GPE":
                # spaCy geopolitical entity — try state first then district
                if result["state"] is None:
                    result["state"] = rf(ent.text)
                elif result["district"] is None:
                    result["district"] = rf(ent.text)
            elif ent.label_ == "DATE" and result["date"] is None:
                result["date"] = rf(ent.text)

        # ---- Rule overrides (more precise for this domain) ----

        m = self.CONTAMINANT_PATTERN.search(text)
        if m:
            result["contaminant"] = rf(m.group())

        m = self.VALUE_UNIT_PATTERN.search(text)
        if m:
            result["value"] = rf(m.group(1))
            result["unit"]  = rf(m.group(2))

        m = self.DATE_PATTERN.search(text)
        if m and result["date"] is None:
            result["date"] = rf(m.group())

        m = self.STATE_PATTERN.search(text)
        if m:
            result["state"] = rf(m.group())

        m = self.LAB_ID_PATTERN.search(text)
        if m:
            result["lab_id"] = rf(m.group())

        m = self.PASS_FAIL_PATTERN.search(text)
        if m:
            result["pass_fail"] = rf(m.group())

        return result


# ============================================================
# TABLE EXTRACTOR
# ============================================================

class TableExtractor:
    """
    FSSAI PDFs are often tables. Extract rows directly using
    pdfplumber before falling back to free-text NER.
    """

    def extract_tables(self, pdf_path: Path) -> list[list[list[str | None]]]:
        """Returns list of tables, each a list of rows, each a list of cells."""
        try:
            import pdfplumber
            tables = []
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    page_tables = page.extract_tables()
                    if page_tables:
                        tables.extend(page_tables)
            return tables
        except ImportError:
            logger.warning("pdfplumber not installed — table extraction skipped")
            return []
        except Exception as e:
            logger.error("Table extraction failed: %s", e)
            return []

    def rows_to_records(
        self,
        tables: list[list[list[str | None]]],
        source_url: str,
        source_type: str,
    ) -> list[RawRecord]:
        """
        Best-effort conversion of table rows to RawRecord.
        Assumes first row is header. Column mapping is heuristic.
        """
        records = []
        for table in tables:
            if not table or len(table) < 2:
                continue

            header = [str(h).lower().strip() if h else "" for h in table[0]]

            def find_col(*keywords: str) -> Optional[int]:
                for kw in keywords:
                    for i, h in enumerate(header):
                        if kw in h:
                            return i
                return None

            col_product     = find_col("product", "commodity", "food article")
            col_brand       = find_col("brand", "manufacturer", "company")
            col_contaminant = find_col("contaminant", "parameter", "analyte", "test")
            col_value       = find_col("result", "value", "found", "detected")
            col_unit        = find_col("unit")
            col_limit       = find_col("limit", "standard", "permissible")
            col_passfail    = find_col("result", "status", "pass", "fail", "compliant")
            col_date        = find_col("date", "tested on", "sample date")
            col_state       = find_col("state")
            col_district    = find_col("district")
            col_lab         = find_col("lab", "laboratory")

            def cell(row: list, idx: Optional[int]) -> Optional[str]:
                if idx is None or idx >= len(row):
                    return None
                val = row[idx]
                return str(val).strip() if val else None

            for row in table[1:]:
                if all(c is None or str(c).strip() == "" for c in row):
                    continue   # skip empty rows

                def rf(col_idx: Optional[int]) -> Optional[RawField]:
                    v = cell(row, col_idx)
                    return RawField(value=v, confidence=1.0, source="pdfplumber") if v else None

                rec = RawRecord(
                    source_url   = source_url,
                    source_type  = source_type,
                    product_name = rf(col_product),
                    brand        = rf(col_brand),
                    contaminant  = rf(col_contaminant),
                    value        = rf(col_value),
                    unit         = rf(col_unit),
                    date         = rf(col_date),
                    state        = rf(col_state),
                    district     = rf(col_district),
                    lab_id       = rf(col_lab),
                    pass_fail    = rf(col_passfail),
                    page_ocr_confidence = 1.0,
                )
                records.append(rec)

        return records


# ============================================================
# PDF EXTRACTOR — MAIN
# ============================================================

class PDFExtractor:
    """
    Orchestrates: PDF → pages → OCR → NER → list[RawRecord]

    Strategy:
    1. Try pdfplumber table extraction first (structured FSSAI reports)
    2. For pages with no table, fall back to Tesseract OCR + NER
    3. If Tesseract confidence < OCR_MIN_CONFIDENCE, retry with Textract
    """

    def __init__(self):
        self.tesseract = TesseractOCR()
        self.textract  = TextractOCR() if TEXTRACT_FALLBACK else None
        self.ner       = FSSAINERExtractor()
        self.table_ext = TableExtractor()

    def extract_pdf(
        self,
        pdf_path: Path,
        source_url: str,
        source_type: str,
        dpi: int = 300,
    ) -> list[RawRecord]:
        pdf_path = Path(pdf_path)
        logger.info("Extracting PDF: %s", pdf_path.name)

        # --- Attempt table extraction first ---
        tables = self.table_ext.extract_tables(pdf_path)
        if tables:
            table_records = self.table_ext.rows_to_records(tables, source_url, source_type)
            if table_records:
                logger.info("Table extraction yielded %d records", len(table_records))
                return table_records

        # --- Fall back to page-by-page OCR ---
        records: list[RawRecord] = []
        try:
            images = convert_from_path(pdf_path, dpi=dpi)
        except Exception as e:
            logger.error("pdf2image conversion failed: %s", e)
            return []

        for page_num, image in enumerate(images, start=1):
            logger.debug("OCR page %d/%d", page_num, len(images))

            text, conf = self.tesseract(image)

            if conf < OCR_MIN_CONFIDENCE and self.textract:
                logger.debug("Low Tesseract confidence (%.2f) on page %d — using Textract", conf, page_num)
                text, conf = self.textract(image)

            if not text.strip():
                logger.debug("No text found on page %d", page_num)
                continue

            fields = self.ner.extract(text, ocr_confidence=conf, source="tesseract")

            # A page must have at least contaminant + value to be a record
            if fields["contaminant"] is None and fields["value"] is None:
                continue

            rec = RawRecord(
                source_url          = source_url,
                source_type         = source_type,
                pdf_page            = page_num,
                page_ocr_confidence = conf,
                **{k: v for k, v in fields.items()},
            )
            records.append(rec)

        logger.info("Extracted %d records from %s", len(records), pdf_path.name)
        return records


# ============================================================
# RSS / JSON PARSERS
# ============================================================

class USDFARSSParser:
    """Parse USFDA Import Alert RSS feed for Indian exporters."""

    def parse(self, rss_text: str, source_url: str) -> list[RawRecord]:
        import xml.etree.ElementTree as ET
        records = []
        try:
            root = ET.fromstring(rss_text)
        except ET.ParseError as e:
            logger.error("RSS parse error: %s", e)
            return []

        for item in root.findall(".//item"):
            def tag(name: str) -> Optional[str]:
                el = item.find(name)
                return el.text.strip() if el is not None and el.text else None

            title       = tag("title") or ""
            description = tag("description") or ""
            pub_date    = tag("pubDate")
            link        = tag("link") or source_url

            # Extract product from title: "Import Alert - Groundnut - Aflatoxin - India"
            parts = [p.strip() for p in title.split("-")]

            def rf(val: Optional[str], src: str = "rss") -> Optional[RawField]:
                return RawField(value=val, confidence=1.0, source=src) if val else None

            contaminant_text = parts[2] if len(parts) > 2 else None
            product_text     = parts[1] if len(parts) > 1 else None

            rec = RawRecord(
                source_url   = link,
                source_type  = "usfda",
                product_name = rf(product_text),
                contaminant  = rf(contaminant_text),
                date         = rf(pub_date),
                pass_fail    = RawField(value="fail", confidence=1.0, source="rss"),
            )
            records.append(rec)

        return records


class AGMARKNETParser:
    """Parse AGMARKNET JSON commodity quality data."""

    def parse(self, data: dict | list, source_url: str) -> list[RawRecord]:
        records = []
        items = data if isinstance(data, list) else data.get("records", [])

        for item in items:
            def get(key: str) -> Optional[str]:
                val = item.get(key)
                return str(val).strip() if val else None

            def rf(key: str, src: str = "json") -> Optional[RawField]:
                v = get(key)
                return RawField(value=v, confidence=1.0, source=src) if v else None

            rec = RawRecord(
                source_url   = source_url,
                source_type  = "agmarknet",
                product_name = rf("commodity") or rf("Commodity"),
                date         = rf("arrivals_date") or rf("date"),
                state        = rf("state") or rf("State"),
                district     = rf("district") or rf("District"),
                value        = rf("min_price") or rf("modal_price"),
            )
            records.append(rec)

        return records


# ============================================================
# PUBLIC INTERFACE
# ============================================================

def extract_pdf(pdf_path: Path, source_url: str, source_type: str) -> list[RawRecord]:
    """Top-level function called by the Airflow DAG."""
    extractor = PDFExtractor()
    return extractor.extract_pdf(pdf_path, source_url, source_type)


def extract_rss_usfda(rss_text: str, source_url: str) -> list[RawRecord]:
    return USDFARSSParser().parse(rss_text, source_url)


def extract_json_agmarknet(data: dict | list, source_url: str) -> list[RawRecord]:
    return AGMARKNETParser().parse(data, source_url)
