"use client";

import { useQuery } from "@tanstack/react-query";

// The daily snapshot of production data that scripts/export_portal.py writes and
// .github/workflows/deploy-pages.yml publishes to GitHub Pages after each ingest. Public
// pages read it instead of the API: it is static (CDN, CORS *), has no rate limit and no
// cold start, and is the same tables the API serves. Interactive lookups still go to the API.
export const SNAPSHOT_BASE =
  process.env.NEXT_PUBLIC_SNAPSHOT_URL || "https://ultramagnus23.github.io/FoodSafe/data/live";

export interface SnapshotMeta {
  generated_at: string;
  files: Record<string, number | null>;
}

export interface StandardsSummary {
  rows: { jurisdiction: string; standard_type: string; n: number }[];
  snapshots: {
    jurisdiction: string;
    document_title: string;
    document_url: string;
    document_version: string | null;
    rows_loaded: number;
    loaded_at: string;
  }[];
  flags: {
    comparisons: number;
    india_higher_than_eu: number;
    india_higher_than_codex: number;
    india_higher_than_us: number;
    no_us_tolerance: number;
    eu_default: number;
    max_ratio_eu: number | null;
    not_approved_in_eu: number;
    india_pesticides: number;
    higher_eu_pesticides: number;
    gap_not_approved: number;
    gap_no_use_on_food: number;
    gap_never_assessed: number;
    gap_at_loq: number;
    gap_above_loq: number;
    gap_above_loq_median_ratio: number | null;
  };
}

/** One food-hazard pair, short keys as exported (see export_portal.standards_compare). */
export interface StdRow {
  t: "pesticide_mrl" | "contaminant_ml";
  h: string;
  hn: string | null;
  f: string;
  i: number | null;
  e: number | null;
  eb: string | null;
  c: number | null;
  cb: string | null;
  u: number | null;
  ub: string | null;
  re: number | null;
  rc: number | null;
  ru: number | null;
  flags: string[] | null;
  st: string | null;
  ig: string | null;
  ib: string | null;
}

export interface Effect {
  outcome: string;
  organ: string;
  exposure: string;
  onset: string | null;
  vulnerable: string[] | null;
  evidence: string;
  source: string;
  url: string;
}

export interface Hazard {
  hazard_key: string;
  name: string;
  hazard_class: string;
  iarc_group: string | null;
  summary: string | null;
  effects: Effect[];
}

export interface HealthProfile {
  origin: string;
  outcome_key: string;
  outcome: string;
  organ_system: string;
  exposure: string;
  notifications: number;
  share_of_classified: number | null;
  serious_notifications: number;
  top_hazards: [string, number][] | null;
  sources: { url: string; title: string }[] | null;
}

export interface RasffCountry {
  origin: string;
  notifications: number;
  serious: number;
  border_rejections: number;
  first: string | null;
  last: string | null;
}

export interface RasffIndia {
  by_year: { year: number; n: number }[];
  by_category: { category: string; n: number }[];
  top_hazards: { hazard: string; n: number }[];
  by_product: { product: string; n: number }[];
}

export interface MeasuredFinding {
  id: number;
  date: string;
  subject: string;
  product: string | null;
  hazard: string;
  mg_kg: number;
  chronic_g: number | null;
  acute_g: number | null;
  guidance: string | null;
  reason: string | null;
  url: string;
}

export interface Country {
  iso3: string;
  iso2: string | null;
  name: string;
  region: string | null;
  income_level: string | null;
  ind: Record<string, [number, number]> | null;
}

export interface BurdenRow {
  measure: string;
  age_group: string;
  hazard_group: string;
  hazard: string;
  value: number;
}

export interface NutritionSummary {
  products: number;
  nutriscore: { g: string; n: number }[];
  nova: { g: number; n: number }[];
  high_in: { k: string; n: number }[];
  complete: number;
  categories: { category: string; products: number; de: number; graded: number; nova4: number }[];
}

/** [fiscal year, samples analysed, samples non-conforming] */
export interface StateSeries {
  state: string;
  series: [string, number, number][];
}

export interface SourceInfo {
  id: string;
  name: string;
  publisher: string;
  publisher_type: string;
  access: string;
  content_kind: string;
  grain: string;
  coverage: string;
  scope: string[];
  base_confidence: "high" | "medium" | "low" | "demo";
  doc?: string | null;
  rows: number | null;
}

export interface HazardModel {
  classes: string[];
  idf: Record<string, number>;
  weights: Record<string, [number, number][]>;
  intercept: number[];
  meta: {
    trained_on: string;
    train_until: string;
    n_train: number;
    test?: { accuracy: number; macro_f1: number; n?: number };
    [k: string]: unknown;
  };
}

