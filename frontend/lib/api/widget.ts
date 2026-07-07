import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { ProvenanceSummary } from "./types";

export interface WidgetData {
  district_id: number;
  district_name: string;
  state: string;
  commodity_id: number;
  commodity_name: string;
  risk_score: number | null;
  n_tests: number;
  provenance: ProvenanceSummary;
  disclaimer: string;
  last_updated: string | null;
}

export function useWidgetData(districtId: number, commodityId: number, enabled = true) {
  return useQuery({
    queryKey: ["widget-district-risk", districtId, commodityId],
    queryFn: () =>
      apiFetch<WidgetData>(`/v1/widget/district/${districtId}/commodity/${commodityId}`, { auth: false }),
    enabled: enabled && !!districtId && !!commodityId,
    staleTime: 5 * 60 * 1000,
  });
}
