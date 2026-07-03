"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useDiseaseAlerts } from "@/lib/api/disease";
import { cap, fmt } from "@/lib/constants";
import { SkeletonAlertRow } from "@/components/ui/Skeletons";

const ALERT_META: Record<string, { icon: string; label: string; sub: string }> = {
  twi_exceedance: { icon: "🔴", label: "TWI Exceedance", sub: "Estimated dietary intake exceeds WHO tolerable level" },
  codex_exceedance_fssai_compliant: {
    icon: "🟡",
    label: "Codex Gap",
    sub: "Passed FSSAI testing but would fail international Codex standard",
  },
  trend_worsening: { icon: "🟠", label: "Worsening Trend", sub: "Contamination trend rising over recent quarters" },
};

function AlertsInner() {
  const router = useRouter();
  const { token, openAuth } = useAuth();
  const loggedIn = !!token;
  const searchParams = useSearchParams();

  const state = searchParams.get("state") || "";
  const alertType = searchParams.get("type") || "";
  const severity = searchParams.get("severity") || "";

  const alerts = useDiseaseAlerts({ state, alert_type: alertType, severity }, loggedIn);

  function setParam(key: string, value: string) {
    const p = new URLSearchParams(searchParams.toString());
    if (value) p.set(key, value);
    else p.delete(key);
    router.push(`/alerts?${p.toString()}`);
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="mb-2 font-serif text-4xl font-light">Exposure Alerts</h1>
      <p className="mb-6 max-w-2xl text-muted">
        Districts where estimated dietary exposure exceeds WHO/JECFA tolerable intake, or where samples passed
        FSSAI&apos;s own limit but would have failed the international Codex Alimentarius benchmark.
      </p>

      <div className="mb-6 flex flex-wrap gap-3">
        <select
          className="rounded-lg border border-border bg-bg-card px-3 py-2 text-sm"
          value={alertType}
          onChange={(e) => setParam("type", e.target.value)}
        >
          <option value="">All Alert Types</option>
          <option value="twi_exceedance">🔴 TWI Exceedance</option>
          <option value="codex_exceedance_fssai_compliant">🟡 Codex Gap</option>
          <option value="trend_worsening">🟠 Worsening Trend</option>
        </select>
        <select
          className="rounded-lg border border-border bg-bg-card px-3 py-2 text-sm"
          value={severity}
          onChange={(e) => setParam("severity", e.target.value)}
        >
          <option value="">All Severities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="moderate">Moderate</option>
        </select>
      </div>

      {!loggedIn ? (
        <div className="rounded-xl bg-forest-pale p-12 text-center">
          <p className="mb-4 font-medium text-forest">Sign in to view exposure alerts.</p>
          <button type="button" onClick={openAuth} className="rounded-md bg-forest px-4 py-2 text-sm font-medium text-white">
            Sign In →
          </button>
        </div>
      ) : alerts.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <SkeletonAlertRow />
          <SkeletonAlertRow />
        </div>
      ) : !alerts.data || alerts.data.length === 0 ? (
        <p className="text-muted">No active alerts match these filters.</p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {alerts.data.map((a) => {
            const meta = ALERT_META[a.alert_type] || { icon: "⚠", label: a.alert_type, sub: "" };
            return (
              <div
                key={a.id}
                className="cursor-pointer rounded-lg border border-border bg-bg-card p-5"
                onClick={() => router.push(`/district/${a.district_id}`)}
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div>
                    <div className="font-semibold">
                      {meta.icon} {meta.label}
                    </div>
                    <div className="text-xs text-muted">{meta.sub}</div>
                  </div>
                  <span
                    className="rounded-full px-2.5 py-1 text-xs font-medium"
                    style={
                      a.severity === "critical"
                        ? { background: "var(--red-lt)", color: "var(--red)" }
                        : { background: "var(--amber-lt)", color: "#92400E" }
                    }
                  >
                    {cap(a.severity)}
                  </span>
                </div>
                <div className="mb-1.5 text-sm">
                  <strong>{a.district_name}</strong>, {a.state} · {cap(a.commodity)} ·{" "}
                  {cap((a.contaminant || "").replace(/_/g, " "))}
                </div>
                <div className="font-mono text-xs text-muted">
                  {a.mean_exposure_ppb != null ? `Mean: ${fmt(a.mean_exposure_ppb, 2)} PPB` : ""}
                  {a.fssai_limit_ppb != null ? ` · FSSAI limit: ${fmt(a.fssai_limit_ppb, 1)}` : ""}
                  {a.codex_limit_ppb != null ? ` · Codex limit: ${fmt(a.codex_limit_ppb, 1)}` : ""}
                  {a.n_samples != null ? ` · ${a.n_samples} samples` : ""}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="disclaimer mt-8">
        <strong>⚠ Disclaimer. </strong>
        Statistical estimates based on public enforcement records. Not a product test result. Not a verdict on any
        specific brand, manufacturer, or batch. Not medical or legal advice.
      </div>
    </div>
  );
}

export default function AlertsPage() {
  return (
    <Suspense fallback={null}>
      <AlertsInner />
    </Suspense>
  );
}
