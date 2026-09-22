"""
FoodSafe India — source registry and confidence classification.

Every dataset in the project comes from a *source* with a fixed character: who
published it, what kind of thing it measures, and how we get it out. This module
is the single place that classifies each source and turns that classification
into a confidence level attached to what the API serves.

WHAT "CONFIDENCE" MEANS HERE (and what it does not)
  Confidence answers one question: how sure are we that this record correctly
  states what the publisher disclosed, and that the publisher's figure is a
  real observation rather than an estimate or a guess?
  It is NOT a statement about representativeness. A record can be high
  confidence and still say nothing about how contaminated India's food is
  (border checks and inspector-targeted sampling are not random). That is
  carried separately, as `scope` caveats, and the two are never blended.

THE RUBRIC (deterministic; no numbers pretending to precision)
  A source has three attributes:
    publisher_type  regulator_primary | foreign_regulator | government_disclosure
                    | peer_reviewed | directory | media
    access          structured_api | scraped_structured | pdf_validated
                    | pdf_unvalidated | text_heuristic
    content_kind    lab_measurement | test_outcome_counts | enforcement_counts
                    | literature_association | directory | event_report

  Base level:
    HIGH    the publisher is an official authority AND the data reaches us in a
            machine-readable structured form (structured_api / scraped_structured)
    MEDIUM  the publisher is official or peer-reviewed but the data reaches us
            through document extraction that we validate with integrity checks
            (pdf_validated), or is literature (a peer-reviewed claim, not a
            measurement)
    LOW     media, or extraction with no integrity validation
            (pdf_unvalidated / text_heuristic)

  Row-level adjustments (never upward):
    * a weak verification tier caps the row at LOW (`row_invariants`,
      `pct_consistent`)
    * `conflicting` corroboration (the same figure disclosed differently by
      other answers) lowers the row one level
    * a synthetic (demo) record is level `demo` and is never a real observation
  Independent agreement between two answers does NOT raise a level: answers from
  one ministry often reuse the same table, so agreement is reported as
  corroboration, not promoted to confidence.

The registry is data, not logic scattered over routes, so changing a source's
classification is a one-line, reviewable, tested change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel

HIGH, MEDIUM, LOW, DEMO = "high", "medium", "low", "demo"
_ORDER = [LOW, MEDIUM, HIGH]

PUBLISHER_TYPES = {"regulator_primary", "foreign_regulator", "government_disclosure", "peer_reviewed", "directory", "media"}
ACCESS_TYPES = {"structured_api", "scraped_structured", "pdf_validated", "pdf_unvalidated", "text_heuristic"}
CONTENT_KINDS = {"lab_measurement", "test_outcome_counts", "enforcement_counts", "literature_association", "directory",
                 "event_report"}

_OFFICIAL = {"regulator_primary", "foreign_regulator", "government_disclosure", "directory"}
_STRUCTURED = {"structured_api", "scraped_structured"}

# Verification tiers that cap a row at LOW regardless of the source's base level.
WEAK_VERIFICATION = {"row_invariants", "pct_consistent"}


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    publisher: str
    publisher_type: str
    access: str
    content_kind: str
    grain: str                       # what one row describes
    coverage: str                    # period / geography actually held
    tables: tuple[str, ...]          # tables holding its rows
    scope: tuple[str, ...]           # what it can NOT be used for (representativeness)
    caveats: tuple[str, ...] = ()    # accuracy/extraction notes
    real: bool = True
    doc: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        assert self.publisher_type in PUBLISHER_TYPES, self.publisher_type
        assert self.access in ACCESS_TYPES, self.access
        assert self.content_kind in CONTENT_KINDS, self.content_kind


def base_level(publisher_type: str, access: str, content_kind: str) -> str:
    """The source-level classification -> confidence rule (see module docstring)."""
    if publisher_type == "media" or access in {"pdf_unvalidated", "text_heuristic"}:
        return LOW
    if publisher_type in _OFFICIAL and access in _STRUCTURED:
        return HIGH
    # official/peer-reviewed publisher, document extraction that we validate
    # (or literature, which is a claim rather than a measurement)
    return MEDIUM


SOURCES: dict[str, Source] = {s.id: s for s in [
    Source(
        id="rasff", name="EU RASFF notifications (India-origin food)",
        publisher="European Commission — Rapid Alert System for Food and Feed (RASFF Window)",
        publisher_type="foreign_regulator", access="structured_api", content_kind="lab_measurement",
        grain="one notification x hazard: measured value, legal limit, unit, hazard category, product, action taken",
        coverage="notifications about food of Indian origin, as far back as the public feed goes; export/border-check grain",
        tables=("rasff_notifications", "rasff_hazards"),
        scope=("Not a sample of Indian food: only consignments exported to, and checked by, EU/EEA authorities.",
               "Targeted checks (risk-based border control) over-represent problem product/origin pairs.",
               "A notification is a finding by an EU member-state authority, not a court finding about a producer."),
        caveats=("Hazard fields are free-form text from the notifying authority; numeric values are parsed only when unambiguous.",),
        doc="docs/RASFF_INGESTION.md",
    ),
    Source(
        id="openfda", name="US FDA food enforcement (recalls)",
        publisher="US Food and Drug Administration (openFDA)",
        publisher_type="foreign_regulator", access="structured_api", content_kind="enforcement_counts",
        grain="one recall event",
        coverage="US recalls, comparison baseline only",
        tables=("enforcement_records",),
        scope=("United States, not India; every record is a recall (a failure), so there is no pass class.",),
        doc="docs/BACKTEST_REPORT.md",
    ),
    Source(
        id="fssai_annual_report", name="FSSAI Annual Report enforcement metrics",
        publisher="Food Safety and Standards Authority of India",
        publisher_type="regulator_primary", access="pdf_unvalidated", content_kind="enforcement_counts",
        grain="one national fiscal-year metric set",
        coverage="3 fiscal years (large PDFs of other years not ingested)",
        tables=("national_enforcement_annual",),
        scope=("National totals only; definitions of 'decided' vs 'convicted' change between years.",),
        caveats=("The regulator's own figures, but read from a PDF by label matching with no total-row check, so LOW by the rubric "
                 "until one is added. One year (2018-19: 106,459 samples) does agree with the sum of the state tables from Parliament.",),
        doc="docs/FSSAI_INGESTION.md",
    ),
    Source(
        id="loksabha_sampling", name="State sampling outcomes (Lok Sabha)",
        publisher="Ministry of Health & Family Welfare, disclosed to Lok Sabha",
        publisher_type="government_disclosure", access="pdf_validated", content_kind="test_outcome_counts",
        grain="one State/UT x fiscal year: samples analysed, found non-conforming",
        coverage="2013-14 to 2025-26, uneven by year",
        tables=("state_sampling_annual",),
        scope=("Inspector-targeted samples: a high rate is not a prevalence estimate.",
               "'Non-conforming' is not necessarily unsafe; two definitions must never be pooled."),
        caveats=("Tables are accepted only if every integrity check passes; vintages differ across answers.",),
        doc="docs/LOKSABHA_SAMPLING.md",
    ),
    Source(
        id="loksabha_qa", name="State enforcement counts (Lok Sabha)",
        publisher="Ministry of Health & Family Welfare, disclosed to Lok Sabha",
        publisher_type="government_disclosure", access="pdf_unvalidated", content_kind="enforcement_counts",
        grain="one State/UT x fiscal year: cases, convictions, licences cancelled",
        coverage="answers in the 16th-18th Lok Sabha that matched the annexure shapes",
        tables=("state_enforcement_annual",),
        scope=("Enforcement activity, not contamination; counts depend on state enforcement effort.",),
        caveats=("Older, less strictly validated parser (no printed-total check): classified LOW until it gains one.",),
        doc="pipeline/sources/loksabha_qa.py",
    ),
    Source(
        id="loksabha_pesticide", name="Pesticide-residue monitoring (MPRNL, via Lok Sabha)",
        publisher="Ministry of Agriculture & Farmers Welfare, disclosed to Lok Sabha",
        publisher_type="government_disclosure", access="pdf_validated", content_kind="test_outcome_counts",
        grain="one commodity x period: samples analysed, above the FSSAI residue limit",
        coverage="2012-13 to 2018-19, national",
        tables=("pesticide_residue_annual",),
        scope=("Monitoring-scheme samples, not random draws from what people eat.",
               "Above the limit is a regulatory exceedance, not proof of harm.",
               "National grain only."),
        caveats=("Early figures were later revised; all vintages are kept and flagged.",),
        doc="docs/LOKSABHA_PESTICIDE.md",
    ),
    Source(
        id="research_evidence", name="Peer-reviewed literature (OpenAlex, Europe PMC)",
        publisher="Journals, via OpenAlex and Europe PMC",
        publisher_type="peer_reviewed", access="structured_api", content_kind="literature_association",
        grain="one paper x contaminant link",
        coverage="about 1,860 papers linking 9 contaminants to health outcomes",
        tables=("research_sources", "contaminant_research_links"),
        scope=("A citation layer: it states that a paper reports an association, not that any Indian sample was contaminated.",
               "Feeds no risk score."),
        doc="docs/RESEARCH_EVIDENCE_INGESTION.md",
    ),
    Source(
        id="fssai_directory", name="FSSAI laboratory and commissioner directories",
        publisher="Food Safety and Standards Authority of India",
        publisher_type="directory", access="scraped_structured", content_kind="directory",
        grain="one laboratory or one State Commissioner of Food Safety",
        coverage="255 labs, 36 commissioners",
        tables=("labs", "state_commissioners"),
        scope=("Contact and accreditation metadata, not enforcement or test data.",),
        doc="docs/FSSAI_INGESTION.md",
    ),
    Source(
        id="local_news", name="Local news food-safety signals",
        publisher="Regional news outlets (public listing pages)",
        publisher_type="media", access="text_heuristic", content_kind="event_report",
        grain="one locality-tagged event report",
        coverage="5 metros, about one usable record per run",
        tables=("enforcement_records",),
        scope=("Unverified press reports; locality inferred by text matching.",),
        doc="docs/LOCAL_NEWS_INGESTION.md",
    ),
]}

# enforcement_records rows carry their origin in source_type; map it to a registry id.
ENFORCEMENT_SOURCE_TYPES = {"usfda": "openfda", "local_news": "local_news", "local_news_mumbai": "local_news"}


class Confidence(BaseModel):
    level: str                 # high | medium | low | demo
    source_id: str
    reasons: list[str]         # plain-language, in the order they were applied


def source_level(source_id: str) -> str:
    s = SOURCES[source_id]
    return base_level(s.publisher_type, s.access, s.content_kind)


def row_confidence(
    source_id: str,
    *,
    verification: Optional[str] = None,
    corroboration: Optional[str] = None,
    evidence_level: Optional[str] = None,
    synthetic: bool = False,
) -> Confidence:
    """Confidence of one served row: the source's base level, adjusted downward
    only (see module docstring). Unknown source ids raise KeyError on purpose:
    an unclassified source must not silently get a level."""
    src = SOURCES[source_id]
    if synthetic or not src.real:
        return Confidence(level=DEMO, source_id=source_id,
                          reasons=["synthetic demonstration record, not a real observation"])

    level = base_level(src.publisher_type, src.access, src.content_kind)
    reasons = [_base_reason(src, level)]

    if evidence_level == "C":     # literature: a single study is weaker than a review
        level, reasons = _cap(level, LOW, reasons, "single study (evidence level C), not a review")
    if verification in WEAK_VERIFICATION:
        level, reasons = _cap(level, LOW, reasons, _WEAK_TEXT[verification])
    elif verification:
        reasons.append(_STRONG_TEXT.get(verification, f"verification: {verification}"))
    if corroboration == "conflicting":
        lowered = _ORDER[max(0, _ORDER.index(level) - 1)]
        if lowered != level:
            reasons.append("other answers disclose a different figure for the same cell; lowered one level")
            level = lowered
        else:
            reasons.append("other answers disclose a different figure for the same cell")
    elif corroboration == "corroborated":
        reasons.append("another answer states the same figure (agreement, not independent confirmation)")
    return Confidence(level=level, source_id=source_id, reasons=reasons)


def _cap(level: str, ceiling: str, reasons: list[str], why: str):
    if _ORDER.index(level) > _ORDER.index(ceiling):
        reasons.append(f"capped at {ceiling}: {why}")
        return ceiling, reasons
    reasons.append(why)
    return level, reasons


_WEAK_TEXT = {
    "row_invariants": "no printed total to check the rows against",
    "pct_consistent": "quoted in a sentence; only the printed percentage supports it",
}
_STRONG_TEXT = {
    "total_row_sum": "rows add up to the printed total",
    "total_row_close": "rows are within 0.1% of the printed total",
}


def _base_reason(src: Source, level: str) -> str:
    who = {"regulator_primary": "the regulator itself", "foreign_regulator": "an official regulator",
           "government_disclosure": "a government disclosure to Parliament", "peer_reviewed": "peer-reviewed literature",
           "directory": "an official directory", "media": "news media"}[src.publisher_type]
    how = {"structured_api": "machine-readable form", "scraped_structured": "structured web data",
           "pdf_validated": "a document extraction that passes integrity checks",
           "pdf_unvalidated": "a document extraction without a total-row check",
           "text_heuristic": "text-matching heuristics"}[src.access]
    return f"published by {who}, obtained as {how} -> {level}"


def describe(source_id: str) -> dict:
    """The registry entry plus its derived level, for /v1/meta/sources."""
    s = SOURCES[source_id]
    return {
        "id": s.id, "name": s.name, "publisher": s.publisher, "publisher_type": s.publisher_type,
        "access": s.access, "content_kind": s.content_kind, "grain": s.grain, "coverage": s.coverage,
        "tables": list(s.tables), "scope": list(s.scope), "caveats": list(s.caveats), "doc": s.doc,
        "base_confidence": source_level(s.id),
    }
