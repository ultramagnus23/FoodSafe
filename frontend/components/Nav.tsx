"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { ThemeToggle } from "@/components/ThemeToggle";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/map", label: "Risk Map" },
  { href: "/compare", label: "Compare" },
  { href: "/alerts", label: "Alerts" },
  { href: "/search", label: "Search" },
  { href: "/directory", label: "Directory" },
  { href: "/report", label: "Report an Issue" },
  { href: "/methodology", label: "Methodology" },
];

export function Nav() {
  const pathname = usePathname();
  const { user, openAuth, logout } = useAuth();

  return (
    <nav className="sticky top-0 z-50 flex h-[60px] items-center justify-between border-b border-line bg-porcelain px-8">
      <Link href="/" className="flex items-center gap-2.5 font-display text-xl font-semibold text-ink">
        <span className="inline-block h-2 w-2 rounded-full bg-clear" />
        FoodSafe India
      </Link>
      <div className="hidden gap-1 lg:flex">
        {LINKS.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className={`rounded px-3.5 py-1.5 text-sm font-medium transition-colors ${
              pathname === l.href ? "bg-provenance-pale text-ink" : "text-provenance hover:bg-provenance-pale hover:text-ink"
            }`}
          >
            {l.label}
          </Link>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <ThemeToggle />
        {user ? (
          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-provenance lg:inline">{user.email}</span>
            <button type="button" onClick={logout} className="rounded bg-ink px-4 py-1.5 text-sm font-medium text-on-ink hover:opacity-90">
              Sign Out
            </button>
          </div>
        ) : (
          <button type="button" onClick={openAuth} className="rounded bg-ink px-4 py-1.5 text-sm font-medium text-on-ink hover:opacity-90">
            Sign In
          </button>
        )}
      </div>
    </nav>
  );
}
