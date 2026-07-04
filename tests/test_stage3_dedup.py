"""
Tests for pipeline/stage3_and_4.py — deduplication and confidence scoring.
No DB connection needed: Deduplicator/ConfidenceScorer fall back to
in-memory/heuristic behaviour when db_conn=None.
"""
from __future__ import annotations

from datetime import date

from pipeline.stage2_standardise import StandardisedRecord
from pipeline.stage3_and_4 import (
    ConfidenceScorer,
    Deduplicator,
    _build_hash,
    _is_in_typical_range,
    dedup_and_score,
)


def _record(**overrides) -> StandardisedRecord:
    defaults = dict(
        source_url="https://fssai.gov.in/sample.pdf",
        source_type="fssai",
        pdf_page=1,
        commodity_name="Rice",
        brand_name="Test Brand",
        manufacturer_name=None,
        contaminant_canonical="aflatoxin_b1",
        contaminant_match_score=100.0,
        raw_value_ppb=5.0,
        legal_limit_ppb=30.0,
        pass_fail=True,
        test_date=date(2024, 3, 15),
        date_ambiguous=False,
        state_canonical="Maharashtra",
        district_id=1,
        district_name="Pune",
        mandi_id=None,
        lab_raw="NABL Accredited Lab",
        lab_id=None,
        page_ocr_confidence=0.95,
    )
    defaults.update(overrides)
    return StandardisedRecord(**defaults)


# ---------------------------------------------------------------- hashing / dedup

def test_build_hash_is_deterministic():
    a = _record()
    b = _record()
    assert _build_hash(a) == _build_hash(b)


def test_build_hash_differs_on_value():
    a = _record(raw_value_ppb=5.0)
    b = _record(raw_value_ppb=6.0)
    assert _build_hash(a) != _build_hash(b)


def test_build_hash_rounds_value_to_avoid_float_noise():
    a = _record(raw_value_ppb=5.0001)
    b = _record(raw_value_ppb=5.0002)
    assert _build_hash(a) == _build_hash(b)


def test_deduplicator_flags_within_batch_duplicate():
    dedup = Deduplicator()
    records = [_record(), _record()]
    results = dedup.process(records)

    assert results[0].is_duplicate is False
    assert results[1].is_duplicate is True
    assert results[1].duplicate_of_hash == results[0].dedup_hash


def test_deduplicator_distinct_records_not_flagged():
    dedup = Deduplicator()
    records = [
        _record(district_id=1, district_name="Pune"),
        _record(district_id=2, district_name="Nashik"),
    ]
    results = dedup.process(records)

    assert results[0].is_duplicate is False
    assert results[1].is_duplicate is False


# ---------------------------------------------------------------- typical range

def test_typical_range_within_bounds():
    assert _is_in_typical_range("aflatoxin_b1", "grain", 5.0) is True


def test_typical_range_outside_bounds():
    assert _is_in_typical_range("aflatoxin_b1", "grain", 5000.0) is False


def test_typical_range_unknown_contaminant_is_false():
    assert _is_in_typical_range("unknown_contaminant", "grain", 5.0) is False


def test_typical_range_missing_value_is_false():
    assert _is_in_typical_range("aflatoxin_b1", "grain", None) is False


# ---------------------------------------------------------------- confidence scoring

def test_confidence_scorer_base_case():
    scorer = ConfidenceScorer()
    from pipeline.stage3_and_4 import DeduplicatedRecord

    rec = _record(lab_raw=None, contaminant_canonical=None, page_ocr_confidence=0.95)
    deduped = DeduplicatedRecord(record=rec, dedup_hash="h", is_duplicate=False, duplicate_of_hash=None)

    scored = scorer.score(deduped)
    assert scored.confidence_score == 0.70
    assert scored.is_usable is False  # below CONFIDENCE_MIN_USABLE (0.75)


def test_confidence_scorer_tier1_lab_and_typical_range_boost():
    scorer = ConfidenceScorer()
    from pipeline.stage3_and_4 import DeduplicatedRecord

    rec = _record(lab_raw="NABL Accredited Lab", contaminant_canonical="aflatoxin_b1", raw_value_ppb=5.0)
    deduped = DeduplicatedRecord(record=rec, dedup_hash="h", is_duplicate=False, duplicate_of_hash=None)

    scored = scorer.score(deduped, commodity_category="grain")
    # base 0.70 + tier1_lab 0.10 + typical_range 0.05 = 0.85
    assert scored.confidence_score == 0.85
    assert scored.is_usable is True
    assert scored.confidence_breakdown["tier1_lab"] == 0.10
    assert scored.confidence_breakdown["typical_range"] == 0.05


def test_confidence_scorer_low_ocr_penalty():
    scorer = ConfidenceScorer()
    from pipeline.stage3_and_4 import DeduplicatedRecord

    rec = _record(lab_raw=None, contaminant_canonical=None, page_ocr_confidence=0.5)
    deduped = DeduplicatedRecord(record=rec, dedup_hash="h", is_duplicate=False, duplicate_of_hash=None)

    scored = scorer.score(deduped)
    assert scored.confidence_score == 0.60  # 0.70 - 0.10
    assert scored.is_usable is False


def test_confidence_scorer_manual_verify_flag():
    scorer = ConfidenceScorer()
    from pipeline.stage3_and_4 import DeduplicatedRecord

    rec = _record(lab_raw=None, contaminant_canonical=None)
    deduped = DeduplicatedRecord(record=rec, dedup_hash="h", is_duplicate=False, duplicate_of_hash=None)

    scored = scorer.score(deduped, manually_verified=True)
    assert scored.confidence_score == 0.85  # 0.70 + 0.15

def test_confidence_scorer_clamps_to_one():
    scorer = ConfidenceScorer()
    from pipeline.stage3_and_4 import DeduplicatedRecord

    rec = _record(lab_raw="NABL Accredited Lab", contaminant_canonical="aflatoxin_b1", raw_value_ppb=5.0)
    deduped = DeduplicatedRecord(record=rec, dedup_hash="h", is_duplicate=False, duplicate_of_hash=None)

    scored = scorer.score(deduped, commodity_category="grain", manually_verified=True)
    # 0.70 + 0.15 + 0.10 + 0.05 = 1.00 exactly, still clamped/rounded correctly
    assert scored.confidence_score == 1.00
    assert scored.is_usable is True


# ---------------------------------------------------------------- combined runner

def test_dedup_and_score_end_to_end():
    records = [
        _record(district_id=1, district_name="Pune"),
        _record(district_id=1, district_name="Pune"),  # exact duplicate of the first
        _record(district_id=2, district_name="Nashik", page_ocr_confidence=0.5),  # distinct, low OCR
    ]
    scored = dedup_and_score(records)

    assert len(scored) == 3
    assert scored[0].is_duplicate is False
    assert scored[1].is_duplicate is True
    assert scored[2].is_duplicate is False
    assert scored[2].confidence_score < scored[0].confidence_score
