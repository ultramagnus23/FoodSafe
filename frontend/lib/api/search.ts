import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { SearchResult, AutocompleteResult, DistrictOut, CommodityOut, LocalityOut } from "./types";

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

// Resolve a 6-digit pincode to its seeded locality (e.g. Juhu, Vile Parle,
// Churchgate) — see schema_migration_009.sql / GET /v1/meta/localities.
// Most of India isn't seeded yet, so an empty result is expected and
// handled as "no locality on file for this pincode," not an error.
export function useLocalityByPincode(pincode: string) {
  return useQuery({
    queryKey: ["meta-localities", "pincode", pincode],
    queryFn: () => apiFetch<LocalityOut[]>(`/v1/meta/localities?pincode=${encodeURIComponent(pincode)}`, { auth: false }),
    enabled: /^\d{6}$/.test(pincode),
    staleTime: Infinity,
  });
}
