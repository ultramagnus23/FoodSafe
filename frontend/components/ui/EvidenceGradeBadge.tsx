// IARC classification tiers mapped onto the 3-step risk scale — no 4th
// decorative hue. Group 1 (confirmed) is the only "risk" state; groups
// 2A/2B (probable/possible) share "caution"; an established JECFA
// tolerance is "clear".
const GRADE_META: Record<string, { label: string; bg: string; fg: string }> = {
  iarc_group_1: { label: "IARC Group 1: Confirmed carcinogen", bg: "var(--risk-pale)", fg: "var(--risk)" },
  iarc_group_2a: { label: "IARC Group 2A: Probable carcinogen", bg: "var(--caution-pale)", fg: "var(--caution)" },
  iarc_group_2b: { label: "IARC Group 2B: Possible carcinogen", bg: "var(--caution-pale)", fg: "var(--caution)" },
  jecfa_established: { label: "JECFA Established", bg: "var(--clear-pale)", fg: "var(--clear)" },
};

export function EvidenceGradeBadge({ grade }: { grade: string }) {
  const meta = GRADE_META[grade] || { label: grade, bg: "var(--provenance-pale)", fg: "var(--provenance)" };
  return (
    <span
      className="inline-flex rounded px-2.5 py-1 text-xs font-medium"
      style={{ background: meta.bg, color: meta.fg }}
    >
      {meta.label}
    </span>
  );
}
