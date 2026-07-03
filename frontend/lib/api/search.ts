import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { SearchResult, AutocompleteResult, DistrictOut, CommodityOut } from "./types";

export function useSearch(query: string, enabled = true) {
  return useQuery({
    queryKey: ["search", query],
    queryFn: () => apiFetch<SearchResult[]>(`/v1/search?q=${encodeURIComponent(query)}`),
    enabled: enabled && query.length > 0,
  });
}

export function useAutocomplete(query: string) {
  return useQuery({
    queryKey: ["autocomplete", query],
    queryFn: () => apiFetch<AutocompleteResult[]>(`/v1/search/autocomplete?q=${encodeURIComponent(query)}`, { auth: false }),
    enabled: query.length >= 2,
  });
}

export function useDistricts(enabled = true) {
  return useQuery({
    queryKey: ["meta-districts"],
    queryFn: () => apiFetch<DistrictOut[]>("/v1/meta/districts", { auth: false }),
    enabled,
    staleTime: Infinity,
  });
}

export function useCommodities(enabled = true) {
  return useQuery({
    queryKey: ["meta-commodities"],
    queryFn: () => apiFetch<CommodityOut[]>("/v1/meta/commodities", { auth: false }),
    enabled,
    staleTime: Infinity,
  });
}
