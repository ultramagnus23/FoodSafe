"use client";

import { useTheme } from "@/lib/theme";

export function ThemeToggle() {
  const { dark, toggle } = useTheme();

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      aria-pressed={dark}
      className="register rounded border border-line px-2.5 py-1 text-[11px] uppercase tracking-wide text-provenance transition-colors hover:border-line-strong hover:text-ink"
    >
      {dark ? "Dark" : "Light"}
    </button>
  );
}
