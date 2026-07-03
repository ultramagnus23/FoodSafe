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
} from "@/lib/api/admin";
import { fmt } from "@/lib/constants";

type Tab = "overview" | "records" | "fraud" | "disputes";

function OverviewTab() {
  const stats = useAdminStats();
  const aggregate = useTriggerAggregate();
  const diseaseBurden = useTriggerDiseaseBurden();

  if (stats.isLoading) return <p className="text-muted">Loading…</p>;
  if (!stats.data) return <p className="text-muted">Could not load stats.</p>;

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
      <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-3">
        {cards.map((c) => (
          <div key={c.label} className="rounded-lg border border-border bg-bg-card p-4">
            <div className="font-serif text-2xl font-semibold text-forest">{c.value}</div>
            <div className="mt-1 text-[11px] uppercase tracking-wide text-muted">{c.label}</div>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          disabled={aggregate.isPending}
          onClick={() => aggregate.mutate()}
          className="rounded-md bg-forest px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {aggregate.isPending ? "Recomputing…" : "Recompute Aggregations"}
        </button>
        <button
          type="button"
          disabled={diseaseBurden.isPending}
          onClick={() => diseaseBurden.mutate()}
          className="rounded-md bg-forest px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {diseaseBurden.isPending ? "Recomputing…" : "Recompute Disease Burden"}
        </button>
      </div>
      {aggregate.data && (
        <pre className="mt-4 overflow-x-auto rounded-md bg-bg p-3 text-xs">{JSON.stringify(aggregate.data.summary, null, 2)}</pre>
      )}
      {diseaseBurden.data && (
        <pre className="mt-4 overflow-x-auto rounded-md bg-bg p-3 text-xs">{JSON.stringify(diseaseBurden.data.summary, null, 2)}</pre>
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
      <select className="mb-4 rounded-lg border border-border bg-bg-card px-3 py-2 text-sm" value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
        <option value="">All Sources</option>
        <option value="fssai">FSSAI</option>
        <option value="usfda">USFDA</option>
        <option value="state_health">State Health</option>
        <option value="apeda">APEDA</option>
        <option value="agmarknet">AGMARKNET</option>
      </select>
      {records.isLoading ? (
        <p className="text-muted">Loading…</p>
      ) : !records.data || records.data.length === 0 ? (
        <p className="text-muted">No records match these filters.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-bg text-left text-xs uppercase tracking-wide text-muted">
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
                <tr key={r.id} className="border-t border-border">
                  <td className="px-3 py-2 font-mono text-xs">{r.test_date}</td>
                  <td className="px-3 py-2">{r.commodity}</td>
                  <td className="px-3 py-2">{r.contaminant}</td>
                  <td className="px-3 py-2">{r.district || "—"}</td>
                  <td className="px-3 py-2 font-mono">{fmt(r.value_ppb, 2)}</td>
                  <td className="px-3 py-2 font-mono">{r.confidence_score.toFixed(2)}</td>
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      className="mr-2 text-xs text-sage underline"
                      onClick={() => override.mutate({ id: r.id, action: "verify" })}
                    >
                      Verify
                    </button>
                    <button
                      type="button"
                      className="text-xs text-red underline"
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
  if (labs.isLoading) return <p className="text-muted">Loading…</p>;
  if (!labs.data || labs.data.length === 0) return <p className="text-muted">No labs currently flagged.</p>;
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-bg text-left text-xs uppercase tracking-wide text-muted">
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
            <tr key={l.lab_id} className="border-t border-border">
              <td className="px-3 py-2 font-medium">{l.lab_name}</td>
              <td className="px-3 py-2">{l.state || "—"}</td>
              <td className="px-3 py-2 font-mono">{l.reliability_score ?? "—"}</td>
              <td className="px-3 py-2 font-mono">{l.pass_rate ?? "—"}</td>
              <td className="px-3 py-2 font-mono">{l.deviation_z_score ?? "—"}</td>
              <td className="px-3 py-2 text-xs text-muted">{l.flag_reason || "—"}</td>
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

  if (disputes.isLoading) return <p className="text-muted">Loading…</p>;
  if (!disputes.data || disputes.data.length === 0) return <p className="text-muted">No pending disputes.</p>;

  return (
    <div className="grid gap-4">
      {disputes.data.map((d) => (
        <div key={d.id} className="rounded-lg border border-border bg-bg-card p-4">
          <div className="mb-1 font-semibold">{d.brand_name}</div>
          <div className="mb-2 text-xs text-muted">
            {d.dispute_type} · submitted by {d.submitted_by_email} · {d.submitted_at.slice(0, 10)}
          </div>
          {d.notes && <p className="mb-3 text-sm">{d.notes}</p>}
          <div className="flex gap-2">
            <button
              type="button"
              className="rounded-md bg-forest px-3 py-1.5 text-xs font-medium text-white"
              onClick={() => review.mutate({ id: d.id, outcome: "resolved_kept", resolver_notes: "Reviewed, no change." })}
            >
              Keep
            </button>
            <button
              type="button"
              className="rounded-md bg-red px-3 py-1.5 text-xs font-medium text-white"
              onClick={() => review.mutate({ id: d.id, outcome: "resolved_removed", resolver_notes: "Record removed per dispute." })}
            >
              Remove Record
            </button>
            <button
              type="button"
              className="rounded-md border border-border px-3 py-1.5 text-xs font-medium"
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

export default function AdminPage() {
  const { token, openAuth } = useAuth();
  const loggedIn = !!token;
  const profile = useProfile(loggedIn);
  const [tab, setTab] = useState<Tab>("overview");

  if (!loggedIn) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-20 text-center">
        <p className="mb-4 font-medium text-forest">Sign in to view the admin panel.</p>
        <button type="button" onClick={openAuth} className="rounded-md bg-forest px-4 py-2 text-sm font-medium text-white">
          Sign In →
        </button>
      </div>
    );
  }

  if (profile.isLoading) return <div className="mx-auto max-w-3xl px-6 py-20 text-center text-muted">Loading…</div>;

  if (!profile.data?.is_superuser) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-20 text-center text-muted">
        This page is restricted to platform administrators.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="mb-6 font-serif text-4xl font-light">Admin Panel</h1>
      <div className="mb-6 flex gap-0 border-b border-border">
        {(["overview", "records", "fraud", "disputes"] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-5 py-2.5 text-sm font-medium capitalize ${
              tab === t ? "border-forest text-forest" : "border-transparent text-muted hover:text-ink"
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
    </div>
  );
}
