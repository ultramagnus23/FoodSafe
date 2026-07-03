"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/map", label: "Risk Map" },
  { href: "/compare", label: "Compare" },
  { href: "/alerts", label: "Alerts" },
  { href: "/search", label: "Search" },
  { href: "/methodology", label: "Methodology" },
];

export function Nav() {
  const pathname = usePathname();
  const { user, openAuth, logout } = useAuth();

  return (
    <nav className="sticky top-0 z-50 flex h-[60px] items-center justify-between border-b border-border bg-bg/95 px-8 backdrop-blur">
      <Link href="/" className="flex items-center gap-2.5 font-serif text-xl font-semibold text-forest">
        <span className="inline-block h-2 w-2 rounded-full bg-sage" />
        FoodSafe India
      </Link>
      <div className="hidden gap-1 sm:flex">
        {LINKS.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className={`rounded-md px-3.5 py-1.5 text-sm font-medium transition-colors ${
              pathname === l.href ? "bg-forest-pale text-forest" : "text-muted hover:bg-forest-pale hover:text-forest"
            }`}
          >
            {l.label}
          </Link>
        ))}
      </div>
      {user ? (
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted">{user.email}</span>
          <button type="button" onClick={logout} className="rounded-md bg-forest px-4 py-1.5 text-sm font-medium text-white hover:bg-forest-lt">
            Sign Out
          </button>
        </div>
      ) : (
        <button type="button" onClick={openAuth} className="rounded-md bg-forest px-4 py-1.5 text-sm font-medium text-white hover:bg-forest-lt">
          Sign In
        </button>
      )}
    </nav>
  );
}
