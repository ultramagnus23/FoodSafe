"use client";

import { useMemo, useState } from "react";
import {
  Chips,
  Field,
  inputClass,
  LoadState,
  Page,
  PageHeader,
  Section,
  SnapshotNote,
  Stat,
  Table,
  Tag,
  Td,
  Th,
} from "@/components/ui/DataBlocks";
import { FOODS, mgkg, num, useSnapshot, type StdRow } from "@/lib/snapshot";

const BASIS: Record<string, string> = {
  specific: "",
  group: "group",
  residual: "catch-all",
  eu_default: "EU default",
  none: "none",
  not_loaded: "not compared",
  not_numeric: "printed as text",
};
const NONE: Record<string, [string, string]> = {
  EU: ["no limit", "EU sets none"],
  CODEX: ["—", "no Codex standard"],
  US: ["not permitted", "no tolerance"],
  IN: ["—", ""],
};
const GAP: Record<string, string> = {
  eu_gap_not_approved: "EU: not approved, detection-level limit",
  eu_gap_no_use_on_food: "EU: no approved use on this food",
  eu_gap_never_assessed: "EU: never assessed (0.01 default)",
  eu_gap_at_loq: "EU: detection-level limit",
  eu_gap_above_loq: "EU sets a residue level",
};

function Limit({ v, b, j }: { v: number | null; b: string | null; j: keyof typeof NONE }) {
  if (v == null) {
    const [main, sub] = b === "none" ? NONE[j] : ["—", BASIS[b ?? ""] ?? b ?? ""];
    return (
      <Td right>
        <span className="text-provenance">{main}</span>
        {sub ? <span className="block text-[11px] text-provenance">{sub}</span> : null}
      </Td>
    );
  }
  const basis = BASIS[b ?? ""] ?? b ?? "";
  return (
    <Td right>
      {mgkg(v)}
      {basis ? <span className="block text-[11px] text-provenance">{basis}</span> : null}
    </Td>
  );
}

function shortName(n: string | null): string {
  const s = String(n || "");
  return s.length > 42 && s.indexOf(" (") > 2 ? s.slice(0, s.indexOf(" (")) : s;
}

function Ratio({ r }: { r: number | null }) {
  if (r == null) return null;
  if (r > 1.0001) return <Tag tone="risk">India {num(r, r < 10 ? 1 : 0)}× EU</Tag>;
  if (r < 0.9999) return <Tag tone="clear">India {num(r, 2)}× EU</Tag>;
  return <Tag>same as EU</Tag>;
}

