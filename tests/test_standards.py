"""
Tests for the food-standards layer: the shared parsers (standards_common), the
four rule-book parsers (FSSAI, EU pesticides + contaminants, Codex pesticides +
contaminants, US 40 CFR 180), the food crosswalk, and the comparison model.

Fixtures are minimal hand-written stand-ins shaped like the real documents
(cells copied from the FSSAI compendium, the EU/Codex APIs, eCFR XML and CXS
193). They exercise layout handling only; no network, no database.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from pipeline.sources import standards_codex as CX
from pipeline.sources import standards_codex_contaminants as CXC
from pipeline.sources import standards_eu as EU
from pipeline.sources import standards_eu_contaminants as EUC
from pipeline.sources import standards_fssai as IN
from pipeline.sources import standards_foods as F
from pipeline.sources import standards_us as US
from pipeline.sources.standards_common import (StandardRow, hazard_key, parse_limit, split_compound,
                                               strip_amendment_marks, to_mg_per_kg)
from models import standards_compare as SC


# ---------------------------------------------------------------- common

@pytest.mark.parametrize("raw,key", [
    ("Chlorpyriphos", "chlorpyrifos"),
    ("Chlorpyrifos (F)", "chlorpyrifos"),
    ("2,4-D", "24d"),
    ("1,4-Dimethylnaphthalene", "14dimethylnaphthalene"),
    ("2,4-Dichlorophenoxy Acetic Acid", "24d"),
    ("Dichlorvos (DDVP) (content of di- chloroacetaldehyde)", "dichlorvos"),
    ("Ethofenprox (Etofenprox)", "etofenprox"),
    ("(c) Mancozeb", "mancozeb"),
    ("(d) Metiram as CS2", "metiram"),
    ("Fluopyram and its metabolites", "fluopyram"),
    ("Cypermethrins (including alpha- and zeta- cypermethrin)", "cypermethrin"),
    ("Lambda-Cyhalothrin (includes gamma-cyhalothrin) (R)", "cyhalothrin"),
    ("Carbendazim and benomyl (sum of benomyl and carbendazim expressed as carbendazim)(R)", "carbendazim"),
    ("2-(Thiocyanomethylthio)benzothiazole", "2thiocyanomethylthiobenzothiazole"),
    ("2, 6-Diisopropylnaphthalene (2, 6-DIPN)", "26diisopropylnaphthalene26dipn"),
    ("Total Aflatoxins", "aflatoxins_total"),
    ("Aflatoxins, total", "aflatoxins_total"),
    ("Arsenic (inorganic)", "arsenic_inorganic"),
    ("Arsenic (total)", "arsenic"),
    ("Methyl Mercury (Calculated as the element)", "methylmercury"),
    ("Paraquat dichloride (Determined as Paraquatcations)", "paraquat"),
    ("Penoxuslum", "penoxsulam"),
])
def test_hazard_key(raw, key):
    assert hazard_key(raw) == key


def test_strip_amendment_marks():
    assert strip_amendment_marks("16[Wheat, wheat bran, rye, barley, coffee") == "Wheat, wheat bran, rye, barley, coffee"
    assert strip_amendment_marks("1000]]") == "1000"
    assert strip_amendment_marks("10]") == "10"


@pytest.mark.parametrize("raw,value,loq,basis,status", [
    ("0.05", Decimal("0.05"), False, None, "exact"),
    ("0.02*", Decimal("0.02"), True, None, "exact"),
    ("0.1 (F)", Decimal("0.1"), False, "fat basis", "exact"),
    ("5.0 on dry matter basis", Decimal("5.0"), False, "dry matter basis", "exact"),
    ("0.1(shell free basis)", Decimal("0.1"), False, "shell-free basis", "exact"),
    ("2.0 ppm", Decimal("2.0"), False, None, "exact"),
    ("0. 4", Decimal("0.4"), False, None, "exact"),
    ("$", None, False, None, "reference"),
    ("Wheat-0.05, Rice-2.0 and other food grains 0.1", None, False, None, "compound"),
    ("15 (But not less than 2.8)", None, False, None, "not_numeric"),
    ("", None, False, None, "not_numeric"),
])
def test_parse_limit(raw, value, loq, basis, status):
    p = parse_limit(raw, "mg/kg")
    assert (p.value, p.at_loq, p.basis, p.status) == (value, loq, basis, status)


def test_parse_limit_units():
    assert parse_limit("5.0 ppb]", None).unit == "µg/kg"
    assert to_mg_per_kg(Decimal("5"), "µg/kg") == Decimal("0.005")
    assert to_mg_per_kg(Decimal("0.01"), "mg/l") is None     # waters are never treated as mg/kg


def test_split_compound_every_number_accounted_for():
    got = split_compound("Food grains", "Maize-0.05, Wheat-2 and Rice-0.1and other food grains- 0.01")
    assert [(f, str(v)) for f, v, _ in got] == [
        ("Food grains (Maize)", "0.05"), ("Food grains (Wheat)", "2"), ("Food grains (Rice)", "0.1"),
        ("Food grains (other food grains)", "0.01")]
    assert [f for f, _, _ in split_compound("Fruit and Vegetables",
                                            "Cherries-25, Grapes-25 and Melons-10, other fruits & other vegetables 15")][-1] \
        == "Fruit and Vegetables (other fruits & other vegetables)"
    # 'Fruit and Vegetables 5' would split into 'Fruit' + 'Vegetables 5': refused, not guessed
    assert split_compound("X", "Fruit and Vegetables 5") == []
    assert split_compound("X", "0.5") == []


# ---------------------------------------------------------------- FSSAI

FSSAI_PAGES = [
    [[["Name of metal\ncontaminant", "Article of food", "Parts per\nMillion\n(mg/kg or\nmg/L)"],
      ["(1)", "(2)", "(3)"],
      ["1. Lead", "Agar", "5.0"],
      [None, "Natural mineral water, expressed in mg/L", "0.01"],
      [None, "Cocoa powder", "5.0 on dry\nmatter basis"]]],
    [[["", "excluding cocoa butter)", ""],            # a food name wrapped onto the next page
      [None, "Turmeric whole and powder", "10"]]],
    [[["S.No.", "Name of the\nContaminants", "Article of the food", "Limit µg/kg"],
      ["(1)", "(2)", "(3)", "(4)"],
      ["1", "Total Aflatoxins", "Nuts:\nNuts for further processing\nReady to eat", "15\n15"],
      [None, None, "Spices/Spice Mix", "30"]],
     [["Sl. No.", "Name of the Insecticide", "Food", "Maximum Residue\nLimit (MRL)\nin mg/kg"],
      ["(1)", "(2)", "(3)", "(4)"],
      ["1.", "2,4-Dichlorophenoxy Acetic Acid", "Food grains", "Maize-0.05, Wheat-2\nand Rice-0.1and other\nfood grains- 0.01"],
      [None, None, "Milk and Milk products", "0.05"],
      ["2.", "Acephate (expressed as mixture of\nMethamidophos and acephate).", "Rice", "1"]]],
    [[["", "", "Chilli", "5"],                          # pesticide continues on a new page
      ["3.", "Chlorpyriphos", "Tea", "2"],
      [None, None, "Rice", "0.02*"]]],
    [[["Sl.No", "Family", "Scientific Name", "Common Name"],   # histamine species list: never limits
      ["1", "Carangidae", "Alectis indica", "Indian Threadfish"]]],
]


def test_fssai_parse_tables():
    rows, serials = IN.parse_tables(FSSAI_PAGES)
    assert serials == [1, 2, 3]
    by = {(r.hazard_raw, r.food_raw): r for r in rows}
    assert by[("Lead", "Agar")].limit_value == Decimal("5.0") and by[("Lead", "Agar")].limit_unit == "mg/kg"
    assert by[("Lead", "Natural mineral water, expressed in mg/L")].limit_unit == "mg/l"
    assert ("Lead", "Cocoa powder excluding cocoa butter)") in by          # wrapped name joined
    assert by[("Lead", "Cocoa powder excluding cocoa butter)")].limit_basis == "dry matter basis"
    assert by[("Total Aflatoxins", "Nuts: Ready to eat")].limit_unit == "µg/kg"
    rice_24d = by[("2,4-Dichlorophenoxy Acetic Acid", "Food grains (Rice)")]
    assert rice_24d.limit_value == Decimal("0.1") and rice_24d.parse_status == "compound_split"
    assert by[("Acephate (expressed as mixture of Methamidophos and acephate).", "Chilli")].limit_value == Decimal("5")
    assert by[("Chlorpyriphos", "Rice")].at_loq is True
    assert not any(r.hazard_raw == "Carangidae" or r.food_raw == "Alectis indica" for r in rows)


def test_fssai_sequence_check():
    IN.check_pesticide_sequence([1, 2, 3], "2.3.1 ...\n3. Chlorpyriphos Tea 2\n2.3.2")
    with pytest.raises(ValueError):
        IN.check_pesticide_sequence([1, 3], "")
    with pytest.raises(ValueError):
        IN.check_pesticide_sequence([1, 2], "2.3.1\n1. A x 1\n2. B y 1\n3. C z 1\n2.3.2")


def test_fssai_biotoxin_and_histamine():
    assert IN._biotoxin_limit("80 μg/100g (Saxitoxin Equivalent)") == Decimal(800)
    assert IN._biotoxin_limit("20 μg/g (Domoic acid equivalent)") == Decimal(20000)
    assert IN._biotoxin_limit("160 μg of Okadaic acid equivalent/Kg") == Decimal(160)
    assert IN._biotoxin_limit("200 mouse units or equivalent/Kg]") is None
    m = IN._SAMPLING_PLAN.search("n=9, c=2; m=100 mg/kg, M=200 mg/kg")
    assert m and m.group(4) == "200"


# ---------------------------------------------------------------- EU pesticides

def test_eu_mrl_rows_dedupes_and_keeps_applicable():
    names = {1: "Chlorpyrifos (F)", 2: "Profenofos (F)"}
    product = {"product_name": "Rice", "product_code": "0500060"}
    base = {"pesticide_residue_id": 1, "regulation_number": "Reg. (EU) 2020/1085", "mrl_lod": "*",
            "mrl_value": "0.01*", "mrl_value_only": "0.01", "applicability_text": "Applicable",
            "application_date": "13/11/2020"}
    mrls = [base, dict(base),                                                   # repeated page
            dict(base, applicability_text="No longer applicable", mrl_value="0.05*", mrl_value_only="0.05"),
            dict(base, pesticide_residue_id=2, application_date="27/04/2017", mrl_value="0.05*",
                 mrl_value_only="0.05"),
            dict(base, pesticide_residue_id=2, application_date="14/09/2023"),
            dict(base, pesticide_residue_id=99)]                                # no English name: skipped
    rows = EU.mrl_rows(mrls, names, product)
    assert [(r.hazard_key, str(r.limit_value), r.at_loq) for r in rows] == [
        ("chlorpyrifos", "0.01", True), ("profenofos", "0.01", True)]


def test_eu_product_label():
    by = {322: {"product_name": "(b) bovine"}}
    assert EU.product_label({"product_name": "Muscle", "product_parent_id": 322, "product_type_id": 4}, by) == "Bovine: muscle"
    assert EU.product_label({"product_name": "Rice", "product_parent_id": 1, "product_type_id": 4}, by) == "Rice"


def test_eu_tox_values():
    vals = EU.tox_values({"tox_value_adi": "0.01 mg/kg bw/day", "tox_source_adi": "EFSA 10",
                          "tox_value_arfd": "0.05 mg/kg bw", "tox_source_earfd": "EFSA 10"})
    assert [(v["value_type"], str(v["value"])) for v in vals] == [("ADI", "0.01"), ("ARfD", "0.05")]


# ---------------------------------------------------------------- EU contaminants

EU_ANNEX = """<table><tr><td>1.1</td><td>Aflatoxins</td><td>Maximum level (μg/kg)</td><td>Remarks</td></tr>
<tr><td></td><td></td><td>B 1</td><td>Sum of B 1 , B 2 , G 1 and G 2</td><td>M 1</td><td>note</td></tr>
<tr><td>1.1.14</td><td>Following dried spices: Capsicum spp. (dried fruits thereof)</td><td>5,0</td><td>10,0</td><td>-</td><td></td></tr>
</table>
<table><tr><td>3.1</td><td>Lead</td><td>Maximum level (mg/kg)</td><td>Remarks</td></tr>
<tr><td>3.1.12</td><td>Spices</td><td></td><td></td></tr>
<tr><td>3.1.12.4</td><td>Root and rhizome spices</td><td>1,50</td><td></td></tr>
<tr><td>3.1.27</td><td>Infant formulae</td><td></td><td></td></tr>
<tr><td>3.1.27.1</td><td>placed on the market as powder</td><td>0,010</td><td></td></tr>
</table>
<table><tr><td>1.4</td><td>Deoxynivalenol</td><td>Maximum level (μg/kg)</td><td>Remarks</td></tr>
<tr><td>1.4.1</td><td>Unprocessed cereal grains</td><td>1 250</td><td></td></tr>
<tr><td>1.8.2.1</td><td>Milling products</td><td>100 50 as from 1 July 2024</td><td></td></tr></table>"""


def test_eu_contaminant_annex():
    from datetime import date
    rows = EUC.parse_annex(EU_ANNEX, "u", "EU 2023/915", today=date(2026, 10, 3))
    got = {(r.hazard_key, r.food_raw): r for r in rows}
    assert got[("aflatoxin_b1", "Following dried spices: Capsicum spp. (dried fruits thereof)")].limit_value == Decimal("5.0")
    assert got[("aflatoxins_total", "Following dried spices: Capsicum spp. (dried fruits thereof)")].limit_value == Decimal("10.0")
    assert not any(r.hazard_raw == "Aflatoxin M1" for r in rows)                  # '-' is not a limit
    assert got[("lead", "Root and rhizome spices")].limit_value == Decimal("1.50")
    assert ("lead", "Infant formulae — placed on the market as powder") in got     # child text gets its parent
    assert got[("deoxynivalenol", "Unprocessed cereal grains")].limit_value == Decimal(1250)
    assert got[("deoxynivalenol", "Milling products")].limit_value == Decimal(50)  # the dated replacement applies


def test_eu_number():
    assert EUC.eu_number("0,050") == Decimal("0.050") and EUC.eu_number("4 000") == Decimal(4000)
    assert EUC.eu_number("1,000.5") is None and EUC.eu_number("-") is None


# ---------------------------------------------------------------- Codex

def test_codex_lenient_json():
    raw = '{\n\t"pesticide": "Chlordane",\n\t"residue": "Sum of "oxychlordane" (fat-soluble).",\n\t"mrls": {"mrl": [\n{"mrl": "0.02",},\n]},\n}'
    d = CX.loads_lenient(raw)
    assert d["residue"] == 'Sum of "oxychlordane" (fat-soluble).' and d["mrls"]["mrl"][0]["mrl"] == "0.02"


def test_codex_detail_rows_only_adopted():
    d = {"pesticide": "2,4-D", "adi": "0-0.01", "adiUnit": "mg/kg bw", "adiNote": "(1996)",
         "mrls": {"mrl": [
             {"mrl": "0.1", "lod": "", "fatPh": "", "step": {"stepCode": "CXL"}, "cacYear": "2001", "jmpr": "1998",
              "commodity": {"name": "Rice, husked", "commCode": "CM 0649"}},
             {"mrl": "0.5", "lod": "(*)", "fatPh": "(fat)", "step": {"stepCode": "CXL"},
              "commodity": {"name": "Milks", "commCode": "ML 0106"}},
             {"mrl": "9", "step": {"stepCode": "5/8"}, "commodity": {"name": "Wheat", "commCode": "GC 0654"}}]}}
    rows, adi = CX.detail_rows("20", d)
    assert [(r.food_code, str(r.limit_value), r.at_loq, r.limit_basis) for r in rows] == [
        ("CM 0649", "0.1", False, None), ("ML 0106", "0.5", True, "fat basis")]
    assert adi["hazard_key"] == "24d" and adi["value"] == Decimal("0.01") and adi["year"] == 1996


def test_codex_contaminants_index_and_tables():
    idx = CXC.parse_index("Table A1: Index of contaminants\nNAME PAGE\nMarine biotoxins 14\nMycotoxins\n"
                          "Aflatoxins, total 15\nAflatoxin M 43\n1\nLead 61")
    assert idx == [("Marine biotoxins", 14), ("Aflatoxins, total", 15), ("Aflatoxin M1", 43), ("Lead", 61)]
    assert CXC.guidance_text("LEAD\nToxicological guidance value: JECFA withdrew\nthe PTWI.\nContaminant definition: Lead") \
        == "JECFA withdrew the PTWI."
    tables = [(16, [["Commodity/\nproduct name", "Maximum level (ML)\nµg/kg", "Portion", "Notes/remarks"],
                    ["Polished rice", "5", "Whole commodity", ""], ["Raw maize grain", "4 000", "", ""]]),
              (17, [["Maximum level", "2 000 µg/kg DON"], ["Number of laboratory samples", "1"]]),   # sampling plan
              (18, [["Lot weight (t)", "Number of incremental samples"], ["≤ 0.05", "3"]])]
    rows = CXC.parse_section("Aflatoxins, total", tables)
    assert [(r.food_raw, str(r.limit_value), r.limit_unit) for r in rows] == [
        ("Polished rice", "5", "µg/kg"), ("Raw maize grain", "4000", "µg/kg")]
    ars = CXC.parse_section("Arsenic", [(56, [["Commodity/ Product name", "Maximum level (ML) mg/kg", "", "Notes"],
                                              ["Rice, husked", "0.35", "", "The ML is for inorganic arsenic (As-in)."],
                                              ["Salt, food grade", "0.5", "", ""]])])
    assert [r.hazard_key for r in ars] == ["arsenic_inorganic", "arsenic"]


# ---------------------------------------------------------------- US

US_XML = b"""<ECFR><DIV8 N="180.342" TYPE="SECTION"><HEAD>&#xA7; 180.342 Chlorpyrifos; tolerances for residues.</HEAD>
<P>(a) <I>General.</I> (1) Tolerances are established ...</P>
<DIV><TABLE><THEAD><TR><TH>Commodity</TH><TH>Parts per million</TH></TR></THEAD><TBODY>
<TR><TD>Banana</TD><TD>0.1</TD></TR>
<TR><TD>Rice, grain<sup>1</sup></TD><TD><sup>1</sup> 0.10</TD></TR>
<TR><TD>Egg</TD><TD>0.05(N)</TD></TR>
<TR><TD>Poultry, meat</TD><TD>.5</TD></TR>
</TBODY></TABLE></DIV>
<P>(b) <I>Section 18 emergency exemptions.</I> [Reserved]</P>
</DIV8>
<DIV8 N="180.900"><HEAD>&#xA7; 180.900 Exemptions from the requirement of a tolerance.</HEAD></DIV8></ECFR>"""


