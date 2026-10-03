"""
FoodSafe India — nutrition of packaged foods sold in India.

  GET /v1/nutrition/summary            how India's packaged foods score: Nutri-Score, NOVA, 'high in' shares, by category
  GET /v1/nutrition/products           search / filter products (name, brand, category, grade, high_in)
  GET /v1/nutrition/products/{code}    one product by barcode

Data: Open Food Facts (crowd-sourced label transcriptions, ODbL) via
pipeline/sources/off_india.py. Classification: models/nutrition.py — UK DHSC
front-of-pack traffic lights (low/medium/high fat, saturates, sugars, salt per
100 g or 100 ml); Nutri-Score and NOVA as Open Food Facts computes them. India
has no final front-of-pack thresholds, so these are named reference schemes, not
Indian legal standards.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.db import get_pool

nutrition_router = APIRouter()

CAVEAT = ("Label data transcribed by Open Food Facts contributors, not laboratory analyses; products listed are "
          "those someone added, not a sample of what India eats. Traffic lights: UK DHSC front-of-pack criteria "
          "(per 100 g / 100 ml). Nutri-Score and NOVA as computed by Open Food Facts.")
ATTRIBUTION = "Open Food Facts (https://world.openfoodfacts.org), Open Database License"


class Summary(BaseModel):
    products: int
    with_nutriscore: int
    nutriscore: dict[str, int]
    nova: dict[str, int]
    with_complete_lights: int
    high_in: dict[str, int]
    high_in_any: int
    top_categories: list[dict[str, Any]]
    caveat: str
    attribution: str


@nutrition_router.get("/summary", response_model=Summary)
async def summary():
    pool = get_pool()
    async with pool.acquire() as conn:
        n = await conn.fetchval("SELECT COUNT(*) FROM packaged_foods")
        grades = await conn.fetch("SELECT nutriscore_grade AS g, COUNT(*) AS n FROM packaged_foods "
                                  "WHERE nutriscore_grade IS NOT NULL GROUP BY 1 ORDER BY 1")
        nova = await conn.fetch("SELECT nova_group AS g, COUNT(*) AS n FROM packaged_foods "
                                "WHERE nova_group IS NOT NULL GROUP BY 1 ORDER BY 1")
        complete = await conn.fetchval("SELECT COUNT(*) FROM packaged_foods WHERE (nutrition->>'complete')::boolean")
        high = await conn.fetch(
            """SELECT h AS k, COUNT(*) AS n FROM packaged_foods, jsonb_array_elements_text(nutrition->'high_in') AS h
               WHERE (nutrition->>'complete')::boolean GROUP BY 1""")
        any_high = await conn.fetchval(
            """SELECT COUNT(*) FROM packaged_foods WHERE (nutrition->>'complete')::boolean
                 AND jsonb_array_length(nutrition->'high_in') > 0""")
        cats = await conn.fetch(
            """SELECT c AS category, COUNT(*) AS products,
                      COUNT(*) FILTER (WHERE nutriscore_grade IN ('d','e')) AS grade_d_or_e,
                      COUNT(*) FILTER (WHERE nutriscore_grade IS NOT NULL) AS graded,
                      COUNT(*) FILTER (WHERE nova_group = 4) AS nova4
               FROM packaged_foods, unnest(categories) AS c
               GROUP BY 1 HAVING COUNT(*) >= 50 ORDER BY products DESC LIMIT 25""")
    return Summary(products=n or 0, with_nutriscore=sum(r["n"] for r in grades),
                   nutriscore={r["g"]: r["n"] for r in grades}, nova={str(r["g"]): r["n"] for r in nova},
                   with_complete_lights=complete or 0, high_in={r["k"]: r["n"] for r in high},
                   high_in_any=any_high or 0, top_categories=[dict(r) for r in cats], caveat=CAVEAT,
                   attribution=ATTRIBUTION)


class Product(BaseModel):
    code: str
    product_name: Optional[str]
    brands: Optional[str]
    categories: list[str]
    nutriscore_grade: Optional[str]
    nova_group: Optional[int]
    energy_kcal_100g: Optional[float]
    fat_100g: Optional[float]
    saturated_fat_100g: Optional[float]
    sugars_100g: Optional[float]
    salt_100g: Optional[float]
    fiber_100g: Optional[float]
    proteins_100g: Optional[float]
    additives: list[str]
    allergens: list[str]
    nutrition: dict[str, Any]
    source_url: str


class ProductList(BaseModel):
    results: list[Product]
    total: int
    caveat: str
    attribution: str


_COLS = """code, product_name, brands, categories, nutriscore_grade, nova_group, energy_kcal_100g::float AS energy_kcal_100g,
           fat_100g::float AS fat_100g, saturated_fat_100g::float AS saturated_fat_100g, sugars_100g::float AS sugars_100g,
           salt_100g::float AS salt_100g, fiber_100g::float AS fiber_100g, proteins_100g::float AS proteins_100g,
           additives, allergens, nutrition"""


def _product(r) -> Product:
    d = dict(r)
    d["nutrition"] = json.loads(d["nutrition"]) if isinstance(d["nutrition"], str) else d["nutrition"]
    return Product(**d, source_url=f"https://world.openfoodfacts.org/product/{r['code']}")


@nutrition_router.get("/products", response_model=ProductList)
async def products(q: Optional[str] = Query(None, max_length=80), brand: Optional[str] = Query(None, max_length=80),
                   category: Optional[str] = Query(None, pattern=r"^[a-z]{2}:[a-z0-9\-]{1,80}$"),
                   grade: Optional[str] = Query(None, pattern=r"^[a-e]$"),
                   high_in: Optional[str] = Query(None, pattern=r"^(fat|saturates|sugars|salt)$"),
                   limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0, le=100000)):
    if "\x00" in (q or "") + (brand or ""):       # a NUL would reach asyncpg and surface as a 500
        raise HTTPException(422, "bad search text")
    term = f"%{q.strip().lower()}%" if q and q.strip() else None
    br = brand.strip().lower() if brand and brand.strip() else None
    where = """WHERE ($1::text IS NULL OR lower(product_name) LIKE $1)
                 AND ($2::text IS NULL OR lower(brands) LIKE '%' || $2 || '%')
                 AND ($3::text IS NULL OR $3 = ANY(categories))
                 AND ($4::text IS NULL OR nutriscore_grade = $4)
                 AND ($5::text IS NULL OR nutrition->'high_in' ? $5)"""
    pool = get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM packaged_foods {where}", term, br, category, grade, high_in)
        # Graded products first, then real names; crowd-sourced rows with no grade and
        # a placeholder name ("# 08/24 B042") would otherwise sort to the top.
        rows = await conn.fetch(f"SELECT {_COLS} FROM packaged_foods {where} "
                                "ORDER BY (nutriscore_grade IS NULL), (product_name !~ '^[[:alnum:]]') NULLS LAST, "
                                "lower(product_name) NULLS LAST, code "
                                "LIMIT $6 OFFSET $7", term, br, category, grade, high_in, limit, offset)
    return ProductList(results=[_product(r) for r in rows], total=total or 0, caveat=CAVEAT, attribution=ATTRIBUTION)


@nutrition_router.get("/products/{code}", response_model=Product)
async def product(code: str):
    if not code.isdigit() or len(code) > 20:
        raise HTTPException(422, "barcode must be digits")
    pool = get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(f"SELECT {_COLS} FROM packaged_foods WHERE code = $1", code)
    if not r:
        raise HTTPException(404, "unknown product")
    return _product(r)
