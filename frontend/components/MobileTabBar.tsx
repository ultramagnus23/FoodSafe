"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

const TABS = [
  { href: "/map", label: "Map" },
  { href: "/search", label: "Search" },
  { href: "/alerts", label: "Alerts" },
  { href: "/account/alerts", label: "Account" },
];

// Bottom tab bar for mobile and tablet — India's internet is majority-
// mobile, and a top nav that collapses to a hamburger loses one-tap access
// to the core flows. Visible below `lg` (1024px): the full 7-link desktop
// nav doesn't fit in less width than that without crowding, so the top
// Nav's link row stays hidden until `lg:flex` and this covers the gap.
export function MobileTabBar() {
  const pathname = usePathname();
  const { openAuth, token } = useAuth();

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-50 flex h-14 items-stretch border-t border-line bg-porcelain lg:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      {TABS.map((t) => {
        const isAccount = t.href === "/account/alerts";
        const active = pathname === t.href || (isAccount && pathname.startsWith("/account"));
        if (isAccount && !token) {
          return (
            <button
              key={t.href}
              type="button"
              onClick={openAuth}
              className="flex flex-1 items-center justify-center text-sm font-medium text-provenance"
            >
              {t.label}
            </button>
          );
        }
        return (
          <Link
            key={t.href}
            href={t.href}
            className={`flex flex-1 items-center justify-center text-sm font-medium ${active ? "text-ink" : "text-provenance"}`}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
