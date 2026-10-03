"""
Hazard-category classifier for food-safety text (ML).

Task: given a short text about a food-safety problem ('Aflatoxins in groundnuts',
'Salmonella in chicken meat', 'Ethylene oxide in sesame seeds', a news headline),
predict the hazard category (pesticide residues, pathogenic micro-organisms,
mycotoxins, heavy metals, allergens, ...). Paired with the knowledge base
(models/health_classifier.py) this turns free text into likely health outcomes.

Training data: EU RASFF notifications, every origin country, 2020 -> 2026. Each
notification's SUBJECT line is the text; the hazard category of its first listed
hazard, as recorded by the notifying authority, is the label. These are real,
independent expert labels (the authority classifies the hazard it found), not
labels FoodSafe made up.

Leakage control (decided before results were looked at):
  * temporal split — train on notifications validated up to 2024-12-31, test on
    2025-01-01 onward; hyper-parameters are chosen on 2024 held out from training;
  * origin-country names and 'from <country>' phrases are removed from the text, so
    the model cannot learn "country X -> category Y" (it is meant for text about
    Indian food, where the country is always India);
  * multilingual subjects keep only their English part (after '///').
Baselines reported next to the model: the majority class, and a keyword lookup
(the category most often seen in training for the first known hazard term in the
subject).

The trained model is exported as plain JSON (vocabulary, idf, sparse weights) and
scored in pure Python, so the API needs no scikit-learn.

Train (offline, needs scikit-learn):
  python -m models.hazard_text_classifier train --dump <dir with list.jsonl, detail.jsonl>
  python -m models.hazard_text_classifier train --from-db
Predict:
  python -m models.hazard_text_classifier predict "aflatoxin in red chilli powder"
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Optional

ARTIFACT = Path(__file__).parent / "artifacts" / "hazard_text_classifier.json"
REPORT = Path(__file__).parent.parent / "docs" / "MODEL_HAZARD_CLASSIFIER.md"
MIN_CLASS_TRAIN = 40          # categories rarer than this in training are merged into 'other hazards'
TEST_FROM = "2025-01-01"
VALID_FROM = "2024-01-01"

_TOKEN = re.compile(r"[a-z][a-z0-9\-]+|\d+")
_STOP = {"in", "of", "the", "and", "from", "for", "with", "on", "a", "an", "to", "by", "at", "or", "as", "is"}


# ---------------------------------------------------------------- text

def english_part(subject: str) -> str:
    s = subject or ""
    if "///" in s:
        s = s.split("///")[-1]
    return s.strip()


# Country names that are also food or hazard words: 'Sudan' (Sudan I-IV dyes),
# 'Turkey' (turkey meat), 'Guinea' (guinea fowl). They are not removed from the
# text body; the trailing 'from <country>' phrase still is.
AMBIGUOUS_COUNTRY_WORDS = {"sudan", "south sudan", "turkey", "guinea", "chad", "jersey", "georgia", "jordan"}


def clean(subject: str, countries: Iterable[str] = ()) -> str:
    t = english_part(subject).lower()
    t = re.sub(r"\bfrom\s+[^,;()]+$", " ", t)              # trailing 'from Poland', 'from India via Belgium'
    t = re.sub(r"\b(?:originating|origin)\s+(?:in|from)?\s*[^,;()]+$", " ", t)
    for c in countries:
        if c and c.lower() not in AMBIGUOUS_COUNTRY_WORDS:
            t = re.sub(r"(?<![a-z])" + re.escape(c.lower()) + r"(?![a-z])", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def tokens(text: str) -> list[str]:
    toks = [w for w in _TOKEN.findall(text.lower()) if w not in _STOP]
    return toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]


# ---------------------------------------------------------------- data

def load_dump(dump_dir: str) -> list[dict]:
    d = Path(dump_dir)
    listed = {}
    for line in open(d / "list.jsonl", encoding="utf-8"):
        n = json.loads(line)
        listed[n["notifId"]] = n
    rows = []
    for line in open(d / "detail.jsonl", encoding="utf-8"):
        try:
            x = json.loads(line)
        except json.JSONDecodeError:
            continue                                    # a line cut off when the dump was stopped
        det = x.get("detail")
        n = listed.get(x.get("notifId"))
        if not n or not isinstance(det, dict) or "product" not in det:
            continue
        cats = [((h.get("hazardCategory") or {}).get("description") or "").strip()
                for h in (det.get("product") or {}).get("hazards") or []]
        cats = [c for c in cats if c]
        if not cats:
            continue
        v = n.get("ecValidationDate") or ""
        rows.append({"id": n["notifId"], "date": f"{v[6:10]}-{v[3:5]}-{v[0:2]}", "subject": n.get("subject") or "",
                     "label": cats[0], "labels": sorted(set(cats)),
                     "origins": [o.get("organizationName") for o in n.get("originCountries") or []]})
    return rows


def load_db() -> list[dict]:
    from pipeline.config import pg_connect
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT n.notif_id, n.validation_date::text, n.subject, n.origin_countries,
                                  array_agg(h.hazard_category ORDER BY h.id) FILTER (WHERE h.hazard_category IS NOT NULL)
                           FROM rasff_notifications n JOIN rasff_hazards h USING (notif_id)
                           GROUP BY 1, 2, 3, 4""")
            out = []
            for nid, d, subj, origins, cats in cur.fetchall():
                if cats:
                    out.append({"id": nid, "date": d, "subject": subj or "", "label": cats[0],
                                "labels": sorted(set(cats)), "origins": []})
            return out
    finally:
        conn.close()


