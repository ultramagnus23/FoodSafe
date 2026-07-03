import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";

export interface DistrictSummary {
  district_id: number;
  district_name: string;
  state: string;
  risk_score: number | null;
  ci_lower: number | null;
  ci_upper: number | null;
  n_tests: number;
  fail_rate: number | null;
  codex_compliant_fraction: number | null;
  top_contaminants: { name: string; fail_rate: number }[];
  inference_type: string;
}

export interface CompareResponse {
  commodity_id: number;
  commodity_name: string;
  a: DistrictSummary;
  b: DistrictSummary;
  delta: {
    risk_score_delta: number | null;
    fail_rate_delta: number | null;
    codex_compliant_fraction_delta: number | null;
  };
  disclaimer: string;
}

export function useCompareDistricts(a: number, b: number, commodityId: number, enabled = true) {
  return useQuery({
    queryKey: ["compare-districts", a, b, commodityId],
    queryFn: () => apiFetch<CompareResponse>(`/v1/compare/districts?a=${a}&b=${b}&commodity_id=${commodityId}`),
    enabled: enabled && !!a && !!b && a !== b && !!commodityId,
  });
}

export interface BestDistrict {
  district_id: number;
  district_name: string;
  state: string;
  risk_score: number;
  n_tests: number;
  codex_compliant_fraction: number | null;
}

export function useBestDistricts(commodityId: number, enabled = true) {
  return useQuery({
    queryKey: ["best-districts", commodityId],
    queryFn: () => apiFetch<BestDistrict[]>(`/v1/compare/best?commodity_id=${commodityId}`),
    enabled: enabled && !!commodityId,
  });
}

export interface StandardsRow {
  contaminant_id: number;
  contaminant_name: string;
  fssai_limit_ppb: number | null;
  codex_limit_ppb: number | null;
  eu_limit_ppb: number | null;
  fssai_vs_codex_ratio: number | null;
  codex_doc_reference: string | null;
}

export function useStandardsTable(enabled = true) {
  return useQuery({
    queryKey: ["standards-table"],
    queryFn: () => apiFetch<StandardsRow[]>("/v1/compare/standards"),
    enabled,
    staleTime: 24 * 60 * 60 * 1000,
  });
}
