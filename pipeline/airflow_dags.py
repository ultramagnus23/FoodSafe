"""
FoodSafe India — Airflow DAGs (v1.1)
Added: fraud detection pass after every ingest job.
Schedule: FSSAI weekly, USFDA/EFSA daily, AGMARKNET daily,
          Fraud detection: nightly standalone pass.
"""

from __future__ import annotations
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago

DEFAULT_ARGS = {
    "owner":            "foodsafe",
    "depends_on_past":  False,
    "email_on_failure": True,
    "email":            ["alerts@foodsafe.in"],
    "retries":          2,
    "retry_delay":      timedelta(minutes=15),
}

# ============================================================
# SHARED TASKS
# ============================================================

def _refresh_agg_tables():
    import psycopg2
    from pipeline.config import DATABASE_URL
    SQL = """
    INSERT INTO agg_district_commodity_risk (
        district_id, commodity_id, quarter,
        fail_rate, n_tests, risk_score, ci_lower, ci_upper,
        top_contaminants, last_updated
    )
    SELECT
        er.district_id, er.commodity_id,
        TO_CHAR(er.test_date, 'YYYY-"Q"Q') AS quarter,
        ROUND(SUM(CASE WHEN er.pass_fail = FALSE THEN 1 ELSE 0 END)::NUMERIC
              / NULLIF(COUNT(*), 0), 4) AS fail_rate,
        COUNT(*) AS n_tests,
        ROUND(SUM(CASE WHEN er.pass_fail = FALSE THEN 1 ELSE 0 END)::NUMERIC
              / NULLIF(COUNT(*), 0) * 100, 2) AS risk_score,
        0.0 AS ci_lower, 0.0 AS ci_upper,
        '[]'::JSONB AS top_contaminants,
        NOW()
    FROM enforcement_records er
    WHERE er.confidence_score >= 0.75
      AND er.is_duplicate = FALSE
      AND er.district_id IS NOT NULL
      AND (er.fraud_score IS NULL OR er.fraud_score < 0.5)
    GROUP BY er.district_id, er.commodity_id, quarter
    ON CONFLICT (district_id, commodity_id, quarter) DO UPDATE SET
        fail_rate    = EXCLUDED.fail_rate,
        n_tests      = EXCLUDED.n_tests,
        risk_score   = EXCLUDED.risk_score,
        last_updated = NOW();
    """
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(SQL)
        conn.commit()
    finally:
        conn.close()


def _run_fraud_pass(**context):
    """Run fraud detection on records ingested in this DAG run."""
    import psycopg2
    from pipeline.config import DATABASE_URL
    from models.fraud_detection import run_fraud_pass
    conn = psycopg2.connect(DATABASE_URL)
    try:
        result = run_fraud_pass(conn, record_ids=None)  # last 7 days
        return result
    finally:
        conn.close()


# ============================================================
# DAG: FSSAI Weekly
# ============================================================

def _run_fssai():
    from pipeline.ingest import run_pipeline
    return run_pipeline(source="fssai", page_types=["enforcement_reports","recall_notices","lab_results"],
                        use_s3=True, max_pages=50)


with DAG(
    dag_id="foodsafe_fssai_weekly", default_args=DEFAULT_ARGS,
    description="Weekly FSSAI enforcement PDF scrape + ingest + fraud check",
    schedule_interval="0 2 * * 1", start_date=days_ago(7),
    catchup=False, tags=["foodsafe","fssai","ingestion"],
) as fssai_dag:

    scrape = PythonOperator(task_id="scrape_and_ingest_fssai", python_callable=_run_fssai)
    fraud  = PythonOperator(task_id="fraud_detection_pass",    python_callable=_run_fraud_pass)
    agg    = PythonOperator(task_id="refresh_aggregation_tables", python_callable=_refresh_agg_tables)

    scrape >> fraud >> agg


# ============================================================
# DAG: USFDA Daily RSS
# ============================================================

