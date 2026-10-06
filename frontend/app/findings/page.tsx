"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  Bars,
  Field,
  inputClass,
  LoadState,
  Page,
  PageHeader,
  Section,
  SnapshotNote,
  Stat,
  Table,
  Td,
  Th,
} from "@/components/ui/DataBlocks";
import { capitalise, cleanHazard, num, ordinal, useCountryNames, useSnapshot } from "@/lib/snapshot";

export default function FindingsPage() {
  const india = useSnapshot("rasff_india");
  const co = useSnapshot("rasff_countries");
  const sources = useSnapshot("sources");
  const names = useCountryNames();
  const [q, setQ] = useState("");
  const [shown, setShown] = useState(30);

  const IN = co.data?.find((c) => c.origin === "IN");
  const rank = co.data ? co.data.findIndex((c) => c.origin === "IN") + 1 : 0;
  // Distinct notifications: one can name several origins, so per-origin counts overlap.
  const total = sources.data?.find((x) => x.id === "rasff")?.rows;
  const ranked = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (co.data ?? [])
      .map((c, i) => ({ ...c, rank: i + 1, name: names[c.origin] || c.origin }))
      .filter((c) => !needle || c.name.toLowerCase().includes(needle) || c.origin.toLowerCase() === needle);
  }, [co.data, names, q]);

  return (
    <Page>
      <PageHeader kicker="Findings · what is found in food" title="Contamination found in food, as public records show it">
        <p>
          The most detailed public record of what is found in food from India is not Indian: it is the EU&apos;s Rapid
          Alert System for Food and Feed (RASFF), which logs every consignment EU and EEA authorities reject at the border
          or withdraw from the market, with the hazard, the measured value and the legal limit. Here it is loaded for every
          origin country, so India can be read in context.
        </p>
        <p>
          These are risk-targeted checks of exported food, so the counts track trade volume and how hard the EU looks, not
          how safe a country&apos;s food is. India&apos;s own testing is disclosed only as yearly state totals (see{" "}
          <Link href="/places#states" className="underline">
            Places
          </Link>
          ) and national pesticide-residue monitoring to 2018-19 (see{" "}
          <Link href="/directory" className="underline">
            Directory
          </Link>
          ).
        </p>
        <SnapshotNote />
      </PageHeader>

      <LoadState error={co.error} loading={co.isLoading} what="EU notifications" />
      {IN ? (
        <div className="mb-10 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat value={num(IN.notifications)} label={`notifications on food from India, ${ordinal(rank)} of ${num(co.data?.length)} origins`} />
          <Stat value={num(IN.serious)} label="classed serious by the notifying authority" />
          <Stat value={num(IN.border_rejections)} label="border rejections" />
          <Stat value={num(total)} label="distinct notifications loaded, every origin" />
        </div>
      ) : null}

      <Section id="india" title="Food from India: what the EU finds">
        <LoadState error={india.error} loading={india.isLoading} what="India's findings" />
        {india.data ? (
          <div className="grid gap-10 lg:grid-cols-2">
            <div>
              <h3 className="mb-3 font-display text-lg">By hazard category</h3>
              <Bars
                rows={india.data.by_category.slice(0, 12).map((r) => ({
                  key: r.category,
                  label: capitalise(r.category),
                  value: r.n,
                  display: num(r.n),
                }))}
              />
            </div>
            <div>
              <h3 className="mb-3 font-display text-lg">Most frequent hazards</h3>
              <Bars
                rows={india.data.top_hazards.slice(0, 12).map((r) => ({
                  key: r.hazard,
                  label: capitalise(cleanHazard(r.hazard)),
                  sub: /unauthori[sz]ed/.test(r.hazard) ? "unauthorised substance in the EU" : undefined,
                  value: r.n,
                  display: num(r.n),
                }))}
              />
            </div>
            <div>
              <h3 className="mb-3 font-display text-lg">By product</h3>
              <Bars
                rows={india.data.by_product.slice(0, 12).map((r) => ({
                  key: r.product,
                  label: capitalise(r.product),
                  value: r.n,
                  display: num(r.n),
                }))}
              />
            </div>
            <div>
              <h3 className="mb-3 font-display text-lg">By year</h3>
              <Bars
                rows={india.data.by_year.map((r) => ({
                  key: String(r.year),
                  label: String(r.year),
                  value: r.n,
                  display: num(r.n),
                }))}
              />
              <p className="mt-2 text-xs text-provenance">The current year is partial. The first year reflects when loading began.</p>
            </div>
          </div>
        ) : null}
      </Section>

      <Section
        id="world"
        title="Every origin, ranked"
        note="Notifications on each country's food, all years loaded. A high count can mean large exports or close scrutiny, not less safe food. Poland and other EU members appear mostly through market checks of their own products, not border rejections."
      >
        <div className="mb-4">
          <Field label="Search">
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="country" className={inputClass} />
          </Field>
        </div>
        <Table minWidth={680} caption="EU notifications by origin country">
          <thead>
            <tr>
              <Th right>#</Th>
              <Th>Origin</Th>
              <Th right>Notifications</Th>
              <Th right>Serious</Th>
              <Th right>Border rejections</Th>
              <Th>Period</Th>
            </tr>
          </thead>
          <tbody>
            {(q ? ranked : ranked.slice(0, shown)).map((c) => (
              <tr key={c.origin} className={c.origin === "IN" ? "font-semibold" : ""}>
                <Td right>{c.rank}</Td>
                <Td>{c.name}</Td>
                <Td right>{num(c.notifications)}</Td>
                <Td right>{num(c.serious)}</Td>
                <Td right>{num(c.border_rejections)}</Td>
                <Td className="register whitespace-nowrap text-xs text-provenance">
                  {String(c.first ?? "").slice(0, 4)}–{String(c.last ?? "").slice(0, 4)}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
        {!q && ranked.length > shown ? (
          <button type="button" onClick={() => setShown(1000)} className="mt-3 rounded border border-line px-3 py-1 text-sm">
            Show all {num(ranked.length)} origins
          </button>
        ) : null}
        <p className="mt-4 text-xs text-provenance">
          Source: European Commission, RASFF Window (public API), loaded daily. Method and limits:{" "}
          <a className="underline" href="https://github.com/ultramagnus23/FoodSafe/blob/main/docs/RASFF_INGESTION.md">
            docs/RASFF_INGESTION.md
          </a>
          .
        </p>
      </Section>
    </Page>
  );
}
