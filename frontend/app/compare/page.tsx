"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useCompareDistricts, useBestDistricts } from "@/lib/api/compare";
import { useDistricts } from "@/lib/api/search";
import { COMMODITIES, fmt, cap } from "@/lib/constants";

function DeltaTag({ value, higherIsWorse = true }: { value: number | null; higherIsWorse?: boolean }) {
  if (value == null || value === 0) return <span className="text-xs text-muted">no difference</span>;
  const bad = higherIsWorse ? value > 0 : value < 0;
  return (
    <span className={`text-xs font-mono ${bad ? "text-red" : "text-sage"}`}>
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
        <p className="mb-4 font-medium text-forest">Sign in to compare districts.</p>
        <button type="button" onClick={openAuth} className="rounded-md bg-forest px-4 py-2 text-sm font-medium text-white">
          Sign In →
        </button>
      </div>
    );
  }

  if (mode === "best") {
    return (
      <div className="mx-auto max-w-3xl px-6 py-10">
        <h1 className="mb-2 font-serif text-4xl font-light">Best Districts</h1>
        <p className="mb-6 text-muted">Lowest-risk districts for a commodity, ranked by computed risk score.</p>
        <select
          className="mb-6 rounded-lg border border-border bg-bg-card px-3 py-2 text-sm"
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
          <p className="text-muted">Loading…</p>
        ) : !best.data || best.data.length === 0 ? (
          <p className="text-muted">No districts with sufficient data for this commodity yet.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-bg text-left text-xs uppercase tracking-wide text-muted">
                  <th className="px-4 py-3">#</th>
                  <th className="px-4 py-3">District</th>
                  <th className="px-4 py-3">Risk</th>
                  <th className="px-4 py-3">Tests</th>
                </tr>
              </thead>
              <tbody>
                {best.data.map((d, i) => (
                  <tr key={d.district_id} className="cursor-pointer border-t border-border hover:bg-bg" onClick={() => router.push(`/district/${d.district_id}?commodity=${commodityId}`)}>
                    <td className="px-4 py-3 text-muted">{i + 1}</td>
                    <td className="px-4 py-3 font-medium">
                      {d.district_name}, {d.state}
                    </td>
                    <td className="px-4 py-3 font-mono text-sage">{fmt(d.risk_score, 0)}</td>
                    <td className="px-4 py-3 font-mono text-xs">{d.n_tests}</td>
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
      <h1 className="mb-2 font-serif text-4xl font-light">Compare Districts</h1>
      <p className="mb-6 text-muted">Side-by-side risk comparison for the same commodity across two districts.</p>

      <div className="mb-6 flex flex-wrap gap-3">
        <select className="rounded-lg border border-border bg-bg-card px-3 py-2 text-sm" value={commodityId} onChange={(e) => setCommodityId(Number(e.target.value))}>
          {COMMODITIES.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <select className="rounded-lg border border-border bg-bg-card px-3 py-2 text-sm" value={districtA} onChange={(e) => setDistrictA(Number(e.target.value))}>
          <option value={0}>District A…</option>
          {(districts.data || []).map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}, {d.state}
            </option>
          ))}
        </select>
        <select className="rounded-lg border border-border bg-bg-card px-3 py-2 text-sm" value={districtB} onChange={(e) => setDistrictB(Number(e.target.value))}>
          <option value={0}>District B…</option>
          {(districts.data || []).map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}, {d.state}
            </option>
          ))}
        </select>
      </div>

      {!districtA || !districtB ? (
        <p className="text-muted">Select two districts to compare.</p>
      ) : compare.isLoading ? (
        <p className="text-muted">Loading…</p>
      ) : compare.isError || !compare.data ? (
        <p className="text-muted">Could not load comparison.</p>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {[compare.data.a, compare.data.b].map((d) => (
            <div key={d.district_id} className="rounded-lg border border-border bg-bg-card p-6">
              <div className="mb-1 font-semibold">
                {d.district_name}, {d.state}
              </div>
              <div className="mb-3 font-serif text-3xl font-semibold text-forest">{fmt(d.risk_score, 0)}</div>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted">Fail rate</span>
                  <span className="font-mono">{d.fail_rate != null ? `${(d.fail_rate * 100).toFixed(1)}%` : "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Codex compliant</span>
                  <span className="font-mono">{d.codex_compliant_fraction != null ? `${(d.codex_compliant_fraction * 100).toFixed(0)}%` : "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Tests</span>
                  <span className="font-mono">{d.n_tests}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {compare.data && (
        <div className="mt-4 rounded-lg border border-border bg-bg p-4 text-sm">
          <span className="mr-2 text-muted">Δ risk score (A − B):</span>
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
