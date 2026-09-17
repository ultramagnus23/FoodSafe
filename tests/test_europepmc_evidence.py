"""
Tests for pipeline/sources/europepmc_evidence.py — HTML stripping,
study-design classification from real Europe PMC pubType tags, and the
cross-dedup merge/upgrade rules. No DB or network needed.
"""
from __future__ import annotations

from pipeline.sources.europepmc_evidence import (
    classify_study_design,
    merge_study_design,
    should_upgrade_to_b,
    strip_html,
)


# ---------------------------------------------------------------- strip_html

def test_strip_html_removes_tags_and_unescapes_entities():
    raw = "Aflatoxin B&lt;sub&gt;1&lt;/sub&gt; and <i>Aspergillus flavus</i>"
    assert strip_html(raw) == "Aflatoxin B1 and Aspergillus flavus"


def test_strip_html_handles_none_and_empty():
    assert strip_html(None) == ""
    assert strip_html("") == ""


# ---------------------------------------------------------------- study design

def test_classify_study_design_systematic_review():
    assert classify_study_design(["Journal Article", "Systematic Review"]) == "systematic_review"


def test_classify_study_design_prefers_most_specific_tag_present():
    # Real Europe PMC shape: a systematic review is often *also* tagged
    # plain "Review" — the more specific tag must win regardless of order.
    assert classify_study_design(["Review", "Systematic Review", "Journal Article"]) == "systematic_review"


def test_classify_study_design_randomized_trial():
    assert classify_study_design(["Randomized Controlled Trial"]) == "randomized_trial"


def test_classify_study_design_generic_article_is_unclassified():
    assert classify_study_design(["Journal Article"]) == "unclassified"


def test_classify_study_design_missing_is_unclassified():
    assert classify_study_design(None) == "unclassified"
    assert classify_study_design([]) == "unclassified"


def test_classify_study_design_plain_review():
    assert classify_study_design(["review-article", "Review", "Journal Article"]) == "review"


# ---------------------------------------------------------------- upgrade rule

def test_should_upgrade_to_b_only_for_systematic_review_or_meta_analysis():
    assert should_upgrade_to_b("systematic_review") is True
    assert should_upgrade_to_b("meta_analysis") is True
    assert should_upgrade_to_b("randomized_trial") is False
    assert should_upgrade_to_b("review") is False
    assert should_upgrade_to_b("unclassified") is False


# ---------------------------------------------------------------- merge rule

def test_merge_study_design_keeps_existing_informative_value():
    assert merge_study_design("cohort", "review") == "cohort"


def test_merge_study_design_replaces_unclassified():
    assert merge_study_design("unclassified", "systematic_review") == "systematic_review"


def test_merge_study_design_replaces_missing():
    assert merge_study_design(None, "case_control") == "case_control"
