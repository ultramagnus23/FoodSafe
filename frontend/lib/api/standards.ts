import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";

// Public (no auth) — see api/routes/standards.py and docs/STANDARDS.md.
// Legal limits from India (FSSAI), the EU, Codex and the US, compared per
// food–hazard pair. Every value is in mg/kg; `basis` says where it came from.

export type Basis =
  | "specific"
  | "group"
  | "residual"
  | "eu_default"
  | "none"
  | "not_loaded"
  | "not_numeric";

export interface LimitCell {
  value_mg_per_kg: number | null;
  basis: Basis | string;
  ratio_india_over: number | null;
}

export interface Comparison {
  standard_type: "pesticide_mrl" | "contaminant_ml";
  hazard_key: string;
  hazard_name: string;
  food_key: string;
  food_name: string | null;
  india: LimitCell;
  eu: LimitCell;
  codex: LimitCell;
  us: LimitCell;
  flags: string[];
  eu_status: string | null;
  iarc_group: string | null;
}

export interface CompareResponse {
  results: Comparison[];
  total: number;
  caveats: string[];
}

export interface StandardsSummary {
  jurisdictions: Record<string, string>;
  rows_by_jurisdiction: Record<string, Record<string, number>>;
  snapshots: {
    jurisdiction: string;
    document_title: string;
    document_url: string;
    document_version: string | null;
    rows_loaded: number;
    loaded_at: string;
  }[];
  comparisons: number;
  india_higher_than_eu: number;
  india_higher_than_codex: number;
  india_higher_than_us: number;
  no_us_tolerance: number;
  no_codex_standard: number;
  eu_default_applies: number;
  india_internal_conflict: number;
  /** Why India's limit is above the EU's: eu_gap_* reason -> pairs, plus "contaminant". */
  india_higher_than_eu_why?: Record<string, number>;
  india_pesticides: number;
  india_pesticides_not_approved_in_eu: number;
  hazards_in_kb: number;
  health_effect_rows: number;
  caveats: string[];
}

export interface StandardsFood {
  food_key: string;
  name: string;
  food_group: string;
  hazards_compared: number;
  india_higher_than_eu: number;
}

const DAY = 24 * 60 * 60 * 1000;

export function useStandardsSummary() {
  return useQuery({
    queryKey: ["standards-summary"],
    queryFn: () => apiFetch<StandardsSummary>("/v1/standards/summary", { auth: false }),
    staleTime: DAY,
  });
}

export function useStandardsFoods() {
  return useQuery({
    queryKey: ["standards-foods"],
    queryFn: () => apiFetch<StandardsFood[]>("/v1/standards/foods", { auth: false }),
    staleTime: DAY,
  });
}

export const COMPARE_PAGE_SIZE = 50;

export interface CompareQuery {
  food?: string;
  standardType?: "pesticide_mrl" | "contaminant_ml";
  flag?: string;
  page?: number;
}

export function useStandardsCompare({ food, standardType, flag, page = 0 }: CompareQuery) {
  const params = new URLSearchParams({
    sort: "ratio_eu",
    limit: String(COMPARE_PAGE_SIZE),
    offset: String(page * COMPARE_PAGE_SIZE),
  });
  if (food) params.set("food", food);
  if (standardType) params.set("standard_type", standardType);
  if (flag) params.set("flag", flag);
  return useQuery({
    queryKey: ["standards-compare", food ?? null, standardType ?? null, flag ?? null, page],
    queryFn: () => apiFetch<CompareResponse>(`/v1/standards/compare?${params}`, { auth: false }),
    staleTime: DAY,
    placeholderData: keepPreviousData,
  });
}
