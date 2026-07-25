interface PAFDisplayProps {
  paf: number | null;
  ci: [number, number] | null;
  disease: string;
  attributableCasesPer100k?: number | null;
}

// PAF must never render without its confidence interval — a bare percentage
// implies more precision than a Monte Carlo estimate over sparse enforcement
// records actually has.
export function PAFDisplay({ paf, ci, disease, attributableCasesPer100k }: PAFDisplayProps) {
  if (paf == null) {
    return (
      <p className="text-sm text-provenance">
        Threshold contaminant: no single PAF. See hazard quotient instead.
      </p>
    );
  }
  const pct = (paf * 100).toFixed(2);
  const lo = ci ? (ci[0] * 100).toFixed(2) : null;
  const hi = ci ? (ci[1] * 100).toFixed(2) : null;

  return (
    <div title="PAF = Population Attributable Fraction. This is a statistical model estimate, not a diagnosis.">
      <p className="text-sm leading-relaxed">
        <span className="font-display text-2xl font-semibold text-ink">{pct}%</span> of {disease.toLowerCase()}{" "}
        cases in this district are estimated to be attributable to dietary exposure
        {lo && hi && (
          <span className="ml-1 font-mono text-xs text-provenance">(95% CI: {lo}%–{hi}%)</span>
        )}
      </p>
      {attributableCasesPer100k != null && (
        <p className="mt-1 text-xs text-provenance">
          ≈ {attributableCasesPer100k.toFixed(2)} estimated attributable cases / 100,000 population
        </p>
      )}
    </div>
  );
}
