import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { DistrictRiskResponse, BrandRiskResponse, MapDataPoint, AlertEvent } from "./types";

export function useMapData(commodityId: number, enabled = true) {
  return useQuery({
    queryKey: ["risk-map", commodityId],
    queryFn: () => apiFetch<MapDataPoint[]>(`/v1/risk/map?commodity_id=${commodityId}`),
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
  });
}

export function useDistrictRisk(districtId: number, commodityId: number, enabled = true) {
  return useQuery({
    queryKey: ["district-risk", districtId, commodityId],
    queryFn: () =>
      apiFetch<DistrictRiskResponse>(`/v1/risk/district/${districtId}/commodity/${commodityId}`),
    enabled: enabled && !!districtId && !!commodityId,
    staleTime: 5 * 60 * 1000,
  });
}

export function useBrandRisk(brandId: number, commodityId: number, districtId: number, enabled = true) {
  return useQuery({
    queryKey: ["brand-risk", brandId, commodityId, districtId],
    queryFn: () =>
      apiFetch<BrandRiskResponse>(`/v1/risk/brand/${brandId}/product/${commodityId}/district/${districtId}`),
    enabled: enabled && !!brandId && !!commodityId && !!districtId,
  });
}

export function useRiskAlerts(limit = 12, enabled = true) {
  return useQuery({
    queryKey: ["risk-alerts", limit],
    queryFn: () => apiFetch<AlertEvent[]>(`/v1/risk/alerts?limit=${limit}`),
    enabled,
    staleTime: 5 * 60 * 1000,
  });
}
