"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { useAuth } from "@/lib/auth-context";
import { useMapData, useMapQuarters } from "@/lib/api/risk";
import { TimeScrubber } from "@/components/TimeScrubber";

const LeafletMap = dynamic(() => import("@/components/LeafletMap"), { ssr: false });

const LEDGER = [
  {
    step: "Source",
    detail:
      "FSSAI enforcement reports, USFDA import refusals, and AGMARKNET reference data are ingested on a daily schedule, each record keeping its original source URL.",
  },
  {
    step: "Verification",
    detail:
      "Every record gets a confidence score from lab tier, OCR quality, and typical-range checks. Only records above threshold feed the risk model. Records below it are marked, not discarded.",
  },
  {
    step: "Risk score",
    detail:
      "District and commodity risk scores are a statistical aggregation of fail rate over the trailing quarter, reported with a 95% confidence interval and a Codex Alimentarius comparison.",
  },
];

// Real known ingest sources (matches enforcement_records.source_type in the
// schema) — not a placeholder count.
const SOURCE_COUNT = 5;

export default function HomePage() {
  const router = useRouter();
  const { token, openAuth } = useAuth();
  const [query, setQuery] = useState("");
  const loggedIn = !!token;

  const quarters = useMapQuarters(1, loggedIn);
  const [quarter, setQuarter] = useState<string | undefined>(undefined);
  const mapState = useMapData(1, loggedIn, quarter);

  const districts = mapState.data || [];
  const coveredCount = districts.filter((d) => d.n_tests > 0).length;

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (query.trim()) router.push(`/search?q=${encodeURIComponent(query)}`);
  }

  return (
    <div>
      {/* Hero: signature scene. The map sits behind a solid (non-gradient)
          porcelain panel carrying the copy, and replays once through the
          real historical quarters on load. */}
      <div className="relative overflow-hidden border-b border-line">
        <div className="pointer-events-none absolute inset-0">
          {loggedIn ? (
            <div className="h-full w-full opacity-40">
              <LeafletMap points={districts} bare />
            </div>
          ) : null}
        </div>
        <div className="absolute inset-0 bg-porcelain/85" />

        <div className="relative mx-auto flex max-w-2xl flex-col items-center px-6 py-24 text-center">
          <h1 className="mb-5 font-display text-4xl font-light leading-tight sm:text-5xl">
            The public record for food safety in India.
          </h1>
          <p className="mb-8 max-w-lg text-provenance">
            FSSAI enforcement reports, USFDA import refusals, and lab results, turned into one sourced,
            confidence-scored record by district and commodity.
          </p>

          <form onSubmit={handleSearch} className="mb-6 flex w-full max-w-xl overflow-hidden rounded border border-line bg-slab shadow">
            <input
              className="flex-1 bg-transparent px-4 py-3 text-sm outline-none"
              placeholder="Search commodity, district, or contaminant"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <button type="submit" className="m-1.5 rounded bg-ink px-5 py-2 text-sm font-medium text-on-ink">
              Check risk
            </button>
          </form>

          {loggedIn && quarters.data && quarters.data.length > 1 && (
            <div className="w-full max-w-xs">
              <TimeScrubber
                quarters={quarters.data}
                value={quarter || quarters.data[quarters.data.length - 1]}
                onChange={setQuarter}
                autoPlayOnce
              />
            </div>
          )}

          {!loggedIn && (
            <button type="button" onClick={openAuth} className="rounded bg-ink px-5 py-2 text-sm font-medium text-on-ink">
              Sign in to see the live record
            </button>
          )}
        </div>
      </div>

      {/* Register line: one quiet mono line, not hero-metric cards. */}
      <div className="border-b border-line bg-slab px-6 py-3">
        <p className="register mx-auto max-w-5xl text-center text-xs text-provenance">
          {SOURCE_COUNT} sources tracked · {loggedIn && districts.length ? coveredCount : "—"} districts covered ·
          updated {quarter || quarters.data?.[quarters.data.length - 1] || "—"}
        </p>
      </div>

      {/* Ruled ledger: source -> verification -> risk score. */}
      <div className="mx-auto max-w-2xl px-6 py-20">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink">How a score is made</div>
        <h2 className="mb-10 font-display text-3xl font-light">A real sequence, not a black box</h2>
        <ol>
          {LEDGER.map((row, i) => (
            <li key={row.step} className="flex gap-5 border-t border-line py-6 first:border-t-0">
              <span className="register w-6 shrink-0 pt-0.5 text-sm text-provenance">{i + 1}</span>
              <div>
                <div className="mb-1 font-display text-lg font-normal text-ink">{row.step}</div>
                <p className="text-sm leading-relaxed text-provenance">{row.detail}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>

      {/* Methodology teaser */}
      <div className="border-t border-line bg-slab">
        <div className="mx-auto max-w-2xl px-6 py-12 text-center">
          <p className="mb-4 text-sm text-provenance">
            Trust products publish their methods. Ours covers confidence scoring, calibration status, and a
            published backtest, including where it fell short.
          </p>
          <a href="/methodology" className="text-sm font-medium text-ink underline">
            Read the full methodology →
          </a>
        </div>
      </div>
    </div>
  );
}
