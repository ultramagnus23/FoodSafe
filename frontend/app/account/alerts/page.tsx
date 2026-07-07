"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { useSubscriptions, useDeleteSubscription } from "@/lib/api/subscriptions";
import { cap } from "@/lib/constants";

export default function MyAlertsPage() {
  const { token, openAuth } = useAuth();
  const loggedIn = !!token;
  const subs = useSubscriptions(loggedIn);
  const del = useDeleteSubscription();

  if (!loggedIn) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-20 text-center">
        <p className="mb-4 font-medium text-ink">Sign in to manage your alert subscriptions.</p>
        <button type="button" onClick={openAuth} className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-on-ink">
          Sign In →
        </button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="mb-2 font-display text-4xl font-light">My Alerts</h1>
      <p className="mb-6 text-provenance">
        Subscribe to a district from its report page. We&apos;ll email you when a new TWI-exceedance or Codex-gap
        alert matches.
      </p>

      {subs.isLoading ? (
        <p className="text-provenance">Loading…</p>
      ) : !subs.data || subs.data.length === 0 ? (
        <p className="text-provenance">
          No subscriptions yet. Visit a{" "}
          <Link href="/map" className="text-ink underline">
            district page
          </Link>{" "}
          and click &ldquo;Get alerts for this district&rdquo;.
        </p>
      ) : (
        <div className="grid gap-3">
          {subs.data.map((s) => (
            <div key={s.id} className="flex items-center justify-between rounded-lg border border-line bg-slab p-4">
              <div>
                <div className="font-medium">
                  {s.district_name || "Any district"} · {s.commodity_name || "Any commodity"}
                </div>
                <div className="text-xs text-provenance">
                  {cap(s.severity_threshold)}+ severity · {s.alert_types.join(", ")}
                  {s.last_notified_at ? ` · last notified ${s.last_notified_at.slice(0, 10)}` : ""}
                </div>
              </div>
              <button type="button" className="text-xs text-risk underline" onClick={() => del.mutate(s.id)}>
                Unsubscribe
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
