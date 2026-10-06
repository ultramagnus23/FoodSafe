"use client";

import { useMemo, useState } from "react";
import {
  Bars,
  Chips,
  Field,
  inputClass,
  LoadState,
  Page,
  PageHeader,
  Section,
  SnapshotNote,
  Table,
  Td,
  Th,
} from "@/components/ui/DataBlocks";
import { num, useSnapshot, type Country } from "@/lib/snapshot";

export default function PlacesPage() {
  return (
    <Page wide>
      <PageHeader kicker="Places" title="How places compare: Indian states, countries, and the global burden">
        <p>
          The population side of the disease risk engine: where testing finds problems, how strong each country&apos;s
          food-safety system says it is, and who is most vulnerable (child stunting, anaemia, undernourishment, unsafe water).
        </p>
        <SnapshotNote />
      </PageHeader>
      <Section
        id="states"
        title="Indian states: samples found non-conforming"
        note='Samples analysed and found non-conforming each year, as the Health Ministry disclosed to Parliament (Lok Sabha answers, 2013-14 to 2025-26). Inspectors choose what to sample, so a high rate can mean sharper targeting as much as worse food; "non-conforming" also covers labelling and quality failures. A backtest found that nothing predicts next year better than this year.'
      >
        <States />
      </Section>
      <Section
        id="countries"
        title="Countries compared"
        note="Food-safety capacity is each country's own IHR self-assessment to WHO. Nutrition and water indicators from the World Bank (latest year shown under each value). EU findings count checks on that country's exports: they do not rank whose food is safer."
      >
        <Countries />
      </Section>
      <Section
        id="burden"
        title="Which foodborne hazards harm the most people worldwide"
        note="WHO's estimates of the global burden of foodborne disease (FERG, 2021 as loaded), by hazard. WHO publishes these at global level only, so there is no country breakdown to show. These are the benchmarks a disease-burden engine has to reproduce."
      >
        <Burden />
      </Section>
    </Page>
  );
}

