"use client";

import { useEffect, useState } from "react";
import { RESEARCH_PAGE_SIZE, useResearch, useResearchSummary } from "@/lib/api/research";
import type { ResearchListItem } from "@/lib/api/types";

const EVIDENCE_LABEL: Record<string, string> = {
  B: "Review / meta-analysis",
  C: "Individual peer-reviewed study",
};

function prettify(s: string) {
  return s.replace(/_/g, " ");
}

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
        {prettify(r.contaminant_name)}
        {r.journal ? ` · ${r.journal}` : ""}
        {r.publication_year ? ` · ${r.publication_year}` : ""}
        {r.study_design && r.study_design !== "unclassified" ? ` · ${prettify(r.study_design)}` : ""}
      </div>
      {r.source_apis.length > 1 && (
        <div className="mt-1 text-[11px] text-provenance">
          Confirmed by {r.source_apis.join(" & ")}
        </div>
      )}
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
  const [contaminantId, setContaminantId] = useState<number | undefined>();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);

  // Debounce the title search so typing doesn't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(search.trim());
      setPage(0);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const summary = useResearchSummary();
  const research = useResearch({ contaminantId, q, page });

  const total = research.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / RESEARCH_PAGE_SIZE));
  const firstShown = total === 0 ? 0 : page * RESEARCH_PAGE_SIZE + 1;
  const lastShown = Math.min(total, (page + 1) * RESEARCH_PAGE_SIZE);
  const sources = summary.data ? Object.keys(summary.data.by_source) : [];

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="mb-2 font-display text-4xl font-light">Research</h1>
      <p className="mb-2 text-provenance">
        Real, peer-reviewed scientific literature linking contaminants tracked on this platform to disease and
        health outcomes — sourced from{" "}
        <a className="underline" href="https://openalex.org" target="_blank" rel="noreferrer">
          OpenAlex
        </a>{" "}
        and{" "}
        <a className="underline" href="https://europepmc.org" target="_blank" rel="noreferrer">
          Europe PMC
        </a>
        , free scholarly indexes. Every entry links to its DOI and original abstract.
      </p>
      {research.data?.disclaimer && (
        <p className="mb-6 rounded-lg border border-line bg-slab p-3 text-xs text-provenance">
          {research.data.disclaimer}
        </p>
      )}

      {summary.data && (
        <p className="mb-6 text-sm text-provenance" data-testid="research-summary">
          <strong className="text-ink">{summary.data.total_papers.toLocaleString()}</strong> distinct papers across{" "}
          {summary.data.by_contaminant.length} contaminants
          {sources.length > 0 ? ` (from ${sources.map(prettify).join(" and ")})` : ""}. A paper linked to more than one
          contaminant appears under each.
        </p>
      )}

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-provenance">
          Contaminant
          <select
            className="rounded border border-line bg-slab px-2 py-1.5 text-ink"
            value={contaminantId ?? ""}
            onChange={(e) => {
              setContaminantId(e.target.value ? Number(e.target.value) : undefined);
              setPage(0);
            }}
          >
            <option value="">All</option>
            {summary.data?.by_contaminant.map((c) => (
              <option key={c.contaminant_id} value={c.contaminant_id}>
                {prettify(c.contaminant_name)} ({c.papers.toLocaleString()})
              </option>
            ))}
          </select>
        </label>
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search titles…"
          maxLength={100}
          aria-label="Search paper titles"
          className="min-w-[14rem] flex-1 rounded border border-line bg-slab px-3 py-1.5 text-ink"
        />
      </div>

      {research.isLoading ? (
        <p className="text-provenance">Loading…</p>
      ) : research.error ? (
        <p className="text-provenance">Could not load research sources.</p>
      ) : !research.data || research.data.results.length === 0 ? (
        <p className="text-provenance">No records match.</p>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            {research.data.results.map((r) => (
              <ResearchCard key={`${r.id}-${r.contaminant_id}`} r={r} />
            ))}
          </div>
          <div className="mt-6 flex items-center justify-between text-sm text-provenance">
            <span>
              {firstShown.toLocaleString()}–{lastShown.toLocaleString()} of {total.toLocaleString()}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="rounded border border-line px-3 py-1.5 disabled:opacity-40"
                disabled={page === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
              >
                Previous
              </button>
              <span>
                Page {page + 1} of {pageCount.toLocaleString()}
              </span>
              <button
                type="button"
                className="rounded border border-line px-3 py-1.5 disabled:opacity-40"
                disabled={page + 1 >= pageCount}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
