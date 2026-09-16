"""
Tests for pipeline/sources/research_evidence.py — abstract reconstruction
and evidence-level classification. No DB or network needed: these are pure
functions over fixture dicts shaped like real OpenAlex API responses.
"""
from __future__ import annotations

from pipeline.sources.research_evidence import (
    classify_evidence_level,
    extract_health_terms,
    reconstruct_abstract,
)


# ---------------------------------------------------------------- abstract

def test_reconstruct_abstract_orders_words_by_position():
    # OpenAlex's real shape: {word: [positions]}. "risk of liver cancer"
    inverted = {"risk": [0], "of": [1], "liver": [2], "cancer": [3]}
    assert reconstruct_abstract(inverted) == "risk of liver cancer"


def test_reconstruct_abstract_handles_repeated_words():
    # "the risk and the outcome" — "the" appears twice
    inverted = {"the": [0, 3], "risk": [1], "and": [2], "outcome": [4]}
    assert reconstruct_abstract(inverted) == "the risk and the outcome"


def test_reconstruct_abstract_returns_empty_for_missing_index():
    assert reconstruct_abstract(None) == ""
    assert reconstruct_abstract({}) == ""


# ---------------------------------------------------------------- evidence level

def test_classify_evidence_level_review_is_b():
    assert classify_evidence_level("review") == "B"
    assert classify_evidence_level("Review") == "B"


def test_classify_evidence_level_article_is_c():
    assert classify_evidence_level("article") == "C"


def test_classify_evidence_level_missing_type_defaults_to_c():
    # Never invent 'A' or 'D' from missing data — fall back to the more
    # conservative-to-claim tier, not the strongest one.
    assert classify_evidence_level(None) == "C"


# ---------------------------------------------------------------- health terms

def test_extract_health_terms_matches_keyword_list():
    concepts = [
        {"display_name": "Aflatoxin", "score": 0.9},
        {"display_name": "Hepatocellular carcinoma", "score": 0.6},
        {"display_name": "Environmental health", "score": 0.4},
    ]
    terms = extract_health_terms(concepts)
    assert "Hepatocellular carcinoma" in terms
    assert "Aflatoxin" not in terms  # no health-outcome keyword in the name


def test_extract_health_terms_caps_at_five():
    concepts = [{"display_name": f"Disease type {i}", "score": 0.5} for i in range(10)]
    assert len(extract_health_terms(concepts)) == 5


def test_extract_health_terms_empty_for_no_concepts():
    assert extract_health_terms(None) == []
    assert extract_health_terms([]) == []
