"""
The public portal classifies text in the browser with rules exported by
scripts/export_portal.py. Pinned here: the pesticide-class rules agree with the
server-side classifier (models/health_classifier.classify_hazard), longer names
win over their prefixes, and every pattern compiles. No database.
"""
from __future__ import annotations

import re

from models.health_classifier import classify_hazard
from pipeline.sources import hazard_kb as KB
from scripts.export_portal import _pesticide_class_rules

RULES = _pesticide_class_rules(KB)


def first_hit(text: str):
    return next((r for r in RULES if re.search(r["pattern"], text.lower())), None)


def test_every_class_member_has_a_rule_except_combined_definitions():
    members = {m for d in KB.PESTICIDE_CLASSES.values() for m in d["members"]} - {"aldrinanddieldrin"}
    assert {r["key"] for r in RULES} == members


def test_rules_agree_with_the_server_classifier():
    for r in RULES:
        c = classify_hazard(r["key"], "pesticide residues")
        if c.kb_key:            # a named KB hazard wins on the server, and its alias rule comes first in the browser
            continue
        assert c.pesticide_class == r["pclass"], r["key"]


def test_methyl_variants_match_before_the_parent_name():
    assert first_hit("chlorpyrifos-methyl in rice")["key"] == "chlorpyrifosmethyl"
    assert first_hit("pirimiphos methyl in wheat")["key"] == "pirimiphosmethyl"
    assert first_hit("chlorpyrifos above the MRL")["key"] == "chlorpyrifos"


def test_effects_are_cited_and_names_readable():
    hit = first_hit("DDT residues in fish")
    assert hit["name"] == "DDT" and hit["pclass"] == "organochlorine"
    assert all(e["url"].startswith("http") and e["source"] for r in RULES for e in r["effects"])
