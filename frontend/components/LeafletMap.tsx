"use client";

import { useEffect } from "react";
import { MapContainer, TileLayer, CircleMarker, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import type { MapDataPoint } from "@/lib/api/types";
import { useCssVar } from "@/lib/useCssVar";

function FitBounds({ points }: { points: MapDataPoint[] }) {
  const map = useMap();
  useEffect(() => {
    const valid = points.filter((p) => p.latitude != null && p.longitude != null);
    if (!valid.length) return;
    try {
      map.fitBounds(
        valid.map((p) => [p.latitude as number, p.longitude as number]),
        { padding: [40, 40], maxZoom: 6 }
      );
    } catch {
      /* ignore */
    }
  }, [points, map]);
  return null;
}

interface LeafletMapProps {
  points: MapDataPoint[];
  onDistrictClick?: (districtId: number) => void;
  /** Decorative-only mode (landing hero backdrop): fills its container,
   *  no rounding/border, no tile attribution clutter. */
  bare?: boolean;
}

export default function LeafletMap({ points, onDistrictClick, bare = false }: LeafletMapProps) {
  const valid = points.filter((p) => p.latitude != null && p.longitude != null);

  // Leaflet sets these as real SVG attributes, not CSS `style` properties,
  // so a raw `var(--x)` string isn't guaranteed to resolve — read the
  // computed value instead, live-updated on theme toggle.
  const clear = useCssVar("--clear");
  const caution = useCssVar("--caution");
  const risk = useCssVar("--risk");
  const noData = useCssVar("--provenance");

  return (
    <div className={bare ? "h-full w-full" : "h-[440px] w-full overflow-hidden rounded-xl border border-line"}>
      <MapContainer
        center={[22.8, 80.0]}
        zoom={4.4}
        scrollWheelZoom={false}
        zoomControl={!bare}
        attributionControl={!bare}
        style={{ height: "100%", width: "100%" }}
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="&copy; OpenStreetMap contributors"
        />
        <FitBounds points={valid} />
        {valid.map((d) => {
          const hasData = d.risk_score != null;
          // No data must never collapse into the low-risk color — a
          // district we've never tested is not the same claim as a
          // district we tested and found safe.
          const color = !hasData ? noData : d.risk_score! >= 60 ? risk : d.risk_score! >= 35 ? caution : clear;
          const radius = hasData ? 6 + d.risk_score! * 0.12 : 5;
          if (!color) return null;
          return (
            <CircleMarker
              key={d.district_id}
              center={[d.latitude as number, d.longitude as number]}
              radius={radius}
              pathOptions={
                hasData
                  ? { color, fillColor: color, fillOpacity: 0.62, weight: 1.5 }
                  : { color, fillColor: color, fillOpacity: 0.35, weight: 1, dashArray: "3,3" }
              }
              eventHandlers={{ click: () => onDistrictClick?.(d.district_id) }}
            />
          );
        })}
      </MapContainer>
    </div>
  );
}
