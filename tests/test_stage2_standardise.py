"""
Tests for pipeline/stage2_standardise.py — contaminant/unit/date/geo
standardisation. No DB connection needed: these classes fall back to the
bootstrap dicts in pipeline/config.py when db_conn=None.
"""
from __future__ import annotations

from pipeline.stage1_extract import RawField, RawRecord
from pipeline.stage2_standardise import (
    ContaminantStandardiser,
    DateStandardiser,
    GeoStandardiser,
    Standardiser,
    UnitConverter,
    normalise_pass_fail,
)


def _field(value: str) -> RawField:
    return RawField(value=value, confidence=0.95, source="tesseract")


# ---------------------------------------------------------------- contaminant

def test_contaminant_exact_alias_match():
    std = ContaminantStandardiser()
    canonical, score = std.standardise("AFB1")
    assert canonical == "aflatoxin_b1"
    assert score == 100.0


def test_contaminant_alias_lookup_ignores_case_and_whitespace():
    std = ContaminantStandardiser()
    # No DB loaded, so _all_aliases is empty and fuzzy matching is skipped —
    # only exact (case/whitespace-insensitive) alias lookups succeed.
    canonical, score = std.standardise("  Lead (Pb)  ")
    assert canonical == "lead"
    assert score == 100.0


def test_contaminant_no_match_returns_none():
    std = ContaminantStandardiser()
    canonical, score = std.standardise("some unrecognised chemical")
    assert canonical is None
    assert score == 0.0


def test_contaminant_empty_input():
    std = ContaminantStandardiser()
    canonical, score = std.standardise("")
    assert canonical is None
    assert score == 0.0


# ---------------------------------------------------------------- units

def test_unit_converter_ppm_to_ppb():
    conv = UnitConverter()
    assert conv.convert("2.5", "ppm") == 2500.0


def test_unit_converter_micro_sign_variants():
    conv = UnitConverter()
    assert conv.convert("10", "µg/kg") == 10.0
    assert conv.convert("10", "μg/kg") == 10.0  # different unicode micro sign
    assert conv.convert("10", "ug/kg") == 10.0


def test_unit_converter_handles_commas():
    conv = UnitConverter()
    assert conv.convert("1,250", "ppb") == 1250.0


def test_unit_converter_unknown_unit_returns_none():
    conv = UnitConverter()
    assert conv.convert("5", "furlongs") is None


def test_unit_converter_bad_value_returns_none():
    conv = UnitConverter()
    assert conv.convert("not-a-number", "ppb") is None


# ---------------------------------------------------------------- dates

def test_date_standardiser_iso_format():
    ds = DateStandardiser()
    d, ambiguous = ds.standardise("2024-03-15")
    assert d.isoformat() == "2024-03-15"
    assert ambiguous is False


def test_date_standardiser_flags_ambiguous_dmy():
    ds = DateStandardiser()
    d, ambiguous = ds.standardise("03/04/2024")
    assert d is not None
    assert ambiguous is True  # both 3-Apr and 4-Mar are valid


def test_date_standardiser_unambiguous_day_over_12():
    ds = DateStandardiser()
    d, ambiguous = ds.standardise("25/04/2024")
    assert d.isoformat() == "2024-04-25"
    assert ambiguous is False  # 25 can't be a month, so DD/MM is certain


def test_date_standardiser_unparseable_returns_none():
    ds = DateStandardiser()
    d, ambiguous = ds.standardise("not a date at all")
    assert d is None
    assert ambiguous is False


# ---------------------------------------------------------------- geography

def test_geo_standardiser_state_alias():
    geo = GeoStandardiser()
    assert geo.standardise_state("mh") == "Maharashtra"
    assert geo.standardise_state("Tamil Nadu") == "Tamil Nadu"


def test_geo_standardiser_unknown_state_titlecased():
    geo = GeoStandardiser()
    assert geo.standardise_state("someplace") == "Someplace"


def test_geo_standardiser_district_unresolved_without_db():
    geo = GeoStandardiser()  # no db_conn -> no district map loaded
    district_id, name = geo.resolve_district("Pune", "Maharashtra")
    assert district_id is None
    assert name == "Pune"


# ---------------------------------------------------------------- pass/fail

def test_normalise_pass_fail_variants():
    assert normalise_pass_fail("Satisfactory") is True
    assert normalise_pass_fail("Non-Conforming") is False
    assert normalise_pass_fail("Unsatisfactory") is False
    assert normalise_pass_fail(None) is None
    assert normalise_pass_fail("unclear") is None


# ---------------------------------------------------------------- full pipeline

def test_standardiser_end_to_end_record():
    raw = RawRecord(
        source_url="https://fssai.gov.in/sample.pdf",
        source_type="fssai",
        pdf_page=3,
        product_name=_field("Basmati Rice"),
        brand=_field("Test Brand"),
        contaminant=_field("AFB1"),
        value=_field("2.5"),
        unit=_field("ppm"),
        date=_field("2024-03-15"),
        state=_field("mh"),
        district=_field("Pune"),
        pass_fail=_field("Fail"),
        page_ocr_confidence=0.9,
    )
    std = Standardiser()
    result = std.standardise(raw)

    assert result.contaminant_canonical == "aflatoxin_b1"
    assert result.raw_value_ppb == 2500.0
    assert result.state_canonical == "Maharashtra"
    assert result.pass_fail is False
    assert result.test_date.isoformat() == "2024-03-15"
    assert result.standardisation_errors == []


def test_standardiser_flags_unresolved_contaminant_as_error():
    raw = RawRecord(
        source_url="https://fssai.gov.in/sample.pdf",
        source_type="fssai",
        contaminant=_field("totally unknown substance xyz"),
    )
    std = Standardiser()
    result = std.standardise(raw)

    assert result.contaminant_canonical is None
    assert any("Unresolved contaminant" in e for e in result.standardisation_errors)
