"use client";

import { useState, useEffect, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useSearch } from "@/lib/api/search";
import { fmt } from "@/lib/constants";

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
      <h1 className="mb-6 font-serif text-4xl font-light">Search</h1>
      <input
        className="mb-6 w-full rounded-lg border border-border bg-bg-card px-4 py-3 outline-none focus:border-forest"
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
        <div className="rounded-xl bg-forest-pale p-10 text-center">
          <p className="mb-4 font-medium text-forest">Sign in to search live data.</p>
          <button type="button" onClick={openAuth} className="rounded-md bg-forest px-4 py-2 text-sm font-medium text-white">
            Sign In →
          </button>
        </div>
      ) : !debounced ? (
        <p className="text-muted">Start typing to search commodities, districts, and contaminants.</p>
      ) : results.isLoading ? (
        <p className="text-muted">Searching…</p>
      ) : !results.data || results.data.length === 0 ? (
        <p className="text-muted">No results for &ldquo;{debounced}&rdquo;.</p>
      ) : (
        <div className="grid gap-3">
          {results.data.map((r, i) => (
            <div key={i} className="rounded-lg border border-border bg-bg-card p-4">
              <div className="flex items-center justify-between">
                <div>
                  <span className="mr-2 rounded bg-forest-pale px-2 py-0.5 text-[11px] uppercase text-forest">
                    {r.type}
                  </span>
                  <span className="font-medium">{r.name}</span>
                </div>
                {r.risk_score != null && <span className="font-mono text-sm">{fmt(r.risk_score, 0)}</span>}
              </div>
              {r.n_tests != null && <div className="mt-1 text-xs text-muted">{r.n_tests} tests</div>}
            </div>
          ))}
        </div>
      )}

      <div className="mt-10 border-t border-border pt-6 text-sm text-muted">
        Looking for a specific place? Try the <Link href="/map" className="text-forest underline">risk map</Link>.
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
