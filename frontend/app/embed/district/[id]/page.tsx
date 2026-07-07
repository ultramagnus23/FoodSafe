"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useWidgetData } from "@/lib/api/widget";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { fmt } from "@/lib/constants";

// Bare, read-only, iframe-embeddable district-risk card for journalists/
// local news. No auth, no nav — see ChromeGate in the root layout, which
// suppresses the main site's nav/footer for anything under /embed.
export default function EmbedDistrictPage() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const districtId = Number(params.id);
  const commodityId = Number(searchParams.get("commodity") || 1);

  const widget = useWidgetData(districtId, commodityId);

  if (widget.isLoading) {
    return <div className="p-4 text-sm text-provenance">Loading…</div>;
  }
  if (widget.isError || !widget.data) {
    return <div className="p-4 text-sm text-provenance">Could not load this district.</div>;
  }

  const d = widget.data;

  return (
    <div className="mx-auto max-w-sm rounded-xl border border-line bg-slab p-5">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <div className="font-display text-lg font-semibold">
            {d.district_name}, {d.state}
          </div>
          <div className="text-xs text-provenance">{d.commodity_name}</div>
        </div>
        <ProvenanceBadge provenance={d.provenance} compact />
      </div>

      <div className="my-3 font-display text-4xl font-semibold text-ink">
        {fmt(d.risk_score, 0)}
        <span className="ml-1 text-sm font-normal text-provenance">/100</span>
      </div>

      <div className="mb-3 text-xs text-provenance">
        {d.n_tests} test{d.n_tests === 1 ? "" : "s"}
        {d.last_updated ? ` · updated ${d.last_updated.slice(0, 10)}` : ""}
      </div>

      <p className="mb-3 text-[11px] leading-relaxed text-provenance">{d.disclaimer}</p>

      <a
        href={`https://foodsafe.in/district/${d.district_id}?commodity=${d.commodity_id}`}
        target="_blank"
        rel="noreferrer"
        className="text-xs font-medium text-ink underline"
      >
        Full report on FoodSafe India →
      </a>
    </div>
  );
}