def test_us_parse_part():
    rows = US.parse_part(US_XML)
    got = {r.food_raw: r for r in rows}
    assert set(got) == {"Banana", "Rice, grain", "Egg", "Poultry, meat"}
    assert got["Rice, grain"].limit_value == Decimal("0.10")                # footnote markers dropped
    assert got["Egg"].limit_value == Decimal("0.05") and "negligible" in got["Egg"].note
    assert got["Poultry, meat"].limit_value == Decimal("0.5")
    assert got["Banana"].legal_reference == "40 CFR 180.342(a)" and got["Banana"].hazard_key == "chlorpyrifos"


# ---------------------------------------------------------------- crosswalk

def test_food_crosswalk():
    assert F.match("IN", "Rice") == (["rice"], "specific")
    assert F.match("IN", "Food grains")[1] == "group"
    assert F.match("IN", "Other vegetables")[1] == "residual"
    assert F.match("EU", "Rice", "0500060") == (["rice"], "specific")
    assert F.match("EU", "Root and rhizome spices", "3.1.12.4") == (["turmeric", "ginger"], "group")
    assert F.match("EU", "Fresh ginger, fresh turmeric", "3.1.2.2") == ([], None)
    assert F.match("CODEX", "Peppers chili, dried", "HS 0444") == (["chilli_dried"], "specific")
    assert F.match("CODEX", "Peanuts", None) == (["groundnut"], "specific")
    assert F.match("US", "Grain, cereal, group 15")[1] == "group"
    assert F.match("US", "Rice, grain") == (["rice"], "specific")
    assert F.match("US", "Rice, hulls") == ([], None)


