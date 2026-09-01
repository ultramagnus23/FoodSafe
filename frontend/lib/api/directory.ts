import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { CommissionerOut, LabOut } from "./types";

// Both endpoints are public (no auth) — see api/other_routes.py.
export function useCommissioners(state?: string) {
  const qs = state ? `?state=${encodeURIComponent(state)}` : "";
  return useQuery({
    queryKey: ["meta-commissioners", state ?? null],
    queryFn: () => apiFetch<CommissionerOut[]>(`/v1/meta/commissioners${qs}`, { auth: false }),
    staleTime: 60 * 60 * 1000,
  });
}

export function useLabs(state?: string, tier?: number) {
  const params = new URLSearchParams();
  if (state) params.set("state", state);
  if (tier) params.set("tier", String(tier));
  const qs = params.toString() ? `?${params.toString()}` : "";
  return useQuery({
    queryKey: ["meta-labs", state ?? null, tier ?? null],
    queryFn: () => apiFetch<LabOut[]>(`/v1/meta/labs${qs}`, { auth: false }),
    staleTime: 60 * 60 * 1000,
  });
}
