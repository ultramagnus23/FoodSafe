"""
Export a static snapshot of FoodSafe's public data for the GitHub Pages portal.

Reads the production database (DATABASE_URL) and writes JSON files the static
site (site/index.html) renders: no backend, no API key, no rate limit, and every
number traceable to the same tables the API serves. Run by
.github/workflows/portal.yml after the daily ingest; never committed to git.

  python -m scripts.export_portal --out site/data/live
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from pipeline.config import pg_connect


def _default(o):
    if isinstance(o, Decimal):
        return float(o)
    if hasattr(o, "isoformat"):
        return o.isoformat()
    raise TypeError(type(o))


def q(conn, sql, *args) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, args or None)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def one(conn, sql, *args):
    rows = q(conn, sql, *args)
    return rows[0] if rows else {}


def safe(fn, fallback):
    """A table that a fresh database has not been migrated to yet must not break the export."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        print(f"  skipped: {type(e).__name__}: {str(e)[:120]}")
        return fallback


def export(conn, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, object] = {}

    def rollback_safe(fn, fallback):
        r = safe(fn, fallback)
        conn.rollback()
        return r

    # ---- standards
    files["standards_summary"] = rollback_safe(lambda: {
        "rows": q(conn, "SELECT jurisdiction, standard_type, COUNT(*) AS n FROM food_standards GROUP BY 1, 2"),
        "snapshots": q(conn, """SELECT DISTINCT ON (jurisdiction, standard_types) jurisdiction, document_title,
                                       document_url, document_version, rows_loaded, loaded_at
                                FROM standards_snapshots ORDER BY jurisdiction, standard_types, loaded_at DESC"""),
        "flags": one(conn, """SELECT COUNT(*) AS comparisons,
                 COUNT(*) FILTER (WHERE 'india_higher_than_eu' = ANY(flags)) AS india_higher_than_eu,
                 COUNT(*) FILTER (WHERE 'india_higher_than_codex' = ANY(flags)) AS india_higher_than_codex,
                 COUNT(*) FILTER (WHERE 'india_higher_than_us' = ANY(flags)) AS india_higher_than_us,
                 COUNT(*) FILTER (WHERE 'no_us_tolerance' = ANY(flags)) AS no_us_tolerance,
                 COUNT(*) FILTER (WHERE eu_basis = 'eu_default') AS eu_default,
                 MAX(ratio_in_eu) AS max_ratio_eu,
                 COUNT(DISTINCT in_substance_key) FILTER (WHERE standard_type = 'pesticide_mrl'
                                                            AND eu_status = 'Not approved') AS not_approved_in_eu,
                 COUNT(DISTINCT in_substance_key) FILTER (WHERE standard_type = 'pesticide_mrl') AS india_pesticides,
                 COUNT(*) FILTER (WHERE 'india_higher_than_eu' = ANY(flags)
                                    AND standard_type = 'pesticide_mrl') AS higher_eu_pesticides,
                 COUNT(*) FILTER (WHERE 'eu_gap_not_approved' = ANY(flags)) AS gap_not_approved,
                 COUNT(*) FILTER (WHERE 'eu_gap_no_use_on_food' = ANY(flags)) AS gap_no_use_on_food,
                 COUNT(*) FILTER (WHERE 'eu_gap_never_assessed' = ANY(flags)) AS gap_never_assessed,
                 COUNT(*) FILTER (WHERE 'eu_gap_at_loq' = ANY(flags)) AS gap_at_loq,
                 COUNT(*) FILTER (WHERE 'eu_gap_above_loq' = ANY(flags)) AS gap_above_loq,
                 percentile_cont(0.5) WITHIN GROUP (ORDER BY ratio_in_eu)
                     FILTER (WHERE 'eu_gap_above_loq' = ANY(flags)) AS gap_above_loq_median_ratio
                 FROM standards_comparison"""),
    }, {})
    files["standards_compare"] = rollback_safe(lambda: q(conn, """
        SELECT standard_type AS t, hazard_key AS h, hazard_name AS hn, food_key AS f, in_value AS i, eu_value AS e,
               eu_basis AS eb, codex_value AS c, codex_basis AS cb, us_value AS u, us_basis AS ub,
               ratio_in_eu AS re, ratio_in_codex AS rc, ratio_in_us AS ru, flags, eu_status AS st, iarc_group AS ig,
               detail->'IN'->>'basis' AS ib
        FROM standards_comparison ORDER BY food_key, hazard_key"""), [])

    # ---- hazards / knowledge base
    files["hazards"] = rollback_safe(lambda: q(conn, """
        SELECT h.hazard_key, h.name, h.hazard_class, h.iarc_group, h.summary,
               COALESCE(json_agg(json_build_object('outcome', e.outcome, 'organ', e.organ_system,
                   'exposure', e.exposure, 'onset', e.onset, 'vulnerable', e.vulnerable_groups,
                   'evidence', e.evidence, 'source', e.source_title, 'url', e.source_url) ORDER BY e.exposure, e.outcome)
                   FILTER (WHERE e.id IS NOT NULL), '[]') AS effects
        FROM hazards h LEFT JOIN hazard_health_effects e USING (hazard_key)
        WHERE h.summary IS NOT NULL GROUP BY 1, 2, 3, 4, 5 ORDER BY h.hazard_class, h.name"""), [])

    # ---- health profiles (origins with >= 50 notifications)
    files["health_profiles"] = rollback_safe(lambda: q(conn, """
        SELECT origin, outcome_key, outcome, organ_system, exposure, notifications, share_of_classified,
               serious_notifications, top_hazards, sources FROM (
            SELECT scope_key AS origin, outcome_key, outcome, organ_system, exposure, notifications,
                   share_of_classified, serious_notifications,
                   (SELECT json_agg(x) FROM (SELECT * FROM jsonb_array_elements(top_hazards) LIMIT 3) t(x)) AS top_hazards,
                   (SELECT json_agg(x) FROM (SELECT * FROM jsonb_array_elements(sources) LIMIT 2) t(x)) AS sources,
                   ROW_NUMBER() OVER (PARTITION BY scope_key ORDER BY notifications DESC) AS rk
            FROM health_outcome_profile WHERE scope_type = 'rasff_origin' AND scope_key IN (
                SELECT scope_key FROM health_outcome_profile GROUP BY scope_key HAVING MAX(notifications) >= 25)) p
        WHERE rk <= 20 ORDER BY origin, notifications DESC"""), [])

    # ---- RASFF
    files["rasff_countries"] = rollback_safe(lambda: q(conn, """
        SELECT o AS origin, COUNT(*) AS notifications, COUNT(*) FILTER (WHERE risk_decision = 'serious') AS serious,
               COUNT(*) FILTER (WHERE classification ILIKE 'border rejection%') AS border_rejections,
               MIN(validation_date) AS first, MAX(validation_date) AS last
        FROM rasff_notifications, unnest(origin_countries) AS o GROUP BY o ORDER BY notifications DESC"""), [])
    files["rasff_india"] = rollback_safe(lambda: {
        "by_year": q(conn, """SELECT EXTRACT(YEAR FROM validation_date)::int AS year, COUNT(*) AS n
                              FROM rasff_notifications WHERE 'IN' = ANY(origin_countries) GROUP BY 1 ORDER BY 1"""),
        "by_category": q(conn, """SELECT COALESCE(h.hazard_category, 'unclassified') AS category,
                                         COUNT(DISTINCT n.notif_id) AS n
                                  FROM rasff_notifications n JOIN rasff_hazards h USING (notif_id)
                                  WHERE 'IN' = ANY(n.origin_countries) GROUP BY 1 ORDER BY n DESC"""),
        "top_hazards": q(conn, """SELECT LOWER(h.hazard) AS hazard, COUNT(DISTINCT n.notif_id) AS n
                                  FROM rasff_notifications n JOIN rasff_hazards h USING (notif_id)
                                  WHERE 'IN' = ANY(n.origin_countries) GROUP BY 1 ORDER BY n DESC LIMIT 25"""),
        "by_product": q(conn, """SELECT COALESCE(product_category, 'unclassified') AS product, COUNT(*) AS n
                                 FROM rasff_notifications WHERE 'IN' = ANY(origin_countries)
                                 GROUP BY 1 ORDER BY n DESC LIMIT 15"""),
    }, {})
    files["rasff_india_measured"] = rollback_safe(lambda: _measured(conn), [])

    # ---- countries, burden, nutrition, states
    files["countries"] = rollback_safe(lambda: _countries(conn), [])
    files["burden"] = rollback_safe(lambda: q(conn, """
        SELECT measure, age_group, hazard_group, hazard, value FROM foodborne_burden_global
        WHERE year = (SELECT MAX(year) FROM foodborne_burden_global) ORDER BY measure, age_group, value DESC"""), [])
    files["nutrition"] = rollback_safe(lambda: _nutrition(conn), {})
    files["states"] = rollback_safe(lambda: _states(conn), [])
    files["sources"] = rollback_safe(lambda: _sources(conn), [])

    meta = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "files": {k: (len(v) if isinstance(v, (list, dict)) else None) for k, v in files.items()}}
    for name, data in {**files, "meta": meta}.items():
        (out / f"{name}.json").write_text(json.dumps(data, default=_default, separators=(",", ":")), encoding="utf-8")
    model = Path(__file__).resolve().parent.parent / "models" / "artifacts" / "hazard_text_classifier.json"
    if model.exists():
        shutil.copy(model, out / "hazard_model.json")
    from models.health_classifier import _ALIASES                                   # rules for the in-browser classifier
    from pipeline.sources import hazard_kb as KB
    rules = [{"pattern": rx.pattern, "key": k, "name": KB.HAZARDS[k]["name"], "class": KB.HAZARDS[k]["hazard_class"]}
             for rx, k in _ALIASES]
    # Then pesticides by chemical class, after the named hazards — the same order as
    # models.health_classifier.classify_hazard (kb name/alias, then pesticide class).
    rules += _pesticide_class_rules(KB)
    (out / "hazard_rules.json").write_text(json.dumps(rules), encoding="utf-8")
    return meta


