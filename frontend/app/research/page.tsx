"use client";

import { useResearch } from "@/lib/api/research";
import type { ResearchListItem } from "@/lib/api/types";

const EVIDENCE_LABEL: Record<string, string> = {
  B: "Review / meta-analysis",
  C: "Individual peer-reviewed study",
};

function EvidenceBadge({ level }: { level: string }) {
  return (
    <span
      className="shrink-0 rounded bg-provenance-pale px-2 py-0.5 text-[11px] uppercase text-ink"
      title={EVIDENCE_LABEL[level] ?? level}
    >
      Evidence {level}
    </span>
  );
}

function ResearchCard({ r }: { r: ResearchListItem }) {
  return (
    <div className="rounded-lg border border-line bg-slab p-4">
      <div className="mb-1 flex items-start justify-between gap-3">
        <a
          className="font-medium text-ink underline-offset-2 hover:underline"
          href={r.landing_page_url}
          target="_blank"
          rel="noreferrer"
        >
          {r.title}
        </a>
        <EvidenceBadge level={r.evidence_level} />
      </div>
      <div className="text-xs text-provenance">
        {r.contaminant_name.replace(/_/g, " ")}
        {r.journal ? ` · ${r.journal}` : ""}
        {r.publication_year ? ` · ${r.publication_year}` : ""}
      </div>
      {r.authors.length > 0 && (
        <div className="mt-1 text-xs text-provenance">{r.authors.slice(0, 4).join(", ")}{r.authors.length > 4 ? " et al." : ""}</div>
      )}
      {r.matched_health_terms.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {r.matched_health_terms.map((t) => (
            <span key={t} className="rounded bg-amber-100 px-2 py-0.5 text-[11px] text-amber-800">
              {t}
            </span>
          ))}
        </div>
      )}
      {r.doi && (
        <div className="mt-2 text-xs text-provenance">
          DOI:{" "}
          <a className="underline" href={`https://doi.org/${r.doi}`} target="_blank" rel="noreferrer">
            {r.doi}
          </a>
        </div>
      )}
    </div>
  );
}

export default function ResearchPage() {
  const research = useResearch();

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="mb-2 font-display text-4xl font-light">Research</h1>
      <p className="mb-2 text-provenance">
        Real, peer-reviewed scientific literature linking contaminants tracked on this platform to disease and
        health outcomes — sourced from{" "}
        <a className="underline" href="https://openalex.org" target="_blank" rel="noreferrer">
          OpenAlex
        </a>
        , a free scholarly-metadata index. Every entry links to its DOI and original abstract.
      </p>
      {research.data?.disclaimer && (
        <p className="mb-8 rounded-lg border border-line bg-slab p-3 text-xs text-provenance">
          {research.data.disclaimer}
        </p>
      )}

      {research.isLoading ? (
        <p className="text-provenance">Loading…</p>
      ) : research.error ? (
        <p className="text-provenance">Could not load research sources.</p>
      ) : !research.data || research.data.results.length === 0 ? (
        <p className="text-provenance">No records.</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {research.data.results.map((r) => (
            <ResearchCard key={r.id} r={r} />
          ))}
        </div>
      )}
    </div>
  );
}
