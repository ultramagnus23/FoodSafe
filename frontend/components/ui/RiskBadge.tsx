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

const COLOR_STYLES: Record<string, { bg: string; fg: string }> = {
  low: { bg: "var(--sage-lt)", fg: "var(--forest)" },
  mid: { bg: "var(--amber-lt)", fg: "#92400E" },
  high: { bg: "var(--red-lt)", fg: "var(--red)" },
  "": { bg: "var(--border)", fg: "var(--muted)" },
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
        className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium"
        style={{ background: color.bg, color: color.fg }}
      >
        {label}
        {showScore && <span className="font-mono">{riskScore!.toFixed(0)}</span>}
      </span>
      {nRecords < 10 && (
        <span className="text-[11px] text-amber" title="Fewer than 10 samples backing this score">
          ⚠ Low confidence
        </span>
      )}
    </span>
  );
}
