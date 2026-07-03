import type { MetadataRoute } from "next";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://foodsafe.in";

const STATIC_PAGES = ["", "/map", "/compare", "/alerts", "/search", "/methodology", "/methodology/standards"];

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticEntries: MetadataRoute.Sitemap = STATIC_PAGES.map((path) => ({
    url: `${SITE_URL}${path}`,
    lastModified: new Date(),
    changeFrequency: path === "" ? "daily" : "weekly",
    priority: path === "" ? 1 : 0.7,
  }));

  let districtEntries: MetadataRoute.Sitemap = [];
  try {
    const res = await fetch(`${API_BASE}/v1/meta/districts`, { next: { revalidate: 86400 } });
    if (res.ok) {
      const districts: { id: number }[] = await res.json();
      districtEntries = districts.map((d) => ({
        url: `${SITE_URL}/district/${d.id}`,
        lastModified: new Date(),
        changeFrequency: "weekly" as const,
        priority: 0.8,
      }));
    }
  } catch {
    // sitemap generation shouldn't fail the build if the API is briefly down
  }

  return [...staticEntries, ...districtEntries];
}
