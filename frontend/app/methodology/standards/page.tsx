"use client";

import { useState } from "react";
import {
  COMPARE_PAGE_SIZE,
  type Comparison,
  type LimitCell,
  useStandardsCompare,
  useStandardsFoods,
  useStandardsSummary,
} from "@/lib/api/standards";

// Public: India's legal limits beside the EU, Codex and the US, from the rule-books
// themselves (FSSAI compendium, EU Pesticides Database + Reg. 2023/915, Codex
// CXLs + CXS 193, 40 CFR 180). See docs/STANDARDS.md.

const num = new Intl.NumberFormat("en-IN", { maximumSignificantDigits: 3 });
const int = new Intl.NumberFormat("en-IN");

function Value({ cell, india = false }: { cell: LimitCell; india?: boolean }) {
  if (cell.value_mg_per_kg == null) {
    const label =
      cell.basis === "none" ? "no limit" : cell.basis === "not_numeric" ? "text only" : "—";
    return <span className="text-provenance">{label}</span>;
  }
  const note =
    cell.basis === "eu_default"
      ? "EU default: a pesticide the EU never assessed for this food"
      : cell.basis === "group"
        ? "limit set for the food's group"
        : cell.basis === "residual"
          ? "catch-all limit for 'other' foods"
          : undefined;
  return (
    <span className={`font-mono ${india ? "font-semibold text-ink" : ""}`} title={note}>
      {num.format(cell.value_mg_per_kg)}
      {cell.basis === "eu_default" && <sup className="text-caution">d</sup>}
      {(cell.basis === "group" || cell.basis === "residual") && <sup className="text-provenance">g</sup>}
    </span>
  );
}

function Ratio({ r }: { r: number | null }) {
  if (r == null) return <span className="text-provenance">—</span>;
  const cls = r > 1 ? "text-risk" : r < 1 ? "text-clear" : "text-provenance";
  return <span className={`font-mono ${cls}`}>{r >= 10 ? int.format(Math.round(r)) : num.format(r)}×</span>;
}

// Why India's limit is above the EU's (models/standards_compare.eu_gap_reason).
const GAP_LABEL: Record<string, string> = {
  eu_gap_not_approved: "EU: not approved, detection-level limit",
  eu_gap_no_use_on_food: "EU: no approved use on this food",
  eu_gap_never_assessed: "EU: never assessed (0.01 default)",
  eu_gap_at_loq: "EU: detection-level limit",
  eu_gap_above_loq: "EU sets a residue level",
};

function Row({ c }: { c: Comparison }) {
  const notApproved = c.eu_status === "Not approved";
  const gap = c.flags.find((f) => f in GAP_LABEL);
  return (
    <tr className="border-t border-line align-top">
      <td className="px-3 py-2.5">
        <div className="font-medium text-ink">{c.hazard_name}</div>
        <div className="mt-0.5 flex flex-wrap gap-1.5 text-[11px] text-provenance">
          {notApproved && <span className="rounded bg-risk-pale px-1.5 py-px text-risk">not approved in EU</span>}
          {c.iarc_group && <span className="rounded bg-caution-pale px-1.5 py-px">IARC {c.iarc_group}</span>}
          {c.flags.includes("india_internal_conflict") && (
            <span className="rounded bg-provenance-pale px-1.5 py-px">FSSAI lists two values; lower shown</span>
          )}
          {c.flags.includes("basis_mismatch") && (
            <span className="rounded bg-provenance-pale px-1.5 py-px">measured differently across rule-books</span>
          )}
        </div>
      </td>
      <td className="px-3 py-2.5 text-provenance">{c.food_name ?? c.food_key}</td>
      <td className="px-3 py-2.5 text-right"><Value cell={c.india} india /></td>
      <td className="px-3 py-2.5 text-right"><Value cell={c.eu} /></td>
      <td className="px-3 py-2.5 text-right"><Value cell={c.codex} /></td>
      <td className="px-3 py-2.5 text-right"><Value cell={c.us} /></td>
      <td className="px-3 py-2.5 text-right">
        <Ratio r={c.eu.ratio_india_over} />
        {gap && <div className="mt-0.5 text-[11px] leading-tight text-provenance">{GAP_LABEL[gap]}</div>}
      </td>
    </tr>
  );
}

