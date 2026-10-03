"""
Nutrition classification of packaged foods (rules, cited — no model needed).

For each product with a nutrition table (per 100 g, or per 100 ml for drinks):

  traffic lights   fat, saturates, total sugars, salt -> low / medium / high, using the
                   UK Department of Health and Social Care front-of-pack criteria
                   (Annex 3, Tables 2 and 3 of "Guide to creating a front of pack (FoP)
                   nutrition label for pre-packed products sold through retail outlets",
                   2016). Its 'low' cut-offs are the EU Nutrition & Health Claims
                   Regulation (EC) 1924/2006 'low' claims. The per-portion 'high' rule
                   (portions over 100 g / 150 ml) is not applied: portion sizes are not
                   reliable in the source data.
  high_in          the nutrients flagged 'high'
  nutriscore/nova  as computed and published by Open Food Facts (not recomputed here)

India has no final front-of-pack thresholds (FSSAI's Indian Nutrition Rating is a
draft), so a recognised published scheme is used and named; nothing here is
presented as an Indian legal standard.
"""

from __future__ import annotations

from typing import Optional

SOURCE = ("UK DHSC (2016) Guide to creating a front of pack (FoP) nutrition label, Annex 3",
          "https://assets.publishing.service.gov.uk/media/5a80cd03ed915d74e33fc7c5/FoP_Nutrition_labelling_UK_guidance.pdf")

# nutrient -> (low <=, high >) in g per 100 g (food) / per 100 ml (drinks)
FOOD = {"fat": (3.0, 17.5), "saturates": (1.5, 5.0), "sugars": (5.0, 22.5), "salt": (0.3, 1.5)}
DRINK = {"fat": (1.5, 8.75), "saturates": (0.75, 2.5), "sugars": (2.5, 11.25), "salt": (0.3, 0.75)}


def is_drink(categories: list[str]) -> bool:
    return any(c in ("en:beverages", "en:drinks", "en:waters") or c.startswith("en:beverages-") for c in categories or [])


def level(value: Optional[float], low: float, high: float) -> Optional[str]:
    if value is None:
        return None
    if value <= low:
        return "low"
    if value > high:
        return "high"
    return "medium"


def traffic_lights(nutrients: dict[str, Optional[float]], categories: list[str]) -> dict:
    """nutrients: {'fat': g, 'saturates': g, 'sugars': g, 'salt': g} per 100 g/ml."""
    table = DRINK if is_drink(categories) else FOOD
    lights = {k: level(nutrients.get(k), lo, hi) for k, (lo, hi) in table.items()}
    return {"basis": "per 100 ml (drink)" if table is DRINK else "per 100 g (food)", "lights": lights,
            "high_in": sorted(k for k, v in lights.items() if v == "high"),
            "complete": all(v is not None for v in lights.values())}


def salt_g(nutriments: dict) -> Optional[float]:
    """Salt per 100 g: as published, else sodium x 2.5 (the EU/UK convention)."""
    s = nutriments.get("salt_100g")
    if isinstance(s, (int, float)):
        return float(s)
    na = nutriments.get("sodium_100g")
    return float(na) * 2.5 if isinstance(na, (int, float)) else None
