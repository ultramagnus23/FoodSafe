"use client";

import { useEffect, useState } from "react";

const DISMISS_KEY = "foodsafe_disclaimer_dismissed_at";
const REAPPEAR_MS = 24 * 60 * 60 * 1000;

const DEFAULT_TEXT =
  "Statistical estimates based on public enforcement records. Not a product test. " +
  "Not medical advice. Geographic framing: does not name or evaluate specific brands.";

// Sticky banner, appears on every risk-displaying page. Dismissable per
// session but re-appears after 24 hours — never permanently hideable.
export function DisclaimerBanner({ text }: { text?: string }) {
  const [dismissed, setDismissed] = useState(true); // default hidden until we check localStorage (avoids SSR flash)

  useEffect(() => {
    try {
      const last = localStorage.getItem(DISMISS_KEY);
      const stillFresh = last && Date.now() - Number(last) < REAPPEAR_MS;
      setDismissed(!!stillFresh);
    } catch {
      setDismissed(false);
    }
  }, []);

  if (dismissed) return null;

  return (
    <div className="disclaimer sticky top-0 z-40 flex items-start justify-between gap-3">
      <span>
        <strong>Disclaimer. </strong>
        {text || DEFAULT_TEXT}
      </span>
      <button
        type="button"
        className="shrink-0 text-xs underline"
        onClick={() => {
          try {
            localStorage.setItem(DISMISS_KEY, String(Date.now()));
          } catch {
            /* ignore */
          }
          setDismissed(true);
        }}
      >
        Dismiss
      </button>
    </div>
  );
}
