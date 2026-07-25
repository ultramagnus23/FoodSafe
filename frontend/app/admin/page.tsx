"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { useProfile } from "@/lib/api/auth";
import {
  useAdminStats,
  useAdminRecords,
  useOverrideRecord,
  useTriggerAggregate,
  useTriggerDiseaseBurden,
  useFraudLabs,
  useAdminDisputes,
  useReviewDispute,
  usePipelineRuns,
  useAdminReports,
  useReviewReport,
  type PipelineRunStatus,
} from "@/lib/api/admin";
import { fmt } from "@/lib/constants";

type Tab = "overview" | "records" | "fraud" | "disputes" | "reports";

const STATUS_META: Record<PipelineRunStatus["status"], { label: string; bg: string; fg: string }> = {
  success: { label: "OK", bg: "var(--clear-pale)", fg: "var(--clear)" },
  expected_failure: { label: "Expected gap", bg: "var(--caution-pale)", fg: "var(--caution)" },
  failed: { label: "Failed: needs attention", bg: "var(--risk-pale)", fg: "var(--risk)" },
  running: { label: "Running…", bg: "var(--line)", fg: "var(--provenance)" },
  never_run: { label: "Never run", bg: "var(--line)", fg: "var(--provenance)" },
};

// FSSAI/AGMARKNET returning nothing is a documented, accepted gap (see
// docs/FSSAI_INGESTION.md) — never render it the same way as a real failure.
function PipelineHealth() {
  const runs = usePipelineRuns();
  if (runs.isLoading) return <p className="text-provenance">Loading ingest status…</p>;
  if (!runs.data) return null;

  return (
    <div className="mb-8">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-provenance">Ingest Health</h2>
      <div className="grid gap-3 sm:grid-cols-3">
        {runs.data.map((r) => {
          const meta = STATUS_META[r.status];
          return (
            <div key={r.source} className="rounded-lg border border-line bg-slab p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="font-mono text-sm">{r.source}</span>
                <span className="rounded-full px-2.5 py-1 text-xs font-medium" style={{ background: meta.bg, color: meta.fg }}>
                  {meta.label}
                </span>
              </div>
              <div className="text-xs text-provenance">
                {r.finished_at ? `Last run: ${r.finished_at.slice(0, 16).replace("T", " ")}` : "No runs recorded yet"}
              </div>
              {r.rows_ingested != null && <div className="text-xs text-provenance">{r.rows_ingested} rows</div>}
              {r.status === "failed" && r.error_detail && (
                <div className="mt-1 truncate text-xs text-risk" title={r.error_detail}>
                  {r.error_detail}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function OverviewTab() {
  const stats = useAdminStats();
  const aggregate = useTriggerAggregate();
  const diseaseBurden = useTriggerDiseaseBurden();

  if (stats.isLoading) return <p className="text-provenance">Loading…</p>;
  if (!stats.data) return <p className="text-provenance">Could not load stats.</p>;

  const cards = [
    { label: "Total Records", value: stats.data.total_records },
    { label: "Districts Covered", value: stats.data.districts_covered },
    { label: "Commodities", value: stats.data.commodities_tracked },
    { label: "Contaminants", value: stats.data.contaminants_tracked },
    { label: "Avg Confidence", value: stats.data.avg_confidence_score ?? "—" },
    { label: "Records (30d)", value: stats.data.records_last_30d },
    { label: "Pending Disputes", value: stats.data.pending_disputes },
    { label: "Flagged Labs", value: stats.data.flagged_labs },
    { label: "Active Alerts", value: stats.data.active_alerts },
  ];

  return (
    <div>
      <PipelineHealth />
      <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-3">
        {cards.map((c) => (
          <div key={c.label} className="rounded-lg border border-line bg-slab p-4">
            <div className="font-display text-2xl font-semibold text-ink">{c.value}</div>
            <div className="mt-1 text-[11px] uppercase tracking-wide text-provenance">{c.label}</div>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          disabled={aggregate.isPending}
          onClick={() => aggregate.mutate()}
          className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-on-ink disabled:opacity-60"
        >
          {aggregate.isPending ? "Recomputing…" : "Recompute Aggregations"}
        </button>
        <button
          type="button"
          disabled={diseaseBurden.isPending}
          onClick={() => diseaseBurden.mutate()}
          className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-on-ink disabled:opacity-60"
        >
          {diseaseBurden.isPending ? "Recomputing…" : "Recompute Disease Burden"}
        </button>
      </div>
      {aggregate.data && (
        <pre className="mt-4 overflow-x-auto rounded-md bg-porcelain p-3 text-xs">{JSON.stringify(aggregate.data.summary, null, 2)}</pre>
      )}
      {diseaseBurden.data && (
        <pre className="mt-4 overflow-x-auto rounded-md bg-porcelain p-3 text-xs">{JSON.stringify(diseaseBurden.data.summary, null, 2)}</pre>
      )}
    </div>
  );
}

function RecordsTab() {
  const [sourceType, setSourceType] = useState("");
  const records = useAdminRecords({ source_type: sourceType || undefined });
  const override = useOverrideRecord();

  return (
    <div>
      <select className="mb-4 rounded-lg border border-line bg-slab px-3 py-2 text-sm" value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
        <option value="">All Sources</option>
        <option value="fssai">FSSAI</option>
        <option value="usfda">USFDA</option>
        <option value="state_health">State Health</option>
        <option value="apeda">APEDA</option>
        <option value="agmarknet">AGMARKNET</option>
      </select>
      {records.isLoading ? (
        <p className="text-provenance">Loading…</p>
      ) : !records.data || records.data.length === 0 ? (
        <p className="text-provenance">No records match these filters.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-porcelain text-left text-xs uppercase tracking-wide text-provenance">
                <th className="px-3 py-2">Date</th>
                <th className="px-3 py-2">Commodity</th>
                <th className="px-3 py-2">Contaminant</th>
                <th className="px-3 py-2">District</th>
                <th className="px-3 py-2">PPB</th>
                <th className="px-3 py-2">Confidence</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {records.data.map((r) => (
                <tr key={r.id} className="border-t border-line">
                  <td className="px-3 py-2 font-mono text-xs">{r.test_date}</td>
                  <td className="px-3 py-2">{r.commodity}</td>
                  <td className="px-3 py-2">{r.contaminant}</td>
                  <td className="px-3 py-2">{r.district || "—"}</td>
                  <td className="px-3 py-2 font-mono">{fmt(r.value_ppb, 2)}</td>
                  <td className="px-3 py-2 font-mono">{r.confidence_score.toFixed(2)}</td>
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      className="mr-2 text-xs text-clear underline"
                      onClick={() => override.mutate({ id: r.id, action: "verify" })}
                    >
                      Verify
                    </button>
                    <button
                      type="button"
                      className="text-xs text-risk underline"
                      onClick={() => override.mutate({ id: r.id, action: "flag" })}
                    >
                      Flag
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function FraudTab() {
  const labs = useFraudLabs(true);
  if (labs.isLoading) return <p className="text-provenance">Loading…</p>;
  if (!labs.data || labs.data.length === 0) return <p className="text-provenance">No labs currently flagged.</p>;
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-porcelain text-left text-xs uppercase tracking-wide text-provenance">
            <th className="px-3 py-2">Lab</th>
            <th className="px-3 py-2">State</th>
            <th className="px-3 py-2">Reliability</th>
            <th className="px-3 py-2">Pass Rate</th>
            <th className="px-3 py-2">Z-Score</th>
            <th className="px-3 py-2">Reason</th>
          </tr>
        </thead>
        <tbody>
          {labs.data.map((l) => (
            <tr key={l.lab_id} className="border-t border-line">
              <td className="px-3 py-2 font-medium">{l.lab_name}</td>
              <td className="px-3 py-2">{l.state || "—"}</td>
              <td className="px-3 py-2 font-mono">{l.reliability_score ?? "—"}</td>
              <td className="px-3 py-2 font-mono">{l.pass_rate ?? "—"}</td>
              <td className="px-3 py-2 font-mono">{l.deviation_z_score ?? "—"}</td>
              <td className="px-3 py-2 text-xs text-provenance">{l.flag_reason || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DisputesTab() {
  const disputes = useAdminDisputes("pending");
  const review = useReviewDispute();

  if (disputes.isLoading) return <p className="text-provenance">Loading…</p>;
  if (!disputes.data || disputes.data.length === 0) return <p className="text-provenance">No pending disputes.</p>;

  return (
    <div className="grid gap-4">
      {disputes.data.map((d) => (
        <div key={d.id} className="rounded-lg border border-line bg-slab p-4">
          <div className="mb-1 font-semibold">{d.brand_name}</div>
          <div className="mb-2 text-xs text-provenance">
            {d.dispute_type} · submitted by {d.submitted_by_email} · {d.submitted_at.slice(0, 10)}
          </div>
          {d.notes && <p className="mb-3 text-sm">{d.notes}</p>}
          <div className="flex gap-2">
            <button
              type="button"
              className="rounded-md bg-ink px-3 py-1.5 text-xs font-medium text-on-ink"
              onClick={() => review.mutate({ id: d.id, outcome: "resolved_kept", resolver_notes: "Reviewed, no change." })}
            >
              Keep
            </button>
            <button
              type="button"
              className="rounded-md bg-risk px-3 py-1.5 text-xs font-medium text-on-ink"
              onClick={() => review.mutate({ id: d.id, outcome: "resolved_removed", resolver_notes: "Record removed per dispute." })}
            >
              Remove Record
            </button>
            <button
              type="button"
              className="rounded-md border border-line px-3 py-1.5 text-xs font-medium"
              onClick={() => review.mutate({ id: d.id, outcome: "resolved_flagged", resolver_notes: "Flagged for further review." })}
            >
              Flag
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

function ReportsTab() {
  const reports = useAdminReports("pending");
  const review = useReviewReport();

  if (reports.isLoading) return <p className="text-provenance">Loading…</p>;
  if (!reports.data || reports.data.length === 0) return <p className="text-provenance">No pending reports.</p>;

  return (
    <div className="grid gap-4">
      {reports.data.map((r) => (
        <div key={r.id} className="rounded-lg border border-line bg-slab p-4">
          <div className="mb-2 text-xs text-provenance">
            #{r.id} · submitted {r.submitted_at.slice(0, 10)}
            {r.reporter_email ? ` · ${r.reporter_email}` : ""}
          </div>
          <p className="mb-3 text-sm">{r.description}</p>
          {r.contaminant_suspected && (
            <div className="mb-3 text-xs text-provenance">Suspected: {r.contaminant_suspected}</div>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              className="rounded-md bg-ink px-3 py-1.5 text-xs font-medium text-on-ink"
              onClick={() => review.mutate({ id: r.id, action: "publish", reviewer_notes: "Reviewed, published." })}
            >
              Publish
            </button>
            <button
              type="button"
              className="rounded-md bg-risk px-3 py-1.5 text-xs font-medium text-on-ink"
              onClick={() => review.mutate({ id: r.id, action: "reject", reviewer_notes: "Reviewed, rejected." })}
            >
              Reject
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function AdminPage() {
  const { token, openAuth } = useAuth();
  const loggedIn = !!token;
  const profile = useProfile(loggedIn);
  const [tab, setTab] = useState<Tab>("overview");

  if (!loggedIn) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-20 text-center">
        <p className="mb-4 font-medium text-ink">Sign in to view the admin panel.</p>
        <button type="button" onClick={openAuth} className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-on-ink">
          Sign In →
        </button>
      </div>
    );
  }

  if (profile.isLoading) return <div className="mx-auto max-w-3xl px-6 py-20 text-center text-provenance">Loading…</div>;

  if (!profile.data?.is_superuser) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-20 text-center text-provenance">
        This page is restricted to platform administrators.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="mb-6 font-display text-4xl font-light">Admin Panel</h1>
      <div className="mb-6 flex gap-0 border-b border-line">
        {(["overview", "records", "fraud", "disputes", "reports"] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-5 py-2.5 text-sm font-medium capitalize ${
              tab === t ? "border-ink text-ink" : "border-transparent text-provenance hover:text-ink"
            }`}
          >
            {t}
          </button>
        ))}
      </div>
      {tab === "overview" && <OverviewTab />}
      {tab === "records" && <RecordsTab />}
      {tab === "fraud" && <FraudTab />}
      {tab === "disputes" && <DisputesTab />}
      {tab === "reports" && <ReportsTab />}
    </div>
  );
}