COUNTRY_NAMES_FALLBACK = ["India", "China", "Turkey", "Türkiye", "Brazil", "Poland", "United States", "Vietnam",
                          "Viet Nam", "Thailand", "Egypt", "Morocco", "Spain", "Italy", "France", "Germany",
                          "Netherlands", "Pakistan", "Bangladesh", "Sri Lanka", "Nigeria", "Ukraine", "Argentina"]


# ---------------------------------------------------------------- pure-python model

class LinearTextModel:
    """TF-IDF (sublinear tf, l2-normalised) + multinomial linear scores."""

    def __init__(self, data: dict):
        self.classes: list[str] = data["classes"]
        self.idf: dict[str, float] = data["idf"]
        self.weights: dict[str, list[list[float]]] = data["weights"]   # token -> [[class_idx, w], ...]
        self.intercept: list[float] = data["intercept"]
        self.meta = data.get("meta", {})

    @classmethod
    def load(cls, path: Path = ARTIFACT) -> "LinearTextModel":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def vector(self, text: str) -> dict[str, float]:
        tf = Counter(t for t in tokens(clean(text)) if t in self.idf)
        v = {t: (1 + math.log(c)) * self.idf[t] for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def predict_proba(self, text: str) -> list[tuple[str, float]]:
        v = self.vector(text)
        scores = list(self.intercept)
        for t, x in v.items():
            for ci, w in self.weights.get(t, []):
                scores[int(ci)] += w * x
        m = max(scores)
        ex = [math.exp(s - m) for s in scores]
        z = sum(ex)
        return sorted(((c, e / z) for c, e in zip(self.classes, ex)), key=lambda p: -p[1])

    def explain(self, text: str, top: int = 5) -> list[tuple[str, float]]:
        """Tokens that pushed the top class up most (token, contribution)."""
        v = self.vector(text)
        best = self.classes.index(self.predict_proba(text)[0][0])
        contrib = []
        for t, x in v.items():
            for ci, w in self.weights.get(t, []):
                if int(ci) == best:
                    contrib.append((t, round(w * x, 4)))
        return sorted(contrib, key=lambda p: -p[1])[:top]


# ---------------------------------------------------------------- training (offline)

def _keyword_baseline(train: list[dict], test: list[dict]) -> list[str]:
    term_cat: dict[str, Counter] = defaultdict(Counter)
    majority = Counter(r["y"] for r in train).most_common(1)[0][0]
    for r in train:
        for t in tokens(r["text"])[:3]:
            term_cat[t][r["y"]] += 1
    preds = []
    for r in test:
        pred = majority
        for t in tokens(r["text"]):
            if t in term_cat:
                pred = term_cat[t].most_common(1)[0][0]
                break
        preds.append(pred)
    return preds


def train(rows: list[dict]) -> dict:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, f1_score, classification_report

    countries = sorted({c for r in rows for c in r["origins"] if c} | set(COUNTRY_NAMES_FALLBACK), key=len, reverse=True)
    for r in rows:
        r["text"] = clean(r["subject"], countries)
    rows = [r for r in rows if r["text"]]
    train_rows = [r for r in rows if r["date"] < TEST_FROM]
    test_rows = [r for r in rows if r["date"] >= TEST_FROM]
    counts = Counter(r["label"] for r in train_rows)
    keep = {c for c, n in counts.items() if n >= MIN_CLASS_TRAIN}
    for r in rows:
        r["y"] = r["label"] if r["label"] in keep else "other hazards"
    fit_rows = [r for r in train_rows if r["date"] < VALID_FROM]
    val_rows = [r for r in train_rows if r["date"] >= VALID_FROM]

    def vec():
        return TfidfVectorizer(tokenizer=tokens, lowercase=False, token_pattern=None, sublinear_tf=True, min_df=2,
                               norm="l2")

    best = None
    for C in (2.0, 5.0, 10.0, 20.0):
        v = vec()
        X = v.fit_transform([r["text"] for r in fit_rows])
        m = LogisticRegression(C=C, max_iter=3000)
        m.fit(X, [r["y"] for r in fit_rows])
        p = m.predict(v.transform([r["text"] for r in val_rows]))
        f1 = f1_score([r["y"] for r in val_rows], p, average="macro")
        if best is None or f1 > best[0]:
            best = (f1, C)
    C = best[1]
    v = vec()
    X = v.fit_transform([r["text"] for r in train_rows])
    m = LogisticRegression(C=C, max_iter=3000)
    m.fit(X, [r["y"] for r in train_rows])
    y_test = [r["y"] for r in test_rows]
    p_test = list(m.predict(v.transform([r["text"] for r in test_rows])))
    majority = Counter(r["y"] for r in train_rows).most_common(1)[0][0]
    kw = _keyword_baseline(train_rows, test_rows)
    in_any = sum(1 for r, p in zip(test_rows, p_test) if p in r["labels"] or (p == "other hazards" and r["y"] == p))
    india = [i for i, r in enumerate(test_rows) if "India" in r["origins"]]
    metrics = {
        "model": {"accuracy": accuracy_score(y_test, p_test), "macro_f1": f1_score(y_test, p_test, average="macro"),
                  "weighted_f1": f1_score(y_test, p_test, average="weighted"),
                  "correct_if_any_listed_category": in_any / len(test_rows)},
        "keyword_baseline": {"accuracy": accuracy_score(y_test, kw), "macro_f1": f1_score(y_test, kw, average="macro")},
        "majority_baseline": {"class": majority, "accuracy": sum(y == majority for y in y_test) / len(y_test),
                              "macro_f1": f1_score(y_test, [majority] * len(y_test), average="macro")},
        "india_origin_test": {"n": len(india),
                              "accuracy": (sum(y_test[i] == p_test[i] for i in india) / len(india)) if india else None},
        "chosen_C": C, "validation_macro_f1": best[0],
        "n_train": len(train_rows), "n_test": len(test_rows), "n_fit": len(fit_rows), "n_validation": len(val_rows),
        "classes": list(m.classes_), "per_class": classification_report(y_test, p_test, output_dict=True,
                                                                         zero_division=0),
    }
    # export: idf + sparse weights (drop |w| < 0.05, which changes no test prediction materially; checked below)
    vocab = v.vocabulary_
    idf = v.idf_
    inv = {i: t for t, i in vocab.items()}
    coef = m.coef_
    weights: dict[str, list[list[float]]] = {}
    for j in range(coef.shape[1]):
        ws = [[ci, round(float(coef[ci, j]), 4)] for ci in range(coef.shape[0]) if abs(coef[ci, j]) >= 0.05]
        if ws:
            weights[inv[j]] = ws
    data = {"classes": list(m.classes_), "idf": {inv[j]: round(float(idf[j]), 4) for j in range(len(idf))
                                                if inv[j] in weights},
            "weights": weights, "intercept": [round(float(b), 4) for b in m.intercept_],
            "meta": {"trained_on": "EU RASFF notification subjects, all origins", "train_until": TEST_FROM,
                     "n_train": len(train_rows), "C": C, "test": {k: metrics["model"][k] for k in metrics["model"]}}}
    pure = LinearTextModel(data)
    agree = sum(pure.predict_proba(r["text"])[0][0] == p for r, p in zip(test_rows, p_test)) / len(test_rows)
    metrics["export_agreement_with_sklearn"] = agree
    return {"artifact": data, "metrics": metrics}


def write_report(metrics: dict, source: str) -> None:
    mm, kb, mj = metrics["model"], metrics["keyword_baseline"], metrics["majority_baseline"]
    pc = metrics["per_class"]
    lines = [
        "# Model card: hazard-category text classifier",
        "",
        "Generated by `python -m models.hazard_text_classifier train` — do not edit by hand.",
        "",
        "**What it does.** Reads a short food-safety text and predicts the hazard category. Used with the",
        "knowledge base (`models/health_classifier.py`) to map free text to likely health outcomes.",
        "",
        f"**Training data.** EU RASFF notification subjects, every origin country ({source}); label = the",
        "notifying authority's category for the first hazard. Train: validated before "
        f"{TEST_FROM} (n={metrics['n_train']:,}); test: from {TEST_FROM} (n={metrics['n_test']:,}).",
        f"Hyper-parameter C={metrics['chosen_C']} chosen on 2024 held out from training "
        f"(validation macro-F1 {metrics['validation_macro_f1']:.3f}). Country names are removed from the text.",
        "",
        "**Model.** TF-IDF (word unigrams + bigrams, sublinear tf) + multinomial logistic regression; exported",
        "as JSON and scored in pure Python "
        f"(export agrees with scikit-learn on {metrics['export_agreement_with_sklearn']:.1%} of test texts).",
        "",
        "## Results on the held-out future period",
        "",
        "| | accuracy | macro-F1 |",
        "|---|---|---|",
        f"| **model** | {mm['accuracy']:.3f} | {mm['macro_f1']:.3f} |",
        f"| keyword baseline | {kb['accuracy']:.3f} | {kb['macro_f1']:.3f} |",
        f"| majority class ('{mj['class']}') | {mj['accuracy']:.3f} | {mj['macro_f1']:.3f} |",
        "",
        f"Weighted F1 {mm['weighted_f1']:.3f}. Counting a prediction as right when it matches ANY category the "
        f"notification lists: {mm['correct_if_any_listed_category']:.3f}.",
    ]
    ind = metrics["india_origin_test"]
    if ind["n"]:
        lines.append(f"India-origin notifications in the test period: n={ind['n']}, accuracy {ind['accuracy']:.3f}.")
    lines += ["", "## Per category (test period)", "", "| category | precision | recall | F1 | n |", "|---|---|---|---|---|"]
    for c in metrics["classes"]:
        r = pc.get(c, {})
        lines.append(f"| {c} | {r.get('precision', 0):.2f} | {r.get('recall', 0):.2f} | {r.get('f1-score', 0):.2f} | "
                     f"{int(r.get('support', 0))} |")
    lines += ["", "## Limits", "",
              "* Trained on regulatory subject lines, which name the hazard explicitly; it is a hazard-text",
              "  categoriser, not a detector of contamination. On news text it should be read with its",
              "  probability, and a low-confidence prediction treated as unknown.",
              "* Categories are the notifier's; 'other hazards' merges categories with fewer than "
              f"{MIN_CLASS_TRAIN} training examples.",
              "* Labels are the first hazard's category; multi-hazard notifications (about 1.5%) have more.", ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--dump")
    t.add_argument("--from-db", action="store_true")
    p = sub.add_parser("predict")
    p.add_argument("text")
    a = ap.parse_args()
    if a.cmd == "train":
        rows = load_db() if a.from_db else load_dump(a.dump)
        out = train(rows)
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(out["artifact"], separators=(",", ":")), encoding="utf-8")
        write_report(out["metrics"], "database" if a.from_db else "RASFF Window API dump")
        print(json.dumps({k: v for k, v in out["metrics"].items() if k != "per_class"}, indent=2, default=str))
    else:
        m = LinearTextModel.load()
        print(m.predict_proba(a.text)[:3], m.explain(a.text))


if __name__ == "__main__":
    main()
