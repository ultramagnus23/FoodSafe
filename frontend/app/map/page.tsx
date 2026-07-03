"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { useAuth } from "@/lib/auth-context";
import { useMapData } from "@/lib/api/risk";
import { useDiseaseMap } from "@/lib/api/disease";
import { COMMODITIES } from "@/lib/constants";
import { SkeletonMapLegend } from "@/components/ui/Skeletons";
import { DisclaimerBanner } from "@/components/ui/DisclaimerBanner";

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

export default function MapPage() {
  const router = useRouter();
  const { token, openAuth } = useAuth();
  const loggedIn = !!token;
  const [commodityId, setCommodityId] = useState(1);
  const [contaminantId, setContaminantId] = useState(1);
  const [mode, setMode] = useState<"fssai" | "disease">("fssai");

  const riskMap = useMapData(commodityId, loggedIn && mode === "fssai");
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
    <div className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="mb-2 font-serif text-4xl font-light">Risk Map</h1>
      <p className="mb-6 text-muted">
        {mode === "fssai"
          ? "District-level food safety risk score, computed from FSSAI/USFDA/AGMARKNET enforcement records."
          : "Estimated disease burden (population attributable fraction) for the selected contaminant's primary disease."}
      </p>

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="flex rounded-lg border border-border p-0.5">
          <button
            type="button"
            onClick={() => setMode("fssai")}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${mode === "fssai" ? "bg-forest text-white" : "text-muted"}`}
          >
            FSSAI Risk Mode
          </button>
          <button
            type="button"
            onClick={() => setMode("disease")}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${mode === "disease" ? "bg-forest text-white" : "text-muted"}`}
          >
            Disease Burden Mode
          </button>
        </div>

        {mode === "fssai" ? (
          <select
            className="rounded-lg border border-border bg-bg-card px-3 py-2 text-sm"
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
            className="rounded-lg border border-border bg-bg-card px-3 py-2 text-sm"
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

      {!loggedIn ? (
        <div className="rounded-xl bg-forest-pale p-12 text-center">
          <p className="mb-4 font-medium text-forest">Sign in to load the live risk map.</p>
          <button type="button" onClick={openAuth} className="rounded-md bg-forest px-4 py-2 text-sm font-medium text-white">
            Sign In →
          </button>
        </div>
      ) : loading ? (
        <SkeletonMapLegend />
      ) : (
        <LeafletMap points={points} onDistrictClick={(id) => router.push(`/district/${id}?commodity=${commodityId}`)} />
      )}

      <p className="mt-4 text-xs text-muted">
        Districts with no data are omitted from the map, not shown as zero risk — insufficient data and low risk are
        different things.
      </p>

      <div className="mt-8">
        <DisclaimerBanner />
      </div>
    </div>
  );
}
