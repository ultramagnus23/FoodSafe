/** @type {import('next').NextConfig} */
// Built as a static site (`next build` writes out/), so the Vercel project serves it from the
// repository root with no framework settings: see ../vercel.json. Every page renders in the
// browser; data comes from the daily snapshot (lib/snapshot.ts) and the API (lib/api/client.ts).
const nextConfig = {
  reactStrictMode: true,
  output: "export",
  images: { unoptimized: true },
  env: {
    // The Vercel project names the Render backend BACKEND_LINK (set in its dashboard when it
    // served the single-file index.html), so a deploy needs no new variable.
    NEXT_PUBLIC_API_URL:
      process.env.NEXT_PUBLIC_API_URL ||
      process.env.BACKEND_LINK ||
      (process.env.VERCEL ? "https://foodsafe-fll9.onrender.com" : "http://127.0.0.1:8000"),
  },
};

module.exports = nextConfig;
