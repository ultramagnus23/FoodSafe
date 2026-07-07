// Ported from index.html's riskColor()/RiskBadge logic.
export function riskColor(score: number | null): "low" | "mid" | "high" | "" {
  if (score == null) return "";
  if (score >= 60) return "high";
  if (score >= 35) return "mid";
  return "low";
}

export function riskLabel(score: number | null): string {
  if (score == null) return "No Data";
  if (score >= 60) return "Elevated Risk";
  if (score >= 35) return "Moderate Risk";
  return "Low Risk";
}

// The 3-step risk scale: clear / caution / risk. `risk` (vermilion) is
// reserved for genuine risk states only — never used decoratively.
const COLOR_STYLES: Record<string, { bg: string; fg: string }> = {
  low: { bg: "var(--clear-pale)", fg: "var(--clear)" },
  mid: { bg: "var(--caution-pale)", fg: "var(--caution)" },
  high: { bg: "var(--risk-pale)", fg: "var(--risk)" },
  "": { bg: "var(--provenance-pale)", fg: "var(--provenance)" },
};

interface RiskBadgeProps {
  riskScore: number | null;
  nRecords: number;
  inferenceType: string;
}

export function RiskBadge({ riskScore, nRecords, inferenceType }: RiskBadgeProps) {
  // Never render a score for insufficient_data — null means "no data", not "safe".
  const showScore = inferenceType !== "insufficient_data" && riskScore != null;
  const color = COLOR_STYLES[showScore ? riskColor(riskScore) : ""];
  const label = showScore ? riskLabel(riskScore) : "Insufficient data";

  return (
    <span className="inline-flex items-center gap-1.5" title={`n=${nRecords}, inference: ${inferenceType}`}>
      <span
        className="inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium"
        style={{ background: color.bg, color: color.fg }}
      >
        {label}
        {showScore && <span className="register">{riskScore!.toFixed(0)}</span>}
      </span>
      {nRecords < 10 && (
        <span className="text-[11px] text-caution" title="Fewer than 10 samples backing this score">
          Low confidence
        </span>
      )}
    </span>
  );
}
