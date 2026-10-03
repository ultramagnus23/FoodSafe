"""
How much of a contaminated food reaches a health-based guidance value?

For a hazard measured at C mg/kg in a food, and a guidance value G (mg per kg
body weight), a person of body weight W kg reaches G after eating

    amount_g = G x W / C x 1000

  * chronic: G = ADI / TDI (per day; a weekly or monthly value is divided by 7
    or 30). "Eating this much every day, for life, stays within the
    acceptable/tolerable intake."
  * acute:   G = ARfD (one day / one meal). "Eating more than this in one day
    exceeds the acute reference dose."

Guidance values come from hazard_reference_values: EU (EFSA) ADI/ARfD, JMPR
ADIs (Codex database), and numeric values printed in JECFA's toxicological
guidance text in Codex CXS 193 (PTWI / PMTDI / TDI / ARfD in mg/kg bw).

Genotoxic carcinogens have no tolerable intake (aflatoxins, ethylene oxide,
inorganic arsenic since JECFA withdrew its PTWI, lead since JECFA withdrew its
PTWI): for them the result is "no safe amount can be computed — exposure should
be as low as reasonably achievable", never a number.

This uses the measured value of ONE sample. It is an illustration of what a
finding means, not an exposure assessment of anyone's diet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

NO_THRESHOLD = {   # hazard_key -> why no tolerable intake exists (source in hazard_kb)
    "aflatoxins_total": "genotoxic carcinogen: JECFA advises intake as low as reasonably possible",
    "aflatoxin_b1": "genotoxic carcinogen: JECFA advises intake as low as reasonably possible",
    "aflatoxin_m1": "genotoxic carcinogen (aflatoxin metabolite)",
    "ethylene_oxide": "genotoxic carcinogen (IARC Group 1): no safe level",
    "arsenic_inorganic": "JECFA withdrew its tolerable intake in 2010 (carcinogen)",
    "arsenic": "JECFA withdrew its tolerable intake for inorganic arsenic in 2010",
    "lead": "JECFA withdrew its tolerable intake in 2010: no level is known to be without harm (WHO)",
    "benzo_a_pyrene": "genotoxic carcinogen (IARC Group 1)",
    "nitrofurans": "genotoxic carcinogenic metabolites: not permitted at any level",
    "chloramphenicol": "no safe residue level (aplastic anaemia): not permitted at any level",
    "malachitegreen": "genotoxic: not permitted at any level",
    "sudan_dyes": "illegal dye, genotoxic: not permitted at any level",
    "chlorpyrifos": "EFSA (2019) could not set safe levels (genotoxicity and developmental neurotoxicity concerns); "
                    "EU approval not renewed in 2020 (doi:10.2903/j.efsa.2019.5809)",
    "chlorpyrifosmethyl": "EFSA (2019) could not set safe levels; EU approval not renewed in 2020 "
                          "(doi:10.2903/j.efsa.2019.5810)",
}
PRACTICAL_LIMIT_G = Decimal(10000)      # above 10 kg a day the amount is not reachable by eating

_GUIDANCE = re.compile(r"\b(PMTDI|PTWI|PTMI|TDI|ARfD|ADI)\s+(\d+(?:\.\d+)?)\s*(mg|µg|μg)/kg\s*bw", re.I)


@dataclass
class Guidance:
    kind: str                  # 'chronic' | 'acute'
    value_mg_per_kg_bw_day: Decimal
    label: str                 # e.g. 'ADI 0.001 mg/kg bw/day (EU)'
    source_ref: Optional[str]
    source_url: Optional[str]


def parse_jecfa_text(text: str) -> list[tuple[str, Decimal, str]]:
    """'Group PMTDI 0.001 mg/kg bw ... Group ARfD 0.008 mg/kg bw' ->
    [('chronic', 0.001, 'PMTDI 0.001 mg/kg bw'), ('acute', 0.008, 'ARfD 0.008 mg/kg bw')].
    Weekly / monthly values are converted to per day."""
    out = []
    for kind, num, unit in _GUIDANCE.findall(text or ""):
        v = Decimal(num)
        if unit.lower() in ("µg", "μg"):
            v = v / 1000
        k = kind.upper()
        per_day = v / 7 if k == "PTWI" else (v / 30 if k == "PTMI" else v)
        out.append(("acute" if k == "ARFD" else "chronic", per_day, f"{kind} {num} {unit}/kg bw"))
    return out


def pick_guidance(ref_rows: list[dict]) -> dict[str, Guidance]:
    """hazard_reference_values rows for one hazard -> best chronic and acute value.
    Preference: EU (EFSA) > JMPR > JECFA text."""
    best: dict[str, Guidance] = {}
    order = {"EU": 0, "JMPR": 1, "JECFA": 2}
    for r in sorted(ref_rows, key=lambda r: order.get(r["body"], 9)):
        candidates = []
        if r["value_type"] in ("ADI", "ARfD") and r["value"] is not None and "mg/kg bw" in (r["unit"] or ""):
            kind = "acute" if r["value_type"] == "ARfD" else "chronic"
            candidates.append((kind, Decimal(str(r["value"])), f"{r['value_type']} {r['value']} {r['unit']}"))
        elif r["value_type"] == "guidance":
            candidates = parse_jecfa_text(r["raw_text"])
        for kind, v, label in candidates:
            if kind not in best and v > 0:
                best[kind] = Guidance(kind, v, f"{label} ({r['body']})", r.get("source_ref"), r.get("source_url"))
    return best


def safe_amount_g(guidance_mg_per_kg_bw: Decimal, concentration_mg_per_kg: Decimal,
                  body_weight_kg: Decimal) -> Optional[Decimal]:
    if concentration_mg_per_kg is None or concentration_mg_per_kg <= 0:
        return None
    return (guidance_mg_per_kg_bw * body_weight_kg / concentration_mg_per_kg * 1000).quantize(Decimal("0.1"))


def assess(hazard_key: Optional[str], concentration_mg_per_kg: Optional[Decimal], body_weight_kg: Decimal,
           ref_rows: list[dict]) -> dict:
    if hazard_key in NO_THRESHOLD:
        return {"computable": False, "reason": NO_THRESHOLD[hazard_key], "chronic": None, "acute": None}
    g = pick_guidance(ref_rows)
    if concentration_mg_per_kg is None or not g:
        return {"computable": False, "chronic": None, "acute": None,
                "reason": "no measured concentration" if concentration_mg_per_kg is None
                else "no health-based guidance value on record for this hazard"}
    out = {"computable": True, "reason": None}
    for kind in ("chronic", "acute"):
        x = g.get(kind)
        grams = safe_amount_g(x.value_mg_per_kg_bw_day, concentration_mg_per_kg, body_weight_kg) if x else None
        out[kind] = None if not x else {
            "grams": float(grams), "reachable_by_eating": grams <= PRACTICAL_LIMIT_G,
            "guidance": x.label, "source_ref": x.source_ref, "source_url": x.source_url,
            "meaning": ("eaten every day for life stays within the acceptable/tolerable intake" if kind == "chronic"
                        else "eaten in one day stays within the acute reference dose")}
    return out
