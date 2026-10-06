import type { MetadataRoute } from "next";

// Static: the site is exported at build time (next.config.js output: "export").
export const dynamic = "force-static";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://foodsafev2.vercel.app";

const PAGES = [
  "",
  "/engine",
  "/standards",
  "/findings",
  "/hazards",
  "/places",
  "/nutrition",
  "/research",
  "/directory",
  "/sources",
  "/brief",
  "/methodology",
];

export default function sitemap(): MetadataRoute.Sitemap {
  return PAGES.map((path) => ({
    url: `${SITE_URL}${path}`,
    changeFrequency: path === "" ? "daily" : "weekly",
    priority: path === "" ? 1 : 0.7,
  }));
}
