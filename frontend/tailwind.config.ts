import type { Config } from "tailwindcss";

// Design tokens ported from the original index.html SPA's <style> block —
// keep visual continuity instead of inventing a new palette.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        "bg-card": "var(--bg-card)",
        forest: "var(--forest)",
        "forest-lt": "var(--forest-lt)",
        "forest-pale": "var(--forest-pale)",
        amber: "var(--amber)",
        "amber-lt": "var(--amber-lt)",
        red: "var(--red)",
        "red-lt": "var(--red-lt)",
        sage: "var(--sage)",
        "sage-lt": "var(--sage-lt)",
        ink: "var(--ink)",
        muted: "var(--muted)",
        border: "var(--border)",
      },
      fontFamily: {
        serif: ["var(--font-serif)"],
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"],
      },
      borderRadius: {
        DEFAULT: "10px",
      },
    },
  },
  plugins: [],
};
export default config;
