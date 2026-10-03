"""
EU legal pesticide limits and safety thresholds, from the European Commission's
EU Pesticides Database public API (DG SANTE data lake, no key).

Two things come out of it:
  1. Maximum residue levels (Regulation (EC) No 396/2005) for the foods that
     matter to India's diet and exports (EU_PRODUCT_CODES below — ~50 of the
     database's 381 products: cereals, pulses, oilseeds, tea, coffee, spices,
     tropical fruit, vegetables, milk, eggs, meat, honey). Only MRLs currently
     *applicable* are kept; superseded versions are not loaded.
     -> food_standards (jurisdiction 'EU', pesticide_mrl)
  2. Every active substance's EU approval status and its toxicological
     reference values (ADI, ARfD, AOEL as published by EFSA/the Commission).
     -> hazards (eu_status, eu_category, eu_clp, cas_number)
     -> hazard_reference_values (body 'EU' — the source cell names EFSA/JMPR/...)

EU conventions kept as printed:
  * '0.01*' = the MRL is set at the analytical limit of quantification: no
    authorised use, effectively "no residue permitted" (at_loq = TRUE).
  * An MRL is per *residue definition* (e.g. 'Dithiocarbamates (expressed as
    CS2, including maneb, mancozeb ...)'), not per active substance; the residue
    name is kept as hazard_raw and keyed by its leading substance name.

API (v3.0, paginated with nextLink):
  /pesticide-residues                  every residue definition, in every EU language
  /pesticide-residues-products         product tree (language=EN)
  /pesticide-residues-mrls?product_id  MRL history for one product
  /active-substances                   approval status + ADI/ARfD/AOEL

Run: python -m pipeline.sources.standards_eu [--dry-run] [--products 0500060,0610000]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
import urllib.error
import urllib.request
from decimal import Decimal
from typing import Iterable, Optional

from pipeline.sources.standards_common import StandardRow, clean_text, replace_snapshot, substance_key, summarise

logger = logging.getLogger("foodsafe.standards_eu")

BASE = "https://api.datalake.sante.service.ec.europa.eu/sante/pesticides"
API_VERSION = "v3.0"
DB_URL = "https://food.ec.europa.eu/plants/pesticides/eu-pesticides-database_en"
USER_AGENT = "FoodSafe-India/1.0 (public-interest research; +https://github.com/ultramagnus23/FoodSafe)"
PARSER_VERSION = "eu-pesticides-1"

# EU Annex I product codes chosen for India relevance (diet staples + main exports).
EU_PRODUCT_CODES = [
    # cereals
    "0500030", "0500040", "0500060", "0500080", "0500090",
    # pulses (dry)
    "0300010", "0300020", "0300030",
    # oilseeds
    "0401020", "0401040", "0401070", "0401080", "0401090",
    # tea, coffee, cocoa
    "0610000", "0620000", "0640000",
    # spices
    "0810040", "0810050", "0820040", "0820060", "0840020", "0840030",
    # fruit and nuts
    "0110020", "0110030", "0110040", "0120030", "0120050", "0130010", "0151010", "0163020", "0163030",
    "0163040", "0163050", "0163070", "0163080",
    # vegetables
    "0211000", "0220020", "0231010", "0231020", "0231030", "0231040", "0232010", "0241020", "0242020",
    "0252010", "0260010", "0260040",
    # sugar
    "0900020",
    # animal products
    "1012010", "1016010", "1020010", "1030010", "1040000",
]


class EuApiUnavailable(RuntimeError):
    """The EU Pesticides Database API could not be read — an outage, not 'no limits'."""


def _get(url: str, attempts: int = 4) -> dict:
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                raise
            last = e
        except Exception as e:  # noqa: BLE001 — timeouts, resets
            last = e
        time.sleep(2 * (i + 1))
    raise EuApiUnavailable(f"{url}: {last}")


def _pages(path: str) -> Iterable[dict]:
    url = f"{BASE}{path}{'&' if '?' in path else '?'}format=json&api-version={API_VERSION}"
    while url:
        d = _get(url)
        yield from d.get("value") or []
        url = d.get("nextLink")


# ---------------------------------------------------------------- pure parsing

def residue_names(residues: Iterable[dict]) -> dict[int, str]:
    """pesticide_residue_id -> English name (the API returns every language)."""
    out: dict[int, str] = {}
    for r in residues:
        if (r.get("pesticide_residue_lg") or "").upper() == "EN" and r.get("pesticide_residue_name"):
            out[int(r["pesticide_residue_id"])] = clean_text(r["pesticide_residue_name"])
    return out


def product_label(product: dict, by_id: dict[int, dict]) -> str:
    """'Muscle' under '(b) bovine' -> 'Bovine: muscle'; 'Cattle' under 'Milk' ->
    'Milk: cattle'. Leaf names that only make sense with their parent get it."""
    name = clean_text(product.get("product_name"))
    parent = by_id.get(int(product.get("product_parent_id") or 0))
    if parent and int(product.get("product_type_id") or 0) >= 4 and re.fullmatch(
            r"(muscle|fat|liver|kidney|edible offals.*|cattle|sheep|goat|horse|chicken|duck|goose|quail|others?.*)",
            name, re.I):
        pname = re.sub(r"^\([a-z]\)\s*", "", clean_text(parent.get("product_name"))).strip()
        return f"{pname[:1].upper()}{pname[1:]}: {name.lower()}"
    return name


def mrl_rows(mrls: Iterable[dict], names: dict[int, str], product: dict, label: Optional[str] = None) -> list[StandardRow]:
    """Applicable MRLs for one product -> rows. A residue id with no English name
    is skipped (counted by the caller), never given a made-up label."""
    # The paginated API repeats records across pages, and a residue can carry more
    # than one 'Applicable' entry; keep exactly one per residue — the one applying
    # from the latest date.
    def _applies(m: dict) -> tuple:
        d = (m.get("application_date") or "").split("/")
        return tuple(reversed(d)) if len(d) == 3 else ("",)

    current: dict[int, dict] = {}
    for m in mrls:
        if (m.get("applicability_text") or "") != "Applicable":
            continue
        rid = int(m.get("pesticide_residue_id") or 0)
        if rid not in current or _applies(m) > _applies(current[rid]):
            current[rid] = m
    out = []
    for rid, m in sorted(current.items()):
        name = names.get(rid)
        if not name:
            continue
        raw = (m.get("mrl_value") or "").strip()
        only = (m.get("mrl_value_only") or "").strip()
        value: Optional[Decimal] = None
        try:
            value = Decimal(only) if only else None
        except Exception:  # noqa: BLE001
            value = None
        out.append(StandardRow(
            jurisdiction="EU", standard_type="pesticide_mrl", hazard_raw=name, hazard_class="pesticide",
            food_raw=label or clean_text(product["product_name"]), food_code=product["product_code"],
            limit_raw=raw or only or "", limit_value=value, limit_unit="mg/kg",
            parse_status="exact" if value is not None else "not_numeric",
            at_loq=(m.get("mrl_lod") or "").strip() == "*" or raw.endswith("*"),
            note=clean_text(m.get("footnote_text")) or None, applicability="Applicable",
            legal_reference=clean_text(m.get("regulation_number")) or "Regulation (EC) No 396/2005",
            source_url=(m.get("regulation_url") or DB_URL),
            extra={"pesticide_residue_id": rid, "entry_into_force": m.get("entry_into_force_date")},
        ))
    return out


_TOX_RE = re.compile(r"^\s*([\d.]+)\s*(mg/kg bw(?:/day)?|µg/kg bw(?:/day)?)", re.I)


def tox_values(sub: dict) -> list[dict]:
    """One active substance -> hazard_reference_values rows (ADI/ARfD/AOEL)."""
    out = []
    for vt, val_k, src_k in (("ADI", "tox_value_adi", "tox_source_adi"),
                             ("ARfD", "tox_value_arfd", "tox_source_earfd"),
                             ("AOEL", "tox_value_aoel", "tox_source_aoel")):
        raw = clean_text(sub.get(val_k))
        if not raw:
            continue
        m = _TOX_RE.match(raw)
        value, unit = (None, None)
        if m:
            try:
                value, unit = Decimal(m.group(1)), m.group(2)
            except Exception:  # noqa: BLE001
                value = None
        src = clean_text(sub.get(src_k) or sub.get("tox_sourc_earfd")) or None
        out.append({"value_type": vt, "value": value, "unit": unit, "raw_text": raw,
                    "body": "EU", "source_ref": f"EU Pesticides Database; evaluation: {src}" if src else
                    "EU Pesticides Database", "year": None})
    return out


def substance_record(sub: dict) -> Optional[dict]:
    name = clean_text(sub.get("substance_name"))
    if not name:
        return None
    return {
        # keyed by the single substance (not the residue family): approval status,
        # CAS and toxicological values belong to one active substance
        "hazard_key": substance_key(name), "name": name, "cas_number": clean_text(sub.get("cas_number")) or None,
        "eu_status": clean_text(sub.get("substance_status")) or None,
        "eu_category": clean_text(sub.get("substance_category")) or None,
        "eu_clp": clean_text(sub.get("classification_reg_1272")) or None,
        "tox": tox_values(sub),
    }


# ---------------------------------------------------------------- loading

def merge_substances(subs: list[dict]) -> list[dict]:
    """The API repeats records across pages, and a few names cover several
    distinct registrations (e.g. 'Paraffin oil' under different CAS numbers).
    One record per key: identical repeats collapse; differing statuses become
    'Mixed: A / B' so no single registration's status is shown as the substance's."""
    by: dict[str, list[dict]] = {}
    for s in subs:
        if s and s["hazard_key"]:
            by.setdefault(s["hazard_key"], []).append(s)
    out = []
    for key, group in sorted(by.items()):
        first = dict(group[0])
        statuses = sorted({g["eu_status"] for g in group if g["eu_status"]})
        if len(statuses) > 1:
            first["eu_status"] = "Mixed: " + " / ".join(statuses)
        cas = sorted({g["cas_number"] for g in group if g["cas_number"]})
        first["cas_number"] = cas[0] if len(cas) == 1 else None
        seen, tox = set(), []
        for g in group:
            for v in g["tox"]:
                if v["value_type"] not in seen:
                    seen.add(v["value_type"])
                    tox.append(v)
        first["tox"] = tox if len({g["name"] for g in group}) == 1 else []   # values of one registration only
        out.append(first)
    return out


def load_substances(conn, subs: list[dict]) -> dict:
    n_h = n_v = 0
    subs = merge_substances(subs)
    with conn.cursor() as cur:
        for s in subs:
            if not s or not s["hazard_key"]:
                continue
            cur.execute(
                """INSERT INTO hazards (hazard_key, name, hazard_class, cas_number, eu_status, eu_category, eu_clp,
                                        sources, updated_at)
                   VALUES (%s,%s,'pesticide',%s,%s,%s,%s,%s,NOW())
                   ON CONFLICT (hazard_key) DO UPDATE SET
                     cas_number = COALESCE(hazards.cas_number, EXCLUDED.cas_number),
                     eu_status = EXCLUDED.eu_status, eu_category = EXCLUDED.eu_category,
                     eu_clp = EXCLUDED.eu_clp, updated_at = NOW()""",
                (s["hazard_key"], s["name"], s["cas_number"], s["eu_status"], s["eu_category"], s["eu_clp"],
                 json.dumps([{"title": "EU Pesticides Database (active substances)", "url": DB_URL}])))
            n_h += 1
            for v in s["tox"]:
                cur.execute(
                    """INSERT INTO hazard_reference_values (hazard_key, body, value_type, value, unit, raw_text, year,
                                                            source_ref, source_url)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (hazard_key, body, value_type) DO UPDATE SET value=EXCLUDED.value,
                         unit=EXCLUDED.unit, raw_text=EXCLUDED.raw_text, source_ref=EXCLUDED.source_ref,
                         loaded_at=NOW()""",
                    (s["hazard_key"], v["body"], v["value_type"], v["value"], v["unit"], v["raw_text"], v["year"],
                     v["source_ref"], DB_URL))
                n_v += 1
    conn.commit()
    return {"substances": n_h, "reference_values": n_v}


def fetch_all(product_codes: list[str]) -> tuple[list[StandardRow], list[dict], dict]:
    plist = list(_pages("/pesticide-residues-products?language=EN"))
    products = {p["product_code"]: p for p in plist}
    by_id = {int(p["product_id"]): p for p in plist}
    if not products:
        raise EuApiUnavailable("product list came back empty")
    names = residue_names(_pages("/pesticide-residues"))
    if len(names) < 100:
        raise EuApiUnavailable(f"only {len(names)} English residue names — the residue list looks truncated")
    rows: list[StandardRow] = []
    missing = []
    for code in product_codes:
        p = products.get(code)
        if not p:
            missing.append(code)
            continue
        got = mrl_rows(_pages(f"/pesticide-residues-mrls?product_id={p['product_id']}"), names, p,
                       product_label(p, by_id))
        logger.info("EU %s %s: %d applicable MRLs", code, p["product_name"], len(got))
        rows += got
    subs = [s for s in (substance_record(x) for x in _pages("/active-substances")) if s]
    info = {"products_requested": len(product_codes), "products_missing": missing,
            "residue_names": len(names), "active_substances": len(subs)}
    return rows, subs, info


def run_substances_only(dry_run: bool = False) -> dict:
    """Refresh approval status and ADI/ARfD/AOEL without re-reading any MRLs."""
    subs = [s for s in (substance_record(x) for x in _pages("/active-substances")) if s]
    if len(subs) < 1000:
        raise EuApiUnavailable(f"only {len(subs)} active substances listed")
    if dry_run:
        return {"active_substances": len(subs), "dry_run": True}
    from pipeline.config import pg_connect
    conn = pg_connect()
    try:
        return {"active_substances": len(subs), **load_substances(conn, subs)}
    finally:
        conn.close()


def run(dry_run: bool = False, product_codes: Optional[list[str]] = None) -> dict:
    rows, subs, info = fetch_all(product_codes or EU_PRODUCT_CODES)
    info.update(summarise(rows))
    if dry_run:
        return {**info, "inserted": 0, "dry_run": True}
    from pipeline.config import pg_connect
    conn = pg_connect()
    try:
        res = replace_snapshot(conn, "EU", {"pesticide_mrl"}, rows,
                               document_title="EU Pesticides Database — MRLs (Reg. (EC) 396/2005), applicable",
                               document_url=DB_URL, document_version=time.strftime("%Y-%m-%d"),
                               document_sha256=None, parser_version=PARSER_VERSION)
        res.update(load_substances(conn, subs))
    finally:
        conn.close()
    return {**info, **res}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--products", help="comma-separated EU product codes (default: the India-relevant set)")
    ap.add_argument("--substances-only", action="store_true", help="refresh approval status / ADI / ARfD only")
    a = ap.parse_args()
    if a.substances_only:
        print(run_substances_only(a.dry_run))
    else:
        print(run(a.dry_run, a.products.split(",") if a.products else None))


if __name__ == "__main__":
    main()
