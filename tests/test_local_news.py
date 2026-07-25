"""
Tests for pipeline/sources/local_news.py — locality-name resolution and the
RawRecord -> stage2/stage3 flow. No DB connection needed: the resolution
functions are pure (they take an already-fetched `localities` row list /
pre-built lookup dict), and Standardiser/dedup_and_score fall back to their
bootstrap/in-memory behaviour when db_conn=None, same pattern as
test_stage2_standardise.py / test_stage3_dedup.py.
"""
from __future__ import annotations

from pipeline.sources.local_news import (
    LocalNewsRecord,
    _normalise_locality_key,
    build_locality_lookup,
    resolve_locality_id,
)
from pipeline.stage1_extract import RawField, RawRecord
from pipeline.stage2_standardise import Standardiser
from pipeline.stage3_and_4 import dedup_and_score


def _field(value: str) -> RawField:
    return RawField(value=value, confidence=0.95, source="html")


# Rows shaped like `SELECT id, name_canonical, parent_district_id FROM localities`
MUMBAI_LOCALITY_ROWS = [
    (1, "Juhu", 10),
    (2, "Vile Parle West", 10),
    (3, "Vile Parle East", 10),
    (4, "Andheri West", 10),
    (5, "Andheri East", 10),
    (6, "Chembur", 10),
]


# ---------------------------------------------------------------- key normalisation

def test_normalise_locality_key_strips_directional_suffix():
    assert _normalise_locality_key("Vile Parle West") == "vile parle"
    assert _normalise_locality_key("Andheri East") == "andheri"


def test_normalise_locality_key_no_suffix_unchanged():
    assert _normalise_locality_key("Juhu") == "juhu"
    assert _normalise_locality_key("Chembur") == "chembur"


def test_normalise_locality_key_case_and_whitespace_insensitive():
    assert _normalise_locality_key("  JUHU  ") == "juhu"


# ---------------------------------------------------------------- lookup + resolution

def test_build_locality_lookup_groups_directional_variants():
    lookup = build_locality_lookup(MUMBAI_LOCALITY_ROWS)
    assert sorted(lookup["andheri"]) == [(4, 10), (5, 10)]
    assert lookup["chembur"] == [(6, 10)]


def test_resolve_locality_id_exact_no_suffix_match():
    lookup = build_locality_lookup(MUMBAI_LOCALITY_ROWS)
    result = resolve_locality_id(["Chembur"], lookup)
    assert result == (6, 10)


def test_resolve_locality_id_matches_keyword_against_directional_variant():
    # Article keyword "Andheri" (from the hardcoded MUMBAI_LOCALITIES list)
    # must resolve against real rows named "Andheri West"/"Andheri East".
    lookup = build_locality_lookup(MUMBAI_LOCALITY_ROWS)
    result = resolve_locality_id(["Andheri"], lookup)
    assert result == (4, 10)   # lowest id of the ambiguous group, deterministic


def test_resolve_locality_id_tries_each_keyword_in_order():
    lookup = build_locality_lookup(MUMBAI_LOCALITY_ROWS)
    # "Dadar" isn't seeded; "Juhu" is later in the list and should still resolve.
    result = resolve_locality_id(["Dadar", "Juhu"], lookup)
    assert result == (1, 10)


def test_resolve_locality_id_no_match_returns_none():
    lookup = build_locality_lookup(MUMBAI_LOCALITY_ROWS)
    assert resolve_locality_id(["Powai"], lookup) is None


def test_resolve_locality_id_empty_keywords_returns_none():
    lookup = build_locality_lookup(MUMBAI_LOCALITY_ROWS)
    assert resolve_locality_id([], lookup) is None


def test_resolve_locality_id_generic_beyond_mumbai():
    # Same functions, a Delhi-shaped `localities` row set — nothing here is
    # Mumbai-specific, matching the requirement that resolution work
    # generically as `localities` gains more cities.
    rows = [(101, "Connaught Place", 50), (102, "Karol Bagh", 50)]
    lookup = build_locality_lookup(rows)
    assert resolve_locality_id(["Karol Bagh"], lookup) == (102, 50)


def test_build_locality_lookup_empty_input():
    assert build_locality_lookup([]) == {}


# ---------------------------------------------------------------- RawRecord -> stage2/stage3

def _local_news_raw_record() -> RawRecord:
    return RawRecord(
        source_url="https://www.freepressjournal.in/mumbai/fda-bans-loose-milk-sales",
        source_type="local_news_mumbai",
        product_name=_field("Aflatoxin M1"),
        contaminant=_field("Aflatoxin"),
        value=None,
        unit=None,
        date=_field("July 2026"),
        state=_field("mh"),
        district=_field("Mumbai"),
        pass_fail=None,
        page_ocr_confidence=1.0,
    )


def test_local_news_record_flows_through_stage2_without_erroring():
    raw = _local_news_raw_record()
    std = Standardiser()
    result = std.standardise(raw)

    assert result.source_type == "local_news_mumbai"
    assert result.source_url == raw.source_url
    assert result.state_canonical == "Maharashtra"
    # No hard requirement that the contaminant/date resolve cleanly (this is
    # narrative text, not tabular) — the point is standardise() must not
    # raise, and it should carry the source_url/source_type through intact.


def test_local_news_record_flows_through_stage2_and_stage3_without_erroring():
    raw = _local_news_raw_record()
    std = Standardiser()
    standardised = [std.standardise(raw)]

    scored = dedup_and_score(standardised)

    assert len(scored) == 1
    assert scored[0].record.source_type == "local_news_mumbai"
    assert isinstance(scored[0].confidence_score, float)
    assert scored[0].is_duplicate is False


def test_local_news_record_qualitative_no_value_still_flows_through():
    # Honesty note in the module docstring: value/unit legitimately stay
    # None for a policy-change article ("bans loose milk sales"), same as
    # a FoSCoS recall — that must not blow up standardisation or scoring.
    raw = RawRecord(
        source_url="https://example.com/article",
        source_type="local_news_mumbai",
        contaminant=None,
        value=None,
        unit=None,
    )
    std = Standardiser()
    standardised = std.standardise(raw)
    assert standardised.raw_value_ppb is None

    scored = dedup_and_score([standardised])
    assert len(scored) == 1


def test_local_news_record_dataclass_carries_locality_names():
    raw = _local_news_raw_record()
    rec = LocalNewsRecord(raw=raw, title="Maharashtra FDA Bans Loose Milk Sales",
                           locality_names=["Chembur", "Andheri"])
    assert rec.locality_names == ["Chembur", "Andheri"]
    assert rec.raw is raw