def _pesticide_class_rules(KB) -> list[dict]:
    """In-browser rules for pesticides the KB knows only by class (e.g. chlorpyrifos ->
    organophosphate), carrying the class's cited effects. Member keys are normalised
    ('chlorpyrifosmethyl'), so '-methyl' variants also match 'chlorpyrifos-methyl'."""
    rules = []
    for cls, d in KB.PESTICIDE_CLASSES.items():
        effects = [{"outcome": e["outcome"], "organ": e["organ_system"], "exposure": e["exposure"], "onset": e["onset"],
                    "vulnerable": e["vulnerable_groups"], "evidence": e["evidence"],
                    "source": KB.SRC[e["source"]][0], "url": KB.SRC[e["source"]][1]} for e in d["effects"]]
        for m in d["members"]:
            if m == "aldrinanddieldrin":            # a combined residue definition; both parts are members
                continue
            rules.append({"pattern": r"\b" + re.sub(r"methyl$", r"[\\s-]?methyl", m) + r"\b", "key": m,
                          "name": m.upper() if len(m) <= 3 else re.sub(r"methyl$", "-methyl", m).capitalize(),
                          "class": "pesticide", "pclass": cls, "effects": effects})
    return sorted(rules, key=lambda r: -len(r["key"]))     # 'chlorpyrifos-methyl' before 'chlorpyrifos'


