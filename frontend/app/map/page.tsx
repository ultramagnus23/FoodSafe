"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { useMapData, useMapQuarters, useDistrictRisk } from "@/lib/api/risk";
import { useDiseaseMap } from "@/lib/api/disease";
import { COMMODITIES } from "@/lib/constants";
import { SkeletonMapLegend } from "@/components/ui/Skeletons";
import { DisclaimerBanner } from "@/components/ui/DisclaimerBanner";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { SpecimenCard } from "@/components/ui/SpecimenCard";
import { TimeScrubber } from "@/components/TimeScrubber";

const LeafletMap = dynamic(() => import("@/components/LeafletMap"), { ssr: false });

// Contaminants matching schema.sql seed order (id: name).
const CONTAMINANTS = [
  { id: 1, name: "Aflatoxin B1" },
  { id: 3, name: "Lead" },
  { id: 4, name: "Cadmium" },
  { id: 5, name: "Arsenic (inorganic)" },
  { id: 6, name: "Chlorpyrifos (pesticide)" },
  { id: 8, name: "Ochratoxin A" },
];

// Evidence panel: the point is the score is never a black box. Every
// district click shows the top contributing signals, sourced and dated,
// not just a number.
function EvidencePanel({ districtId, commodityId }: { districtId: number; commodityId: number }) {
  const risk = useDistrictRisk(districtId, commodityId, true);

  if (risk.isLoading) {
    return <p className="p-4 text-sm text-provenance">Loading evidence…</p>;
  }
  if (risk.isError || !risk.data) {
    return <p className="p-4 text-sm text-provenance">No evidence available for this district/commodity.</p>;
  }

  const r = risk.data;

  return (
    <div className="flex h-full flex-col overflow-y-auto p-5">
      <div className="mb-1 flex items-start justify-between gap-2">
        <h2 className="font-display text-xl font-normal text-ink">
          {r.district_name}, {r.state}
        </h2>
      </div>
      <div className="mb-4 flex items-center gap-2">
        <RiskBadge riskScore={r.risk_score} nRecords={r.n_tests} inferenceType={r.inference_type} />
        <ProvenanceBadge provenance={r.provenance} compact />
      </div>

      {r.top_factors.length > 0 && (
        <div className="mb-5">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-provenance">
            Contributing signals
          </div>
          <ul className="grid gap-2">
            {r.top_factors.map((f, i) => (
              <li key={i} className="flex items-center justify-between rounded border border-line px-3 py-2 text-sm">
                <span className="text-ink">{String(f.factor)}</span>
                <span className="register text-provenance">
                  {String(f.value)}
                  {f.unit ? ` ${f.unit}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-provenance">
        Recent evidence
      </div>
      {r.enforcement_events.length === 0 ? (
        <p className="text-sm text-provenance">No enforcement records for this selection.</p>
      ) : (
        <div className="grid gap-2">
          {r.enforcement_events.slice(0, 6).map((e, i) => (
            <SpecimenCard
              key={i}
              source={e.source_type.toUpperCase()}
              date={e.test_date}
              reference={e.lab_name}
              finding={`${e.contaminant.replace(/_/g, " ")}: ${e.value_ppb.toFixed(2)} PPB${
                e.legal_limit_ppb != null ? ` (limit ${e.legal_limit_ppb.toFixed(1)})` : ""
              }`}
              outcome={e.pass_fail}
              sourceUrl={e.source_url}
            />
          ))}
        </div>
      )}

      <Link href={`/district/${districtId}?commodity=${commodityId}`} className="mt-4 text-sm font-medium text-ink underline">
        Full district report →
      </Link>
    </div>
  );
}

export default function MapPage() {
  const { token, openAuth } = useAuth();
  const loggedIn = !!token;
  const [commodityId, setCommodityId] = useState(1);
  const [contaminantId, setContaminantId] = useState(1);
  const [mode, setMode] = useState<"fssai" | "disease">("fssai");
  const [selectedDistrict, setSelectedDistrict] = useState<number | null>(null);
  const [quarter, setQuarter] = useState<string | undefined>(undefined);

  const quarters = useMapQuarters(commodityId, loggedIn && mode === "fssai");
  const riskMap = useMapData(commodityId, loggedIn && mode === "fssai", quarter);
  const diseaseMap = useDiseaseMap(contaminantId, loggedIn && mode === "disease");

  const points =
    mode === "fssai"
      ? riskMap.data || []
      : (diseaseMap.data || []).map((d) => ({
          district_id: d.district_id,
          district_name: d.district_name,
          state: d.state,
          latitude: d.latitude,
          longitude: d.longitude,
          risk_score: d.paf_estimate != null ? d.paf_estimate * 100 * 20 : null, // scale PAF% for marker sizing only
          n_tests: d.n_records,
        }));
  const loading = mode === "fssai" ? riskMap.isLoading : diseaseMap.isLoading;

  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <h1 className="mb-2 font-display text-4xl font-light">Risk Map</h1>
      <p className="mb-6 text-provenance">
        {mode === "fssai"
          ? "District-level food safety risk score, computed from FSSAI/USFDA/AGMARKNET enforcement records."
          : "Estimated disease burden (population attributable fraction) for the selected contaminant's primary disease."}
      </p>

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="flex rounded border border-line p-0.5">
          <button
            type="button"
            onClick={() => {
              setMode("fssai");
              setSelectedDistrict(null);
            }}
            className={`rounded px-3 py-1.5 text-sm font-medium ${mode === "fssai" ? "bg-ink text-on-ink" : "text-provenance"}`}
          >
            FSSAI Risk Mode
          </button>
          <button
            type="button"
            onClick={() => {
              setMode("disease");
              setSelectedDistrict(null);
            }}
            className={`rounded px-3 py-1.5 text-sm font-medium ${mode === "disease" ? "bg-ink text-on-ink" : "text-provenance"}`}
          >
            Disease Burden Mode
          </button>
        </div>

        {mode === "fssai" ? (
          <select
            className="rounded-lg border border-line bg-slab px-3 py-2 text-sm"
            value={commodityId}
            onChange={(e) => setCommodityId(Number(e.target.value))}
          >
            {COMMODITIES.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        ) : (
          <select
            className="rounded-lg border border-line bg-slab px-3 py-2 text-sm"
            value={contaminantId}
            onChange={(e) => setContaminantId(Number(e.target.value))}
          >
            {CONTAMINANTS.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        )}
      </div>

      {mode === "fssai" && loggedIn && quarters.data && quarters.data.length > 1 && (
        <div className="mb-4 max-w-md">
          <TimeScrubber
            quarters={quarters.data}
            value={quarter || quarters.data[quarters.data.length - 1]}
            onChange={setQuarter}
          />
        </div>
      )}

      {!loggedIn ? (
        <div className="rounded-xl bg-provenance-pale p-12 text-center">
          <p className="mb-4 font-medium text-ink">Sign in to load the live risk map.</p>
          <button type="button" onClick={openAuth} className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-on-ink">
            Sign In →
          </button>
        </div>
      ) : loading ? (
        <SkeletonMapLegend />
      ) : (
        <div className="grid gap-4 md:grid-cols-[1fr_360px]">
          <LeafletMap points={points} onDistrictClick={(id) => setSelectedDistrict(id)} />
          <div className="rounded border border-line bg-slab md:h-[440px]">
            {selectedDistrict && mode === "fssai" ? (
              <EvidencePanel districtId={selectedDistrict} commodityId={commodityId} />
            ) : (
              <div className="flex h-full items-center justify-center p-6 text-center text-sm text-provenance">
                {mode === "fssai" ? "Select a district to see its evidence." : "Evidence panel is available in FSSAI Risk Mode."}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-provenance">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: "var(--provenance-pale)", border: "1px dashed var(--provenance)" }} />
          No data
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: "var(--clear)" }} />
          Lower risk
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: "var(--caution)" }} />
          Moderate risk
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: "var(--risk)" }} />
          Higher risk
        </span>
      </div>
      <p className="mt-2 text-xs text-provenance">
        Districts with no data are shown as a distinct gray dashed marker, never as zero or low risk. Insufficient
        data and low risk are different claims.
      </p>

      <div className="mt-8">
        <DisclaimerBanner />
      </div>
    </div>
  );
}
