// The atomic unit for any report/recall/test result — feeds, search
// results, district evidence panels all render the same component.
interface SpecimenCardProps {
  source: string;
  date: string;
  reference?: string | null;
  finding: string;
  /** Only set this from a genuine pass/fail determination — never from a
   *  guess. `null` renders a neutral state, not a false "clear". */
  outcome?: boolean | null;
  /** Data-quality confidence (0-1), not a risk signal — rendered as a
   *  segmented bar, never a dial or gauge. Omit if unscored. */
  confidence?: number | null;
  sourceUrl?: string | null;
}

function ConfidenceMeter({ value }: { value: number }) {
  const segments = 5;
  const filled = Math.round(value * segments);
  return (
    <div className="flex items-center gap-2" title={`Confidence ${(value * 100).toFixed(0)}%`}>
      <div className="flex gap-0.5">
        {Array.from({ length: segments }).map((_, i) => (
          <span
            key={i}
            className="h-2 w-2.5"
            style={{ background: i < filled ? "var(--ink)" : "var(--line)" }}
          />
        ))}
      </div>
      <span className="register text-[11px] text-provenance">{(value * 100).toFixed(0)}%</span>
    </div>
  );
}

export function SpecimenCard({ source, date, reference, finding, outcome, confidence, sourceUrl }: SpecimenCardProps) {
  const outcomeStyle =
    outcome === false
      ? { bg: "var(--risk-pale)", fg: "var(--risk)", label: "Fail" }
      : outcome === true
      ? { bg: "var(--clear-pale)", fg: "var(--clear)", label: "Pass" }
      : null;

  return (
    <div className="rounded border border-line bg-slab p-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="register flex items-center gap-2 text-[11px] uppercase tracking-wide text-provenance">
          <span>{source}</span>
          <span aria-hidden>·</span>
          <span>{date}</span>
          {reference && (
            <>
              <span aria-hidden>·</span>
              <span>{reference}</span>
            </>
          )}
        </div>
        {outcomeStyle && (
          <span
            className="rounded px-2 py-0.5 text-[11px] font-medium"
            style={{ background: outcomeStyle.bg, color: outcomeStyle.fg }}
          >
            {outcomeStyle.label}
          </span>
        )}
      </div>

      <p className="mb-3 text-sm leading-relaxed text-ink">{finding}</p>

      <div className="flex items-center justify-between gap-3">
        {confidence != null ? <ConfidenceMeter value={confidence} /> : <span />}
        {sourceUrl && (
          <a href={sourceUrl} target="_blank" rel="noreferrer" className="register text-[11px] text-provenance underline">
            Source document
          </a>
        )}
      </div>
    </div>
  );
}
