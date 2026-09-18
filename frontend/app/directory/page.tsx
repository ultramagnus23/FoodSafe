"use client";

import { useMemo, useState } from "react";
import {
  useCommissioners,
  useLabs,
  useStateEnforcement,
  useStateSampling,
  useNationalEnforcement,
} from "@/lib/api/directory";
import type {
  CommissionerOut,
  LabOut,
  StateEnforcementOut,
  StateSamplingOut,
  NationalEnforcementOut,
} from "@/lib/api/types";

const BASIS_LABEL: Record<StateSamplingOut["non_conforming_basis"], string> = {
  non_conforming: "Non-conforming",
  adulterated_misbranded: "Adulterated & misbranded (older definition)",
};
const VERIFICATION_LABEL: Record<StateSamplingOut["verification"], string> = {
  total_row_sum: "Matches the table's printed total",
  total_row_close: "Within 0.1% of the printed total",
  row_invariants: "Row-level checks only (no printed total)",
};
const CORROBORATION_LABEL: Record<StateSamplingOut["corroboration"], string> = {
  single_source: "Single answer",
  corroborated: "Agrees with another answer",
  conflicting: "Conflicts with another answer",
};

function fmtNum(n: number | null): string {
  return n == null ? "—" : n.toLocaleString("en-IN");
}
function fmtRupees(n: number | null): string {
  return n == null ? "—" : `₹${n.toLocaleString("en-IN")}`;
}

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

function NationalEnforcementRow({ r }: { r: NationalEnforcementOut }) {
  const civilOutcome = r.civil_cases_convictions ?? r.civil_cases_decided;
  const civilLabel = r.civil_cases_convictions != null ? "convicted" : "decided";
  const criminalOutcome = r.criminal_cases_convictions ?? r.criminal_cases_decided;
  const criminalLabel = r.criminal_cases_convictions != null ? "convicted" : "decided";
  const summedPenalty = (r.civil_penalty_amount ?? 0) + (r.criminal_penalty_amount ?? 0) || null;
  const penalty = r.total_penalty_amount ?? summedPenalty;
  return (
    <tr className="border-b border-line last:border-0">
      <td className="py-2 pr-3 text-sm font-medium text-ink">{r.fiscal_year}</td>
      <td className="py-2 pr-3 text-right font-mono text-sm">{fmtNum(r.samples_analyzed)}</td>
      <td className="py-2 pr-3 text-right font-mono text-sm">{fmtNum(r.samples_non_conforming)}</td>
      <td className="py-2 pr-3 text-right font-mono text-sm">
        {fmtNum(r.civil_cases_launched)}
        <span className="ml-1 text-xs text-provenance">({fmtNum(civilOutcome)} {civilLabel})</span>
      </td>
      <td className="py-2 pr-3 text-right font-mono text-sm">
        {fmtNum(r.criminal_cases_launched)}
        <span className="ml-1 text-xs text-provenance">({fmtNum(criminalOutcome)} {criminalLabel})</span>
      </td>
      <td className="py-2 pr-3 text-right font-mono text-sm">{fmtRupees(penalty)}</td>
      <td className="py-2 text-right">
        <a className="text-xs text-provenance underline" href={r.source_url} target="_blank" rel="noreferrer">
          Annual Report
        </a>
      </td>
    </tr>
  );
}

function EnforcementRow({ r }: { r: StateEnforcementOut }) {
  return (
    <tr className="border-b border-line last:border-0">
      <td className="py-2 pr-3 text-sm font-medium text-ink">{r.state}</td>
      <td className="py-2 pr-3 text-sm text-provenance">{r.fiscal_year}</td>
      <td className="py-2 pr-3 text-right font-mono text-sm">{r.samples_analyzed ?? "—"}</td>
      <td className="py-2 pr-3 text-right font-mono text-sm">{r.civil_cases_decided_penalty ?? "—"}</td>
      <td className="py-2 pr-3 text-right font-mono text-sm">{r.criminal_cases_convictions ?? "—"}</td>
      <td className="py-2 pr-3 text-right font-mono text-sm">{r.licenses_cancelled ?? "—"}</td>
      <td className="py-2 text-right">
        <a
          className="text-xs text-provenance underline"
          href={r.source_url}
          target="_blank"
          rel="noreferrer"
          title={r.source_question_subject ?? undefined}
        >
          LS{r.lok_sabha_no} Q{r.source_question_no}
        </a>
      </td>
    </tr>
  );
}