function States() {
  const st = useSnapshot("states");
  if (st.error || st.isLoading) return <LoadState error={st.error} loading what="state sampling" />;
  const rows = (st.data ?? [])
    .map((s) => {
      const ser = s.series.filter((x) => x[1] > 0);
      const last = ser[ser.length - 1];
      const rates = ser.map((x) => (100 * x[2]) / x[1]);
      return { s, last, rates };
    })
    .filter((r) => r.last)
    .sort((a, b) => (100 * b.last[2]) / b.last[1] - (100 * a.last[2]) / a.last[1]);
  return (
    <Table minWidth={720} caption="State sampling outcomes, latest year">
      <thead>
        <tr>
          <Th>State / UT</Th>
          <Th>Latest year</Th>
          <Th right>Analysed</Th>
          <Th right>Non-conforming</Th>
          <Th right>Rate</Th>
          <Th>Range across years</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map(({ s, last, rates }) => (
          <tr key={s.state}>
            <Td>{s.state}</Td>
            <Td className="register text-xs">{last[0]}</Td>
            <Td right>{num(last[1])}</Td>
            <Td right>{num(last[2])}</Td>
            <Td right>{num((100 * last[2]) / last[1], 1)}%</Td>
            <Td className="register text-xs text-provenance">
              {rates.length > 1 ? `${num(Math.min(...rates), 1)}–${num(Math.max(...rates), 1)}% over ${rates.length} years` : "one year"}
            </Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

const COLS: [string, string][] = [
  ["IHRSPAR2_C13", "Food-safety capacity"],
  ["SH.STA.STNT.ME.ZS", "Child stunting"],
  ["SH.ANM.ALLW.ZS", "Anaemia, women"],
  ["SN.ITK.DEFC.ZS", "Undernourishment"],
  ["SH.H2O.SMDW.ZS", "Safely managed water"],
  ["eu", "EU findings on its food"],
];

function countryValue(c: Country, k: string, euBy: Record<string, number>): number | string | null {
  if (k === "name") return c.name;
  if (k === "eu") return euBy[c.iso2 ?? ""] ?? 0;
  return c.ind && c.ind[k] ? c.ind[k][0] : null;
}

function Countries() {
  const co = useSnapshot("countries");
  const eu = useSnapshot("rasff_countries");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<[string, number]>(["eu", -1]);
  const [all, setAll] = useState(false);

  const euBy = useMemo(() => Object.fromEntries((eu.data ?? []).map((e) => [e.origin, e.notifications])), [eu.data]);
  const val = (c: Country, k: string) => countryValue(c, k, euBy);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const [k, dir] = sort;
    return (co.data ?? [])
      .filter((c) => !needle || c.name.toLowerCase().includes(needle) || (c.region ?? "").toLowerCase().includes(needle))
      .sort((a, b) => {
        const x = countryValue(a, k, euBy);
        const y = countryValue(b, k, euBy);
        if (x == null) return 1;
        if (y == null) return -1;
        return (x > y ? 1 : x < y ? -1 : 0) * dir;
      });
  }, [co.data, euBy, q, sort]);

  if (co.error || co.isLoading) return <LoadState error={co.error} loading what="countries" />;
  const shown = q || all ? rows : rows.slice(0, 40);
  const head = (k: string, label: string, right = true) => (
    <Th right={right}>
      <button
        type="button"
        onClick={() => setSort(([pk, pd]) => [k, pk === k ? -pd : k === "name" ? 1 : -1])}
        aria-sort={sort[0] === k ? (sort[1] > 0 ? "ascending" : "descending") : "none"}
        className="uppercase"
      >
        {label}
        {sort[0] === k ? (sort[1] > 0 ? " ↑" : " ↓") : ""}
      </button>
    </Th>
  );
  return (
    <div>
      <div className="mb-4">
        <Field label="Search">
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="country or region" className={inputClass} />
        </Field>
      </div>
      <Table minWidth={900} caption="Country indicators">
        <thead>
          <tr>
            {head("name", "Country", false)}
            {COLS.map(([k, l]) => head(k, l))}
          </tr>
        </thead>
        <tbody>
          {shown.map((c) => (
            <tr key={c.iso3} className={c.iso2 === "IN" ? "font-semibold" : ""}>
              <Td>
                {c.name}
                <span className="block text-[11px] font-normal text-provenance">{c.region}</span>
              </Td>
              {COLS.map(([k]) => {
                const v = val(c, k);
                const year = k !== "eu" && c.ind && c.ind[k] ? c.ind[k][1] : null;
                return (
                  <Td key={k} right>
                    {v == null ? <span className="text-provenance">—</span> : k === "eu" ? num(v as number) : `${num(v as number, 1)}%`}
                    {year ? <span className="block text-[11px] font-normal text-provenance">{year}</span> : null}
                  </Td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </Table>
      {!q && !all && rows.length > 40 ? (
        <button type="button" onClick={() => setAll(true)} className="mt-3 rounded border border-line px-3 py-1 text-sm">
          Show all {num(rows.length)} countries
        </button>
      ) : null}
    </div>
  );
}

function Burden() {
  const bu = useSnapshot("burden");
  const [measure, setMeasure] = useState<"deaths" | "illnesses" | "DALYs">("deaths");
  const [age, setAge] = useState<"all ages" | "under 5">("all ages");
  if (bu.error || bu.isLoading) return <LoadState error={bu.error} loading what="global burden" />;
  const rows = (bu.data ?? [])
    .filter((b) => b.measure === measure && b.age_group === age && !/^All /.test(b.hazard) && b.hazard !== b.hazard_group)
    .sort((a, b) => b.value - a.value)
    .slice(0, 15);
  const total = (bu.data ?? []).find((b) => b.measure === measure && b.age_group === age && b.hazard === "All hazards");
  return (
    <div>
      <div className="mb-5 flex flex-wrap gap-3">
        <Chips
          label="Measure"
          value={measure}
          onChange={setMeasure}
          options={[
            ["deaths", "Deaths"],
            ["illnesses", "Illnesses"],
            ["DALYs", "DALYs"],
          ]}
        />
        <Chips
          label="Age group"
          value={age}
          onChange={setAge}
          options={[
            ["all ages", "All ages"],
            ["under 5", "Under 5"],
          ]}
        />
      </div>
      {total ? (
        <p className="register mb-4 text-sm text-ink">
          All foodborne hazards: {num(total.value >= 1e6 ? total.value / 1e6 : total.value / 1e3, 2)}
          {total.value >= 1e6 ? " million" : " thousand"} {measure === "DALYs" ? "DALYs" : measure} a year ({age})
        </p>
      ) : null}
      <Bars
        rows={rows.map((r) => ({
          key: `${r.hazard_group}:${r.hazard}`,
          label: r.hazard,
          sub: r.hazard_group,
          value: r.value,
          display: `${num(r.value >= 1e6 ? r.value / 1e6 : r.value / 1e3, 1)}${r.value >= 1e6 ? " M" : " k"}`,
        }))}
      />
    </div>
  );
}
