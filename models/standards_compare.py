"""
India vs EU vs Codex vs US: one comparison row per (hazard, food) that India
regulates, computed from `food_standards` and written to `standards_comparison`.

For each (hazard_key, food_key) with an India limit it records, per rule-book:

  value      the limit in mg/kg, or NULL
  basis      how that value was found — never blended:
               'specific'      a row naming this food
               'group'         a row naming a group that covers this food
               'eu_default'    EU only: the substance has no EU residue definition
                               for this food, so Reg. (EC) 396/2005 Art. 18(1)(b)'s
                               general default of 0.01 mg/kg applies
               'none'          the rule-book sets nothing for it (Codex: no
                               standard; US: no tolerance, i.e. no residue is legal)
               'not_loaded'    the rule-book's limits for this food were not loaded
                               (e.g. an EU product outside the India-relevant set)
  rows       the printed rows behind the value (for display and audit)

and the India/other ratios where both values exist. A ratio > 1 means India's
limit is HIGHER (more permissive) than the other rule-book's.

Comparability guards (no ratio is computed when they fail):
  * both limits must be numeric mass fractions (limit_mg_per_kg);
  * substances whose residue is expressed on different chemical bases across
    rule-books (dithiocarbamates: as CS2 in the EU/Codex/India, as the parent
    compound in some US tolerances) are flagged `basis_mismatch`;
  * if India itself prints two different limits for the same pair (e.g. a
    'Food grains (Rice)' value and a separate 'Rice' row), the pair is flagged
    `india_internal_conflict` and the LOWER value is used for ratios — the
    stricter reading, so a 'more permissive' flag is never inflated by it.

Why India's pesticide limit is above the EU's — one reason flag per such pair
(`eu_gap_reason`), read from the EU value itself, not inferred:
  eu_gap_never_assessed   the EU has no residue definition: the 0.01 mg/kg default
  eu_gap_not_approved     the EU limit is set at the limit of quantification and
                          the substance is not approved in the EU (no legal use)
  eu_gap_no_use_on_food   EU limit at the limit of quantification for this food,
                          though the substance is approved: no authorised EU use on it
  eu_gap_at_loq           EU limit at the limit of quantification, approval status
                          unknown or mixed
  eu_gap_above_loq        the EU sets a residue level above quantification (an
                          authorised EU use, an import tolerance or a temporary
                          limit; for a substance not approved in the EU it is one
                          of the latter two), and India's limit is higher still
A limit at quantification means "no residue should be found", not a level judged
safe, so most of the India > EU gap is the EU not permitting a use rather than
the EU tolerating a smaller residue.

Run after the standards loaders:  python -m models.standards_compare
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from decimal import Decimal
from typing import Optional

logger = logging.getLogger("foodsafe.models.standards_compare")

EU_DEFAULT_MRL = Decimal("0.01")
BASIS_MISMATCH_KEYS = {"dithiocarbamates", "mancozeb", "maneb", "metiram", "zineb", "thiram", "ziram", "propineb",
                       "ethylenebisdithiocarbamates"}
JURIS = ("IN", "EU", "CODEX", "US")


def _row(r: dict) -> dict:
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in r.items()
            if k in ("food_raw", "food_code", "hazard_raw", "limit_raw", "limit_mg_per_kg", "at_loq", "food_match",
                     "legal_reference", "source_url", "note", "applicability")}


def pick(rows: list[dict]) -> tuple[Optional[Decimal], str, list[dict], bool]:
    """rows of one rule-book for one (hazard, food) -> (value, basis, rows used,
    internal_conflict). Specific rows beat group rows, which beat catch-all
    ('Other vegetables', 'Foods not specified') rows."""
    numeric = [r for r in rows if r["limit_mg_per_kg"] is not None]
    for basis in ("specific", "group", "residual"):
        cand = [r for r in numeric if r["food_match"] == basis]
        if cand:
            values = {Decimal(str(r["limit_mg_per_kg"])) for r in cand}
            return min(values), basis, cand, len(values) > 1
    if rows:
        return None, "not_numeric", rows, False
    return None, "none", [], False


def eu_gap_reason(rec: dict) -> Optional[str]:
    """For a pesticide pair where India's limit is above the EU's: why (see the
    module docstring). None for anything else."""
    if rec["standard_type"] != "pesticide_mrl" or "india_higher_than_eu" not in rec["flags"]:
        return None
    eu = rec["EU"]
    if eu["basis"] == "eu_default":
        return "eu_gap_never_assessed"
    if eu["rows"] and all(r.get("at_loq") for r in eu["rows"]):
        status = (rec.get("eu_status") or "").strip().lower()
        if status.startswith("not approved"):
            return "eu_gap_not_approved"
        if status.startswith("approved"):
            return "eu_gap_no_use_on_food"
        return "eu_gap_at_loq"
    return "eu_gap_above_loq"


def compare(rows: list[dict], eu_foods_loaded: set[str], eu_hazards_loaded: set[str],
            substances: Optional[dict[str, tuple]] = None) -> list[dict]:
    """Pure: food_standards rows (dicts) -> comparison records. Only pesticide
    MRLs are compared here; contaminant MLs go through the same function with
    standard_type='contaminant_ml'."""
    by: dict[tuple, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if not r["hazard_key"]:
            continue
        for fk in r["food_keys"] or []:
            by[(r["standard_type"], r["hazard_key"], fk)][r["jurisdiction"]].append(r)
    out = []
    for (stype, hk, fk), per in sorted(by.items()):
        if not per.get("IN"):
            continue
        from pipeline.sources.standards_common import substance_key
        sk = substance_key(per["IN"][0]["hazard_raw"])
        status, iarc = (substances or {}).get(sk) or (substances or {}).get(hk) or (None, None)
        rec = {"standard_type": stype, "hazard_key": hk, "food_key": fk,
               "hazard_name": per["IN"][0]["hazard_raw"], "flags": [], "in_substance_key": sk,
               "eu_status": status, "iarc_group": iarc}
        for j in JURIS:
            value, basis, used, conflict = pick(per.get(j, []))
            if j == "EU" and stype == "pesticide_mrl" and basis == "none":
                if fk not in eu_foods_loaded:
                    basis = "not_loaded"
                elif hk not in eu_hazards_loaded:
                    value, basis = EU_DEFAULT_MRL, "eu_default"
            if j in ("CODEX", "US") and stype != "pesticide_mrl" and basis == "none":
                basis = "not_loaded" if j == "US" else basis
            rec[j] = {"value": value, "basis": basis, "rows": [_row(u) for u in used]}
            if j == "IN" and conflict:
                rec["flags"].append("india_internal_conflict")
        if hk in BASIS_MISMATCH_KEYS:
            rec["flags"].append("basis_mismatch")
        india = rec["IN"]["value"]
        for j in ("EU", "CODEX", "US"):
            other = rec[j]["value"]
            ratio = None
            if india is not None and other is not None and other > 0 and "basis_mismatch" not in rec["flags"]:
                ratio = (india / other).quantize(Decimal("0.0001"))
            rec[j]["ratio_india_over"] = ratio
            if ratio is not None and ratio > 1:
                rec["flags"].append(f"india_higher_than_{j.lower()}")
            if india is not None and rec[j]["basis"] == "none" and j == "US" and stype == "pesticide_mrl":
                rec["flags"].append("no_us_tolerance")
            if india is not None and rec[j]["basis"] == "none" and j == "CODEX":
                rec["flags"].append("no_codex_standard")
        reason = eu_gap_reason(rec)
        if reason:
            rec["flags"].append(reason)
        out.append(rec)
    return out


def rekey(conn) -> int:
    """Recompute hazard_key / food_keys / food_match for every stored row from its
    printed names, with the CURRENT normalisers. Aliases and the food crosswalk
    are code; a change to them must reach rows loaded before the change without
    re-fetching any rule-book. Returns the number of rows whose keys changed."""
    from pipeline.sources.standards_common import hazard_key
    from pipeline.sources.standards_foods import match
    changed = 0
    with conn.cursor() as cur:
        cur.execute("SELECT id, jurisdiction, hazard_raw, food_raw, food_code, hazard_key, food_keys, food_match "
                    "FROM food_standards")
        rows = cur.fetchall()
        updates = []
        for rid, j, hz, food, code, old_hk, old_fk, old_fm in rows:
            hk = hazard_key(hz)
            fk, fm = match(j, food, code)
            if hk != old_hk or list(fk) != list(old_fk or []) or fm != old_fm:
                updates.append((hk, fk, fm, rid))
        from psycopg2.extras import execute_batch
        execute_batch(cur, "UPDATE food_standards SET hazard_key=%s, food_keys=%s, food_match=%s WHERE id=%s",
                      updates, page_size=500)
        changed = len(updates)
    conn.commit()
    return changed


def _fetch_rows(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""SELECT jurisdiction, standard_type, hazard_key, hazard_raw, food_raw, food_code, food_keys,
                              food_match, limit_raw, limit_mg_per_kg, at_loq, legal_reference, source_url, note,
                              applicability
                       FROM food_standards
                       WHERE standard_type IN ('pesticide_mrl', 'contaminant_ml')
                         AND hazard_key IS NOT NULL AND cardinality(food_keys) > 0""")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _eu_universe(conn) -> tuple[set[str], set[str]]:
    with conn.cursor() as cur:
        cur.execute("""SELECT DISTINCT unnest(food_keys) FROM food_standards
                       WHERE jurisdiction='EU' AND standard_type='pesticide_mrl'""")
        foods = {r[0] for r in cur.fetchall()}
        cur.execute("""SELECT DISTINCT hazard_key FROM food_standards
                       WHERE jurisdiction='EU' AND standard_type='pesticide_mrl' AND hazard_key IS NOT NULL""")
        hazards = {r[0] for r in cur.fetchall()}
    return foods, hazards


