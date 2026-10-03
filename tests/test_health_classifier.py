"""
Tests for models/health_classifier.py (hazard text -> KB hazard -> outcomes) and
the pure-Python scorer in models/hazard_text_classifier.py. The shipped model
artifact is checked for shape and for a few unambiguous texts; the scorer's maths
is checked on a tiny hand-made model. No network, no database.
"""
from __future__ import annotations

import math

import pytest

from models import hazard_text_classifier as HT
from models.health_classifier import classify_hazard, outcomes_for


@pytest.mark.parametrize("text,category,key,cls,by", [
    ("Aflatoxin B1", "mycotoxins", "aflatoxin_b1", "mycotoxin", "kb_name"),
    ("Salmonella Infantis", "pathogenic micro-organisms", "salmonella", "pathogen_bacteria", "kb_alias"),
    ("Salmonella Typhi", None, "salmonella_typhi", "pathogen_bacteria", "kb_alias"),     # longest alias wins
    ("Listeria monocytogenes", None, "listeria_monocytogenes", "pathogen_bacteria", "kb_alias"),
    ("ethylene oxide", "pesticide residues", "ethylene_oxide", "pesticide", "kb_alias"),
    ("chlorpyriphos-ethyl", "pesticide residues", None, "pesticide", "pesticide_class"),
    ("carbendazim  - unauthorised substance", "pesticide residues", None, "pesticide", "rasff_category"),
    ("sulphite  - too high content", "food additives and flavourings", "sulphites", "additive", "kb_alias"),
    ("khoya adulterated with detergent", None, "india_adulterants", "adulterant", "kb_alias"),
])
def test_classify_hazard(text, category, key, cls, by):
    c = classify_hazard(text, category)
    assert (c.classified_by, c.hazard_class) == (by, cls)
    if key:
        assert c.kb_key == key
    if by == "pesticide_class":
        assert c.pesticide_class == "organophosphate" and c.hazard_key == "chlorpyrifos"


def test_allergen_words_need_the_allergen_category():
    assert classify_hazard("milk powder", None).kb_key != "undeclared_allergen"
    c = classify_hazard("milk", "allergens")
    assert c.kb_key == "undeclared_allergen" and c.hazard_class == "allergen"


def test_outcomes_carry_sources_and_level():
    o = outcomes_for(classify_hazard("Aflatoxin B1"))
    assert {x["outcome_key"] for x in o} == {"liver_cancer", "aflatoxicosis"}
    assert all(x["source_url"].startswith("https://") and x["level"] == "hazard" for x in o)
    cls = outcomes_for(classify_hazard("chlorpyrifos", "pesticide residues"))
    assert cls and all(x["level"] == "class" for x in cls)
    assert outcomes_for(classify_hazard("urea in milk")) == []          # adulterant: no outcome asserted
    assert outcomes_for(classify_hazard("some unknown thing")) == []


def test_clean_removes_origin_but_keeps_hazard_words():
    assert HT.clean("Salmonella in chicken meat from Poland", ["Poland"]) == "salmonella in chicken meat"
    assert HT.clean("Sudan IV in palm oil from Ghana", ["Sudan", "Ghana"]) == "sudan iv in palm oil"
    assert HT.clean("przekroczenie NDP /// exceedance of the MRL for dimethoate in limes from Brazil") == \
        "exceedance of the mrl for dimethoate in limes"


def test_linear_model_scoring_matches_hand_computation():
    data = {"classes": ["a", "b"], "idf": {"xa": 1.0, "yb": 2.0},
            "weights": {"xa": [[0, 1.0]], "yb": [[1, 1.0]]}, "intercept": [0.0, 0.0]}
    m = HT.LinearTextModel(data)
    v = m.vector("xa yb")                       # the bigram 'xa_yb' is not in the vocabulary: ignored
    assert v["xa"] == pytest.approx(1 / math.sqrt(5)) and v["yb"] == pytest.approx(2 / math.sqrt(5))
    probs = dict(m.predict_proba("xa yb"))
    expected_b = math.exp(2 / math.sqrt(5)) / (math.exp(1 / math.sqrt(5)) + math.exp(2 / math.sqrt(5)))
    assert probs["b"] == pytest.approx(expected_b)


@pytest.mark.skipif(not HT.ARTIFACT.exists(), reason="model artifact not built")
def test_shipped_model_on_unambiguous_texts():
    m = HT.LinearTextModel.load()
    assert "pesticide residues" in m.classes and "pathogenic micro-organisms" in m.classes
    for text, cat in [("Salmonella in chicken meat", "pathogenic micro-organisms"),
                      ("Aflatoxins in groundnuts", "mycotoxins"),
                      ("Ethylene oxide in sesame seeds", "pesticide residues"),
                      ("Undeclared peanut in biscuits", "allergens")]:
        top, p = m.predict_proba(text)[0]
        assert top == cat and p > 0.6, (text, top, p)
    assert m.meta["test"]["accuracy"] > 0.85
