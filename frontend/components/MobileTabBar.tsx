"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

const TABS = [
  { href: "/map", label: "Map", icon: "🗺️" },
  { href: "/search", label: "Search", icon: "🔍" },
  { href: "/alerts", label: "Alerts", icon: "🔔" },
  { href: "/account/alerts", label: "Account", icon: "👤" },
];

// Bottom tab bar for mobile — India's internet is majority-mobile, and a
// top nav that collapses to a hamburger loses one-tap access to the core
// flows. Only visible below the `sm` breakpoint; the top Nav's link row
// stays hidden there via its own `hidden sm:flex`.
export function MobileTabBar() {
  const pathname = usePathname();
  const { openAuth, token } = useAuth();

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-50 flex h-16 items-stretch border-t border-border bg-bg/95 backdrop-blur sm:hidden"
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
              className="flex flex-1 flex-col items-center justify-center gap-0.5 text-muted"
            >
              <span className="text-lg leading-none">{t.icon}</span>
              <span className="text-[10px] font-medium">{t.label}</span>
            </button>
          );
        }
        return (
          <Link
            key={t.href}
            href={t.href}
            className={`flex flex-1 flex-col items-center justify-center gap-0.5 ${active ? "text-forest" : "text-muted"}`}
          >
            <span className="text-lg leading-none">{t.icon}</span>
            <span className="text-[10px] font-medium">{t.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
