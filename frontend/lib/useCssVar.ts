"use client";

import { useEffect, useState } from "react";

// Resolves a CSS custom property to its current computed value, and
// re-reads it when the theme toggles. Needed anywhere a color has to be a
// real string (e.g. SVG/Canvas APIs like Leaflet's pathOptions) rather than
// a `var(--x)` reference a stylesheet would resolve for us.
export function useCssVar(name: string): string {
  const [value, setValue] = useState("");

  useEffect(() => {
    const read = () => setValue(getComputedStyle(document.documentElement).getPropertyValue(name).trim());
    read();
    const observer = new MutationObserver(read);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, [name]);

  return value;
}