function SamplingRow({ r }: { r: StateSamplingOut }) {
  return (
    <tr className="border-b border-line last:border-0">
      <td className="whitespace-nowrap py-2 pr-3 text-sm font-medium text-ink">{r.state}</td>
      <td className="whitespace-nowrap py-2 pr-3 text-sm text-provenance">
        {r.fiscal_year}
        {r.fy_source === "text_above" && (
          <span title="Fiscal year read from the text directly above the table, not from the table's own title"> †</span>
        )}
      </td>
      <td className="py-2 pr-3 text-right font-mono text-sm">{fmtNum(r.samples_analyzed)}</td>
      <td className="py-2 pr-3 text-right font-mono text-sm">{fmtNum(r.samples_non_conforming)}</td>
      <td className="py-2 pr-3 text-right font-mono text-sm">
        {r.non_conforming_pct == null ? "—" : `${r.non_conforming_pct.toFixed(1)}%`}
      </td>
      <td className="py-2 pr-3 text-xs text-provenance">{BASIS_LABEL[r.non_conforming_basis]}</td>
      <td className="py-2 pr-3 text-xs text-provenance">
        <div>{VERIFICATION_LABEL[r.verification]}</div>
        <div className={r.corroboration === "conflicting" ? "text-amber-800" : undefined}>
          {CORROBORATION_LABEL[r.corroboration]}
        </div>
      </td>
      <td className="whitespace-nowrap py-2 text-right">
        <a
          className="text-xs text-provenance underline"
          href={r.source_url}
          target="_blank"
          rel="noreferrer"
          title={r.source_question_subject ?? undefined}
        >
          LS{r.lok_sabha_no} Q{r.source_question_no}
        </a>
      </td>
    </tr>
  );
}

