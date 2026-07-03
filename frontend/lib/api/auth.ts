import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { CurrentUserProfile } from "./types";

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  tier: string;
  user_id: string;
  disclaimer: string;
}

export function login(email: string, password: string) {
  return apiFetch<AuthResponse>("/v1/auth/login", { method: "POST", auth: false, body: { email, password } });
}

export function register(email: string, password: string) {
  return apiFetch<AuthResponse>("/v1/auth/register", { method: "POST", auth: false, body: { email, password } });
}

export function fetchProfile() {
  return apiFetch<CurrentUserProfile>("/v1/user/profile");
}

export function useProfile(enabled = true) {
  return useQuery({
    queryKey: ["profile"],
    queryFn: fetchProfile,
    enabled,
    staleTime: 60 * 1000,
  });
}

export function setHomeDistrict(districtId: number) {
  return apiFetch("/v1/user/location", { method: "POST", body: { district_id: districtId } });
}
