"use client";

import { useMemo, useState } from "react";
import { Field, inputClass, LoadState, Page, PageHeader, SnapshotNote, Tag } from "@/components/ui/DataBlocks";
import { num, useSnapshot } from "@/lib/snapshot";

export default function HazardsPage() {
  const hz = useSnapshot("hazards");
  const [q, setQ] = useState("");
  const [cls, setCls] = useState("");

  const classes = useMemo(() => Array.from(new Set((hz.data ?? []).map((h) => h.hazard_class))).sort(), [hz.data]);
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (hz.data ?? []).filter((h) => (!cls || h.hazard_class === cls) && (!needle || JSON.stringify(h).toLowerCase().includes(needle)));
  }, [hz.data, q, cls]);
  const links = (hz.data ?? []).reduce((a, h) => a + h.effects.length, 0);

  return (
    <Page>
      <PageHeader kicker="Hazard to disease" title="Hazards and what they do to people">
        <p>
          The knowledge base behind the disease risk engine: each hazard&apos;s known health outcomes, the organ system, how
          fast it acts, who is most at risk, the IARC cancer classification where one exists, and the source of each
          statement (WHO, IARC, EFSA, US EPA, CDC, FAO). It says what can happen, not how likely it is.
        </p>
        {hz.data ? (
          <p className="register text-xs">
            {num(hz.data.length)} curated hazards · {num(links)} cited outcome links · held alongside the IARC classification of
            1,128 agents and five pesticide classes
          </p>
        ) : null}
        <SnapshotNote />
      </PageHeader>

      <div className="mb-6 flex flex-wrap items-end gap-4">
        <Field label="Search">
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. liver, children, salmonella" className={inputClass} />
        </Field>
        <Field label="Class">
          <select value={cls} onChange={(e) => setCls(e.target.value)} className={inputClass}>
            <option value="">All classes</option>
            {classes.map((c) => (
              <option key={c} value={c}>
                {c.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <LoadState error={hz.error} loading={hz.isLoading} what="the knowledge base" />
      <div className="divide-y divide-line rounded-lg border border-line">
        {rows.map((h) => (
          <details key={h.hazard_key} className="group px-4 py-3">
            <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="font-medium text-ink">{h.name}</span>
              <Tag>{h.hazard_class.replace(/_/g, " ")}</Tag>
              {h.iarc_group ? <Tag tone={h.iarc_group === "1" ? "risk" : h.iarc_group === "2A" ? "caution" : "neutral"}>IARC {h.iarc_group}</Tag> : null}
              <span className="w-full truncate text-sm text-provenance sm:w-auto sm:flex-1">
                {h.effects.map((e) => e.outcome).slice(0, 2).join("; ")}
              </span>
            </summary>
            {h.summary ? <p className="mt-3 max-w-prose text-sm text-provenance">{h.summary}</p> : null}
            {h.effects.length ? (
              <ul className="mt-3 space-y-2 text-sm">
                {h.effects.map((e, i) => (
                  <li key={i} className="leading-relaxed">
                    <strong className="font-medium text-ink">{e.outcome}</strong>
                    <span className="text-provenance">
                      {" "}
                      — {e.organ}, {e.exposure}
                      {e.onset ? `, onset ${e.onset}` : ""}
                      {(e.vulnerable ?? []).length ? `. Most at risk: ${(e.vulnerable ?? []).join(", ")}` : ""}. {e.evidence}.{" "}
                    </span>
                    <a href={e.url} className="text-provenance underline" target="_blank" rel="noreferrer">
                      {e.source}
                    </a>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-sm text-provenance">No health outcome asserted (depends on substance and dose).</p>
            )}
          </details>
        ))}
        {hz.data && !rows.length ? <p className="px-4 py-6 text-sm text-provenance">No hazard matches. Try a broader word.</p> : null}
      </div>
    </Page>
  );
}
