interface ProvenanceStep {
  label: string;
  detail: string;
  timestamp?: string;
  /** A mono figure worth calling out — a credibility score, a hash, a page number. */
  value?: string;
}

// The trust feature: original document -> extraction -> credibility score,
// as a vertical ruled sequence. A real structural timeline connector (1px),
// not a decorative accent stripe.
export function ProvenanceTrail({ steps }: { steps: ProvenanceStep[] }) {
  return (
    <ol className="ml-1.5 border-l border-line pl-5">
      {steps.map((s, i) => (
        <li key={i} className="relative pb-5 last:pb-0">
          <span className="absolute -left-[25px] top-1 h-2 w-2 rounded-full border border-line bg-slab" />
          <div className="register text-[11px] uppercase tracking-wide text-provenance">
            {s.label}
            {s.timestamp && <span> · {s.timestamp}</span>}
          </div>
          <div className="mt-0.5 text-sm text-ink">{s.detail}</div>
          {s.value && <div className="register mt-0.5 text-xs text-provenance">{s.value}</div>}
        </li>
      ))}
    </ol>
  );
}

export type { ProvenanceStep };