def _num(v):
    return None if v is None else Decimal(v)


def store(conn, recs: list[dict]) -> int:
    from psycopg2.extras import execute_batch
    with conn.cursor() as cur:
        cur.execute("DELETE FROM standards_comparison")
        execute_batch(cur,
            """INSERT INTO standards_comparison
                 (standard_type, hazard_key, food_key, hazard_name,
                  in_value, eu_value, eu_basis, codex_value, codex_basis, us_value, us_basis,
                  ratio_in_eu, ratio_in_codex, ratio_in_us, flags, in_substance_key, eu_status, iarc_group,
                  detail)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            [(r["standard_type"], r["hazard_key"], r["food_key"], r["hazard_name"],
              _num(r["IN"]["value"]), _num(r["EU"]["value"]), r["EU"]["basis"],
              _num(r["CODEX"]["value"]), r["CODEX"]["basis"], _num(r["US"]["value"]), r["US"]["basis"],
              r["EU"]["ratio_india_over"], r["CODEX"]["ratio_india_over"], r["US"]["ratio_india_over"],
              sorted(set(r["flags"])), r.get("in_substance_key"), r.get("eu_status"), r.get("iarc_group"),
              json.dumps({j: {"basis": r[j]["basis"], "rows": r[j]["rows"]} for j in JURIS}, default=str))
             for r in recs], page_size=500)
    conn.commit()
    return len(recs)


def run() -> dict:
    from pipeline.config import pg_connect
    conn = pg_connect()
    try:
        rekeyed = rekey(conn)
        rows = _fetch_rows(conn)
        foods, hazards = _eu_universe(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT hazard_key, eu_status, iarc_group FROM hazards")
            substances = {k: (st, ig) for k, st, ig in cur.fetchall()}
        recs = compare(rows, foods, hazards, substances)
        n = store(conn, recs)
    finally:
        conn.close()
    flags = defaultdict(int)
    for r in recs:
        for f in set(r["flags"]):
            flags[f] += 1
    return {"rekeyed_rows": rekeyed, "comparisons": n, **dict(flags)}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    print(run())


if __name__ == "__main__":
    main()
