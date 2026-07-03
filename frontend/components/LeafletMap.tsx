"use client";

import { useEffect } from "react";
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import type { MapDataPoint } from "@/lib/api/types";

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
}

export default function LeafletMap({ points, onDistrictClick }: LeafletMapProps) {
  const valid = points.filter((p) => p.latitude != null && p.longitude != null);

  return (
    <div className="h-[440px] w-full overflow-hidden rounded-xl border border-border">
      <MapContainer center={[22.8, 80.0]} zoom={4.4} scrollWheelZoom={false} style={{ height: "100%", width: "100%" }}>
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="&copy; OpenStreetMap contributors"
        />
        <FitBounds points={valid} />
        {valid.map((d) => {
          const score = d.risk_score || 0;
          const color = score >= 60 ? "#C2410C" : score >= 35 ? "#B45309" : "#4D7C5A";
          return (
            <CircleMarker
              key={d.district_id}
              center={[d.latitude as number, d.longitude as number]}
              radius={6 + score * 0.12}
              pathOptions={{ color, fillColor: color, fillOpacity: 0.62, weight: 1.5 }}
              eventHandlers={{ click: () => onDistrictClick?.(d.district_id) }}
            >
              <Popup>
                <strong>{d.district_name}</strong>
                <br />
                {d.state}
                <br />
                Risk: {score.toFixed(0)}/100 · {d.n_tests || 0} tests
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </div>
  );
}
