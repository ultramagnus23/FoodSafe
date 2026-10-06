// In-browser port of the hazard classification the API serves at POST /v1/classify:
// knowledge-base rules first (models/health_classifier.py), then the TF-IDF + logistic
// regression model trained on EU RASFF subjects (models/hazard_text_classifier.py), used only
// when it is at least 60% sure. Same tokeniser and weights as the Python model.
import type { Effect, Hazard, HazardModel, HazardRule } from "./snapshot";

const STOP = new Set(["in", "of", "the", "and", "from", "for", "with", "on", "a", "an", "to", "by", "at", "or", "as", "is"]);
export const MODEL_THRESHOLD = 0.6;

function tokens(text: string): string[] {
  let t = text.toLowerCase();
  if (t.includes("///")) t = t.split("///").pop() || "";
  t = t.replace(/\bfrom\s+[^,;()]+$/, " ").replace(/\s+/g, " ").trim();
  const w = (t.match(/[a-z][a-z0-9-]+|\d+/g) || []).filter((x) => !STOP.has(x));
  return w.concat(w.slice(1).map((x, i) => `${w[i]}_${x}`));
}

export interface ModelResult {
  probs: { category: string; p: number }[];
  why: string[];
}

export function scoreText(M: HazardModel, text: string): ModelResult {
  const tf: Record<string, number> = {};
  for (const t of tokens(text)) if (t in M.idf) tf[t] = (tf[t] || 0) + 1;
  const v: Record<string, number> = {};
  let norm = 0;
  for (const t in tf) {
    v[t] = (1 + Math.log(tf[t])) * M.idf[t];
    norm += v[t] * v[t];
  }
  norm = Math.sqrt(norm) || 1;
  const s = M.intercept.slice();
  const contrib: [string, number, number][] = [];
  for (const t in v) {
    const x = v[t] / norm;
    for (const [ci, w] of M.weights[t] || []) {
      s[ci] += w * x;
      contrib.push([t, ci, w * x]);
    }
  }
  const m = Math.max(...s);
  const ex = s.map((z) => Math.exp(z - m));
  const z = ex.reduce((a, b) => a + b, 0);
  const ranked = M.classes.map((c, i) => ({ category: c, p: ex[i] / z, i })).sort((a, b) => b.p - a.p);
  const top = ranked[0].i;
  const why = contrib
    .filter((c) => c[1] === top && c[2] > 0)
    .sort((a, b) => b[2] - a[2])
    .slice(0, 5)
    .map((c) => c[0].replace("_", " "));
  return { probs: ranked.map(({ category, p }) => ({ category, p })), why };
}

export interface Classification {
  label: string;
  hazardClass: string | null;
  pesticideClass: string | null;
  decidedBy: string;
  effects: Effect[];
  matchedHazard: boolean;
  model: ModelResult;
}

type CompiledRule = HazardRule & { rx: RegExp };
let compiled: { from: HazardRule[]; rules: CompiledRule[] } | null = null;

function compile(rules: HazardRule[]): CompiledRule[] {
  if (compiled && compiled.from === rules) return compiled.rules;
  const out: CompiledRule[] = [];
  for (const r of rules) {
    if (r.key === "undeclared_allergen") continue;
    try {
      out.push({ ...r, rx: new RegExp(r.pattern) });
    } catch {
      /* a pattern this browser's regex engine can't compile is skipped, not fatal */
    }
  }
  compiled = { from: rules, rules: out };
  return out;
}

export function classify(text: string, M: HazardModel, rules: HazardRule[], hazards: Hazard[]): Classification {
  const low = text.toLowerCase().replace(/\s+/g, " ");
  const hit = compile(rules).find((r) => r.rx.test(low));
  const model = scoreText(M, text);
  const top = model.probs[0];
  const kb = hit ? hazards.find((h) => h.hazard_key === hit.key) : undefined;
  const confident = top.p >= MODEL_THRESHOLD;
  const decidedBy = hit
    ? hit.pclass
      ? `the knowledge base knows it as ${/^[aeiou]/.test(hit.pclass) ? "an" : "a"} ${hit.pclass.replace(/_/g, " ")} pesticide`
      : "the knowledge base matched a named hazard"
    : confident
      ? "the model is confident enough"
      : "neither layer is confident, so the category is unknown";
  const label = hit ? hit.name : confident ? top.category.charAt(0).toUpperCase() + top.category.slice(1) : "Unknown";
  return {
    label,
    hazardClass: hit ? hit.class.replace(/_/g, " ") : null,
    pesticideClass: hit?.pclass ?? null,
    decidedBy,
    effects: kb ? kb.effects : hit?.effects ?? [],
    matchedHazard: !!hit,
    model,
  };
}
