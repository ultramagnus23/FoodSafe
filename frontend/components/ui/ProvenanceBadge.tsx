interface ProvenanceSummary {
  real_count: number;
  synthetic_count: number;
  synthetic_fraction: number | null;
  is_synthetic: boolean;
}

interface ProvenanceBadgeProps {
  provenance?: ProvenanceSummary | null;
  compact?: boolean;
}

// Every risk score, alert, search result, and map marker must carry this.
// Synthetic-demo data (pipeline/seed_enforcement.py, etl_version='seed-demo')
// stands in for FSSAI enforcement records that don't exist as an open
// dataset yet — this badge is the one place that fact can't be missed.
// Never render this only on hover: the badge itself must be visible.
export function ProvenanceBadge({ provenance, compact = false }: ProvenanceBadgeProps) {
  if (!provenance || (provenance.real_count === 0 && provenance.synthetic_count === 0)) {
    return (
      <span
        className="inline-flex rounded px-2.5 py-1 text-xs font-medium"
        style={{ background: "var(--provenance-pale)", color: "var(--provenance)" }}
      >
        No data
      </span>
    );
  }

  if (provenance.is_synthetic) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded px-2.5 py-1 text-xs font-medium"
        style={{ background: "var(--caution-pale)", color: "var(--caution)" }}
        title="This figure is computed from synthetic demonstration data standing in for FSSAI enforcement records, which are not available as an open dataset today. See /methodology."
      >
        Demo data
        {!compact && provenance.real_count > 0 && (
          <span className="register opacity-80">
            ({provenance.real_count} real / {provenance.synthetic_count} synthetic)
          </span>
        )}
      </span>
    );
  }

  return (
    <span
      className="inline-flex rounded px-2.5 py-1 text-xs font-medium"
      style={{ background: "var(--clear-pale)", color: "var(--clear)" }}
      title={`Based on ${provenance.real_count} real enforcement record${provenance.real_count === 1 ? "" : "s"}.`}
    >
      Verified source
    </span>
  );
}

export type { ProvenanceSummary };
