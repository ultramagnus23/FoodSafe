"""
Tests for pipeline/sources/hazard_kb.py — the hazard -> health knowledge base.
Checks the IARC bundle parser on a minimal stand-in for IARC's JS object
literal, and that every curated statement carries a resolvable source.
No network, no database.
"""
from __future__ import annotations

import json

import pytest

from pipeline.sources import hazard_kb as K
from pipeline.sources.standards_common import hazard_key

IARC_JS = ('!function(e){...}([function(e,a){e.exports={last_volume:"142",last_update:"2026-07-23 14:08 (CET)",'
           'agents:[{name:"Aflatoxins",group:"1",cas:["1402-68-2"],volume:["100F"],year:2012,yeareval:2009},'
           '{name:"Alcoholic beverages",group:"1",cas:[],volume:["44"],year:2e3,comment:\'NB There is "evidence '
           'suggesting lack" here\',in_prep:!1},'
           '{name:"Malathion",group:"2A",cas:["121-75-5"],volume:["112"],year:2017},'
           '{name:"<i>N</i>-Nitrosodimethylamine",group:"2A",cas:["62-75-9"],volume:["17"],year:1987}'
           + ',{name:"x",group:"3",cas:[],volume:[],year:1}' * 600 + "]}}])")


def test_parse_iarc_bundle_handles_minified_literal():
    meta, agents = K.parse_iarc_bundle(IARC_JS)
    assert meta == {"last_volume": "142", "last_update": "2026-07-23 14:08 (CET)"}
    by = {a["name"]: a for a in agents}
    assert by["Aflatoxins"]["group"] == "1"
    assert 'evidence suggesting lack' in by["Alcoholic beverages"]["comment"]       # single-quoted JS string
    assert by["Alcoholic beverages"]["year"] == 2000                                # '2e3'
    assert "N-Nitrosodimethylamine" in by                                           # HTML tags stripped


def test_parse_iarc_bundle_rejects_truncated_list():
    with pytest.raises(ValueError):
        K.parse_iarc_bundle('e.exports={last_volume:"1",last_update:"x",agents:[{name:"a",group:"1"}]}')


def test_js_literal_to_json_quotes_keys_not_string_contents():
    js = '{a:"x: y",b:\'it\\\'s "q"\',c:!0,d:[1,2e3]}'
    assert json.loads(K.js_literal_to_json(js, 0)) == {"a": "x: y", "b": 'it\'s "q"', "c": True, "d": [1, 2000.0]}


def test_every_effect_cites_a_known_source():
    for key, h in K.HAZARDS.items():
        for e in h.get("effects", []):
            assert e["source"] in K.SRC, (key, e["source"])
            assert e["exposure"] in ("acute", "chronic", "both")
    for cls in K.PESTICIDE_CLASSES.values():
        for e in cls["effects"]:
            assert e["source"] in K.SRC
    for title, url in K.SRC.values():
        assert url.startswith("https://") and title


def test_curated_keys_match_standards_normaliser():
    # a hazard in the KB must use the same key the rule-book parsers produce
    for name, key in [("Total Aflatoxins", "aflatoxins_total"), ("Ochratoxin A", "ochratoxin_a"),
                      ("Lead", "lead"), ("Arsenic (inorganic)", "arsenic_inorganic"), ("Chlorpyriphos", "chlorpyrifos"),
                      ("Methyl Mercury", "methylmercury"), ("Benzo(a)pyrene", "benzo_a_pyrene")]:
        assert hazard_key(name) == key
        assert key in K.HAZARDS or K.pesticide_class_of(key)


def test_build_joins_iarc_and_limits_generic_effects():
    agents = [{"name": "Aflatoxins", "group": "1", "cas": ["1402-68-2"], "volumes": [], "year": 2012, "comment": None},
              {"name": "Malathion", "group": "2A", "cas": ["121-75-5"], "volumes": [], "year": 2017, "comment": None},
              {"name": "Glyphosate", "group": "2A", "cas": ["1071-83-6"], "volumes": [], "year": 2017, "comment": None}]
    kb = K.build(agents, {"malathion": "121-75-5", "glyphosate": "1071-83-6", "pheromonex": "000-00-0"},
                 regulated={"glyphosate"})
    hz = {h["hazard_key"]: h for h in kb["hazards"]}
    assert hz["aflatoxins_total"]["iarc_group"] == "1" and hz["aflatoxin_m1"]["iarc_group"] == "1"
    assert {p["hazard_key"]: p["iarc_group"] for p in kb["iarc_pesticides"]} == {"malathion": "2A", "glyphosate": "2A"}
    keys = {e[0] for e in kb["effects"]}
    assert "malathion" in keys                    # organophosphate class effects
    assert "glyphosate" in keys                   # regulated, no class -> generic pesticide outcome
    assert "pheromonex" not in keys               # an EU record alone is not a food-residue hazard
    assert K.pesticide_class_of("chlorpyrifos") == "organophosphate"
    assert K.pesticide_class_of("imidacloprid") == "neonicotinoid"
