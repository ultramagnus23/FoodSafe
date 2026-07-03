import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export interface Subscription {
  id: number;
  district_id: number | null;
  district_name: string | null;
  commodity_id: number | null;
  commodity_name: string | null;
  contaminant_id: number | null;
  contaminant_name: string | null;
  alert_types: string[];
  severity_threshold: string;
  active: boolean;
  created_at: string;
  last_notified_at: string | null;
}

export interface CreateSubscriptionInput {
  district_id?: number;
  commodity_id?: number;
  contaminant_id?: number;
  alert_types?: string[];
  severity_threshold?: string;
}

export function useSubscriptions(enabled = true) {
  return useQuery({
    queryKey: ["subscriptions"],
    queryFn: () => apiFetch<Subscription[]>("/v1/subscriptions"),
    enabled,
  });
}

export function useCreateSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateSubscriptionInput) => apiFetch<Subscription>("/v1/subscriptions", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["subscriptions"] }),
  });
}

export function useDeleteSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch(`/v1/subscriptions/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["subscriptions"] }),
  });
}