def _measured(conn) -> list[dict]:
    from models.safe_intake import assess
    from pipeline.sources.standards_common import hazard_key as fam, substance_key
    rows = q(conn, """
        SELECT n.notif_id, n.validation_date, n.subject, n.product_category, n.source_url, h.hazard, h.hazard_key,
               h.result_value, h.result_unit, h.limit_value, h.limit_unit
        FROM rasff_hazards h JOIN rasff_notifications n USING (notif_id)
        WHERE 'IN' = ANY(n.origin_countries) AND h.result_value IS NOT NULL AND h.result_qualifier IN ('=', '>')
          AND h.result_unit IN ('mg/kg', 'ug/kg')
        ORDER BY n.validation_date DESC LIMIT 300""")
    out = []
    for r in rows:
        keys = [k for k in (r["hazard_key"], substance_key(r["hazard"]), fam(r["hazard"])) if k]
        refs = q(conn, """SELECT body, value_type, value, unit, raw_text, source_ref, source_url
                          FROM hazard_reference_values WHERE hazard_key = ANY(%s)""", keys)
        conc = Decimal(str(r["result_value"])) / (1 if r["result_unit"] == "mg/kg" else 1000)
        a = assess(r["hazard_key"], conc, Decimal(60), refs)
        out.append({"id": r["notif_id"], "date": r["validation_date"], "subject": r["subject"],
                    "product": r["product_category"], "hazard": r["hazard"], "mg_kg": conc,
                    "chronic_g": a["chronic"]["grams"] if a.get("chronic") else None,
                    "acute_g": a["acute"]["grams"] if a.get("acute") else None,
                    "guidance": (a.get("chronic") or a.get("acute") or {}).get("guidance"),
                    "reason": a.get("reason"), "url": r["source_url"]})
    return out


def _countries(conn) -> list[dict]:
    rows = q(conn, """
        SELECT c.iso3, c.iso2, c.name, c.region, c.income_level,
               json_object_agg(l.indicator_code, json_build_array(l.value, l.year)) FILTER (WHERE l.indicator_code IS NOT NULL)
                 AS ind
        FROM countries c LEFT JOIN LATERAL (
            SELECT DISTINCT ON (indicator_code) indicator_code, value, year FROM country_indicators i
            WHERE i.iso3 = c.iso3 ORDER BY indicator_code, year DESC) l ON TRUE
        WHERE NOT c.is_aggregate GROUP BY 1, 2, 3, 4, 5 ORDER BY c.name""")
    return rows