export interface HazardRule {
  pattern: string;
  key: string;
  name: string;
  class: string;
  pclass?: string;
  effects?: Effect[];
}

export interface SnapshotFiles {
  meta: SnapshotMeta;
  standards_summary: StandardsSummary;
  standards_compare: StdRow[];
  hazards: Hazard[];
  health_profiles: HealthProfile[];
  rasff_countries: RasffCountry[];
  rasff_india: RasffIndia;
  rasff_india_measured: MeasuredFinding[];
  countries: Country[];
  burden: BurdenRow[];
  nutrition: NutritionSummary;
  states: StateSeries[];
  sources: SourceInfo[];
  hazard_model: HazardModel;
  hazard_rules: HazardRule[];
}

export async function fetchSnapshot<K extends keyof SnapshotFiles>(name: K): Promise<SnapshotFiles[K]> {
  let res: Response;
  try {
    res = await fetch(`${SNAPSHOT_BASE}/${name}.json`);
  } catch {
    throw new Error(`Could not reach the data snapshot (${name}).`);
  }
  if (!res.ok) throw new Error(`${name}: HTTP ${res.status}`);
  return (await res.json()) as SnapshotFiles[K];
}

export function useSnapshot<K extends keyof SnapshotFiles>(name: K, enabled = true) {
  return useQuery({
    queryKey: ["snapshot", name],
    queryFn: () => fetchSnapshot(name),
    staleTime: 10 * 60 * 1000,
    enabled,
  });
}

/** ISO2 -> country name, from the countries file (falls back to the code). */
export function useCountryNames(): Record<string, string> {
  const co = useSnapshot("countries");
  const names: Record<string, string> = { ALL: "All origins" };
  for (const c of co.data ?? []) if (c.iso2) names[c.iso2] = c.name;
  return names;
}

// ---- formatting shared by the snapshot pages

const IN_LOCALE = "en-IN";

export function num(n: number | null | undefined, digits = 0): string {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return Number(n).toLocaleString(IN_LOCALE, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

/** A concentration in mg/kg: plain above 1, two significant figures below. */
export function mgkg(v: number | null | undefined): string {
  if (v == null) return "—";
  return v >= 1 ? num(v, 2) : Number(v).toPrecision(2).replace(/\.?0+e/, "e");
}

export function pct(part: number, whole: number, digits = 0): string {
  return whole ? `${num((100 * part) / whole, digits)}%` : "—";
}

export function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

export function capitalise(s: string | null | undefined): string {
  if (!s) return "";
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** RASFF hazard text without the "- unauthorised substance" style suffix. */
export function cleanHazard(h: string | null | undefined): string {
  return String(h || "")
    .replace(/\s+-\s+.*$/, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function grams(g: number | null | undefined): string | null {
  if (g == null) return null;
  if (g >= 10000) return "over 10 kg";
  if (g >= 1000) return `${num(g / 1000, 1)} kg`;
  return `${num(g)} g`;
}

export function snapshotStamp(meta: SnapshotMeta | undefined): string {
  if (!meta) return "";
  return meta.generated_at.replace("T", " ").replace("+00:00", " UTC");
}

export const FOODS: Record<string, string> = {
  rice: "Rice", wheat: "Wheat", maize: "Maize", sorghum: "Sorghum (jowar)", millet: "Millets", chickpea: "Chickpea",
  lentil: "Lentil", pigeon_pea: "Pigeon pea (tur)", black_gram: "Black gram (urad)", green_gram: "Green gram (mung)",
  dry_beans: "Dry beans", dry_peas: "Dry peas", soybean: "Soybean", groundnut: "Groundnut", mustard_seed: "Mustard seed",
  sesame: "Sesame", cottonseed: "Cottonseed", sunflower_seed: "Sunflower seed", tea: "Tea", coffee: "Coffee",
  chilli_dried: "Dried chilli", black_pepper: "Black pepper", cardamom: "Cardamom", cumin: "Cumin",
  coriander_seed: "Coriander seed", turmeric: "Turmeric", ginger: "Ginger", mango: "Mango", banana: "Banana",
  grapes: "Grapes", pomegranate: "Pomegranate", apple: "Apple", orange: "Orange", lemon_lime: "Lemon / lime",
  papaya: "Papaya", guava: "Guava", pineapple: "Pineapple", tomato: "Tomato", potato: "Potato", onion: "Onion",
  brinjal: "Brinjal", okra: "Okra", cabbage: "Cabbage", cauliflower: "Cauliflower", chilli_fresh: "Green chilli / peppers",
  cucumber: "Cucumber", spinach: "Spinach", sugarcane: "Sugarcane", milk: "Milk", eggs: "Eggs",
  poultry_meat: "Poultry meat", bovine_meat: "Bovine meat", honey: "Honey", fish: "Fish", coconut: "Coconut",
};