def _run_usfda_rss():
    import httpx
    from pipeline.stage1_extract import extract_rss_usfda
    from pipeline.stage2_standardise import standardise_batch
    from pipeline.stage3_and_4 import dedup_and_score
    from pipeline.ingest import write_records, get_db

    USFDA_RSS = "https://www.fda.gov/food/recalls-market-withdrawals-safety-alerts/rss.xml"
    resp = httpx.get(USFDA_RSS, timeout=30)
    resp.raise_for_status()
    raw = extract_rss_usfda(resp.text, USFDA_RSS)
    raw = [r for r in raw if "india" in (r.source_url or "").lower()
           or "india" in str(getattr(r, "state", "") or "").lower()]
    with get_db() as conn:
        std   = standardise_batch(raw, conn)
        scored = dedup_and_score(std, conn)
        inserted, skipped = write_records(conn, scored)
    return {"raw": len(raw), "inserted": inserted, "skipped": skipped}


with DAG(
    dag_id="foodsafe_usfda_daily", default_args=DEFAULT_ARGS,
    description="Daily USFDA RSS import alerts",
    schedule_interval="0 6 * * *", start_date=days_ago(1),
    catchup=False, tags=["foodsafe","usfda","rss"],
) as usfda_dag:

    ingest_usfda = PythonOperator(task_id="ingest_usfda_rss",    python_callable=_run_usfda_rss)
    fraud_usfda  = PythonOperator(task_id="fraud_detection_pass", python_callable=_run_fraud_pass)

    ingest_usfda >> fraud_usfda


# ============================================================
# DAG: AGMARKNET Daily
# ============================================================

def _run_agmarknet():
    import httpx, logging
    from pipeline.stage1_extract import extract_json_agmarknet
    from pipeline.stage2_standardise import standardise_batch
    from pipeline.stage3_and_4 import dedup_and_score
    from pipeline.ingest import write_records, get_db
    from datetime import date

    AGMARKNET_BASE = "https://agmarknet.gov.in/api/CommodityReport"
    today = date.today().strftime("%d-%b-%Y")
    try:
        resp = httpx.get(AGMARKNET_BASE, params={"commodity":"all","fromDate":today,"toDate":today}, timeout=30)
        data = resp.json()
    except Exception as e:
        logging.getLogger("foodsafe.agmarknet").warning("AGMARKNET fetch failed: %s", e)
        return {"raw": 0, "inserted": 0}
    raw = extract_json_agmarknet(data, AGMARKNET_BASE)
    with get_db() as conn:
        std = standardise_batch(raw, conn)
        scored = dedup_and_score(std, conn)
        inserted, skipped = write_records(conn, scored)
    return {"raw": len(raw), "inserted": inserted, "skipped": skipped}


with DAG(
    dag_id="foodsafe_agmarknet_daily", default_args=DEFAULT_ARGS,
    description="Daily AGMARKNET commodity quality data",
    schedule_interval="0 7 * * *", start_date=days_ago(1),
    catchup=False, tags=["foodsafe","agmarknet"],
) as agmarknet_dag:

    PythonOperator(task_id="ingest_agmarknet", python_callable=_run_agmarknet)


# ============================================================
# DAG: Nightly Fraud + Lab Reliability
# ============================================================

def _full_fraud_and_lab_pass():
    """Nightly: recompute all lab reliability scores + fraud flags."""
    import psycopg2
    from pipeline.config import DATABASE_URL
    from models.fraud_detection import (
        compute_lab_reliability_scores,
        update_lab_reliability_in_db,
        run_fraud_pass,
    )
    conn = psycopg2.connect(DATABASE_URL)
    try:
        lab_scores = compute_lab_reliability_scores(conn)
        update_lab_reliability_in_db(conn, lab_scores)
        result = run_fraud_pass(conn)
        return {**result, "lab_scores_updated": len(lab_scores)}
    finally:
        conn.close()


with DAG(
    dag_id="foodsafe_fraud_nightly", default_args=DEFAULT_ARGS,
    description="Nightly lab reliability scoring + fraud detection pass",
    schedule_interval="0 3 * * *", start_date=days_ago(1),
    catchup=False, tags=["foodsafe","fraud","labs"],
) as fraud_dag:

    PythonOperator(task_id="fraud_and_lab_reliability", python_callable=_full_fraud_and_lab_pass)
