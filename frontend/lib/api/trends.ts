import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";

export interface MonthlyPoint {
  month: string;
  mean_ppb: number;
  max_ppb: number;
  fail_rate_fssai: number | null;
  fail_rate_codex: number | null;
  n_records: number;
}

export interface TrendResponse {
  series: MonthlyPoint[];
  trend: "improving" | "worsening" | "stable" | "insufficient_data";
  trend_pvalue: number | null;
  trend_magnitude: number | null;
  disclaimer: string;
}

export function useDistrictTrend(districtId: number, commodityId?: number, contaminantId?: number, enabled = true) {
  const params = new URLSearchParams();
  if (commodityId) params.set("commodity_id", String(commodityId));
  if (contaminantId) params.set("contaminant_id", String(contaminantId));
  const qs = params.toString();
  return useQuery({
    queryKey: ["district-trend", districtId, commodityId, contaminantId],
    queryFn: () => apiFetch<TrendResponse>(`/v1/trends/district/${districtId}${qs ? `?${qs}` : ""}`),
    enabled: enabled && !!districtId,
    staleTime: 30 * 60 * 1000,
  });
}
