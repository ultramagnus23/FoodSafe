"""
FoodSafe India — Demo enforcement-record generator

Generates a realistic volume of enforcement_records (the kind the FSSAI OCR
pipeline would produce) so the aggregation job computes believable district /
brand risk scores with tight confidence intervals.

These are clearly-marked demo records (etl_version='seed-demo') standing in for
real FSSAI test data until the OCR ingestion path is operational. The point is
that the *aggregation is real* — it computes scores from these records exactly
as it would from live data.

Idempotent: deletes prior 'seed-demo' records, then regenerates.
Run:  python -m pipeline.seed_enforcement
"""

from __future__ import annotations

import logging
import random
from datetime import date, timedelta

from pipeline.config import pg_connect

logger = logging.getLogger("foodsafe.seed_enforcement")

# district_id -> (state, base fail rate, total tests, [(commodity_id, weight)])
DISTRICTS = {
    1:  ("Maharashtra",   0.15, 234, [(1, 0.6), (5, 0.4)]),   # Mumbai: rice, chilli
    2:  ("Maharashtra",   0.07, 178, [(1, 0.7), (3, 0.3)]),   # Pune: rice, milk
    3:  ("Maharashtra",   0.10,  92, [(1, 1.0)]),             # Nagpur
    4:  ("Maharashtra",   0.05,  67, [(1, 1.0)]),             # Nashik
    5:  ("Gujarat",       0.12, 145, [(5, 0.6), (1, 0.4)]),   # Ahmedabad: chilli, rice
    6:  ("Gujarat",       0.08,  98, [(1, 0.6), (3, 0.4)]),   # Surat
    7:  ("Delhi",         0.21, 312, [(1, 0.5), (5, 0.5)]),   # Delhi: rice, chilli
    8:  ("Uttar Pradesh", 0.13,  89, [(3, 0.6), (1, 0.4)]),   # Noida: milk, rice
    9:  ("Uttar Pradesh", 0.09, 123, [(4, 0.5), (1, 0.5)]),   # Lucknow: groundnut, rice
    10: ("Tamil Nadu",    0.075,201, [(6, 0.5), (1, 0.5)]),   # Chennai: turmeric, rice
    11: ("Tamil Nadu",    0.02,  87, [(1, 1.0)]),             # Coimbatore
    12: ("Karnataka",     0.02, 267, [(1, 0.7), (3, 0.3)]),   # Bengaluru: rice, milk
}

# commodity_id -> contaminant choices [(contaminant_id, weight)]
COMMODITY_CONTAMINANTS = {
    1: [(1, 0.5), (3, 0.3), (6, 0.2)],   # rice: aflatoxin_b1, lead, chlorpyrifos
    3: [(7, 0.6), (3, 0.4)],             # milk: melamine, lead
    4: [(2, 0.7), (1, 0.3)],             # groundnut: aflatoxin_total, aflatoxin_b1
    5: [(3, 0.7), (8, 0.3)],             # chilli: lead, ochratoxin_a
    6: [(3, 0.8), (5, 0.2)],             # turmeric: lead, arsenic
}

# a few brands per district that appear in records (brand_id, weight of being tagged)
DISTRICT_BRANDS = {
    1: [1, 5], 2: [1, 3], 5: [5, 2], 7: [5, 1], 8: [3], 9: [4], 10: [6], 12: [3, 1],
}

SOURCES = ["fssai", "fssai", "fssai", "state_health", "apeda"]


def _legal_limits(conn) -> dict[int, float]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, legal_limit_ppb_fssai FROM contaminants")
        return {r[0]: float(r[1]) if r[1] is not None else 100.0 for r in cur.fetchall()}


def _weighted(choices):
    items = [c for c, _ in choices]
    weights = [w for _, w in choices]
    return random.choices(items, weights=weights, k=1)[0]


def generate(conn, seed: int = 42) -> int:
    random.seed(seed)
    limits = _legal_limits(conn)
    today = date(2026, 6, 23)
    rows = []
    counter = 0

    for district_id, (state, fail_rate, n_tests, commodities) in DISTRICTS.items():
        brands = DISTRICT_BRANDS.get(district_id, [None])
        for _ in range(n_tests):
            commodity_id = _weighted(commodities)
            contaminant_id = _weighted(COMMODITY_CONTAMINANTS.get(commodity_id, [(1, 1.0)]))
            limit = limits.get(contaminant_id, 100.0)

            is_fail = random.random() < fail_rate
            if is_fail:
                value = round(limit * random.uniform(1.15, 4.0), 3)
            else:
                value = round(limit * random.uniform(0.05, 0.85), 3)

            test_date = today - timedelta(days=random.randint(0, 540))  # last ~18 months
            brand_id = random.choice(brands) if random.random() < 0.4 else None
            counter += 1
            rows.append((
                test_date, f"https://fssai.gov.in/demo/{district_id}/{counter}",
                random.choice(SOURCES), commodity_id, contaminant_id,
                value, limit, (not is_fail), state, district_id, brand_id,
                round(random.uniform(0.80, 0.96), 3), f"seed-{district_id}-{counter}",
            ))

    with conn.cursor() as cur:
        cur.execute("DELETE FROM enforcement_records WHERE etl_version = 'seed-demo'")
        cur.executemany(
            """INSERT INTO enforcement_records
                 (test_date, source_url, source_type, commodity_id, contaminant_id,
                  raw_value_ppb, legal_limit_ppb, pass_fail, state, district_id, brand_id,
                  confidence_score, dedup_hash, is_duplicate, etl_version, parsed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE,'seed-demo',NOW())""",
            rows,
        )
    conn.commit()
    return len(rows)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    conn = pg_connect()
    try:
        n = generate(conn)
    finally:
        conn.close()
    print(f"Generated {n} demo enforcement records (etl_version='seed-demo').")


if __name__ == "__main__":
    main()