# ---------------------------------------------------------------- comparison

def _row(j, hk, food_keys, mg, match="specific", stype="pesticide_mrl", raw=None):
    return {"jurisdiction": j, "standard_type": stype, "hazard_key": hk, "hazard_raw": raw or hk,
            "food_raw": "x", "food_code": None, "food_keys": food_keys, "food_match": match,
            "limit_raw": str(mg), "limit_mg_per_kg": None if mg is None else Decimal(str(mg)), "at_loq": False,
            "legal_reference": "r", "source_url": "u", "note": None, "applicability": None}


def test_compare_tiers_defaults_and_flags():
    rows = [
        _row("IN", "chlorpyrifos", ["rice"], 0.5), _row("IN", "chlorpyrifos", ["rice"], 0.05, "group"),
        _row("EU", "chlorpyrifos", ["rice"], 0.01), _row("CODEX", "chlorpyrifos", ["rice"], 0.5, "group"),
        _row("IN", "fenobucarb", ["rice"], 0.01),                                     # no EU residue definition
        _row("EU", "other", ["rice"], 0.01),
        _row("IN", "monocrotophos", ["tea"], 0.05),                                   # EU tea not loaded
        _row("IN", "mancozeb", ["rice"], 1), _row("US", "mancozeb", ["rice"], 0.2),  # residue basis differs
        _row("IN", "carbendazim", ["rice"], 2), _row("IN", "carbendazim", ["rice"], 0.5),
    ]
    recs = {(r["hazard_key"], r["food_key"]): r for r in SC.compare(rows, {"rice"}, {"chlorpyrifos", "other"})}
    c = recs[("chlorpyrifos", "rice")]
    assert c["IN"]["value"] == Decimal("0.5") and c["IN"]["basis"] == "specific"   # specific beats group
    assert c["EU"]["ratio_india_over"] == Decimal("50") and "india_higher_than_eu" in c["flags"]
    assert c["CODEX"]["basis"] == "group" and c["CODEX"]["ratio_india_over"] == Decimal("1")
    assert "no_us_tolerance" in c["flags"]
    f = recs[("fenobucarb", "rice")]
    assert f["EU"]["basis"] == "eu_default" and f["EU"]["value"] == Decimal("0.01")
    assert recs[("monocrotophos", "tea")]["EU"]["basis"] == "not_loaded"
    m = recs[("mancozeb", "rice")]
    assert "basis_mismatch" in m["flags"] and m["US"]["ratio_india_over"] is None
    cb = recs[("carbendazim", "rice")]
    assert "india_internal_conflict" in cb["flags"] and cb["IN"]["value"] == Decimal("0.5")   # stricter reading


def test_compare_residual_only_when_nothing_better():
    rows = [_row("IN", "lead", ["tomato"], 2.5, "residual", "contaminant_ml"),
            _row("IN", "lead", ["tomato"], 0.1, "group", "contaminant_ml"),
            _row("IN", "lead", ["mango"], 2.5, "residual", "contaminant_ml"),
            _row("EU", "lead", ["tomato", "mango"], 0.05, "group", "contaminant_ml")]
    recs = {(r["food_key"]): r for r in SC.compare(rows, set(), set())}
    assert recs["tomato"]["IN"]["value"] == Decimal("0.1") and recs["tomato"]["IN"]["basis"] == "group"
    assert recs["mango"]["IN"]["basis"] == "residual" and recs["mango"]["IN"]["value"] == Decimal("2.5")
    assert recs["mango"]["US"]["basis"] == "not_loaded"                           # US contaminants not loaded


def test_standard_row_rejects_unknown_values():
    with pytest.raises(AssertionError):
        StandardRow(jurisdiction="XX", standard_type="pesticide_mrl", hazard_raw="a", hazard_class="pesticide",
                    food_raw="b", limit_raw="1", limit_value=None, limit_unit=None, parse_status="exact",
                    legal_reference="r", source_url="u")
