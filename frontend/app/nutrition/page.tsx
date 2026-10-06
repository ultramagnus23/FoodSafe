"use client";

import { Bars, LoadState, Page, PageHeader, Section, SnapshotNote, Stat, Table, Td, Th } from "@/components/ui/DataBlocks";
import { capitalise, num, pct, useSnapshot } from "@/lib/snapshot";

const NOVA: Record<number, string> = {
  1: "1 · unprocessed",
  2: "2 · culinary ingredients",
  3: "3 · processed",
  4: "4 · ultra-processed",
};

export default function NutritionPage() {
  const nu = useSnapshot("nutrition");
  const n = nu.data;
  const graded = (n?.nutriscore ?? []).reduce((a, b) => a + b.n, 0);
  const novaN = (n?.nova ?? []).reduce((a, b) => a + b.n, 0);
  const de = (n?.nutriscore ?? []).filter((x) => x.g === "d" || x.g === "e").reduce((a, b) => a + b.n, 0);
  const nova4 = (n?.nova ?? []).find((x) => x.g === 4)?.n ?? 0;

  return (
    <Page>
      <PageHeader kicker="Nutrition" title="Packaged food sold in India">
        <p>
          The diet-quality side of food and health: products listed in Open Food Facts as sold in India. These are
          crowd-sourced label transcriptions, not lab analyses, and not a sample of what India eats. Nutri-Score and NOVA as
          Open Food Facts computes them; &quot;high in&quot; uses the UK front-of-pack thresholds per 100 g (India has no
          final scheme).
        </p>
        <SnapshotNote />
      </PageHeader>
      <LoadState error={nu.error} loading={nu.isLoading} what="nutrition data" />
      {n && n.products ? (
        <>
          <div className="mb-10 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat value={num(n.products)} label="packaged foods listed as sold in India" />
            <Stat value={pct(de, graded)} label={`of ${num(graded)} graded products score D or E`} />
            <Stat value={pct(nova4, novaN)} label={`of ${num(novaN)} with a NOVA group are ultra-processed`} />
            <Stat value={num(n.complete)} label="with a complete nutrition table" />
          </div>
          <Section title="Nutri-Score and processing">
            <div className="grid gap-10 lg:grid-cols-2">
              <div>
                <h3 className="mb-3 font-display text-lg">Nutri-Score of {num(graded)} graded products</h3>
                <Bars rows={n.nutriscore.map((r) => ({ key: r.g, label: `Grade ${r.g.toUpperCase()}`, value: r.n, display: pct(r.n, graded) }))} />
              </div>
              <div>
                <h3 className="mb-3 font-display text-lg">Processing (NOVA) of {num(novaN)} products</h3>
                <Bars rows={n.nova.map((r) => ({ key: String(r.g), label: NOVA[r.g] ?? String(r.g), value: r.n, display: pct(r.n, novaN) }))} />
              </div>
            </div>
            <h3 className="mb-3 mt-10 font-display text-lg">High in, of {num(n.complete)} products with a complete table</h3>
            <Bars max={n.complete} rows={n.high_in.map((r) => ({ key: r.k, label: capitalise(r.k), value: r.n, display: pct(r.n, n.complete) }))} />
          </Section>
          <Section title="By category">
            <Table minWidth={560}>
              <thead>
                <tr>
                  <Th>Category</Th>
                  <Th right>Products</Th>
                  <Th right>Nutri-Score D or E</Th>
                  <Th right>Ultra-processed (NOVA 4)</Th>
                </tr>
              </thead>
              <tbody>
                {n.categories.map((c) => (
                  <tr key={c.category}>
                    <Td>{capitalise(c.category.replace(/^en:/, "").replace(/-/g, " "))}</Td>
                    <Td right>{num(c.products)}</Td>
                    <Td right>{c.graded ? pct(c.de, c.graded) : "—"}</Td>
                    <Td right>{pct(c.nova4, c.products)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <p className="mt-4 text-xs text-provenance">Data: Open Food Facts (Open Database License).</p>
          </Section>
        </>
      ) : n ? (
        <p className="text-sm text-provenance">Packaged-food data has not been loaded into this snapshot yet.</p>
      ) : null}
    </Page>
  );
}
