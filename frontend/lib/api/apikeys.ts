import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export interface KeySummary {
  id: string;
  key_prefix: string;
  name: string | null;
  tier: string;
  rate_limit_per_day: number;
  created_at: string;
  last_used: string | null;
  expires_at: string | null;
  revoked: boolean;
}

export interface CreateKeyResponse {
  id: string;
  key: string;
  key_prefix: string;
  name: string | null;
  tier: string;
  rate_limit_per_day: number;
  expires_at: string | null;
  warning: string;
}

export function useApiKeys(enabled = true) {
  return useQuery({
    queryKey: ["api-keys"],
    queryFn: () => apiFetch<KeySummary[]>("/v1/keys"),
    enabled,
  });
}

export function useCreateApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => apiFetch<CreateKeyResponse>("/v1/keys", { method: "POST", body: { name } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
  });
}

export function useRevokeApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/v1/keys/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
  });
}

export interface UsageDay {
  day: string;
  calls: number;
}

export function useKeyUsage(keyId: string | null) {
  return useQuery({
    queryKey: ["key-usage", keyId],
    queryFn: () => apiFetch<UsageDay[]>(`/v1/keys/${keyId}/usage`),
    enabled: !!keyId,
  });
}
