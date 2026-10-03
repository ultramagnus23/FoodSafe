"""
FoodSafe India — classify food-safety text into hazard -> health outcomes.

  GET /v1/classify?text=...

Two layers, reported separately so a reader can see which one decided:
  rules  the knowledge base (models/health_classifier.py): a named hazard,
         alias or pesticide class found in the text. Deterministic, cited.
  model  the hazard-category classifier trained on ~15,000 EU RASFF notifications
         (models/hazard_text_classifier.py; model card docs/MODEL_HAZARD_CLASSIFIER.md),
         with its probability and the words that drove it.
Decision: a rules match wins (it names the hazard); otherwise the model's category
is used only if its probability is at least MODEL_MIN_PROB; below that the
category is 'unknown'. Health outcomes come from the knowledge base for a named
hazard, or the class-level outcomes for a category, each with its source.

What this is NOT: a test result. It classifies what a text SAYS, e.g. a news
report or a label complaint; it cannot tell whether any food is contaminated.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

classify_router = APIRouter()

MODEL_MIN_PROB = 0.6


@lru_cache(maxsize=1)
def _model():
    from models.hazard_text_classifier import ARTIFACT, LinearTextModel
    if not ARTIFACT.exists():
        return None
    return LinearTextModel.load(ARTIFACT)


class RuleHit(BaseModel):
    hazard_key: Optional[str]
    hazard_name: Optional[str]
    hazard_class: Optional[str]
    matched_by: Optional[str]


class ModelOut(BaseModel):
    top: list[tuple[str, float]]
    because_of: list[tuple[str, float]]
    trained_on: str
    test_accuracy: Optional[float]
    test_macro_f1: Optional[float]


class Outcome(BaseModel):
    outcome_key: str
    outcome: str
    organ_system: str
    exposure: str
    onset: Optional[str]
    icd10: Optional[str]
    vulnerable_groups: list[str]
    evidence: str
    source_title: str
    source_url: str
    level: str


class ClassifyOut(BaseModel):
    text: str
    rules: Optional[RuleHit]
    model: Optional[ModelOut]
    hazard_category: str
    decided_by: str                  # 'rules' | 'model' | 'unknown'
    health_outcomes: list[Outcome]
    caveat: str


@classify_router.get("", response_model=ClassifyOut)
async def classify(text: str = Query(..., min_length=3, max_length=500)):
    from models.health_classifier import Classified, classify_hazard, outcomes_for
    from pipeline.sources import hazard_kb as KB

    t = text.replace("\x00", "").strip()
    if not t:
        raise HTTPException(422, "empty text")
    c = classify_hazard(t)
    rules = None
    if c.classified_by in ("kb_name", "kb_alias", "pesticide_class"):
        name = KB.HAZARDS[c.kb_key]["name"] if c.kb_key else c.hazard_key
        rules = RuleHit(hazard_key=c.kb_key or c.hazard_key, hazard_name=name, hazard_class=c.hazard_class,
                        matched_by=c.classified_by)
    m = _model()
    model_out, top_cat, top_p = None, None, 0.0
    if m is not None:
        probs = m.predict_proba(t)
        top_cat, top_p = probs[0]
        meta = m.meta.get("test", {})
        model_out = ModelOut(top=[(k, round(p, 4)) for k, p in probs[:3]], because_of=m.explain(t),
                             trained_on=m.meta.get("trained_on", ""), test_accuracy=meta.get("accuracy"),
                             test_macro_f1=meta.get("macro_f1"))
    if rules:
        category, decided = (top_cat if top_p >= MODEL_MIN_PROB else rules.hazard_class) or "unknown", "rules"
        outcomes = outcomes_for(c)
    elif top_cat and top_p >= MODEL_MIN_PROB:
        category, decided = top_cat, "model"
        outcomes = outcomes_for(Classified(None, KB.RASFF_CATEGORY_CLASS.get(top_cat), "model"))
    else:
        category, decided, outcomes = "unknown", "unknown", []
    return ClassifyOut(
        text=t, rules=rules, model=model_out, hazard_category=category, decided_by=decided,
        health_outcomes=[Outcome(**o) for o in outcomes],
        caveat="Classifies what the text says, not whether any food is contaminated. Outcomes are what the "
               "hazard can cause (with sources), not how likely they are.",
    )
