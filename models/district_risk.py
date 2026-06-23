"""
FoodSafe India — Model 1: District Contamination Risk Score
Random Forest with geographic holdout cross-validation.
Run: python -m models.district_risk --train / --predict
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score, precision_score, recall_score
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger("foodsafe.models.district_risk")

MODEL_PATH = Path(__file__).parent / "saved" / "district_risk_rf.pkl"
MODEL_PATH.parent.mkdir(exist_ok=True)

# ============================================================
# FEATURE ENGINEERING
# ============================================================

FEATURES = [
    "lab_fail_rate_12m",
    "n_tests_12m",
    "water_quality_index",
    "industrial_proximity_score",
    "seasonal_factor",       # 1–4 (quarter)
    "historical_trend_slope",
    "district_pop_density",  # from Census 2021
    "state_avg_fail_rate",   # hierarchical prior
]


def load_training_data(conn) -> pd.DataFrame:
    """Pull feature matrix from DB for all district-commodity-quarter combos."""
    query = """
        SELECT
            agg.district_id,
            agg.commodity_id,
            agg.quarter,
            agg.fail_rate,
            agg.n_tests AS n_tests_12m,
            d.water_quality_index,
            d.industrial_proximity_score,
            d.state,
            EXTRACT(QUARTER FROM TO_DATE(agg.quarter || '-01', 'YYYY-"Q"Q-DD'))::int AS seasonal_factor,
            -- trailing 12m fail rate as primary feature
            agg.fail_rate AS lab_fail_rate_12m,
            -- trend: difference from previous quarter
            agg.fail_rate - LAG(agg.fail_rate) OVER (
                PARTITION BY agg.district_id, agg.commodity_id
                ORDER BY agg.quarter
            ) AS historical_trend_slope,
            -- state-level prior
            AVG(agg.fail_rate) OVER (
                PARTITION BY d.state, agg.commodity_id, agg.quarter
            ) AS state_avg_fail_rate,
            -- label: fail_rate > 0 means at least one failure
            CASE WHEN agg.fail_rate > 0 THEN 1 ELSE 0 END AS label
        FROM agg_district_commodity_risk agg
        JOIN districts d ON d.id = agg.district_id
        WHERE agg.n_tests >= 3
        ORDER BY agg.district_id, agg.commodity_id, agg.quarter
    """
    import psycopg2
    import psycopg2.extras
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query)
        rows = cur.fetchall()
    return pd.DataFrame(rows)


def engineer_features(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, list[str]]:
    df = df.copy()

    # Fill missing trend slope (first quarter per district) with 0
    df["historical_trend_slope"] = df["historical_trend_slope"].fillna(0)
    df["state_avg_fail_rate"]     = df["state_avg_fail_rate"].fillna(df["lab_fail_rate_12m"])
    df["water_quality_index"]     = df["water_quality_index"].fillna(50.0)
    df["industrial_proximity_score"] = df["industrial_proximity_score"].fillna(50.0)
    df["district_pop_density"]    = df.get("district_pop_density", pd.Series(500.0, index=df.index)).fillna(500.0)

    feature_cols = [f for f in FEATURES if f in df.columns]
    X = df[feature_cols].values.astype(float)
    y = df["label"].values.astype(int)

    return X, y, feature_cols


# ============================================================
# TRAINING
# ============================================================

def train(conn, holdout_states: list[str] | None = None) -> dict:
    """
    Train on all states except holdout_states (geographic split, not random).
    Per spec: train on 20 states, test on 5 held-out states.
    """
    if holdout_states is None:
        holdout_states = ["Rajasthan", "Kerala", "Assam", "Odisha", "Himachal Pradesh"]

    logger.info("Loading training data...")
    df = load_training_data(conn)
    logger.info("Rows: %d", len(df))

    train_df = df[~df["state"].isin(holdout_states)].copy()
    test_df  = df[df["state"].isin(holdout_states)].copy()

    X_train, y_train, feat_cols = engineer_features(train_df)
    X_test,  y_test,  _         = engineer_features(test_df)

    logger.info("Train: %d rows | Test (geo holdout): %d rows", len(X_train), len(X_test))

    # Scale
    scaler  = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test  = scaler.transform(X_test)

    # Time-series CV on training set
    tscv  = TimeSeriesSplit(n_splits=10)
    cv_aucs = []
    for fold, (tr_idx, val_idx) in enumerate(tscv.split(X_train)):
        clf = RandomForestClassifier(
            n_estimators     = 200,
            max_depth        = 12,
            min_samples_leaf = 10,
            random_state     = 42,
            n_jobs           = -1,
        )
        clf.fit(X_train[tr_idx], y_train[tr_idx])
        preds = clf.predict_proba(X_train[val_idx])[:, 1]
        auc   = roc_auc_score(y_train[val_idx], preds)
        cv_aucs.append(auc)
        logger.info("CV fold %d AUC: %.4f", fold, auc)

    # Final model on full train set
    final_clf = RandomForestClassifier(
        n_estimators     = 300,
        max_depth        = 12,
        min_samples_leaf = 10,
        random_state     = 42,
        n_jobs           = -1,
    )
    final_clf.fit(X_train, y_train)

    # Holdout eval
    test_probs  = final_clf.predict_proba(X_test)[:, 1]
    test_preds  = (test_probs >= 0.5).astype(int)
    holdout_auc = roc_auc_score(y_test, test_probs)
    precision   = precision_score(y_test, test_preds, zero_division=0)
    recall      = recall_score(y_test, test_preds, zero_division=0)

    metrics = {
        "cv_auc_mean":    float(np.mean(cv_aucs)),
        "cv_auc_std":     float(np.std(cv_aucs)),
        "holdout_auc":    float(holdout_auc),
        "holdout_precision": float(precision),
        "holdout_recall": float(recall),
        "holdout_states": holdout_states,
        "n_train":        len(X_train),
        "n_test":         len(X_test),
        "features":       feat_cols,
    }

    logger.info("Holdout AUC: %.4f | Precision: %.4f | Recall: %.4f",
                holdout_auc, precision, recall)

    # Save model + scaler
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({"clf": final_clf, "scaler": scaler, "features": feat_cols}, f)
    logger.info("Model saved to %s", MODEL_PATH)

    return metrics


# ============================================================
# PREDICTION
# ============================================================

class DistrictRiskPredictor:
    def __init__(self):
        self._model = None

    def _load(self):
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"Model not found at {MODEL_PATH}. Run train() first.")
        with open(MODEL_PATH, "rb") as f:
            self._model = pickle.load(f)

    def predict(
        self,
        features: dict,
        n_bootstrap: int = 200,
        random_state: int = 42,
    ) -> dict:
        """
        Returns risk_score (0-100), ci_lower, ci_upper, shap_top3.
        Uses bootstrap of tree predictions for 95% CI.
        """
        if self._model is None:
            self._load()

        clf: RandomForestClassifier = self._model["clf"]
        scaler: StandardScaler      = self._model["scaler"]
        feat_cols: list[str]        = self._model["features"]

        # Build feature vector
        x = np.array([[features.get(f, 0.0) for f in feat_cols]], dtype=float)
        x = scaler.transform(x)

        # Mean prediction across all trees
        tree_preds = np.array([tree.predict_proba(x)[0, 1] for tree in clf.estimators_])
        risk_prob  = float(np.mean(tree_preds))
        risk_score = round(risk_prob * 100, 2)

        # Bootstrap CI
        rng       = np.random.default_rng(random_state)
        boot_means = [
            float(np.mean(rng.choice(tree_preds, size=len(tree_preds), replace=True)))
            for _ in range(n_bootstrap)
        ]
        ci_lower = round(float(np.percentile(boot_means, 2.5)) * 100, 2)
        ci_upper = round(float(np.percentile(boot_means, 97.5)) * 100, 2)

        # Feature importance as proxy for SHAP (replace with shap lib for production)
        importances = clf.feature_importances_
        top3_idx    = np.argsort(importances)[::-1][:3]
        shap_top3   = [{"feature": feat_cols[i], "importance": round(float(importances[i]), 4)}
                       for i in top3_idx]

        return {
            "risk_score": risk_score,
            "ci_lower":   ci_lower,
            "ci_upper":   ci_upper,
            "shap_top3":  shap_top3,
            "n_trees":    len(clf.estimators_),
        }


# Singleton
predictor = DistrictRiskPredictor()


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import argparse, psycopg2
    from pipeline.config import DATABASE_URL

    parser = argparse.ArgumentParser()
    parser.add_argument("--train",   action="store_true")
    parser.add_argument("--predict", action="store_true")
    args = parser.parse_args()

    if args.train:
        conn = psycopg2.connect(DATABASE_URL)
        metrics = train(conn)
        conn.close()
        print("\n=== Training Metrics ===")
        for k, v in metrics.items():
            print(f"  {k}: {v}")

    if args.predict:
        # Demo prediction
        sample = {
            "lab_fail_rate_12m":          0.15,
            "n_tests_12m":                30,
            "water_quality_index":        45.0,
            "industrial_proximity_score": 70.0,
            "seasonal_factor":            3,
            "historical_trend_slope":     0.02,
            "district_pop_density":       800.0,
            "state_avg_fail_rate":        0.12,
        }
        result = predictor.predict(sample)
        print(f"\nRisk score: {result['risk_score']} (95% CI: {result['ci_lower']}–{result['ci_upper']})")
        print(f"Top factors: {result['shap_top3']}")
