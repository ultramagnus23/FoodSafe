"""
Disease classification of contamination records: hazard text -> hazard -> the
health outcomes that hazard is known to cause.

A contamination record names a hazard in free text ('Aflatoxin B1', 'Salmonella
Enteritidis', 'chlorpyrifos', 'Listeria monocytogenes') and, for RASFF, the
notifier's own hazard category ('mycotoxins', 'pathogenic micro-organisms').
classify_hazard() resolves it, most specific first:

  1. kb_name          the hazard's comparison key is a curated KB hazard
                      ('Aflatoxin B1' -> aflatoxin_b1)
  2. kb_alias         a curated alias appears in the text as a whole phrase,
                      longest alias first ('Salmonella Typhi' -> salmonella_typhi
                      before salmonella; 'E. coli O157' -> stec before e. coli)
  3. pesticide_class  the key belongs to a pesticide chemical class
                      (chlorpyrifos -> organophosphate)
  4. rasff_category   only the notifier's category is known -> a hazard class
                      with class-level outcomes (labelled as such)

outcomes_for() then returns the KB's outcome rows for the resolved hazard (or the
class-level rows for a category-only match). Nothing here estimates how likely
an outcome is; it says which outcomes the recorded hazard can cause, with the
source of that statement. See docs/HAZARD_KB.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from pipeline.sources import hazard_kb as KB
from pipeline.sources.standards_common import hazard_key


@dataclass
class Classified:
    hazard_key: Optional[str]
    hazard_class: Optional[str]
    classified_by: Optional[str]
    kb_key: Optional[str] = None          # the KB entry whose outcomes apply
    pesticide_class: Optional[str] = None
    outcomes: list[dict] = field(default_factory=list)


def _alias_table() -> list[tuple[re.Pattern, str]]:
    pairs = []
    for key, h in KB.HAZARDS.items():
        names = {h["name"].lower()} | {a.lower() for a in h.get("aliases", [])}
        for n in names:
            n = n.strip()
            if len(n) < 3:
                continue
            pairs.append((n, key))
    pairs.sort(key=lambda p: -len(p[0]))
    return [(re.compile(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])"), k) for n, k in pairs]


_ALIASES = _alias_table()
# allergen names are ordinary words ('milk', 'egg', 'soy') — only trusted when the
# notifier itself says the hazard is an allergen
_ALLERGEN_ONLY = {"undeclared_allergen"}


def classify_hazard(text: Optional[str], rasff_category: Optional[str] = None) -> Classified:
    # RASFF prints qualifiers after ' - ' ('carbendazim  - unauthorised substance',
    # 'sulphite  - too high content') and doubles spaces; neither names the hazard.
    t = re.sub(r"\s+", " ", (text or "")).strip()
    t = re.sub(r"\s+-\s+(unauthorised|too high|high level|migration|undeclared|presence|absence|not "
               r"authorised|prohibited).*$", "", t, flags=re.I).strip()
    cat = (rasff_category or "").strip().lower()
    hk = hazard_key(t) if t else None
    if hk and hk in KB.HAZARDS:
        h = KB.HAZARDS[hk]
        return Classified(hk, h["hazard_class"], "kb_name", kb_key=hk)
    low = t.lower()
    for rx, key in _ALIASES:
        if key in _ALLERGEN_ONLY and cat != "allergens":
            continue
        if rx.search(low):
            return Classified(hk or key, KB.HAZARDS[key]["hazard_class"], "kb_alias", kb_key=key)
    pc = KB.pesticide_class_of(hk)
    if pc:
        return Classified(hk, "pesticide", "pesticide_class", pesticide_class=pc)
    if cat == "allergens":
        return Classified(hk, "allergen", "rasff_category", kb_key="undeclared_allergen")
    cls = KB.RASFF_CATEGORY_CLASS.get(cat)
    if cls:
        return Classified(hk, cls, "rasff_category")
    return Classified(hk, None, None)


def outcomes_for(c: Classified) -> list[dict]:
    """Outcome dicts (outcome_key, outcome, organ_system, exposure, evidence,
    source title/url, icd10, vulnerable_groups, level) for a classified hazard.
    level = 'hazard' (named hazard) | 'class' (pesticide class or category only)."""
    effects, level = [], "hazard"
    if c.kb_key:
        h = KB.HAZARDS[c.kb_key]
        effects = h.get("effects") or (KB.HAZARDS[h["parent"]]["effects"] if h.get("parent") else [])
    elif c.pesticide_class:
        effects, level = KB.PESTICIDE_CLASSES[c.pesticide_class]["effects"], "class"
    elif c.hazard_class in KB.CLASS_EFFECTS:
        effects, level = KB.CLASS_EFFECTS[c.hazard_class], "class"
    out = []
    for e in effects:
        title, url = KB.SRC[e["source"]]
        out.append({**{k: e[k] for k in ("outcome_key", "outcome", "organ_system", "exposure", "evidence",
                                          "icd10", "onset", "vulnerable_groups")},
                    "source_title": title, "source_url": url, "level": level})
    return out
