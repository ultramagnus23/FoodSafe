"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { MORE, PRIMARY } from "@/lib/nav";
import { ThemeToggle } from "@/components/ThemeToggle";

export function Nav() {
  const pathname = usePathname();
  const { user, openAuth, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const menu = useRef<HTMLDivElement>(null);

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (menu.current && !menu.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const moreActive = MORE.some((l) => pathname === l.href);

  return (
    <nav className="sticky top-0 z-50 flex h-[60px] items-center justify-between gap-4 border-b border-line bg-porcelain px-4 sm:px-6">
      <Link href="/" className="flex shrink-0 items-center gap-2.5 font-display text-xl font-semibold text-ink">
        <span className="inline-block h-2 w-2 rounded-full bg-clear" />
        FoodSafe
      </Link>
      <div className="hidden min-w-0 items-center gap-0.5 lg:flex">
        {PRIMARY.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className={`whitespace-nowrap rounded px-3 py-1.5 text-sm font-medium transition-colors ${
              pathname === l.href ? "bg-provenance-pale text-ink" : "text-provenance hover:bg-provenance-pale hover:text-ink"
            }`}
          >
            {l.label}
          </Link>
        ))}
        <div className="relative" ref={menu}>
          <button
            type="button"
            aria-expanded={open}
            aria-haspopup="true"
            onClick={() => setOpen((o) => !o)}
            className={`rounded px-3 py-1.5 text-sm font-medium transition-colors ${
              moreActive || open ? "bg-provenance-pale text-ink" : "text-provenance hover:bg-provenance-pale hover:text-ink"
            }`}
          >
            More ▾
          </button>
          {open ? (
            <div className="absolute right-0 top-full mt-2 w-72 rounded-lg border border-line bg-slab p-1.5 shadow">
              {MORE.map((l) => (
                <Link key={l.href} href={l.href} className="block rounded px-3 py-2 hover:bg-provenance-pale">
                  <span className="block text-sm font-medium text-ink">{l.label}</span>
                  {l.note ? <span className="block text-xs text-provenance">{l.note}</span> : null}
                </Link>
              ))}
            </div>
          ) : null}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <ThemeToggle />
        {user ? (
          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-provenance xl:inline">{user.email}</span>
            <button type="button" onClick={logout} className="rounded bg-ink px-4 py-1.5 text-sm font-medium text-on-ink hover:opacity-90">
              Sign Out
            </button>
          </div>
        ) : (
          <button type="button" onClick={openAuth} className="rounded border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-provenance-pale">
            Sign In
          </button>
        )}
      </div>
    </nav>
  );
}
