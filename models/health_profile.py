"""
Health-outcome profiles of recorded contamination: for food from each origin
country, which health outcomes do the hazards found in it point to?

Input: every EU RASFF notification and its hazards (rasff_notifications,
rasff_hazards). Each hazard is (re)classified with the CURRENT knowledge base
(models/health_classifier.classify_hazard) — the stored classification columns
are refreshed here too, so a KB improvement reaches old rows. Each classified
hazard yields the outcomes it can cause (outcomes_for), with their sources.

Output: health_outcome_profile, one row per (origin, outcome): distinct
notifications whose hazards link to the outcome, how many were 'serious', the
hazards and product categories behind it, a per-year series, and whether the
link was through a named hazard or only a hazard class.

This counts contamination findings, not illness. A notification is a border or
market finding by an EU authority; the profile says what those findings imply
health-wise if the food were eaten, with the evidence for each link.

Run: python -m models.health_profile [--min-notifications 20]
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter, defaultdict

from models.health_classifier import classify_hazard, outcomes_for

logger = logging.getLogger("foodsafe.models.health_profile")

# Outcomes reached through several different hazards get one neutral label in the
# profile (each hazard's own wording, e.g. 'Cancer (genotoxic carcinogen)', stays
# in the knowledge base and in /v1/hazards).
SHARED_LABELS = {
    "cancer": "Cancer", "kidney_damage": "Kidney damage", "acute_gastroenteritis": "Gastroenteritis (vomiting, diarrhoea)",
    "neurodevelopmental_impairment": "Impaired brain development in children",
    "cardiovascular_disease": "Cardiovascular disease", "liver_cancer": "Liver cancer",
    "toxin_food_poisoning": "Food poisoning from bacterial toxins", "shellfish_poisoning": "Shellfish poisoning",
    "chronic_neurotoxicity": "Long-term nervous-system effects", "acute_neurotoxicity": "Acute nervous-system effects",
    "cholinergic_poisoning": "Acute cholinergic (organophosphate/carbamate) poisoning",
    "pesticide_toxicity": "Pesticide toxicity (unspecified class)", "reproductive_developmental_toxicity":
    "Reproductive and developmental effects", "viral_hepatitis": "Viral hepatitis", "allergic_reaction":
    "Allergic reaction",
}


def build(rows: list[tuple], min_notifications: int = 20) -> tuple[list[dict], list[tuple]]:
    """rows: (notif_id, origins[], risk_decision, product_category, year, hazard_id,
    hazard, hazard_category, stored_key, stored_class, stored_by).
    Returns (profile records, classification updates for rasff_hazards)."""
    updates = []
    per_notif: dict[int, dict] = {}
    for nid, origins, risk, product, year, hid, hazard, cat, s_key, s_cls, s_by in rows:
        c = classify_hazard(hazard, cat)
        key = c.kb_key or c.hazard_key
        if (key, c.hazard_class, c.classified_by) != (s_key, s_cls, s_by):
            updates.append((key, c.hazard_class, c.classified_by, hid))
        n = per_notif.setdefault(nid, {"origins": origins or [], "serious": risk == "serious", "product": product,
                                       "year": year, "outcomes": {}, "classified": False})
        outs = outcomes_for(c)
        if c.classified_by:
            n["classified"] = True
        for o in outs:
            cur = n["outcomes"].setdefault(o["outcome_key"], {"o": o, "hazards": set(), "level": o["level"]})
            cur["hazards"].add((hazard or "").strip().lower()[:80])
            if o["level"] == "hazard":
                cur["level"] = "hazard"

    scopes: dict[str, list[dict]] = defaultdict(list)
    for n in per_notif.values():
        scopes["ALL"].append(n)
        for o in set(n["origins"]):
            scopes[o].append(n)

    out = []
    for scope, notifs in scopes.items():
        if len(notifs) < min_notifications:
            continue
        classified = sum(1 for n in notifs if n["classified"])
        agg: dict[str, dict] = {}
        for n in notifs:
            for ok, v in n["outcomes"].items():
                a = agg.setdefault(ok, {"o": v["o"], "n": 0, "serious": 0, "levels": Counter(), "hazards": Counter(),
                                        "products": Counter(), "years": Counter(), "sources": {}, "vuln": set()})
                a["n"] += 1
                a["serious"] += n["serious"]
                a["levels"][v["level"]] += 1
                for h in v["hazards"]:
                    a["hazards"][h] += 1
                a["products"][n["product"] or "unclassified"] += 1
                a["years"][str(n["year"])] += 1
                a["sources"][v["o"]["source_url"]] = v["o"]["source_title"]
                a["vuln"].update(v["o"].get("vulnerable_groups") or [])
        for ok, a in agg.items():
            o = a["o"]
            out.append({
                "scope_type": "rasff_origin", "scope_key": scope, "outcome_key": ok,
                "outcome": SHARED_LABELS.get(ok, o["outcome"]),
                "organ_system": o["organ_system"], "exposure": o["exposure"], "notifications": a["n"],
                "share_of_classified": round(a["n"] / classified, 4) if classified else None,
                "serious_notifications": a["serious"], "level_counts": dict(a["levels"]),
                "top_hazards": a["hazards"].most_common(8), "top_products": a["products"].most_common(6),
                "by_year": dict(sorted(a["years"].items())),
                "sources": [{"title": t, "url": u} for u, t in sorted(a["sources"].items())],
                "vulnerable_groups": sorted(a["vuln"]),
            })
    return out, updates


def run(min_notifications: int = 20) -> dict:
    from pipeline.config import pg_connect
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT n.notif_id, n.origin_countries, n.risk_decision, n.product_category,
                                  EXTRACT(YEAR FROM n.validation_date)::int, h.id, h.hazard, h.hazard_category,
                                  h.hazard_key, h.hazard_class, h.classified_by
                           FROM rasff_notifications n JOIN rasff_hazards h USING (notif_id)""")
            rows = cur.fetchall()
        profile, updates = build(rows, min_notifications)
        with conn.cursor() as cur:
            for u in updates:
                cur.execute("UPDATE rasff_hazards SET hazard_key=%s, hazard_class=%s, classified_by=%s WHERE id=%s", u)
            cur.execute("DELETE FROM health_outcome_profile WHERE scope_type = 'rasff_origin'")
            for p in profile:
                cur.execute(
                    """INSERT INTO health_outcome_profile (scope_type, scope_key, outcome_key, outcome, organ_system,
                         exposure, notifications, share_of_classified, serious_notifications, level_counts,
                         top_hazards, top_products, by_year, sources, vulnerable_groups)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (p["scope_type"], p["scope_key"], p["outcome_key"], p["outcome"], p["organ_system"],
                     p["exposure"], p["notifications"], p["share_of_classified"], p["serious_notifications"],
                     json.dumps(p["level_counts"]), json.dumps(p["top_hazards"]), json.dumps(p["top_products"]),
                     json.dumps(p["by_year"]), json.dumps(p["sources"]), p["vulnerable_groups"]))
        conn.commit()
    finally:
        conn.close()
    return {"hazard_rows": len(rows), "reclassified": len(updates), "profile_rows": len(profile),
            "scopes": len({p["scope_key"] for p in profile})}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-notifications", type=int, default=20)
    print(run(ap.parse_args().min_notifications))


if __name__ == "__main__":
    main()
