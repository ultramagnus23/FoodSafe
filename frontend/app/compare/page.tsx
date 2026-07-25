"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useCompareDistricts, useBestDistricts } from "@/lib/api/compare";
import { useDistricts } from "@/lib/api/search";
import { COMMODITIES, fmt, cap } from "@/lib/constants";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";

function DeltaTag({ value, higherIsWorse = true }: { value: number | null; higherIsWorse?: boolean }) {
  if (value == null || value === 0) return <span className="text-xs text-provenance">no difference</span>;
  const bad = higherIsWorse ? value > 0 : value < 0;
  return (
    <span className={`text-xs font-mono ${bad ? "text-risk" : "text-clear"}`}>
      {value > 0 ? "+" : ""}
      {value.toFixed(2)}
    </span>
  );
}

function CompareInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { token, openAuth } = useAuth();
  const loggedIn = !!token;
  const mode = searchParams.get("mode");

  const [commodityId, setCommodityId] = useState(Number(searchParams.get("commodity")) || 1);
  const [districtA, setDistrictA] = useState(Number(searchParams.get("a")) || 0);
  const [districtB, setDistrictB] = useState(Number(searchParams.get("b")) || 0);

  const districts = useDistricts(loggedIn);
  const compare = useCompareDistricts(districtA, districtB, commodityId, loggedIn && !mode);
  const best = useBestDistricts(commodityId, loggedIn && mode === "best");

  if (!loggedIn) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-20 text-center">
        <p className="mb-4 font-medium text-ink">Sign in to compare districts.</p>
        <button type="button" onClick={openAuth} className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-on-ink">
          Sign In →
        </button>
      </div>
    );
  }

  if (mode === "best") {
    return (
      <div className="mx-auto max-w-3xl px-6 py-10">
        <h1 className="mb-2 font-display text-4xl font-light">Best Districts</h1>
        <p className="mb-2 text-provenance">Lowest-risk districts for a commodity, ranked by computed risk score.</p>
        <div className="disclaimer mb-6">
          This ranking is a statistical estimate, not a safety certification. Where the badge below reads
          &ldquo;Demo data&rdquo;, the underlying enforcement records are synthetic. See{" "}
          <a href="/methodology" className="underline">methodology</a>.
        </div>
        <select
          className="mb-6 rounded-lg border border-line bg-slab px-3 py-2 text-sm"
          value={commodityId}
          onChange={(e) => router.push(`/compare?mode=best&commodity=${e.target.value}`)}
        >
          {COMMODITIES.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        {best.isLoading ? (
          <p className="text-provenance">Loading…</p>
        ) : !best.data || best.data.length === 0 ? (
          <p className="text-provenance">No districts with sufficient data for this commodity yet.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-line">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-porcelain text-left text-xs uppercase tracking-wide text-provenance">
                  <th className="px-4 py-3">#</th>
                  <th className="px-4 py-3">District</th>
                  <th className="px-4 py-3">Risk</th>
                  <th className="px-4 py-3">Tests</th>
                  <th className="px-4 py-3">Source</th>
                </tr>
              </thead>
              <tbody>
                {best.data.map((d, i) => (
                  <tr key={d.district_id} className="cursor-pointer border-t border-line hover:bg-porcelain" onClick={() => router.push(`/district/${d.district_id}?commodity=${commodityId}`)}>
                    <td className="px-4 py-3 text-provenance">{i + 1}</td>
                    <td className="px-4 py-3 font-medium">
                      {d.district_name}, {d.state}
                    </td>
                    <td className="px-4 py-3 font-mono text-clear">{fmt(d.risk_score, 0)}</td>
                    <td className="px-4 py-3 font-mono text-xs">{d.n_tests}</td>
                    <td className="px-4 py-3">
                      <ProvenanceBadge provenance={d.provenance} compact />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="mb-2 font-display text-4xl font-light">Compare Districts</h1>
      <p className="mb-6 text-provenance">Side-by-side risk comparison for the same commodity across two districts.</p>

      <div className="mb-6 flex flex-wrap gap-3">
        <select className="rounded-lg border border-line bg-slab px-3 py-2 text-sm" value={commodityId} onChange={(e) => setCommodityId(Number(e.target.value))}>
          {COMMODITIES.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <select className="rounded-lg border border-line bg-slab px-3 py-2 text-sm" value={districtA} onChange={(e) => setDistrictA(Number(e.target.value))}>
          <option value={0}>District A…</option>
          {(districts.data || []).map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}, {d.state}
            </option>
          ))}
        </select>
        <select className="rounded-lg border border-line bg-slab px-3 py-2 text-sm" value={districtB} onChange={(e) => setDistrictB(Number(e.target.value))}>
          <option value={0}>District B…</option>
          {(districts.data || []).map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}, {d.state}
            </option>
          ))}
        </select>
      </div>

      {!districtA || !districtB ? (
        <p className="text-provenance">Select two districts to compare.</p>
      ) : compare.isLoading ? (
        <p className="text-provenance">Loading…</p>
      ) : compare.isError || !compare.data ? (
        <p className="text-provenance">Could not load comparison.</p>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {[compare.data.a, compare.data.b].map((d) => (
            <div key={d.district_id} className="rounded-lg border border-line bg-slab p-6">
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="font-semibold">
                  {d.district_name}, {d.state}
                </span>
                <ProvenanceBadge provenance={d.provenance} compact />
              </div>
              <div className="mb-3 font-display text-3xl font-semibold text-ink">{fmt(d.risk_score, 0)}</div>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-provenance">Fail rate</span>
                  <span className="font-mono">{d.fail_rate != null ? `${(d.fail_rate * 100).toFixed(1)}%` : "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-provenance">Codex compliant</span>
                  <span className="font-mono">{d.codex_compliant_fraction != null ? `${(d.codex_compliant_fraction * 100).toFixed(0)}%` : "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-provenance">Tests</span>
                  <span className="font-mono">{d.n_tests}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {compare.data && (
        <div className="mt-4 rounded-lg border border-line bg-porcelain p-4 text-sm">
          <span className="mr-2 text-provenance">Δ risk score (A − B):</span>
          <DeltaTag value={compare.data.delta.risk_score_delta} higherIsWorse={true} />
        </div>
      )}

      <div className="disclaimer mt-8">{compare.data?.disclaimer || "Statistical estimates based on public enforcement records. Not a verdict on any specific brand."}</div>
    </div>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={null}>
      <CompareInner />
    </Suspense>
  );
}
