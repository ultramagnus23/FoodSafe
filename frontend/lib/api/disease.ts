import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { DistrictBurdenResponse, ContaminantMapPoint, ExposureAlertOut, BenchmarkResponse } from "./types";

export function useDistrictDisease(districtId: number, enabled = true) {
  return useQuery({
    queryKey: ["district-disease", districtId],
    queryFn: () => apiFetch<DistrictBurdenResponse>(`/v1/disease/district/${districtId}`),
    enabled: enabled && !!districtId,
    staleTime: 5 * 60 * 1000,
  });
}

export function useDiseaseMap(contaminantId: number, enabled = true) {
  return useQuery({
    queryKey: ["disease-map", contaminantId],
    queryFn: () => apiFetch<ContaminantMapPoint[]>(`/v1/disease/contaminant/${contaminantId}/map`),
    enabled: enabled && !!contaminantId,
    staleTime: 5 * 60 * 1000,
  });
}

export interface AlertFilters {
  state?: string;
  commodity_id?: number;
  contaminant_id?: number;
  severity?: string;
  alert_type?: string;
}

export function useDiseaseAlerts(filters: AlertFilters, enabled = true) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== "") params.set(k, String(v));
  });
  const qs = params.toString();
  return useQuery({
    queryKey: ["disease-alerts", filters],
    queryFn: () => apiFetch<ExposureAlertOut[]>(`/v1/disease/alerts${qs ? `?${qs}` : ""}`),
    enabled,
    staleTime: 5 * 60 * 1000,
  });
}

export function useBenchmark(contaminantId: number, commodityId: number, districtId?: number, enabled = true) {
  const qs = districtId ? `?district_id=${districtId}` : "";
  return useQuery({
    queryKey: ["benchmark", contaminantId, commodityId, districtId],
    queryFn: () =>
      apiFetch<BenchmarkResponse>(`/v1/disease/benchmark/${contaminantId}/${commodityId}${qs}`),
    enabled: enabled && !!contaminantId && !!commodityId,
    staleTime: 24 * 60 * 60 * 1000,
  });
}
