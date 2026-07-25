"use client";

import { useCallback, useEffect, useState } from "react";

const THEME_KEY = "foodsafe-theme";

// Light is the default (daytime civic/reference use); dark is an explicit,
// persisted choice for monitoring, never inferred from system preference.
export function useTheme() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  const toggle = useCallback(() => {
    setDark((prev) => {
      const next = !prev;
      document.documentElement.classList.toggle("dark", next);
      try {
        localStorage.setItem(THEME_KEY, next ? "dark" : "light");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  return { dark, toggle };
}
