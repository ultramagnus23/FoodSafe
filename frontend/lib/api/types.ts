// Mirrors the Pydantic response models in api/routes/risk.py, disease.py,
// other_routes.py. Keep field names identical to the API — no remapping.

export interface EnforcementEvent {
  test_date: string;
  contaminant: string;
  value_ppb: number;
  legal_limit_ppb: number | null;
  pass_fail: boolean | null;
  source_url: string | null;
  source_type: string;
  lab_name: string | null;
}

export interface DistrictRiskResponse {
  district_id: number;
  district_name: string;
  state: string;
  commodity_id: number;
  commodity_name: string;
  risk_score: number | null;
  ci_lower: number | null;
  ci_upper: number | null;
  n_tests: number;
  fail_rate: number | null;
  top_factors: Record<string, unknown>[];
  top_contaminants: { name: string; fail_rate: number }[];
  enforcement_events: EnforcementEvent[];
  inference_type: string;
  codex_compliant_fraction: number | null;
  eu_compliant_fraction: number | null;
  twi_exceedance_fraction: number | null;
  fssai_vs_codex_flag: boolean | null;
  disclaimer: string;
  last_updated: string | null;
}

export interface BrandRiskResponse {
  brand_id: number;
  brand_name: string;
  commodity_id: number;
  commodity_name: string;
  district_id: number;
  district_name: string;
  estimated_ppb: number | null;
  risk_score: number | null;
  ci_lower: number | null;
  ci_upper: number | null;
  n_tests: number;
  inference_type: string;
  inference_label: string;
  supply_chain: Record<string, unknown>[];
  enforcement_events: EnforcementEvent[];
  disclaimer: string;
}

export interface MapDataPoint {
  district_id: number;
  district_name: string;
  state: string;
  latitude: number | null;
  longitude: number | null;
  risk_score: number | null;
  n_tests: number;
}

export interface AlertEvent {
  id: number;
  test_date: string;
  commodity: string;
  contaminant: string;
  value_ppb: number;
  legal_limit_ppb: number | null;
  district: string | null;
  state: string | null;
  brand: string | null;
  source_type: string;
  source_url: string | null;
}

export interface DistrictBurdenRow {
  commodity_id: number;
  commodity_name: string;
  contaminant_id: number;
  contaminant_name: string;
  mean_exposure_ppb: number | null;
  dietary_intake_ug_per_kg_day: number | null;
  fssai_compliant: boolean | null;
  codex_compliant: boolean | null;
  fssai_vs_codex_gap: number | null;
  paf_estimate: number | null;
  paf_ci: [number, number] | null;
  hazard_quotient: number | null;
  attributable_cases_per_100k: number | null;
  disease_name: string;
  disease_icd10: string;
  evidence_grade: string;
  latency_years: string | null;
  n_records: number;
  inference_type: string;
  disclaimer: string;
}

export interface DistrictBurdenResponse {
  district_id: number;
  district_name: string;
  state: string;
  rows: DistrictBurdenRow[];
  disclaimer: string;
}

export interface ContaminantMapPoint {
  district_id: number;
  district_name: string;
  state: string;
  latitude: number | null;
  longitude: number | null;
  paf_estimate: number | null;
  fssai_compliant: boolean | null;
  codex_compliant: boolean | null;
  n_records: number;
  inference_type: string;
}

export interface ExposureAlertOut {
  id: number;
  district_id: number;
  district_name: string;
  state: string;
  commodity: string;
  contaminant: string;
  alert_type: string;
  severity: string;
  mean_exposure_ppb: number | null;
  codex_limit_ppb: number | null;
  fssai_limit_ppb: number | null;
  n_samples: number | null;
  first_seen: string | null;
  last_seen: string | null;
  disclaimer: string;
}

export interface BenchmarkResponse {
  contaminant_id: number;
  contaminant_name: string;
  commodity_id: number;
  commodity_name: string;
  fssai_limit_ppb: number | null;
  codex_limit_ppb: number | null;
  eu_limit_ppb: number | null;
  who_jecfa_twi_ug_per_kg: number | null;
  codex_doc_reference: string | null;
  fssai_vs_codex_ratio: number | null;
  interpretation: string;
  evidence_grade: string | null;
  disclaimer: string;
}

export interface SearchResult {
  type: string;
  id: number;
  name: string;
  risk_score: number | null;
  n_tests: number | null;
}

export interface AutocompleteResult {
  id: number;
  name: string;
  type: string;
}

export interface DistrictOut {
  id: number;
  name: string;
  state: string;
}

export interface CommodityOut {
  id: number;
  name: string;
  category: string;
}

export interface CurrentUserProfile {
  email: string;
  tier: string;
  user_id: string;
  is_superuser?: boolean;
}
