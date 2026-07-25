"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { useCreateSubscription } from "@/lib/api/subscriptions";

interface SubscribeButtonProps {
  districtId: number;
  commodityId?: number;
}

export function SubscribeButton({ districtId, commodityId }: SubscribeButtonProps) {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [severity, setSeverity] = useState("moderate");
  const [anyCommodity, setAnyCommodity] = useState(true);
  const create = useCreateSubscription();
  const [done, setDone] = useState(false);

  const eligible = user && ["consumer_premium", "fmcg", "insurance"].includes(user.tier);

  if (!eligible) {
    return (
      <p className="text-xs text-provenance">
        Alert subscriptions require a Premium account.
      </p>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-md border border-line px-3 py-1.5 text-sm font-medium hover:border-ink hover:text-ink"
      >
        Get alerts for this district
      </button>

      {open && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-ink/50 p-6" onClick={() => setOpen(false)}>
          <div className="w-full max-w-sm rounded-2xl bg-slab p-6 shadow-lg" onClick={(e) => e.stopPropagation()}>
            <h3 className="mb-4 font-display text-xl">Subscribe to alerts</h3>
            {done ? (
              <p className="text-sm text-clear">Subscribed! Manage this anytime under Account → Alerts.</p>
            ) : (
              <>
                <div className="mb-4">
                  <label className="mb-1.5 block text-sm font-medium">Commodity scope</label>
                  <div className="flex gap-2 text-sm">
                    <button
                      type="button"
                      onClick={() => setAnyCommodity(true)}
                      className={`rounded-md px-3 py-1.5 ${anyCommodity ? "bg-ink text-on-ink" : "border border-line"}`}
                    >
                      Any commodity
                    </button>
                    <button
                      type="button"
                      onClick={() => setAnyCommodity(false)}
                      disabled={!commodityId}
                      className={`rounded-md px-3 py-1.5 ${!anyCommodity ? "bg-ink text-on-ink" : "border border-line"} disabled:opacity-40`}
                    >
                      This commodity only
                    </button>
                  </div>
                </div>
                <div className="mb-5">
                  <label className="mb-1.5 block text-sm font-medium">Severity threshold</label>
                  <select className="w-full rounded-lg border border-line bg-slab px-3 py-2 text-sm" value={severity} onChange={(e) => setSeverity(e.target.value)}>
                    <option value="moderate">All alerts</option>
                    <option value="high">High risk only</option>
                    <option value="critical">Critical only</option>
                  </select>
                </div>
                <button
                  type="button"
                  disabled={create.isPending}
                  onClick={() =>
                    create.mutate(
                      {
                        district_id: districtId,
                        commodity_id: anyCommodity ? undefined : commodityId,
                        severity_threshold: severity,
                      },
                      { onSuccess: () => setDone(true) }
                    )
                  }
                  className="w-full rounded-lg bg-ink px-4 py-2.5 text-sm font-medium text-on-ink disabled:opacity-60"
                >
                  {create.isPending ? "Subscribing…" : "Subscribe"}
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
