"""
Tests for models/nutrition.py (UK DHSC front-of-pack traffic lights) and
pipeline/sources/off_india.py (Open Food Facts rows -> packaged_foods).
Thresholds are the published Annex 3 values. No network, no database.
"""
from __future__ import annotations

import pytest

from models import nutrition as N
from pipeline.sources import off_india as O


@pytest.mark.parametrize("nutrient,value,expected", [
    ("fat", 3.0, "low"), ("fat", 3.01, "medium"), ("fat", 17.5, "medium"), ("fat", 17.6, "high"),
    ("saturates", 1.5, "low"), ("saturates", 5.1, "high"),
    ("sugars", 5.0, "low"), ("sugars", 22.5, "medium"), ("sugars", 22.6, "high"),
    ("salt", 0.3, "low"), ("salt", 1.5, "medium"), ("salt", 1.51, "high"),
])
def test_food_thresholds(nutrient, value, expected):
    lo, hi = N.FOOD[nutrient]
    assert N.level(value, lo, hi) == expected


def test_drinks_use_per_100ml_table():
    lights = N.traffic_lights({"fat": 0, "saturates": 0, "sugars": 11.3, "salt": 0.01}, ["en:beverages", "en:sodas"])
    assert lights["basis"] == "per 100 ml (drink)" and lights["lights"]["sugars"] == "high"
    food = N.traffic_lights({"fat": 0, "saturates": 0, "sugars": 11.3, "salt": 0.01}, ["en:snacks"])
    assert food["lights"]["sugars"] == "medium" and food["high_in"] == []


def test_incomplete_table_is_marked_not_guessed():
    t = N.traffic_lights({"fat": 20.0, "saturates": None, "sugars": 1.0, "salt": None}, [])
    assert t["complete"] is False and t["lights"]["saturates"] is None and t["high_in"] == ["fat"]


def test_salt_from_sodium():
    assert N.salt_g({"sodium_100g": 0.4}) == pytest.approx(1.0)
    assert N.salt_g({"salt_100g": 0.9, "sodium_100g": 0.1}) == 0.9
    assert N.salt_g({}) is None


def test_bulk_csv_row_parses_like_the_api():
    row = {"code": "8901719134845", "product_name": "Parle-G Biscuit", "brands": "Parle",
           "categories_tags": "en:snacks,en:biscuits", "countries_tags": "en:india", "nutriscore_grade": "e",
           "nutriscore_score": "21", "nova_group": "4.0", "fat_100g": "12.5", "saturated-fat_100g": "6",
           "sugars_100g": "25", "salt_100g": "", "sodium_100g": "0.2", "energy-kcal_100g": "454",
           "additives_tags": "en:e322,en:e500", "allergens": "en:gluten", "last_modified_t": "1700000000"}
    p = O.parse_product(O.csv_row_to_api(row))
    assert p["code"] == "8901719134845" and p["nova_group"] == 4 and p["nutriscore_grade"] == "e"
    assert p["salt_100g"] == pytest.approx(0.5) and p["categories"] == ["en:snacks", "en:biscuits"]
    assert p["nutrition"]["high_in"] == ["saturates", "sugars"] and p["nutrition"]["complete"] is True


def test_parse_product_rejects_bad_codes_and_grades():
    assert O.parse_product({"code": "not-a-barcode"}) is None
    p = O.parse_product({"code": "123", "nutriscore_grade": "unknown", "nova_group": 7})
    assert p["nutriscore_grade"] is None and p["nova_group"] is None
