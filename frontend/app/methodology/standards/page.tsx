"use client";

import { useAuth } from "@/lib/auth-context";
import { useStandardsTable } from "@/lib/api/compare";
import { cap } from "@/lib/constants";

export default function StandardsPage() {
  const { token, openAuth } = useAuth();
  const loggedIn = !!token;
  const table = useStandardsTable(loggedIn);

  return (
    <div className="mx-auto max-w-3xl px-6 py-12">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-ink">India vs. World</div>
      <h1 className="mb-4 font-display text-4xl font-light leading-tight">FSSAI vs. Codex Alimentarius</h1>
      <p className="mb-8 leading-relaxed text-provenance">
        For every contaminant tracked, FoodSafe compares India&apos;s FSSAI limit against the Codex Alimentarius
        international standard and the EU limit where available. A ratio above 1× means FSSAI&apos;s limit is more
        permissive than the international benchmark, sorted below by the size of that gap.
      </p>

      {!loggedIn ? (
        <div className="rounded-xl bg-provenance-pale p-10 text-center">
          <p className="mb-4 font-medium text-ink">Sign in to view the benchmark table.</p>
          <button type="button" onClick={openAuth} className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-on-ink">
            Sign In →
          </button>
        </div>
      ) : table.isLoading ? (
        <p className="text-provenance">Loading…</p>
      ) : !table.data || table.data.length === 0 ? (
        <p className="text-provenance">No benchmark data available.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-porcelain text-left text-xs uppercase tracking-wide text-provenance">
                <th className="px-4 py-3">Contaminant</th>
                <th className="px-4 py-3">FSSAI Limit</th>
                <th className="px-4 py-3">Codex Limit</th>
                <th className="px-4 py-3">EU Limit</th>
                <th className="px-4 py-3">Ratio (FSSAI/Codex)</th>
              </tr>
            </thead>
            <tbody>
              {table.data.map((r) => (
                <tr key={r.contaminant_id} className="border-t border-line">
                  <td className="px-4 py-3 font-medium">{cap(r.contaminant_name.replace(/_/g, " "))}</td>
                  <td className="px-4 py-3 font-mono">{r.fssai_limit_ppb} PPB</td>
                  <td className="px-4 py-3 font-mono">{r.codex_limit_ppb} PPB</td>
                  <td className="px-4 py-3 font-mono">{r.eu_limit_ppb != null ? `${r.eu_limit_ppb} PPB` : "—"}</td>
                  <td className="px-4 py-3">
                    {r.fssai_vs_codex_ratio != null && (
                      <span
                        className={`font-mono ${r.fssai_vs_codex_ratio > 1 ? "text-risk" : "text-clear"}`}
                      >
                        {r.fssai_vs_codex_ratio.toFixed(1)}×
                        {r.fssai_vs_codex_ratio > 1 ? " more permissive" : ""}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="disclaimer mt-8">
        <strong>Note. </strong>
        Limits shown are per-commodity food safety MRLs (maximum residue limits) as tracked in FoodSafe&apos;s
        reference data; the exact commodity a limit applies to may vary. See individual district pages for
        commodity-specific benchmark interpretations.
      </div>
    </div>
  );
}
