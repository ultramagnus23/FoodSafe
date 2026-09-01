"use client";

import { useMemo, useState } from "react";
import { useCommissioners, useLabs } from "@/lib/api/directory";
import type { CommissionerOut, LabOut } from "@/lib/api/types";

const TIER_LABEL: Record<number, string> = {
  1: "National reference / NABL-accredited",
  2: "State-notified referral",
  3: "Private",
};

function StatePicker({ value, onChange, states }: { value: string; onChange: (v: string) => void; states: string[] }) {
  return (
    <select
      className="rounded-lg border border-line bg-slab px-3 py-2 text-sm outline-none focus:border-ink"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">All states/UTs</option>
      {states.map((s) => (
        <option key={s} value={s}>
          {s}
        </option>
      ))}
    </select>
  );
}

function CommissionerCard({ c }: { c: CommissionerOut }) {
  return (
    <div className="rounded-lg border border-line bg-slab p-4">
      <div className="mb-1 flex items-center justify-between">
        <span className="font-medium text-ink">{c.state}</span>
      </div>
      {c.commissioner_name && <div className="text-sm">{c.commissioner_name}</div>}
      {c.address && <div className="mt-1 whitespace-pre-line text-xs text-provenance">{c.address}</div>}
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-provenance">
        {c.contact && <span className="whitespace-pre-line">{c.contact}</span>}
        {c.email && <span className="whitespace-pre-line">{c.email}</span>}
      </div>
      {c.nodal_officer && (
        <div className="mt-2 whitespace-pre-line border-t border-line pt-2 text-xs text-provenance">
          <span className="font-medium text-ink">Nodal officer(s): </span>
          {c.nodal_officer}
        </div>
      )}
    </div>
  );
}

function LabRow({ l }: { l: LabOut }) {
  return (
    <div className="grid grid-cols-[1fr_auto] items-start gap-3 border-b border-line py-2.5 last:border-0">
      <div>
        <div className="text-sm font-medium text-ink">{l.name}</div>
        <div className="text-xs text-provenance">
          {l.state ?? "State not recorded"} · {TIER_LABEL[l.tier] ?? `Tier ${l.tier}`}
          {l.accreditation ? ` · ${l.accreditation}` : ""}
          {l.accreditation_ref ? ` (${l.accreditation_ref})` : ""}
        </div>
      </div>
      <span
        className={`shrink-0 rounded px-2 py-0.5 text-[11px] uppercase ${
          l.source_url ? "bg-provenance-pale text-ink" : "bg-amber-100 text-amber-800"
        }`}
        title={l.source_url ? l.source_url : "No source URL — demo/seed data, not scraped from a live source"}
      >
        {l.source_url ? "FSSAI source" : "Demo data"}
      </span>
    </div>
  );
}

export default function DirectoryPage() {
  const [commissionerState, setCommissionerState] = useState("");
  const [labState, setLabState] = useState("");
  const [labTier, setLabTier] = useState<number | undefined>(undefined);

  const commissioners = useCommissioners(commissionerState || undefined);
  const labs = useLabs(labState || undefined, labTier);

  const commissionerStates = useMemo(
    () => (commissioners.data ?? []).map((c) => c.state).sort(),
    [commissioners.data]
  );
  const labStates = useMemo(
    () => Array.from(new Set((labs.data ?? []).map((l) => l.state).filter((s): s is string => !!s))).sort(),
    [labs.data]
  );

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="mb-2 font-display text-4xl font-light">Directory</h1>
      <p className="mb-8 text-provenance">
        Who to contact and where samples get tested — real FSSAI-published directories, refreshed daily.
      </p>

      <section className="mb-12">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-2xl font-normal">State Commissioners of Food Safety</h2>
          {commissionerStates.length > 0 && (
            <StatePicker value={commissionerState} onChange={setCommissionerState} states={commissionerStates} />
          )}
        </div>
        <p className="mb-4 text-sm text-provenance">
          Source:{" "}
          <a
            className="underline"
            href="https://fssai.gov.in/business/commissioners-of-food-safety"
            target="_blank"
            rel="noreferrer"
          >
            fssai.gov.in
          </a>{" "}
          — escalation contact metadata, not enforcement data.
        </p>
        {commissioners.isLoading ? (
          <p className="text-provenance">Loading…</p>
        ) : commissioners.error ? (
          <p className="text-provenance">Could not load the commissioner directory.</p>
        ) : !commissioners.data || commissioners.data.length === 0 ? (
          <p className="text-provenance">No records.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {commissioners.data.map((c) => (
              <CommissionerCard key={c.state} c={c} />
            ))}
          </div>
        )}
      </section>

      <section>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-2xl font-normal">Food Testing Laboratories</h2>
          <div className="flex gap-2">
            <select
              className="rounded-lg border border-line bg-slab px-3 py-2 text-sm outline-none focus:border-ink"
              value={labTier ?? ""}
              onChange={(e) => setLabTier(e.target.value ? Number(e.target.value) : undefined)}
            >
              <option value="">All tiers</option>
              <option value="1">National reference / NABL-accredited</option>
              <option value="2">State-notified referral</option>
              <option value="3">Private</option>
            </select>
            {labStates.length > 0 && <StatePicker value={labState} onChange={setLabState} states={labStates} />}
          </div>
        </div>
        <p className="mb-4 text-sm text-provenance">
          Source:{" "}
          <a className="underline" href="https://fssai.gov.in/food-testing/food-laboratories" target="_blank" rel="noreferrer">
            fssai.gov.in
          </a>{" "}
          — NABL-accredited Primary labs, statutory Referral labs (FSS Act s.43), and National Reference Labs.
        </p>
        {labs.isLoading ? (
          <p className="text-provenance">Loading…</p>
        ) : labs.error ? (
          <p className="text-provenance">Could not load the lab directory.</p>
        ) : !labs.data || labs.data.length === 0 ? (
          <p className="text-provenance">No records.</p>
        ) : (
          <div className="rounded-lg border border-line bg-slab px-4">
            {labs.data.map((l) => (
              <LabRow key={l.id} l={l} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
