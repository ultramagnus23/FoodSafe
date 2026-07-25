"use client";

import { useState, useEffect, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useSearch } from "@/lib/api/search";
import { fmt } from "@/lib/constants";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";

function SearchInner() {
  const searchParams = useSearchParams();
  const { token, openAuth } = useAuth();
  const loggedIn = !!token;
  const [query, setQuery] = useState(searchParams.get("q") || "");
  const [debounced, setDebounced] = useState(query);

  // 300ms debounce
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query), 300);
    return () => clearTimeout(t);
  }, [query]);

  const results = useSearch(debounced, loggedIn);

  const looksLikeBrand = /\b(atta|rice|oil|dal|ghee)\b/i.test(query) && /^[A-Z]/.test(query.trim());

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="mb-6 font-display text-4xl font-light">Search</h1>
      <input
        className="mb-6 w-full rounded-lg border border-line bg-slab px-4 py-3 outline-none focus:border-ink"
        placeholder="Search commodity, district, or contaminant…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />

      {looksLikeBrand && (
        <div className="disclaimer mb-6">
          FoodSafe tracks geographic sourcing regions, not individual brands. Try searching for a commodity or
          district instead.
        </div>
      )}

      {!loggedIn ? (
        <div className="rounded-xl bg-provenance-pale p-10 text-center">
          <p className="mb-4 font-medium text-ink">Sign in to search live data.</p>
          <button type="button" onClick={openAuth} className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-on-ink">
            Sign In →
          </button>
        </div>
      ) : !debounced ? (
        <p className="text-provenance">Start typing to search commodities, districts, and contaminants.</p>
      ) : results.isLoading ? (
        <p className="text-provenance">Searching…</p>
      ) : !results.data || results.data.length === 0 ? (
        <p className="text-provenance">No results for &ldquo;{debounced}&rdquo;.</p>
      ) : (
        <div className="grid gap-3">
          {results.data.map((r, i) => (
            <div key={i} className="rounded-lg border border-line bg-slab p-4">
              <div className="flex items-center justify-between">
                <div>
                  <span className="mr-2 rounded bg-provenance-pale px-2 py-0.5 text-[11px] uppercase text-ink">
                    {r.type}
                  </span>
                  <span className="font-medium">{r.name}</span>
                </div>
                {r.risk_score != null && <span className="font-mono text-sm">{fmt(r.risk_score, 0)}</span>}
              </div>
              <div className="mt-2 flex items-center gap-2">
                {r.n_tests != null && <span className="text-xs text-provenance">{r.n_tests} tests</span>}
                <ProvenanceBadge provenance={r.provenance} compact />
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="mt-10 border-t border-line pt-6 text-sm text-provenance">
        Looking for a specific place? Try the <Link href="/map" className="text-ink underline">risk map</Link>.
      </div>
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense fallback={null}>
      <SearchInner />
    </Suspense>
  );
}
