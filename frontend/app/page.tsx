"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { useAuth } from "@/lib/auth-context";
import { useMapData, useRiskAlerts } from "@/lib/api/risk";
import { fmt, cap } from "@/lib/constants";
import { SkeletonMapLegend } from "@/components/ui/Skeletons";

const LeafletMap = dynamic(() => import("@/components/LeafletMap"), { ssr: false });

export default function HomePage() {
  const router = useRouter();
  const { token, openAuth } = useAuth();
  const [query, setQuery] = useState("");
  const loggedIn = !!token;
  const mapState = useMapData(1, loggedIn);
  const alerts = useRiskAlerts(6, loggedIn);

  const districts = mapState.data || [];
  const totalTests = districts.reduce((s, d) => s + (d.n_tests || 0), 0);
  const stateCount = new Set(districts.map((d) => d.state)).size;

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (query.trim()) router.push(`/search?q=${encodeURIComponent(query)}`);
  }

  return (
    <div>
      {loggedIn && alerts.data && alerts.data.length > 0 && (
        <div className="overflow-hidden bg-forest py-2.5 text-white">
          <div className="flex animate-[ticker_30s_linear_infinite] gap-16 whitespace-nowrap">
            {[...alerts.data, ...alerts.data].map((a, i) => (
              <span key={i} className="inline-flex items-center gap-2 text-sm">
                <span className="h-1.5 w-1.5 rounded-full bg-red" />
                <strong>{cap(a.commodity)}</strong> · {cap((a.contaminant || "").replace(/_/g, " "))} ·{" "}
                {a.state || a.district || "—"}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="flex min-h-[80vh] flex-col items-center justify-center px-6 py-16 text-center">
        <span className="mb-6 inline-flex items-center gap-1.5 rounded-full bg-forest-pale px-3 py-1 text-xs font-medium uppercase tracking-wide text-forest">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-sage" />
          Real enforcement data · FSSAI · USFDA
        </span>
        <h1 className="mb-5 max-w-3xl font-serif text-5xl font-light leading-tight sm:text-6xl">
          Know what&apos;s in your food.
          <br />
          <em className="text-forest not-italic italic">Before you eat it.</em>
        </h1>
        <p className="mb-10 max-w-lg text-muted">
          India&apos;s food contamination and disease-burden intelligence platform — mapping risk by geography,
          commodity, and international standards using public enforcement data.
        </p>
        <form onSubmit={handleSearch} className="flex w-full max-w-xl overflow-hidden rounded-xl border border-border bg-bg-card shadow-lg">
          <input
            className="flex-1 bg-transparent px-5 py-4 outline-none"
            placeholder="Search commodity, district, or contaminant…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit" className="m-1.5 rounded-lg bg-forest px-6 py-2.5 text-sm font-medium text-white">
            Check Risk →
          </button>
        </form>

        <div className="mt-14 flex flex-wrap justify-center gap-10 border-t border-border pt-10">
          {[
            { n: loggedIn && districts.length ? totalTests.toLocaleString() : "—", l: "Rice Tests Scored" },
            { n: loggedIn && districts.length ? String(districts.length) : "—", l: "Districts Scored" },
            { n: loggedIn && districts.length ? String(stateCount) : "—", l: "States & UTs" },
            { n: "9", l: "Contaminants Tracked" },
          ].map((s) => (
            <div key={s.l} className="text-center">
              <div className="font-serif text-4xl font-semibold text-forest">{s.n}</div>
              <div className="mt-1 text-xs uppercase tracking-wide text-muted">{s.l}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="mx-auto max-w-5xl px-6 py-20">
        <div className="mb-10">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-forest">Risk Heatmap</div>
          <h2 className="font-serif text-3xl font-light">
            Contamination risk across <em className="text-forest">India</em>
          </h2>
        </div>
        {loggedIn ? (
          mapState.isLoading ? (
            <SkeletonMapLegend />
          ) : (
            <LeafletMap points={districts} onDistrictClick={(id) => router.push(`/district/${id}?commodity=1`)} />
          )
        ) : (
          <div className="rounded-xl bg-forest-pale p-12 text-center">
            <p className="mb-4 font-medium text-forest">Sign in to load the live risk heatmap.</p>
            <button type="button" onClick={openAuth} className="rounded-md bg-forest px-4 py-2 text-sm font-medium text-white">
              Sign In →
            </button>
          </div>
        )}
        <div className="mt-4 flex flex-wrap gap-6 text-sm text-muted">
          {[
            { c: "var(--sage)", l: "Low Risk (0–35)" },
            { c: "var(--amber)", l: "Moderate (35–60)" },
            { c: "var(--red)", l: "Elevated (60+)" },
          ].map(({ c, l }) => (
            <div key={l} className="flex items-center gap-2">
              <div className="h-2.5 w-2.5 rounded-full" style={{ background: c }} />
              {l}
            </div>
          ))}
        </div>
      </div>

      {loggedIn && districts.length > 0 && (
        <div className="mx-auto max-w-5xl px-6 pb-20">
          <div className="mb-6">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-forest">Latest Scores</div>
            <h2 className="font-serif text-3xl font-light">
              District risk scores — <em className="text-forest">Rice</em>
            </h2>
          </div>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-bg text-left text-xs uppercase tracking-wide text-muted">
                  <th className="px-4 py-3">District</th>
                  <th className="px-4 py-3">State</th>
                  <th className="px-4 py-3">Risk</th>
                  <th className="px-4 py-3">Tests</th>
                </tr>
              </thead>
              <tbody>
                {districts
                  .slice()
                  .sort((a, b) => (b.risk_score || 0) - (a.risk_score || 0))
                  .slice(0, 20)
                  .map((d) => (
                    <tr
                      key={d.district_id}
                      className="cursor-pointer border-t border-border hover:bg-bg"
                      onClick={() => router.push(`/district/${d.district_id}?commodity=1`)}
                    >
                      <td className="px-4 py-3 font-medium">{d.district_name}</td>
                      <td className="px-4 py-3">{d.state}</td>
                      <td className="px-4 py-3 font-mono">{fmt(d.risk_score, 0)}</td>
                      <td className="px-4 py-3 font-mono text-xs">{d.n_tests}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
