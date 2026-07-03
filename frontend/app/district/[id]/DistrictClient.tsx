"use client";

import { useState, Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useDistrictRisk } from "@/lib/api/risk";
import { useDistrictDisease } from "@/lib/api/disease";
import { COMMODITIES, fmt, cap } from "@/lib/constants";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { CodexComplianceBadge } from "@/components/ui/CodexComplianceBadge";
import { EvidenceGradeBadge } from "@/components/ui/EvidenceGradeBadge";
import { PAFDisplay } from "@/components/ui/PAFDisplay";
import { DisclaimerBanner } from "@/components/ui/DisclaimerBanner";
import { SkeletonDistrictCard } from "@/components/ui/Skeletons";
import { TrendChart } from "@/components/TrendChart";
import { SubscribeButton } from "@/components/SubscribeButton";

type Tab = "tests" | "contaminants" | "disease";

function DistrictInner() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const districtId = Number(params.id);
  const { token, openAuth } = useAuth();
  const loggedIn = !!token;

  const [commodityId, setCommodityId] = useState(Number(searchParams.get("commodity")) || 1);
  const [tab, setTab] = useState<Tab>("tests");

  const risk = useDistrictRisk(districtId, commodityId, loggedIn);
  const disease = useDistrictDisease(districtId, loggedIn && tab === "disease");

  if (!loggedIn) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-20 text-center">
        <p className="mb-4 font-medium text-forest">Sign in to view district risk reports.</p>
        <button type="button" onClick={openAuth} className="rounded-md bg-forest px-4 py-2 text-sm font-medium text-white">
          Sign In →
        </button>
      </div>
    );
  }

  if (risk.isLoading) {
    return (
      <div className="mx-auto max-w-5xl px-6 py-10">
        <SkeletonDistrictCard />
      </div>
    );
  }

  if (risk.isError || !risk.data) {
    return <div className="mx-auto max-w-3xl px-6 py-20 text-center text-muted">No data for this district/commodity.</div>;
  }

  const r = risk.data;
  const tc = r.top_contaminants || [];

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <h1 className="font-serif text-3xl font-light">
          {r.district_name} · {r.commodity_name}
        </h1>
        <RiskBadge riskScore={r.risk_score} nRecords={r.n_tests} inferenceType={r.inference_type} />
      </div>
      <p className="mb-3 text-muted">
        {r.state}
        {r.last_updated ? ` · Updated ${r.last_updated.slice(0, 10)}` : " · Latest quarter"}
      </p>
      <div className="mb-6">
        <SubscribeButton districtId={districtId} commodityId={commodityId} />
      </div>

      <div className="mb-6 flex flex-wrap gap-3">
        <select
          className="rounded-lg border border-border bg-bg-card px-3 py-2 text-sm"
          value={commodityId}
          onChange={(e) => setCommodityId(Number(e.target.value))}
        >
          {COMMODITIES.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          { v: r.fail_rate != null ? `${(r.fail_rate * 100).toFixed(1)}%` : "—", k: "Fail Rate" },
          { v: r.n_tests, k: "Total Tests" },
          {
            v: r.codex_compliant_fraction != null ? `${(r.codex_compliant_fraction * 100).toFixed(0)}%` : "—",
            k: "Codex Compliant",
          },
          { v: tc.length ? cap(tc[0].name.replace(/_/g, " ")) : "—", k: "Top Contaminant" },
        ].map((m) => (
          <div key={m.k} className="rounded-lg border border-border bg-bg p-4">
            <div className="font-serif text-2xl font-semibold text-forest">{m.v}</div>
            <div className="mt-1 text-[11px] uppercase tracking-wide text-muted">{m.k}</div>
          </div>
        ))}
      </div>

      <div className="mb-6 flex gap-0 border-b border-border">
        {(["tests", "contaminants", "disease"] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-5 py-2.5 text-sm font-medium ${
              tab === t ? "border-forest text-forest" : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {t === "tests" ? "Direct Tests" : t === "contaminants" ? "Contaminants" : "Disease Burden"}
          </button>
        ))}
      </div>

      {tab === "tests" && (
        <div className="overflow-x-auto rounded-lg border border-border">
          {r.enforcement_events.length ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-bg text-left text-xs uppercase tracking-wide text-muted">
                  <th className="sticky left-0 z-10 bg-bg px-4 py-3">Date</th>
                  <th className="px-4 py-3">Contaminant</th>
                  <th className="px-4 py-3">PPB</th>
                  <th className="px-4 py-3">Limit</th>
                  <th className="px-4 py-3">Result</th>
                  <th className="px-4 py-3">Source</th>
                </tr>
              </thead>
              <tbody>
                {r.enforcement_events.map((e, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="sticky left-0 z-10 bg-bg-card px-4 py-3 font-mono text-xs">{e.test_date}</td>
                    <td className="px-4 py-3">{e.contaminant.replace(/_/g, " ")}</td>
                    <td className="px-4 py-3 font-mono font-semibold">{fmt(e.value_ppb, 2)}</td>
                    <td className="px-4 py-3">{e.legal_limit_ppb != null ? fmt(e.legal_limit_ppb, 1) : "—"}</td>
                    <td className="px-4 py-3">
                      <span
                        className="rounded px-2 py-0.5 font-mono text-xs"
                        style={
                          e.pass_fail === false
                            ? { background: "var(--red-lt)", color: "var(--red)" }
                            : { background: "var(--sage-lt)", color: "#166534" }
                        }
                      >
                        {e.pass_fail === false ? "FAIL" : e.pass_fail === true ? "PASS" : "—"}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded bg-forest-pale px-2 py-0.5 font-mono text-[11px] text-forest">
                        {e.source_type.toUpperCase()}
                      </span>
                      {e.source_url && (
                        <a href={e.source_url} target="_blank" rel="noreferrer" className="ml-1.5 text-xs text-forest">
                          ↗
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="p-6 text-muted">No enforcement records found for this selection.</p>
          )}
        </div>
      )}

      {tab === "contaminants" && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          {tc.length ? (
            tc.map((c, i) => (
              <div key={i} className="rounded-lg border border-border bg-bg-card p-6">
                <div className="mb-1.5 font-semibold">{cap(c.name.replace(/_/g, " "))}</div>
                <div className="mb-1 font-mono text-2xl text-red">{((c.fail_rate || 0) * 100).toFixed(1)}%</div>
                <div className="text-xs text-muted">Failure rate</div>
              </div>
            ))
          ) : (
            <p className="text-muted">No contaminant breakdown for this selection.</p>
          )}
        </div>
      )}

      {tab === "disease" && (
        <div>
          {disease.isLoading ? (
            <SkeletonDistrictCard />
          ) : !disease.data || disease.data.rows.length === 0 ? (
            <p className="text-muted">
              No disease-burden estimates for this district yet — needs at least 3 confidence-scored enforcement
              records per contaminant.
            </p>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {disease.data.rows.map((row, i) => (
                <div key={i} className="rounded-lg border border-border bg-bg-card p-6">
                  <div className="mb-2 flex items-start justify-between gap-2">
                    <div>
                      <div className="font-semibold">{row.disease_name}</div>
                      <div className="text-xs text-muted">
                        {cap(row.contaminant_name.replace(/_/g, " "))} in {row.commodity_name} · {row.disease_icd10}
                      </div>
                    </div>
                    <EvidenceGradeBadge grade={row.evidence_grade} />
                  </div>
                  <div className="mb-3">
                    <PAFDisplay
                      paf={row.paf_estimate}
                      ci={row.paf_ci}
                      disease={row.disease_name}
                      attributableCasesPer100k={row.attributable_cases_per_100k}
                    />
                  </div>
                  <CodexComplianceBadge fssaiCompliant={row.fssai_compliant} codexCompliant={row.codex_compliant} />
                  {row.fssai_vs_codex_gap != null && row.fssai_vs_codex_gap > 1 && (
                    <div className="mt-2 rounded-md bg-amber-lt px-3 py-1.5 text-xs text-[#92400E]">
                      ⚡ FSSAI&apos;s limit here is {row.fssai_vs_codex_gap.toFixed(1)}x more permissive than Codex
                      Alimentarius.
                    </div>
                  )}
                  <div className="mt-3 text-xs text-muted">
                    {row.latency_years ? `Latency: ${row.latency_years} · ` : ""}
                    {row.n_records < 10 ? `⚠ Based on ${row.n_records} samples — low confidence` : `Based on ${row.n_records} samples`}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="mt-10">
        <h2 className="mb-1 font-serif text-2xl font-normal">Contamination Trend</h2>
        <p className="mb-4 text-sm text-muted">Monthly mean PPB over time, with Mann-Kendall trend detection.</p>
        <TrendChart districtId={districtId} commodityId={commodityId} />
      </div>

      <div className="mt-8">
        <DisclaimerBanner text={r.disclaimer} />
      </div>
    </div>
  );
}

export default function DistrictClient() {
  return (
    <Suspense fallback={null}>
      <DistrictInner />
    </Suspense>
  );
}
