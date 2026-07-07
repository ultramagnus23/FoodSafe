import { useMutation } from "@tanstack/react-query";
import { apiFetch } from "./client";

export interface ReportSubmit {
  description: string;
  reporter_email?: string;
  commodity_id?: number;
  district_id?: number;
  contaminant_suspected?: string;
}

export interface ReportSubmitResponse {
  report_id: number;
  submitted_at: string;
  status: string;
  message: string;
}

export function useSubmitReport() {
  return useMutation({
    mutationFn: (body: ReportSubmit) =>
      apiFetch<ReportSubmitResponse>("/v1/reports", { method: "POST", body, auth: false }),
  });
}
