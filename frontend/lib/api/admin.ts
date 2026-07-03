import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export interface PlatformStats {
  total_records: number;
  districts_covered: number;
  commodities_tracked: number;
  contaminants_tracked: number;
  avg_confidence_score: number | null;
  records_last_30d: number;
  pending_disputes: number;
  flagged_labs: number;
  active_alerts: number;
}

export function useAdminStats(enabled = true) {
  return useQuery({
    queryKey: ["admin-stats"],
    queryFn: () => apiFetch<PlatformStats>("/v1/admin/stats"),
    enabled,
  });
}

export interface RecordRow {
  id: number;
  test_date: string;
  commodity: string;
  contaminant: string;
  district: string | null;
  value_ppb: number;
  pass_fail: boolean | null;
  source_type: string;
  confidence_score: number;
  is_duplicate: boolean;
}

export function useAdminRecords(filters: { source_type?: string; is_duplicate?: boolean }, enabled = true) {
  const params = new URLSearchParams();
  if (filters.source_type) params.set("source_type", filters.source_type);
  if (filters.is_duplicate !== undefined) params.set("is_duplicate", String(filters.is_duplicate));
  const qs = params.toString();
  return useQuery({
    queryKey: ["admin-records", filters],
    queryFn: () => apiFetch<RecordRow[]>(`/v1/admin/records${qs ? `?${qs}` : ""}`),
    enabled,
  });
}

export function useOverrideRecord() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: "verify" | "flag" }) =>
      apiFetch(`/v1/admin/records/${id}`, { method: "PATCH", body: { action } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-records"] }),
  });
}

export function useTriggerAggregate() {
  return useMutation({
    mutationFn: () => apiFetch<{ summary: Record<string, unknown>; message: string }>("/v1/admin/aggregate", { method: "POST" }),
  });
}

export function useTriggerDiseaseBurden() {
  return useMutation({
    mutationFn: () => apiFetch<{ summary: Record<string, unknown>; message: string }>("/v1/admin/disease-burden", { method: "POST" }),
  });
}

export interface LabFraudSummary {
  lab_id: number;
  lab_name: string;
  lab_tier: number;
  state: string | null;
  reliability_score: number | null;
  pass_rate: number | null;
  deviation_z_score: number | null;
  flagged_suspicious: boolean;
  flag_reason: string | null;
  last_evaluated: string | null;
}

export function useFraudLabs(flaggedOnly = true, enabled = true) {
  return useQuery({
    queryKey: ["fraud-labs", flaggedOnly],
    queryFn: () => apiFetch<LabFraudSummary[]>(`/v1/admin/fraud/labs?flagged_only=${flaggedOnly}`),
    enabled,
  });
}

export interface DisputeResponse {
  id: number;
  brand_id: number;
  brand_name: string;
  dispute_type: string;
  status: string;
  submitted_by_email: string;
  notes: string | null;
  submitted_at: string;
  resolved_at: string | null;
  resolver_notes: string | null;
}

export function useAdminDisputes(status = "pending", enabled = true) {
  return useQuery({
    queryKey: ["admin-disputes", status],
    queryFn: () => apiFetch<DisputeResponse[]>(`/v1/admin/disputes?status=${status}`),
    enabled,
  });
}

export function useReviewDispute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, outcome, resolver_notes }: { id: number; outcome: string; resolver_notes: string }) =>
      apiFetch(`/v1/admin/disputes/${id}/review`, { method: "POST", body: { outcome, resolver_notes } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-disputes"] }),
  });
}
