"""
Tests for api/source_registry.py — the source classification and the
confidence levels derived from it. The rubric is deterministic, so every rule is
pinned here; changing a source's level should be a visible test diff.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from api import source_registry as R

ROOT = Path(__file__).resolve().parent.parent


# ---- the rubric -------------------------------------------------------------

@pytest.mark.parametrize("publisher,access,expected", [
    ("regulator_primary", "structured_api", "high"),
    ("foreign_regulator", "structured_api", "high"),
    ("directory", "scraped_structured", "high"),
    ("government_disclosure", "pdf_validated", "medium"),
    ("regulator_primary", "pdf_validated", "medium"),
    ("peer_reviewed", "structured_api", "medium"),          # literature: a claim, not a measurement
    ("regulator_primary", "pdf_unvalidated", "low"),        # official, but no integrity check on our extraction
    ("government_disclosure", "text_heuristic", "low"),
    ("media", "structured_api", "low"),                     # media never rises, however it is obtained
    ("media", "scraped_structured", "low"),
])
def test_base_level_rubric(publisher, access, expected):
    assert R.base_level(publisher, access, "lab_measurement") == expected


def test_every_registered_source_is_classified_and_consistent():
    assert R.SOURCES  # non-empty
    for sid, s in R.SOURCES.items():
        assert s.id == sid
        assert R.source_level(sid) in (R.HIGH, R.MEDIUM, R.LOW)
        assert s.scope, f"{sid} states no scope limits"
        assert s.tables, f"{sid} lists no tables"


def test_the_classification_of_each_current_source_is_pinned():
    # Changing any of these is a deliberate, reviewed decision.
    assert {sid: R.source_level(sid) for sid in R.SOURCES} == {
        "rasff": "high",
        "openfda": "high",
        "fssai_annual_report": "low",       # regulator-primary but label-regex PDF extraction, no total check
        "loksabha_sampling": "medium",
        "loksabha_qa": "low",               # older parser without a total-row check
        "loksabha_pesticide": "medium",
        "research_evidence": "medium",
        "fssai_directory": "high",
        "local_news": "low",
    }


def test_registry_tables_and_docs_exist_in_the_repo():
    schema = "\n".join(p.read_text(encoding="utf-8") for p in ROOT.glob("schema*.sql"))
    missing = []
    for s in R.SOURCES.values():
        for t in s.tables:
            if not re.search(rf"CREATE TABLE(?: IF NOT EXISTS)?\s+{re.escape(t)}\b", schema, re.I):
                missing.append(t)
        if s.doc and not s.doc.startswith("pipeline/") and not (ROOT / s.doc).exists():
            missing.append(s.doc)
    assert missing == []


# ---- row-level confidence -----------------------------------------------------

def test_a_total_row_verified_row_keeps_its_sources_level():
    c = R.row_confidence("loksabha_sampling", verification="total_row_sum", corroboration="single_source")
    assert c.level == "medium" and any("add up" in r for r in c.reasons)


@pytest.mark.parametrize("verification", ["row_invariants", "pct_consistent"])
def test_a_weak_verification_tier_caps_the_row_at_low(verification):
    c = R.row_confidence("loksabha_pesticide", verification=verification)
    assert c.level == "low"


def test_a_weak_tier_never_raises_a_low_source():
    assert R.row_confidence("loksabha_qa", verification="row_invariants").level == "low"


def test_conflicting_corroboration_lowers_a_row_one_level():
    assert R.row_confidence("loksabha_sampling", verification="total_row_sum", corroboration="conflicting").level == "low"
    assert R.row_confidence("rasff", corroboration="conflicting").level == "medium"


def test_agreement_between_answers_does_not_raise_confidence():
    base = R.row_confidence("loksabha_sampling", verification="total_row_sum").level
    agreed = R.row_confidence("loksabha_sampling", verification="total_row_sum", corroboration="corroborated")
    assert agreed.level == base == "medium"
    assert any("not independent confirmation" in r for r in agreed.reasons)


def test_a_conflict_on_a_row_already_low_stays_low_but_is_still_said():
    c = R.row_confidence("loksabha_qa", corroboration="conflicting")
    assert c.level == "low" and any("different figure" in r for r in c.reasons)


def test_a_single_study_is_weaker_than_a_review():
    assert R.row_confidence("research_evidence", evidence_level="B").level == "medium"
    assert R.row_confidence("research_evidence", evidence_level="C").level == "low"


def test_synthetic_records_are_demo_never_a_real_level():
    c = R.row_confidence("openfda", synthetic=True)
    assert c.level == "demo" and "synthetic" in c.reasons[0]


def test_an_unclassified_source_cannot_get_a_level():
    with pytest.raises(KeyError):
        R.row_confidence("some_new_scraper")


def test_reasons_always_start_with_why_the_source_has_its_base_level():
    for sid in R.SOURCES:
        c = R.row_confidence(sid)
        assert c.reasons and c.reasons[0].startswith("published by ")


def test_describe_exposes_the_classification_and_scope():
    d = R.describe("loksabha_sampling")
    assert d["base_confidence"] == "medium" and d["publisher_type"] == "government_disclosure"
    assert d["scope"] and d["tables"] == ["state_sampling_annual"]
