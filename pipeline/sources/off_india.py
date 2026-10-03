"""
Packaged foods sold in India, from Open Food Facts (open, crowd-sourced product
database, ODbL; https://world.openfoodfacts.org), with a nutrition classification.

What is read: every product tagged with country India (~24,600), from OFF's
daily bulk CSV export (streamed and filtered, ~1.3 GB gzipped; the route OFF asks
bulk users to take — its search API returns 503s on deep pages). `--api` pages
through the v2 search API instead (100 per page, <= 9 requests a minute). Fields: barcode, name, brand, categories, nutrients per 100 g/ml,
Nutri-Score and NOVA group (as OFF computes them), additives, allergens,
ingredients text.

What it is: product labels typed in by contributors and checked by OFF's own
consistency rules — not laboratory analyses and not a sample of what Indians eat.
A product's nutrition values are only as good as its label photo transcription.

Classification (models/nutrition.py): UK DHSC front-of-pack traffic lights (fat,
saturates, sugars, salt: low / medium / high) and the 'high in' list.

-> packaged_foods (migration 026)

Run: python -m pipeline.sources.off_india [--max-pages N] [--dump file.jsonl] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from models.nutrition import salt_g, traffic_lights

logger = logging.getLogger("foodsafe.off_india")

SEARCH = "https://world.openfoodfacts.org/api/v2/search"
USER_AGENT = "FoodSafe-India/1.0 (public-interest research; https://github.com/ultramagnus23/FoodSafe)"
FIELDS = ("code,product_name,product_name_en,brands,categories_tags,countries_tags,nutriscore_grade,nutriscore_score,"
          "nova_group,nutriments,ingredients_text,ingredients_text_en,additives_tags,allergens_tags,last_modified_t,"
          "quantity")
PAGE_SIZE = 100
DELAY_S = 6.7          # <= 9 requests/minute


class OffUnavailable(RuntimeError):
    pass


def _get(url: str, attempts: int = 5) -> dict:
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            time.sleep(30 if e.code == 429 else 5 * (i + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 * (i + 1))
    raise OffUnavailable(f"{url}: {last}")


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and v == v and v >= 0 else None


def parse_product(p: dict) -> Optional[dict]:
    code = str(p.get("code") or "").strip()
    if not code.isdigit():
        return None
    n = p.get("nutriments") or {}
    nutrients = {"fat": _num(n.get("fat_100g")), "saturates": _num(n.get("saturated-fat_100g")),
                 "sugars": _num(n.get("sugars_100g")), "salt": salt_g(n)}
    cats = [c for c in p.get("categories_tags") or [] if isinstance(c, str)]
    grade = (p.get("nutriscore_grade") or "").lower()
    return {
        "code": code,
        "product_name": (p.get("product_name_en") or p.get("product_name") or "").strip() or None,
        "brands": (p.get("brands") or "").strip() or None,
        "categories": cats[:30],
        "countries": [c for c in p.get("countries_tags") or [] if isinstance(c, str)][:20],
        "nutriscore_grade": grade if grade in ("a", "b", "c", "d", "e") else None,
        "nutriscore_score": p.get("nutriscore_score") if isinstance(p.get("nutriscore_score"), int) else None,
        "nova_group": p.get("nova_group") if p.get("nova_group") in (1, 2, 3, 4) else None,
        "energy_kcal_100g": _num(n.get("energy-kcal_100g")),
        "fat_100g": nutrients["fat"], "saturated_fat_100g": nutrients["saturates"],
        "sugars_100g": nutrients["sugars"], "salt_100g": nutrients["salt"],
        "fiber_100g": _num(n.get("fiber_100g")), "proteins_100g": _num(n.get("proteins_100g")),
        "additives": [a for a in p.get("additives_tags") or [] if isinstance(a, str)][:40],
        "allergens": [a for a in p.get("allergens_tags") or [] if isinstance(a, str)][:20],
        "ingredients_text": ((p.get("ingredients_text_en") or p.get("ingredients_text") or "").strip()[:4000]) or None,
        "quantity": (p.get("quantity") or "").strip()[:80] or None,
        "last_modified": datetime.fromtimestamp(p["last_modified_t"], tz=timezone.utc)
        if isinstance(p.get("last_modified_t"), int) else None,
        "nutrition": traffic_lights(nutrients, cats),
    }


def fetch(max_pages: Optional[int] = None, dump: Optional[str] = None) -> list[dict]:
    first = _get(f"{SEARCH}?countries_tags_en=india&page_size={PAGE_SIZE}&page=1&fields={FIELDS}")
    total = int(first.get("count") or 0)
    if total < 1000:
        raise OffUnavailable(f"Open Food Facts reports only {total} India products")
    pages = -(-total // PAGE_SIZE)
    if max_pages:
        pages = min(pages, max_pages)
    raw = list(first.get("products") or [])
    out = open(dump, "w", encoding="utf-8") if dump else None
    try:
        for p in raw:
            if out:
                out.write(json.dumps(p) + "\n")
        for page in range(2, pages + 1):
            time.sleep(DELAY_S)
            d = _get(f"{SEARCH}?countries_tags_en=india&page_size={PAGE_SIZE}&page={page}&fields={FIELDS}")
            items = d.get("products") or []
            raw += items
            if out:
                for p in items:
                    out.write(json.dumps(p) + "\n")
                out.flush()
            if page % 25 == 0:
                logger.info("OFF page %d/%d (%d products)", page, pages, len(raw))
    finally:
        if out:
            out.close()
    return raw


BULK_CSV = "https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz"
_CSV_NUM = {"energy-kcal_100g", "fat_100g", "saturated-fat_100g", "sugars_100g", "salt_100g", "sodium_100g",
            "fiber_100g", "proteins_100g"}


def _csv_float(v: str):
    try:
        return float(v) if v not in ("", None) else None
    except ValueError:
        return None


def csv_row_to_api(row: dict) -> dict:
    """One row of the bulk CSV export -> the shape the v2 API returns, so both
    paths share parse_product()."""
    split = lambda s: [x for x in (s or "").split(",") if x]                       # noqa: E731
    nutr = {k: _csv_float(row.get(k)) for k in _CSV_NUM}
    nova = row.get("nova_group") or ""
    score = row.get("nutriscore_score") or ""
    return {
        "code": row.get("code"), "product_name": row.get("product_name"), "brands": row.get("brands"),
        "categories_tags": split(row.get("categories_tags")), "countries_tags": split(row.get("countries_tags")),
        "nutriscore_grade": row.get("nutriscore_grade"),
        "nutriscore_score": int(float(score)) if score.lstrip("-").replace(".", "", 1).isdigit() else None,
        "nova_group": int(float(nova)) if nova.replace(".", "", 1).isdigit() else None,
        "nutriments": {k: v for k, v in nutr.items() if v is not None},
        "ingredients_text": row.get("ingredients_text"), "additives_tags": split(row.get("additives_tags")),
        "allergens_tags": split(row.get("allergens")), "quantity": row.get("quantity"),
        "last_modified_t": int(row["last_modified_t"]) if (row.get("last_modified_t") or "").isdigit() else None,
    }


def fetch_bulk(country_tag: str = "en:india", dump: Optional[str] = None) -> list[dict]:
    """Stream Open Food Facts' daily CSV export (~1.3 GB gzipped, the route OFF asks
    bulk users to take) and keep the rows tagged with `country_tag`. Nothing is
    written to disk unless `dump` is given."""
    import csv
    import gzip
    import io
    import sys

    csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))
    req = urllib.request.Request(BULK_CSV, headers={"User-Agent": USER_AGENT})
    out = open(dump, "w", encoding="utf-8") if dump else None
    kept: list[dict] = []
    scanned = 0
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            text = io.TextIOWrapper(gzip.GzipFile(fileobj=resp), encoding="utf-8", errors="replace", newline="")
            reader = csv.DictReader(text, delimiter="\t", quoting=csv.QUOTE_NONE)
            for row in reader:
                scanned += 1
                if country_tag not in (row.get("countries_tags") or ""):
                    continue
                api = csv_row_to_api(row)
                if country_tag not in api["countries_tags"]:
                    continue
                kept.append(api)
                if out:
                    out.write(json.dumps(api) + "\n")
                if scanned % 500000 == 0:
                    logger.info("OFF bulk: %d rows scanned, %d kept", scanned, len(kept))
    finally:
        if out:
            out.close()
    if scanned < 1_000_000:
        raise OffUnavailable(f"bulk export ended after {scanned} rows: truncated download?")
    logger.info("OFF bulk: %d rows scanned, %d for %s", scanned, len(kept), country_tag)
    return kept


def load(conn, products: list[dict]) -> int:
    from psycopg2.extras import execute_batch
    with conn.cursor() as cur:
        execute_batch(cur,
                """INSERT INTO packaged_foods (code, product_name, brands, categories, countries, nutriscore_grade,
                     nutriscore_score, nova_group, energy_kcal_100g, fat_100g, saturated_fat_100g, sugars_100g,
                     salt_100g, fiber_100g, proteins_100g, additives, allergens, ingredients_text, quantity,
                     last_modified, nutrition, fetched_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                   ON CONFLICT (code) DO UPDATE SET product_name=EXCLUDED.product_name, brands=EXCLUDED.brands,
                     categories=EXCLUDED.categories, countries=EXCLUDED.countries,
                     nutriscore_grade=EXCLUDED.nutriscore_grade, nutriscore_score=EXCLUDED.nutriscore_score,
                     nova_group=EXCLUDED.nova_group, energy_kcal_100g=EXCLUDED.energy_kcal_100g,
                     fat_100g=EXCLUDED.fat_100g, saturated_fat_100g=EXCLUDED.saturated_fat_100g,
                     sugars_100g=EXCLUDED.sugars_100g, salt_100g=EXCLUDED.salt_100g, fiber_100g=EXCLUDED.fiber_100g,
                     proteins_100g=EXCLUDED.proteins_100g, additives=EXCLUDED.additives,
                     allergens=EXCLUDED.allergens, ingredients_text=EXCLUDED.ingredients_text,
                     quantity=EXCLUDED.quantity, last_modified=EXCLUDED.last_modified, nutrition=EXCLUDED.nutrition,
                     fetched_at=NOW()""",
                [(p["code"], p["product_name"], p["brands"], p["categories"], p["countries"], p["nutriscore_grade"],
                  p["nutriscore_score"], p["nova_group"], p["energy_kcal_100g"], p["fat_100g"], p["saturated_fat_100g"],
                  p["sugars_100g"], p["salt_100g"], p["fiber_100g"], p["proteins_100g"], p["additives"], p["allergens"],
                  p["ingredients_text"], p["quantity"], p["last_modified"], json.dumps(p["nutrition"]))
                 for p in products], page_size=500)
    conn.commit()
    return len(products)


def run(max_pages: Optional[int] = None, dump: Optional[str] = None, dry_run: bool = False,
        from_dump: Optional[str] = None, api: bool = False) -> dict:
    if from_dump:
        raw = [json.loads(l) for l in open(from_dump, encoding="utf-8") if l.strip()]
    elif api:
        raw = fetch(max_pages, dump)
    else:
        raw = fetch_bulk(dump=dump)
    seen, products = set(), []
    for r in raw:
        p = parse_product(r)
        if p and p["code"] not in seen:
            seen.add(p["code"])
            products.append(p)
    info = {"fetched": len(raw), "products": len(products),
            "with_nutriscore": sum(1 for p in products if p["nutriscore_grade"]),
            "with_complete_traffic_lights": sum(1 for p in products if p["nutrition"]["complete"])}
    if dry_run:
        return {**info, "dry_run": True}
    from pipeline.config import pg_connect
    conn = pg_connect()
    try:
        info["inserted"] = load(conn, products)
    finally:
        conn.close()
    return info


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-pages", type=int)
    ap.add_argument("--dump")
    ap.add_argument("--from-dump")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--api", action="store_true", help="page through the search API instead of the bulk export")
    a = ap.parse_args()
    print(run(a.max_pages, a.dump, a.dry_run, a.from_dump, a.api))


if __name__ == "__main__":
    main()
