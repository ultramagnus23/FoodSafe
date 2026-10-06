"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { MOBILE_TABS, MORE, PRIMARY } from "@/lib/nav";

// Bottom tab bar for mobile and tablet (below `lg`, where the top nav's links are hidden):
// India's internet is majority-mobile, so the core pages stay one tap away and "All"
// opens every page.
export function MobileTabBar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [pathname]);

  const tabHrefs = new Set(MOBILE_TABS.map((t) => t.href));
  const rest = [...PRIMARY, ...MORE].filter((l) => !tabHrefs.has(l.href));

  return (
    <>
      {open ? (
        <div className="fixed inset-x-0 bottom-14 z-50 max-h-[70vh] overflow-y-auto border-t border-line bg-slab p-2 shadow lg:hidden">
          {rest.map((l) => (
            <Link key={l.href} href={l.href} className={`block rounded px-4 py-2.5 text-sm ${pathname === l.href ? "bg-provenance-pale text-ink" : "text-ink"}`}>
              {l.label}
              {l.note ? <span className="block text-xs text-provenance">{l.note}</span> : null}
            </Link>
          ))}
        </div>
      ) : null}
      <nav
        className="fixed bottom-0 left-0 right-0 z-50 flex h-14 items-stretch border-t border-line bg-porcelain lg:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        {MOBILE_TABS.map((t) => (
          <Link
            key={t.href}
            href={t.href}
            className={`flex flex-1 items-center justify-center text-sm font-medium ${pathname === t.href ? "text-ink" : "text-provenance"}`}
          >
            {t.label}
          </Link>
        ))}
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
          className={`flex flex-1 items-center justify-center text-sm font-medium ${open ? "text-ink" : "text-provenance"}`}
        >
          All ▴
        </button>
      </nav>
    </>
  );
}