def _nutrition(conn) -> dict:
    return {
        "products": one(conn, "SELECT COUNT(*) AS n FROM packaged_foods").get("n", 0),
        "nutriscore": q(conn, """SELECT nutriscore_grade AS g, COUNT(*) AS n FROM packaged_foods
                                 WHERE nutriscore_grade IS NOT NULL GROUP BY 1 ORDER BY 1"""),
        "nova": q(conn, "SELECT nova_group AS g, COUNT(*) AS n FROM packaged_foods WHERE nova_group IS NOT NULL "
                        "GROUP BY 1 ORDER BY 1"),
        "high_in": q(conn, """SELECT h AS k, COUNT(*) AS n FROM packaged_foods,
                              jsonb_array_elements_text(nutrition->'high_in') AS h
                              WHERE (nutrition->>'complete')::boolean GROUP BY 1 ORDER BY n DESC"""),
        "complete": one(conn, "SELECT COUNT(*) AS n FROM packaged_foods WHERE (nutrition->>'complete')::boolean")
        .get("n", 0),
        "categories": q(conn, """SELECT c AS category, COUNT(*) AS products,
                                        COUNT(*) FILTER (WHERE nutriscore_grade IN ('d','e')) AS de,
                                        COUNT(*) FILTER (WHERE nutriscore_grade IS NOT NULL) AS graded,
                                        COUNT(*) FILTER (WHERE nova_group = 4) AS nova4
                                 FROM packaged_foods, unnest(categories) AS c
                                 GROUP BY 1 HAVING COUNT(*) >= 80 ORDER BY products DESC LIMIT 30"""),
    }


def _states(conn) -> list[dict]:
    return q(conn, """
        WITH s AS (SELECT DISTINCT ON (state, fiscal_year) state, fiscal_year, samples_analyzed, samples_non_conforming
                   FROM state_sampling_annual WHERE non_conforming_basis = 'non_conforming'
                   ORDER BY state, fiscal_year, lok_sabha_no DESC, answered_date DESC NULLS LAST)
        SELECT state, json_agg(json_build_array(fiscal_year, samples_analyzed, samples_non_conforming)
                               ORDER BY fiscal_year) AS series
        FROM s GROUP BY state ORDER BY state""")


ROW_COUNTS = {   # same definitions as /v1/meta/sources (api/other_routes.SOURCE_ROW_COUNTS), without importing the API
    "rasff": "SELECT COUNT(*) AS count FROM rasff_notifications",
    "openfda": "SELECT COUNT(*) AS count FROM enforcement_records WHERE source_type = 'usfda'",
    "fssai_annual_report": "SELECT COUNT(*) AS count FROM national_enforcement_annual",
    "loksabha_sampling": "SELECT COUNT(*) AS count FROM state_sampling_annual",
    "loksabha_qa": "SELECT COUNT(*) AS count FROM state_enforcement_annual",
    "loksabha_pesticide": "SELECT COUNT(*) AS count FROM pesticide_residue_annual",
    "research_evidence": "SELECT COUNT(*) AS count FROM research_sources",
    "fssai_directory": "SELECT (SELECT COUNT(*) FROM labs) + (SELECT COUNT(*) FROM state_commissioners) AS count",
    "local_news": "SELECT COUNT(*) AS count FROM enforcement_records WHERE source_type LIKE 'local_news%'",
    "standards_fssai": "SELECT COUNT(*) AS count FROM food_standards WHERE jurisdiction = 'IN'",
    "standards_eu": "SELECT COUNT(*) AS count FROM food_standards WHERE jurisdiction = 'EU'",
    "standards_codex": "SELECT COUNT(*) AS count FROM food_standards WHERE jurisdiction = 'CODEX'",
    "standards_us": "SELECT COUNT(*) AS count FROM food_standards WHERE jurisdiction = 'US'",
    "hazard_kb": "SELECT COUNT(*) AS count FROM hazard_health_effects",
}


def _sources(conn) -> list[dict]:
    from api.source_registry import SOURCES, describe
    SOURCE_ROW_COUNTS = ROW_COUNTS
    out = []
    for sid in SOURCES:
        d = describe(sid)
        try:
            d["rows"] = one(conn, SOURCE_ROW_COUNTS[sid]).get("count") if sid in SOURCE_ROW_COUNTS else None
        except Exception:  # noqa: BLE001
            conn.rollback()
            d["rows"] = None
        out.append(d)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="site/data/live")
    a = ap.parse_args()
    conn = pg_connect()
    try:
        meta = export(conn, Path(a.out))
    finally:
        conn.close()
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
