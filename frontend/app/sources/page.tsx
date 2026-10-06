"use client";

import { LoadState, Page, PageHeader, SnapshotNote, Table, Tag, Td, Th } from "@/components/ui/DataBlocks";
import { num, useSnapshot } from "@/lib/snapshot";

const REPO = "https://github.com/ultramagnus23/FoodSafe/blob/main/";

export default function SourcesPage() {
  const so = useSnapshot("sources");
  return (
    <Page wide>
      <PageHeader kicker="Trust" title="Sources and how far to trust them">
        <p>
          Every dataset comes from a source with a fixed character: who published it, what it measures, and how it is
          extracted. A fixed rubric turns that into a confidence level served next to the data: high for official
          machine-readable data, medium for validated document extraction or cited curation, low for unvalidated extraction
          or media. Confidence says whether a record states what its publisher disclosed. It says nothing about
          representativeness, so each source&apos;s limits are listed with it.
        </p>
        <p>Synthetic data is never served. Row counts are live from the production database.</p>
        <SnapshotNote />
      </PageHeader>
      <LoadState error={so.error} loading={so.isLoading} what="the source registry" />
      {so.data ? (
        <Table minWidth={980} caption="Sources, confidence and limits">
          <thead>
            <tr>
              <Th>Source</Th>
              <Th>Publisher</Th>
              <Th>Confidence</Th>
              <Th right>Rows</Th>
              <Th>What it cannot tell you</Th>
            </tr>
          </thead>
          <tbody>
            {so.data.map((s) => (
              <tr key={s.id}>
                <Td>
                  <span className="text-ink">{s.name}</span>
                  <span className="block text-xs text-provenance">{s.grain}</span>
                  {s.doc ? (
                    <a href={REPO + s.doc} className="text-xs text-provenance underline" target="_blank" rel="noreferrer">
                      method
                    </a>
                  ) : null}
                </Td>
                <Td className="text-provenance">{s.publisher}</Td>
                <Td>
                  <Tag tone={s.base_confidence === "high" ? "clear" : s.base_confidence === "medium" ? "caution" : "risk"}>{s.base_confidence}</Tag>
                </Td>
                <Td right>{s.rows == null ? "—" : num(s.rows)}</Td>
                <Td className="text-provenance">
                  <ul className="list-disc space-y-1 pl-4 text-xs">
                    {(s.scope ?? []).slice(0, 3).map((x) => (
                      <li key={x}>{x}</li>
                    ))}
                  </ul>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}
      <p className="mt-6 text-xs text-provenance">
        Rubric: <a className="underline" href={`${REPO}api/source_registry.py`}>api/source_registry.py</a> · the same registry is
        served by the API at <span className="register">GET /v1/meta/sources</span>.
      </p>
    </Page>
  );
}
