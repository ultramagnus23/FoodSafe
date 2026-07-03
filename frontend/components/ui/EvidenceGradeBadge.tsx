const GRADE_META: Record<string, { label: string; bg: string; fg: string }> = {
  iarc_group_1: { label: "IARC Group 1 — Confirmed carcinogen", bg: "var(--red-lt)", fg: "var(--red)" },
  iarc_group_2a: { label: "IARC Group 2A — Probable carcinogen", bg: "var(--amber-lt)", fg: "#92400E" },
  iarc_group_2b: { label: "IARC Group 2B — Possible carcinogen", bg: "#FEF9C3", fg: "#854D0E" },
  jecfa_established: { label: "JECFA Established", bg: "var(--forest-pale)", fg: "var(--forest)" },
};

export function EvidenceGradeBadge({ grade }: { grade: string }) {
  const meta = GRADE_META[grade] || { label: grade, bg: "var(--border)", fg: "var(--muted)" };
  return (
    <span
      className="inline-flex rounded-full px-2.5 py-1 text-xs font-medium"
      style={{ background: meta.bg, color: meta.fg }}
    >
      {meta.label}
    </span>
  );
}