export default function StandardsPage() {
  const sum = useSnapshot("standards_summary");
  const cmp = useSnapshot("standards_compare");
  const [food, setFood] = useState("rice");
  const [q, setQ] = useState("");
  const [type, setType] = useState<"" | "pesticide_mrl" | "contaminant_ml">("");
  const [onlyHigher, setOnlyHigher] = useState(false);
  const [shown, setShown] = useState(50);

  const foods = useMemo(
    () => Array.from(new Set((cmp.data ?? []).map((r) => r.f))).sort((a, b) => (FOODS[a] || a).localeCompare(FOODS[b] || b)),
    [cmp.data],
  );
  const rows: StdRow[] = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (cmp.data ?? [])
      .filter(
        (r) =>
          (!food || r.f === food) &&
          (!type || r.t === type) &&
          (!onlyHigher || (r.flags ?? []).includes("india_higher_than_eu")) &&
          (!needle || (r.hn ?? "").toLowerCase().includes(needle) || r.h.includes(needle)),
      )
      .sort((a, b) => (b.re ?? -1) - (a.re ?? -1));
  }, [cmp.data, food, q, type, onlyHigher]);

  const f = sum.data?.flags;
  const floor = f ? f.gap_not_approved + f.gap_no_use_on_food + f.gap_never_assessed + f.gap_at_loq : 0;
  const reset = () => setShown(50);

  return (
    <Page>
      <PageHeader kicker="Rules · India vs the world" title="India's food limits beside the EU, Codex and the US">
        <p>
          Every pesticide residue limit and contaminant maximum level India sets in law (FSSAI&apos;s Contaminants, Toxins
          and Residues Regulations), matched food by food against the European Union, the Codex Alimentarius and the
          United States. A ratio above 1× means India permits more of that substance in that food.
        </p>
        <SnapshotNote />
      </PageHeader>

      <LoadState error={sum.error} loading={sum.isLoading} what="the summary" />
      {f ? (
        <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat value={num(f.comparisons)} label="food–hazard pairs compared" />
          <Stat value={num(f.india_higher_than_eu)} label="where India permits more than the EU" />
          <Stat value={num(f.not_approved_in_eu)} label={`of ${num(f.india_pesticides)} India-regulated pesticides not approved in the EU`} />
          <Stat value={num(f.india_higher_than_codex)} label="where India permits more than Codex" />
        </div>
      ) : null}
      {f && f.higher_eu_pesticides ? (
        <p className="mb-10 max-w-prose leading-relaxed text-provenance">
          <strong className="text-ink">Why most of the gap exists.</strong> Of the {num(f.higher_eu_pesticides)} pesticide
          limits where India permits more than the EU, {num(floor)} are pesticides the EU does not permit on that food (
          {num(f.gap_not_approved)} not approved, {num(f.gap_no_use_on_food)} approved but not for that food,{" "}
          {num(f.gap_never_assessed)} never assessed), so its limit is the level a laboratory can just detect: &quot;should
          not be found&quot;, not a safe level. In only {num(f.gap_above_loq)} does the EU set a residue level above
          detection; there India&apos;s limit is a median {num(f.gap_above_loq_median_ratio, 1)} times the EU&apos;s.
        </p>
      ) : null}

      <Section id="table" title="Every pair, with the reason for each gap">
        <div className="mb-4 flex flex-wrap items-end gap-4">
          <Field label="Food">
            <select value={food} onChange={(e) => { setFood(e.target.value); reset(); }} className={inputClass}>
              <option value="">All foods</option>
              {foods.map((k) => (
                <option key={k} value={k}>
                  {FOODS[k] || k}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Hazard">
            <input
              type="search"
              value={q}
              onChange={(e) => { setQ(e.target.value); reset(); }}
              placeholder="e.g. chlorpyrifos, lead"
              className={inputClass}
            />
          </Field>
          <div className="text-xs text-provenance">
            <span className="mb-1 block font-semibold uppercase tracking-wide">Kind</span>
            <Chips
              label="Kind of limit"
              value={type}
              onChange={(v) => { setType(v); reset(); }}
              options={[
                ["", "All"],
                ["pesticide_mrl", "Pesticides"],
                ["contaminant_ml", "Contaminants"],
              ]}
            />
          </div>
          <label className="flex items-center gap-2 pb-2 text-sm text-ink">
            <input type="checkbox" checked={onlyHigher} onChange={(e) => { setOnlyHigher(e.target.checked); reset(); }} />
            Only where India permits more than the EU
          </label>
        </div>
        <LoadState error={cmp.error} loading={cmp.isLoading} what="the comparison" />
        {cmp.data ? (
          <>
            <Table minWidth={860} caption="Legal limits in mg/kg, sorted by India divided by EU">
              <thead>
                <tr>
                  <Th>Hazard</Th>
                  <Th>Food</Th>
                  <Th right>India</Th>
                  <Th right>EU</Th>
                  <Th right>Codex</Th>
                  <Th right>US</Th>
                  <Th>Note</Th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, shown).map((r) => {
                  const flags = r.flags ?? [];
                  const gap = flags.find((x) => GAP[x]);
                  return (
                    <tr key={`${r.t}:${r.h}:${r.f}`}>
                      <Td>
                        <span title={r.hn ?? r.h}>{shortName(r.hn) || r.h}</span>
                        {r.st === "Not approved" ? <Tag tone="caution">not approved in EU</Tag> : null}
                        {r.ig ? <Tag tone={r.ig === "1" ? "risk" : "neutral"}>IARC {r.ig}</Tag> : null}
                        {flags.includes("basis_mismatch") ? <Tag>residue defined differently</Tag> : null}
                      </Td>
                      <Td>{FOODS[r.f] || r.f}</Td>
                      <Limit v={r.i} b={r.ib} j="IN" />
                      <Limit v={r.e} b={r.eb} j="EU" />
                      <Limit v={r.c} b={r.cb} j="CODEX" />
                      <Limit v={r.u} b={r.ub} j="US" />
                      <Td>
                        <Ratio r={r.re} />
                        {gap ? <Tag tone={gap === "eu_gap_above_loq" ? "caution" : "neutral"}>{GAP[gap]}</Tag> : null}
                        {flags.includes("no_us_tolerance") ? <Tag>no US tolerance</Tag> : null}
                        {flags.includes("india_internal_conflict") ? <Tag tone="caution">India prints two limits</Tag> : null}
                      </Td>
                    </tr>
                  );
                })}
                {!rows.length ? (
                  <tr>
                    <Td className="text-provenance">No pair matches. Clear the hazard search or choose another food.</Td>
                  </tr>
                ) : null}
              </tbody>
            </Table>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm text-provenance">
              <span>
                {num(rows.length)} pairs, sorted by India ÷ EU{rows.length > shown ? `; first ${shown} shown` : ""}. Values in
                mg/kg.
              </span>
              {rows.length > shown ? (
                <button type="button" onClick={() => setShown((n) => n + 200)} className="rounded border border-line px-3 py-1 text-ink">
                  Show more
                </button>
              ) : null}
            </div>
          </>
        ) : null}
        <p className="mt-4 max-w-prose text-xs leading-relaxed text-provenance">
          Basis under each value: <em>group</em> = a food group covering it; <em>catch-all</em> = India&apos;s &quot;foods not
          specified&quot;; <em>EU default</em> = no EU residue definition, so the general 0.01 mg/kg applies; <em>none</em> =
          no Codex standard, or in the US no tolerance (no residue is legal). Method:{" "}
          <a className="underline" href="https://github.com/ultramagnus23/FoodSafe/blob/main/docs/STANDARDS.md">
            docs/STANDARDS.md
          </a>
          .
        </p>
      </Section>

      <Section id="why-limits" title="Why the same food has different limits in different places">
        <div className="max-w-prose space-y-3 text-sm leading-relaxed text-provenance">
          <p>
            <strong className="text-ink">A pesticide limit follows from how the pesticide is allowed to be used.</strong>{" "}
            Regulators estimate the highest residue left when a crop is treated as the label permits, and set acceptable
            intakes from the toxicology alongside (
            <a className="underline" href="https://www.who.int/groups/joint-fao-who-meeting-on-pesticide-residues-(jmpr)">
              FAO/WHO JMPR
            </a>
            ). A country that permits a use on a crop sets a limit that allows for it; a country that does not, sets none.
          </p>
          <p>
            <strong className="text-ink">Where the EU permits no use, its limit is the detection floor.</strong> For
            substances it has not approved, or not on that food, the EU sets the limit at the lowest level a laboratory can
            reliably quantify, and a general 0.01 mg/kg wherever it has set nothing (
            <a className="underline" href="http://data.europa.eu/eli/reg/2005/396/oj">
              Regulation (EC) 396/2005
            </a>
            , Art. 18). Such a limit says &quot;this should not be found&quot;, not &quot;this level is safe&quot;.
          </p>
          <p>
            <strong className="text-ink">The US permits no residue without a tolerance</strong>, and a tolerance must give
            &quot;a reasonable certainty of no harm&quot;, with an extra tenfold safety factor for children unless data support
            another (
            <a className="underline" href="https://www.epa.gov/laws-regulations/summary-food-quality-protection-act">
              Food Quality Protection Act
            </a>
            ).
          </p>
          <p>
            <strong className="text-ink">Codex limits are the international reference.</strong> Under the WTO&apos;s SPS
            Agreement countries base their measures on them, and may be stricter with scientific justification (
            <a className="underline" href="https://www.wto.org/english/tratop_e/sps_e/spsagr_e.htm">
              SPS Agreement, Art. 3
            </a>
            ).
          </p>
          <p>
            <strong className="text-ink">Contaminants are not used on purpose</strong> (metals, mycotoxins), so their limits
            are set as low as reasonably achievable with good practice, after a risk assessment (Codex CXS 193). They reflect
            what a food supply can meet as well as toxicity.
          </p>
          <p className="rounded-md border border-line bg-caution-pale px-4 py-3 text-xs">
            A legal limit is a regulatory line, not a safety verdict: a higher limit can reflect different farming
            practice, diet or data, and a lower one is not proof of safer food.
          </p>
        </div>
      </Section>

      {sum.data?.snapshots?.length ? (
        <Section id="sources" title="Rule-books, as loaded">
          <Table minWidth={640}>
            <thead>
              <tr>
                <Th>Jurisdiction</Th>
                <Th>Document</Th>
                <Th right>Rows</Th>
                <Th>Loaded</Th>
              </tr>
            </thead>
            <tbody>
              {sum.data.snapshots.map((s, i) => (
                <tr key={`${s.jurisdiction}${i}`}>
                  <Td className="register text-xs">{s.jurisdiction}</Td>
                  <Td>
                    <a href={s.document_url} className="underline" target="_blank" rel="noreferrer">
                      {s.document_title}
                    </a>
                    {s.document_version ? <span className="block text-xs text-provenance">{s.document_version}</span> : null}
                  </Td>
                  <Td right>{num(s.rows_loaded)}</Td>
                  <Td className="register whitespace-nowrap text-xs">{String(s.loaded_at).slice(0, 10)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Section>
      ) : null}
    </Page>
  );
}
