import type { Metadata } from "next";
import DistrictClient from "./DistrictClient";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

async function fetchDistrictName(id: string): Promise<{ name: string; state: string } | null> {
  try {
    // /v1/meta/districts is public (no auth) — safe to call from the server
    // for metadata generation, unlike the risk endpoints which require a
    // user's JWT and can't be fetched at build/request time server-side.
    const res = await fetch(`${API_BASE}/v1/meta/districts`, { next: { revalidate: 3600 } });
    if (!res.ok) return null;
    const districts: { id: number; name: string; state: string }[] = await res.json();
    const match = districts.find((d) => String(d.id) === id);
    return match ? { name: match.name, state: match.state } : null;
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: { id: string } }): Promise<Metadata> {
  const district = await fetchDistrictName(params.id);
  const title = district
    ? `${district.name} Food Safety Report | FoodSafe India`
    : "District Food Safety Report | FoodSafe India";
  const description = district
    ? `Food contamination risk and disease-burden estimates for ${district.name}, ${district.state}. See the report for data source and provenance, compared against Codex Alimentarius international standards.`
    : "District-level food contamination risk estimates. See each report for data source and provenance.";

  return {
    title,
    description,
    openGraph: { title, description, type: "article" },
  };
}

export default function DistrictPage() {
  return <DistrictClient />;
}
