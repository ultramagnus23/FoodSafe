import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { ResearchListResponse, ResearchSummary } from "./types";

export const RESEARCH_PAGE_SIZE = 20;

export interface ResearchQuery {
  contaminantId?: number;
  q?: string;
  page?: number;
}

// Public (no auth) — see api/routes/research.py.
export function useResearch({ contaminantId, q, page = 0 }: ResearchQuery = {}) {
  const params = new URLSearchParams({
    limit: String(RESEARCH_PAGE_SIZE),
    offset: String(page * RESEARCH_PAGE_SIZE),
  });
  if (contaminantId) params.set("contaminant_id", String(contaminantId));
  if (q) params.set("q", q);
  return useQuery({
    queryKey: ["research", contaminantId ?? null, q ?? "", page],
    queryFn: () => apiFetch<ResearchListResponse>(`/v1/research?${params}`, { auth: false }),
    staleTime: 60 * 60 * 1000,
    placeholderData: keepPreviousData,
  });
}

export function useResearchSummary() {
  return useQuery({
    queryKey: ["research-summary"],
    queryFn: () => apiFetch<ResearchSummary>("/v1/research/summary", { auth: false }),
    staleTime: 60 * 60 * 1000,
  });
}
