"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { snapshotStamp, useSnapshot } from "@/lib/snapshot";

// Building blocks for the pages that render the daily data snapshot. Same register as the
// rest of the app: hairline tables, mono figures, one accent per state (clear/caution/risk).

export function PageHeader({ kicker, title, children }: { kicker: string; title: string; children?: ReactNode }) {
  return (
    <header className="mb-10">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-ink">{kicker}</div>
      <h1 className="mb-4 font-display text-3xl font-light leading-tight sm:text-4xl">{title}</h1>
      {children ? <div className="max-w-prose space-y-3 leading-relaxed text-provenance">{children}</div> : null}
    </header>
  );
}

export function Section({ id, title, note, children }: { id?: string; title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-20 border-t border-line py-10 first:border-t-0 first:pt-0">
      <h2 className="mb-2 font-display text-2xl font-light">{title}</h2>
      {note ? <p className="mb-5 max-w-prose text-sm leading-relaxed text-provenance">{note}</p> : null}
      {children}
    </section>
  );
}

export function Page({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return <div className={`mx-auto px-4 py-12 sm:px-6 ${wide ? "max-w-6xl" : "max-w-5xl"}`}>{children}</div>;
}

type Tone = "neutral" | "clear" | "caution" | "risk";
const TONE: Record<Tone, string> = {
  neutral: "border-line text-provenance",
  clear: "border-clear bg-clear-pale text-clear",
  caution: "border-caution bg-caution-pale text-caution",
  risk: "border-risk bg-risk-pale text-risk",
};

export function Tag({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`ml-1 inline-block whitespace-nowrap rounded border px-1.5 py-px align-middle text-[11px] font-medium ${TONE[tone]}`}>
      {children}
    </span>
  );
}

export function Stat({ value, label, href }: { value: ReactNode; label: string; href?: string }) {
  const body = (
    <>
      <div className="register mb-1 text-2xl font-medium text-ink">{value ?? "—"}</div>
      <div className="text-xs leading-snug text-provenance">{label}</div>
    </>
  );
  return href ? (
    <Link href={href} className="block rounded-lg border border-line bg-slab p-4 transition-colors hover:border-line-strong">
      {body}
    </Link>
  ) : (
    <div className="rounded-lg border border-line bg-slab p-4">{body}</div>
  );
}

export interface BarRow {
  key: string;
  label: ReactNode;
  sub?: ReactNode;
  value: number;
  display: string;
}

export function Bars({ rows, max, empty = "Nothing recorded for this selection." }: { rows: BarRow[]; max?: number; empty?: string }) {
  if (!rows.length) return <p className="py-4 text-sm text-provenance">{empty}</p>;
  const top = max ?? Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="space-y-2.5">
      {rows.map((r) => (
        <div key={r.key} className="grid grid-cols-[minmax(0,1fr)_minmax(80px,2fr)_auto] items-center gap-3 text-sm sm:grid-cols-[minmax(0,2fr)_minmax(120px,3fr)_auto]">
          <div className="min-w-0">
            <div className="truncate text-ink" title={typeof r.label === "string" ? r.label : undefined}>
              {r.label}
            </div>
            {r.sub ? <div className="truncate text-xs text-provenance">{r.sub}</div> : null}
          </div>
          <div className="h-2.5 overflow-hidden rounded-sm bg-provenance-pale" aria-hidden="true">
            <div className="h-full origin-left bg-ink opacity-70" style={{ transform: `scaleX(${Math.max(0.004, r.value / top)})` }} />
          </div>
          <div className="register w-16 text-right text-xs text-ink">{r.display}</div>
        </div>
      ))}
    </div>
  );
}

export function LoadState({ error, loading, what }: { error?: unknown; loading?: boolean; what: string }) {
  if (error) {
    return (
      <p className="rounded-md border border-risk bg-risk-pale px-4 py-3 text-sm text-risk">
        Could not load {what}: {error instanceof Error ? error.message : String(error)}. The rest of the page still works.
      </p>
    );
  }
  if (loading) return <p className="py-4 text-sm text-provenance">Loading {what}…</p>;
  return null;
}

export function SnapshotNote() {
  const meta = useSnapshot("meta");
  return (
    <p className="register text-xs text-provenance">
      {meta.data ? `Data snapshot ${snapshotStamp(meta.data)}, rebuilt daily from the production database.` : "Loading snapshot…"}
    </p>
  );
}

export function Table({ children, minWidth = 640, caption }: { children: ReactNode; minWidth?: number; caption?: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full text-sm" style={{ minWidth }}>
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        {children}
      </table>
    </div>
  );
}

export function Th({ children, right = false }: { children?: ReactNode; right?: boolean }) {
  return <th className={`bg-porcelain px-3 py-3 text-xs font-semibold uppercase tracking-wide text-provenance ${right ? "text-right" : "text-left"}`}>{children}</th>;
}

export function Td({ children, right = false, className = "" }: { children?: ReactNode; right?: boolean; className?: string }) {
  return <td className={`border-t border-line px-3 py-2.5 align-top ${right ? "register text-right" : ""} ${className}`}>{children}</td>;
}

export function Chips<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: [T, string][];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap overflow-hidden rounded-md border border-line">
      {options.map(([v, text]) => (
        <button
          key={v}
          type="button"
          aria-pressed={value === v}
          onClick={() => onChange(v)}
          className={`px-3 py-1.5 text-sm ${value === v ? "bg-ink text-on-ink" : "bg-porcelain text-ink hover:bg-provenance-pale"}`}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="text-xs text-provenance">
      <span className="mb-1 block font-semibold uppercase tracking-wide">{label}</span>
      {children}
    </label>
  );
}

export const inputClass = "rounded-md border border-line bg-porcelain px-3 py-2 text-sm text-ink";