export default function DirectoryPage() {
  const [sampState, setSampState] = useState("");
  const [commissionerState, setCommissionerState] = useState("");
  const [labState, setLabState] = useState("");
  const [labTier, setLabTier] = useState<number | undefined>(undefined);
  const [enfState, setEnfState] = useState("");

  const commissioners = useCommissioners(commissionerState || undefined);
  const labs = useLabs(labState || undefined, labTier);
  const enforcement = useStateEnforcement(enfState || undefined);
  const sampling = useStateSampling();
  const national = useNationalEnforcement();

  const sampStates = useMemo(
    () => Array.from(new Set((sampling.data ?? []).map((r) => r.state))).sort(),
    [sampling.data]
  );
  const sampRows = useMemo(
    () => (sampling.data ?? []).filter((r) => !sampState || r.state === sampState),
    [sampling.data, sampState]
  );

  const commissionerStates = useMemo(
    () => (commissioners.data ?? []).map((c) => c.state).sort(),
    [commissioners.data]
  );
  const labStates = useMemo(
    () => Array.from(new Set((labs.data ?? []).map((l) => l.state).filter((s): s is string => !!s))).sort(),
    [labs.data]
  );
  const enfStates = useMemo(
    () => Array.from(new Set((enforcement.data ?? []).map((r) => r.state))).sort(),
    [enforcement.data]
  );

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="mb-2 font-display text-4xl font-light">Directory</h1>
      <p className="mb-8 text-provenance">
        Real State/UT enforcement numbers, who to contact, and where samples get tested — sourced from Parliament
        and FSSAI&apos;s own published directories, refreshed regularly.
      </p>

      <section className="mb-12">
        <h2 className="mb-4 font-display text-2xl font-normal">National Enforcement (FSSAI Annual Reports)</h2>
        <p className="mb-4 text-sm text-provenance">
          Source: each fiscal year&apos;s FSSAI Annual Report, &quot;Progress on enforcement metrics&quot; table —
          FSSAI&apos;s own annual publication, not a third party or Parliament. Report format changed over the
          years (some years report case outcomes as &quot;decided&quot;, others as &quot;convicted&quot; — these
          are shown separately, not merged, since they are not the same claim). Only years with a
          reasonably-sized PDF have been ingested so far; several recent years run 130–600MB for one document
          and are not yet included.
        </p>
        {national.isLoading ? (
          <p className="text-provenance">Loading…</p>
        ) : national.error ? (
          <p className="text-provenance">Could not load national enforcement data.</p>
        ) : !national.data || national.data.length === 0 ? (
          <p className="text-provenance">No records.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-line bg-slab px-4">
            <table className="w-full min-w-[720px]">
              <thead>
                <tr className="border-b border-line text-left text-xs uppercase text-provenance">
                  <th className="py-2 pr-3 font-medium">FY</th>
                  <th className="py-2 pr-3 text-right font-medium">Samples analyzed</th>
                  <th className="py-2 pr-3 text-right font-medium">Non-conforming</th>
                  <th className="py-2 pr-3 text-right font-medium">Civil cases</th>
                  <th className="py-2 pr-3 text-right font-medium">Criminal cases</th>
                  <th className="py-2 pr-3 text-right font-medium">Penalty</th>
                  <th className="py-2 text-right font-medium">Source</th>
                </tr>
              </thead>
              <tbody>
                {national.data.map((r) => (
                  <NationalEnforcementRow key={r.fiscal_year} r={r} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="mb-12">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-2xl font-normal">State Enforcement (Lok Sabha)</h2>
          {enfStates.length > 0 && <StatePicker value={enfState} onChange={setEnfState} states={enfStates} />}
        </div>
        <p className="mb-4 text-sm text-provenance">
          Source: written answers to Lok Sabha (Parliament) questions to the Ministry of Health &amp; Family
          Welfare — FSSAI itself publishes no structured state-level enforcement data; this is the same
          government, disclosed through a different, unauthenticated public channel. Two questions can each
          independently report the same state/year, shown separately rather than merged.
        </p>
        {enforcement.isLoading ? (
          <p className="text-provenance">Loading…</p>
        ) : enforcement.error ? (
          <p className="text-provenance">Could not load enforcement data.</p>
        ) : !enforcement.data || enforcement.data.length === 0 ? (
          <p className="text-provenance">No records.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-line bg-slab px-4">
            <table className="w-full min-w-[640px]">
              <thead>
                <tr className="border-b border-line text-left text-xs uppercase text-provenance">
                  <th className="py-2 pr-3 font-medium">State/UT</th>
                  <th className="py-2 pr-3 font-medium">FY</th>
                  <th className="py-2 pr-3 text-right font-medium">Samples analyzed</th>
                  <th className="py-2 pr-3 text-right font-medium">Civil cases (penalty)</th>
                  <th className="py-2 pr-3 text-right font-medium">Criminal convictions</th>
                  <th className="py-2 pr-3 text-right font-medium">Licenses cancelled</th>
                  <th className="py-2 text-right font-medium">Source</th>
                </tr>
              </thead>
              <tbody>
                {enforcement.data.map((r, i) => (
                  <EnforcementRow key={`${r.state}-${r.fiscal_year}-${r.lok_sabha_no}-${r.source_question_no}-${i}`} r={r} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="mb-12">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-2xl font-normal">Samples Tested &amp; Found Non-Conforming (by State)</h2>
          {sampStates.length > 0 && <StatePicker value={sampState} onChange={setSampState} states={sampStates} />}
        </div>
        <p className="mb-2 text-sm text-provenance">
          How many food samples each State/UT analysed in a fiscal year, and how many were found non-conforming,
          as disclosed to Parliament (Lok Sabha written answers, 2013-14 to 2025-26). These are the only sampled-test
          results in this project with both a pass and a fail side.
        </p>
        <ul className="mb-4 list-disc space-y-1 pl-5 text-xs text-provenance">
          <li>A non-conforming sample is not necessarily unsafe — it includes sub-standard and labelling findings.</li>
          <li>
            Older answers count samples &quot;adulterated and misbranded&quot;, a different definition; the two are labelled
            and never merged, so percentages are not comparable across that change.
          </li>
          <li>
            The same state and year can appear in several answers, sometimes with different figures (provisional vs
            revised). Each is shown separately and marked as agreeing or conflicting.
          </li>
          <li>
            Only tables that passed automated integrity checks are included; anything malformed is rejected and logged,
            not guessed at. States missing from a year simply reported nothing usable in that answer. † = fiscal year
            read from the text above the table rather than its title.
          </li>
        </ul>
        {sampling.isLoading ? (
          <p className="text-provenance">Loading…</p>
        ) : sampling.error ? (
          <p className="text-provenance">Could not load sampling data.</p>
        ) : sampRows.length === 0 ? (
          <p className="text-provenance">No records.</p>
        ) : (
          <div className="max-h-[32rem] overflow-auto rounded-lg border border-line bg-slab px-4">
            <table className="w-full min-w-[760px]">
              <thead className="sticky top-0 bg-slab">
                <tr className="border-b border-line text-left text-xs uppercase text-provenance">
                  <th className="py-2 pr-3 font-medium">State/UT</th>
                  <th className="py-2 pr-3 font-medium">FY</th>
                  <th className="py-2 pr-3 text-right font-medium">Analysed</th>
                  <th className="py-2 pr-3 text-right font-medium">Non-conforming</th>
                  <th className="py-2 pr-3 text-right font-medium">%</th>
                  <th className="py-2 pr-3 font-medium">Definition</th>
                  <th className="py-2 pr-3 font-medium">Checks</th>
                  <th className="py-2 text-right font-medium">Source</th>
                </tr>
              </thead>
              <tbody>
                {sampRows.map((r) => (
                  <SamplingRow
                    key={`${r.state}-${r.fiscal_year}-${r.non_conforming_basis}-${r.lok_sabha_no}-${r.source_question_no}`}
                    r={r}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

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