function Stat({ value, label }: { value: number | undefined; label: string }) {
  return (
    <div className="rounded-lg border border-line bg-porcelain p-4">
      <div className="font-display text-3xl font-light text-ink">{value == null ? "…" : int.format(value)}</div>
      <div className="mt-1 text-xs leading-snug text-provenance">{label}</div>
    </div>
  );
}

export default function StandardsPage() {
  const [food, setFood] = useState("");
  const [standardType, setStandardType] = useState<"" | "pesticide_mrl" | "contaminant_ml">("");
  const [onlyHigher, setOnlyHigher] = useState(false);
  const [page, setPage] = useState(0);

  const summary = useStandardsSummary();
  const foods = useStandardsFoods();
  const table = useStandardsCompare({
    food: food || undefined,
    standardType: standardType || undefined,
    flag: onlyHigher ? "india_higher_than_eu" : undefined,
    page,
  });

  const s = summary.data;
  const total = table.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / COMPARE_PAGE_SIZE));
  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setPage(0);
  };

  return (
    <div className="mx-auto max-w-5xl px-6 py-12">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-ink">India vs. World</div>
      <h1 className="mb-4 font-display text-4xl font-light leading-tight">
        India&apos;s food limits beside the EU, Codex and the US
      </h1>
      <p className="mb-8 max-w-prose leading-relaxed text-provenance">
        Every maximum residue limit and contaminant limit India sets in law (FSSAI&apos;s Contaminants, Toxins and
        Residues Regulations), matched food by food against the European Union, the Codex Alimentarius and the
        United States. A ratio above 1× means India allows more of that substance in that food.
      </p>

      <div className="mb-10 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat value={s?.comparisons} label="food–hazard pairs compared" />
        <Stat value={s?.india_higher_than_eu} label="where India allows more than the EU" />
        <Stat value={s?.india_pesticides_not_approved_in_eu} label="India-regulated pesticides not approved in the EU" />
        <Stat value={s?.eu_default_applies} label="EU values that are its 0.01 mg/kg default" />
      </div>

      {s?.india_higher_than_eu_why && (s.india_higher_than_eu_why.eu_gap_above_loq ?? 0) > 0 && (
        <p className="mb-8 max-w-prose leading-relaxed text-provenance">
          <strong className="text-ink">Why most of the gap exists.</strong> Of the pesticide limits where India allows
          more than the EU,{" "}
          {int.format(
            (s.india_higher_than_eu_why.eu_gap_not_approved ?? 0) +
              (s.india_higher_than_eu_why.eu_gap_no_use_on_food ?? 0) +
              (s.india_higher_than_eu_why.eu_gap_never_assessed ?? 0) +
              (s.india_higher_than_eu_why.eu_gap_at_loq ?? 0),
          )}{" "}
          are pesticides the EU does not permit on that food at all, so its limit is the level a laboratory can just
          detect: a statement that the residue should not be there, not a judgement of a safe level. In only{" "}
          {int.format(s.india_higher_than_eu_why.eu_gap_above_loq ?? 0)} does the EU set a residue level above detection
          (for an EU use, an import tolerance or a temporary limit).
        </p>
      )}

      <div className="mb-4 flex flex-wrap items-end gap-4">
        <label className="text-xs text-provenance">
          <span className="mb-1 block font-semibold uppercase tracking-wide">Food</span>
          <select
            value={food}
            onChange={(e) => reset(setFood)(e.target.value)}
            className="rounded-md border border-line bg-porcelain px-3 py-2 text-sm text-ink"
          >
            <option value="">All foods</option>
            {(foods.data ?? [])
              .filter((f) => f.hazards_compared > 0)
              .map((f) => (
                <option key={f.food_key} value={f.food_key}>
                  {f.name} ({f.hazards_compared})
                </option>
              ))}
          </select>
        </label>
        <div className="text-xs text-provenance" role="group" aria-label="Kind of limit">
          <span className="mb-1 block font-semibold uppercase tracking-wide">Kind</span>
          <div className="flex overflow-hidden rounded-md border border-line">
            {(
              [
                ["", "All"],
                ["pesticide_mrl", "Pesticides"],
                ["contaminant_ml", "Contaminants"],
              ] as const
            ).map(([v, label]) => (
              <button
                key={v}
                type="button"
                aria-pressed={standardType === v}
                onClick={() => reset(setStandardType)(v)}
                className={`px-3 py-2 text-sm ${standardType === v ? "bg-ink text-on-ink" : "bg-porcelain text-ink"}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <label className="flex items-center gap-2 pb-2 text-sm text-ink">
          <input type="checkbox" checked={onlyHigher} onChange={(e) => reset(setOnlyHigher)(e.target.checked)} />
          Only where India allows more than the EU
        </label>
      </div>

      {table.isError ? (
        <p className="text-risk">Could not load the comparison: {(table.error as Error).message}</p>
      ) : table.isLoading ? (
        <p className="text-provenance">Loading…</p>
      ) : total === 0 ? (
        <p className="text-provenance">No pairs match these filters.</p>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full min-w-[720px] text-sm">
              <caption className="sr-only">Legal limits in mg/kg, sorted by how far India&apos;s exceeds the EU&apos;s</caption>
              <thead>
                <tr className="bg-porcelain text-left text-xs uppercase tracking-wide text-provenance">
                  <th className="px-3 py-3">Substance</th>
                  <th className="px-3 py-3">Food</th>
                  <th className="px-3 py-3 text-right">India</th>
                  <th className="px-3 py-3 text-right">EU</th>
                  <th className="px-3 py-3 text-right">Codex</th>
                  <th className="px-3 py-3 text-right">US</th>
                  <th className="px-3 py-3 text-right">India ÷ EU</th>
                </tr>
              </thead>
              <tbody>
                {table.data!.results.map((c) => (
                  <Row key={`${c.standard_type}:${c.hazard_key}:${c.food_key}`} c={c} />
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex items-center justify-between text-sm text-provenance">
            <span>
              {int.format(total)} pairs · limits in mg/kg · <sup className="text-caution">d</sup> EU default ·{" "}
              <sup>g</sup> group or catch-all limit
            </span>
            <span className="flex items-center gap-2">
              <button
                type="button"
                disabled={page === 0}
                onClick={() => setPage((p) => p - 1)}
                className="rounded-md border border-line px-3 py-1 disabled:opacity-40"
              >
                ← Prev
              </button>
              {page + 1} / {pages}
              <button
                type="button"
                disabled={page + 1 >= pages}
                onClick={() => setPage((p) => p + 1)}
                className="rounded-md border border-line px-3 py-1 disabled:opacity-40"
              >
                Next →
              </button>
            </span>
          </div>
        </>
      )}

      <div className="disclaimer mt-8">
        <strong>How to read this. </strong>
        A legal limit is a regulatory line, not a safety verdict: a higher limit can reflect different farming
        practice, diet or data, and a lower one is not proof of safer food. &quot;No limit&quot; means that rule-book
        sets no value for the pair (for EU pesticides it means the substance is not in the EU database).
        {s?.caveats?.length ? (
          <ul className="mt-2 list-disc pl-5">
            {s.caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        ) : null}
        {s?.snapshots?.length ? (
          <p className="mt-2">
            Sources:{" "}
            {s.snapshots.map((sn, i) => (
              <span key={`${sn.jurisdiction}${i}`}>
                {i > 0 && "; "}
                <a href={sn.document_url} className="underline" target="_blank" rel="noreferrer">
                  {sn.document_title}
                </a>
                {sn.document_version ? ` (${sn.document_version})` : ""}
              </span>
            ))}
            .
          </p>
        ) : null}
      </div>
    </div>
  );
}
