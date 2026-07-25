import type { Config } from "tailwindcss";

// "The Public Register" design system — every color is an OKLCH custom
// property with light and dark values (see app/globals.css). Dark mode is
// class-based (manual toggle), not system-driven: light is the default.
const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        porcelain: "var(--porcelain)",
        slab: "var(--slab)",
        ink: "var(--ink)",
        "on-ink": "var(--on-ink)",
        provenance: "var(--provenance)",
        "provenance-pale": "var(--provenance-pale)",
        line: "var(--line)",
        "line-strong": "var(--line-strong)",
        clear: "var(--clear)",
        "clear-pale": "var(--clear-pale)",
        caution: "var(--caution)",
        "caution-pale": "var(--caution-pale)",
        risk: "var(--risk)",
        "risk-pale": "var(--risk-pale)",
      },
      fontFamily: {
        display: ["var(--font-display)"],
        body: ["var(--font-body)"],
        register: ["var(--font-register)"],
        sans: ["var(--font-body)"],
        mono: ["var(--font-register)"],
      },
      borderRadius: {
        DEFAULT: "6px",
      },
      boxShadow: {
        DEFAULT: "var(--shadow)",
      },
      maxWidth: {
        prose: "70ch",
      },
    },
  },
  plugins: [],
};
export default config;
