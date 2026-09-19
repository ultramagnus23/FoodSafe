// Mirrors the Pydantic response models in api/routes/risk.py, disease.py,
// other_routes.py. Keep field names identical to the API — no remapping.

export interface ProvenanceSummary {
  real_count: number;
  synthetic_count: number;
  synthetic_fraction: number | null;
  is_synthetic: boolean;
}

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
  provenance: ProvenanceSummary;
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
  provenance: ProvenanceSummary;
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
  // Optional because the disease-burden map mode (app/map/page.tsx) builds
  // MapDataPoint client-side from a different response shape that has no
  // per-record provenance breakdown yet.
  provenance?: ProvenanceSummary;
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
  provenance: ProvenanceSummary;
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

export interface LocalityOut {
  id: number;
  name: string;
  district_id: number;
  district_name: string;
  state: string;
  pincodes: string[];
  latitude: number | null;
  longitude: number | null;
}

export interface NationalEnforcementOut {
  fiscal_year: string;
  samples_analyzed: number | null;
  samples_non_conforming: number | null;
  non_conforming_unsafe: number | null;
  non_conforming_substandard: number | null;
  non_conforming_labelling: number | null;
  civil_cases_launched: number | null;
  civil_cases_decided: number | null;
  civil_cases_convictions: number | null;
  civil_penalty_amount: number | null;
  criminal_cases_launched: number | null;
  criminal_cases_decided: number | null;
  criminal_cases_convictions: number | null;
  criminal_penalty_amount: number | null;
  criminal_acquittals: number | null;
  total_penalty_amount: number | null;
  source_url: string;
}

export interface CommissionerOut {
  state: string;
  commissioner_name: string | null;
  address: string | null;
  contact: string | null;
  email: string | null;
  nodal_officer: string | null;
  source_url: string;
}

export interface StateEnforcementOut {
  state: string;
  fiscal_year: string;
  samples_analyzed: number | null;
  civil_cases_decided_penalty: number | null;
  criminal_cases_convictions: number | null;
  licenses_cancelled: number | null;
  lok_sabha_no: number;
  source_question_no: number;
  source_question_subject: string | null;
  answered_date: string | null;
  source_url: string;
}

export interface StateSamplingOut {
  state: string;
  fiscal_year: string;
  samples_analyzed: number;
  samples_non_conforming: number;
  non_conforming_pct: number | null;
  non_conforming_basis: "non_conforming" | "adulterated_misbranded";
  verification: "total_row_sum" | "total_row_close" | "row_invariants";
  fy_source: "table_title" | "text_above";
  corroboration: "single_source" | "corroborated" | "conflicting";
  n_sources: number;
  lok_sabha_no: number;
  source_question_no: number;
  source_question_subject: string | null;
  answered_date: string | null;
  source_url: string;
}

export interface PesticideResidueOut {
  commodity: string;
  commodity_label: string;
  period_label: string;
  fiscal_year: string | null;
  period_kind: "fiscal_year" | "partial_year" | "multi_year_pool";
  samples_analyzed: number;
  samples_above_mrl: number;
  above_mrl_pct: number | null;
  verification: "total_row_sum" | "pct_consistent";
  corroboration: "single_source" | "corroborated" | "conflicting";
  n_sources: number;
  lok_sabha_no: number;
  source_question_no: number;
  source_question_subject: string | null;
  answered_date: string | null;
  source_url: string;
}

export interface LabOut {
  id: number;
  name: string;
  tier: number;
  state: string | null;
  accreditation: string | null;
  accreditation_ref: string | null;
  source_url: string | null;
}

export interface CommodityOut {
  id: number;
  name: string;
  category: string;
}

// Real OpenAlex scientific-literature citations linking a contaminant to a
// disease/health outcome — see api/routes/research.py and
// docs/RESEARCH_EVIDENCE_INGESTION.md. Not a claim about any Indian sample.
export interface ResearchListItem {
  id: number;
  contaminant_id: number;
  contaminant_name: string;
  title: string;
  authors: string[];
  journal: string | null;
  publication_year: number | null;
  doi: string | null;
  landing_page_url: string;
  evidence_level: "B" | "C";
  matched_health_terms: string[];
  is_oa: boolean | null;
  study_design: string | null;
  source_apis: string[];
}

export interface ResearchListResponse {
  results: ResearchListItem[];
  total: number;
  disclaimer: string;
}

export interface ResearchSummary {
  total_papers: number;
  total_links: number;
  by_contaminant: { contaminant_id: number; contaminant_name: string; papers: number }[];
  by_study_design: Record<string, number>;
  by_source: Record<string, number>;
}

export interface ResearchDetail extends ResearchListItem {
  abstract: string;
  pmid: string | null;
  pmcid: string | null;
  oa_status: string | null;
  work_type: string | null;
}

export interface CurrentUserProfile {
  email: string;
  tier: string;
  user_id: string;
  is_superuser?: boolean;
}
