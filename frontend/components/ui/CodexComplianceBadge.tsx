interface CodexComplianceBadgeProps {
  fssaiCompliant: boolean | null;
  codexCompliant: boolean | null;
  fssaiLimitPpb?: number | null;
  codexLimitPpb?: number | null;
}

function Chip({ label, ok }: { label: string; ok: boolean | null }) {
  const style =
    ok === true
      ? { background: "var(--sage-lt)", color: "var(--forest)" }
      : ok === false
      ? { background: "var(--red-lt)", color: "var(--red)" }
      : { background: "var(--border)", color: "var(--muted)" };
  return (
    <span className="inline-flex rounded-full px-2.5 py-1 text-xs font-medium" style={style}>
      {label}: {ok === true ? "Pass" : ok === false ? "Fail" : "—"}
    </span>
  );
}

// The "Mother Dairy problem": passed India's own test, fails the
// international Codex Alimentarius benchmark. This is the platform's
// single most important visual — never collapse it into one badge.
export function CodexComplianceBadge({
  fssaiCompliant,
  codexCompliant,
  fssaiLimitPpb,
  codexLimitPpb,
}: CodexComplianceBadgeProps) {
  const isGap = fssaiCompliant === true && codexCompliant === false;
  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={
        fssaiLimitPpb != null && codexLimitPpb != null
          ? `FSSAI limit: ${fssaiLimitPpb} PPB · Codex limit: ${codexLimitPpb} PPB`
          : undefined
      }
    >
      <Chip label="FSSAI" ok={fssaiCompliant} />
      <Chip label="Codex" ok={codexCompliant} />
      {isGap && <span className="text-[11px] text-[#92400E]">⚠ Passed FSSAI, fails Codex</span>}
    </span>
  );
}
