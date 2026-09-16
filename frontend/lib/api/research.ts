import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { ResearchListResponse } from "./types";

// Public (no auth) — see api/routes/research.py.
export function useResearch(contaminantId?: number) {
  const qs = contaminantId ? `?contaminant_id=${contaminantId}` : "";
  return useQuery({
    queryKey: ["research", contaminantId ?? null],
    queryFn: () => apiFetch<ResearchListResponse>(`/v1/research${qs}`, { auth: false }),
    staleTime: 60 * 60 * 1000,
  });
}
