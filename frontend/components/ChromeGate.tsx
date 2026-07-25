"use client";

import { usePathname } from "next/navigation";

// Embed pages (frontend/app/embed/...) are meant to be iframed on
// third-party sites — they must render bare, with none of the main site's
// nav/footer/auth chrome.
export function ChromeGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (pathname?.startsWith("/embed")) return null;
  return <>{children}</>;
}
