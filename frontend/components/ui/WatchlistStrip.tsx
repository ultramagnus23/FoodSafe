import Link from "next/link";

interface WatchlistItem {
  id: string | number;
  name: string;
  href: string;
  riskState: "clear" | "caution" | "risk" | null;
}

const STATE_COLOR: Record<string, string> = {
  clear: "var(--clear)",
  caution: "var(--caution)",
  risk: "var(--risk)",
};

// User-pinned districts/products as a compact rail. Risk-state changes
// transition color on the chip itself — a plain CSS transition on
// background-color, never a pulse or repeating animation.
export function WatchlistStrip({ items }: { items: WatchlistItem[] }) {
  if (items.length === 0) {
    return (
      <p className="text-sm text-provenance">Pin your district to start your watchlist.</p>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item) => (
        <Link
          key={item.id}
          href={item.href}
          className="flex items-center gap-2 rounded border border-line bg-slab px-3 py-1.5 text-sm text-ink transition-colors hover:border-line-strong"
        >
          <span
            className="h-2 w-2 rounded-full transition-colors duration-500"
            style={{ background: item.riskState ? STATE_COLOR[item.riskState] : "var(--provenance)" }}
          />
          {item.name}
        </Link>
      ))}
    </div>
  );
}

export type { WatchlistItem };
