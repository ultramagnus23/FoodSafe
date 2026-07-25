"use client";

import { useState } from "react";
import { useDistricts, useCommodities, useLocalityByPincode } from "@/lib/api/search";
import { useSubmitReport } from "@/lib/api/reports";

export default function ReportPage() {
  const districts = useDistricts(true);
  const commodities = useCommodities(true);
  const submit = useSubmitReport();

  const [description, setDescription] = useState("");
  const [email, setEmail] = useState("");
  const [districtId, setDistrictId] = useState<number | "">("");
  const [commodityId, setCommodityId] = useState<number | "">("");
  const [contaminant, setContaminant] = useState("");
  const [pincode, setPincode] = useState("");

  const tooShort = description.trim().length > 0 && description.trim().length < 10;
  const locality = useLocalityByPincode(pincode);
  const resolvedLocality = locality.data && locality.data.length > 0 ? locality.data[0] : null;

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (description.trim().length < 10) return;
    submit.mutate({
      description: description.trim(),
      reporter_email: email.trim() || undefined,
      district_id: districtId === "" ? undefined : districtId,
      commodity_id: commodityId === "" ? undefined : commodityId,
      contaminant_suspected: contaminant.trim() || undefined,
      pincode: /^\d{6}$/.test(pincode) ? pincode : undefined,
    });
  }

  if (submit.isSuccess) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-20 text-center">
        <h1 className="mb-4 font-display text-3xl font-light">Report received</h1>
        <p className="text-provenance">{submit.data.message}</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl px-6 py-12">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-ink">Report an Issue</div>
      <h1 className="mb-4 font-display text-4xl font-light leading-tight">Tell us what you saw</h1>
      <p className="mb-8 text-provenance">
        This is a consumer report, not a lab test. It is a low-credibility, high-volume signal, reviewed by our
        team before it ever appears anywhere on the platform. We will never publish an accusation against a
        specific brand or manufacturer from a report alone.
      </p>

      <form onSubmit={onSubmit} className="grid gap-4">
        <label className="grid gap-1.5 text-sm">
          <span className="font-medium">What happened? *</span>
          <textarea
            className="min-h-[120px] rounded-lg border border-line bg-slab px-4 py-3 outline-none focus:border-ink"
            placeholder="Describe what you noticed: product, place, symptoms, anything relevant. No need to name a specific brand."
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
          />
          {tooShort && <span className="text-xs text-risk">Please add a bit more detail (at least 10 characters).</span>}
        </label>

        <label className="grid gap-1.5 text-sm">
          <span className="font-medium">Pincode (optional, most precise)</span>
          <input
            className="rounded-lg border border-line bg-slab px-4 py-2 outline-none focus:border-ink"
            placeholder="e.g. 400049"
            inputMode="numeric"
            maxLength={6}
            value={pincode}
            onChange={(e) => setPincode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          />
          {resolvedLocality && (
            <span className="text-xs text-provenance">
              Matched to {resolvedLocality.name}, {resolvedLocality.district_name} — this report will be tagged at
              the locality level, not just the district.
            </span>
          )}
          {!resolvedLocality && /^\d{6}$/.test(pincode) && !locality.isLoading && (
            <span className="text-xs text-provenance">
              We don&apos;t have this pincode mapped to a locality yet — the report will still be tagged to the
              district you pick below.
            </span>
          )}
        </label>

        <label className="grid gap-1.5 text-sm">
          <span className="font-medium">District (optional)</span>
          <select
            className="rounded-lg border border-line bg-slab px-3 py-2"
            value={districtId}
            onChange={(e) => setDistrictId(e.target.value ? Number(e.target.value) : "")}
          >
            <option value="">Not specified</option>
            {(districts.data || []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}, {d.state}
              </option>
            ))}
          </select>
        </label>

        <label className="grid gap-1.5 text-sm">
          <span className="font-medium">Commodity (optional)</span>
          <select
            className="rounded-lg border border-line bg-slab px-3 py-2"
            value={commodityId}
            onChange={(e) => setCommodityId(e.target.value ? Number(e.target.value) : "")}
          >
            <option value="">Not specified</option>
            {(commodities.data || []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>

        <label className="grid gap-1.5 text-sm">
          <span className="font-medium">Suspected contaminant (optional)</span>
          <input
            className="rounded-lg border border-line bg-slab px-4 py-2 outline-none focus:border-ink"
            placeholder="e.g. mislabeled ingredient, off smell/taste, foreign object"
            value={contaminant}
            onChange={(e) => setContaminant(e.target.value)}
          />
        </label>

        <label className="grid gap-1.5 text-sm">
          <span className="font-medium">Your email (optional, for follow-up only, never shown publicly)</span>
          <input
            type="email"
            className="rounded-lg border border-line bg-slab px-4 py-2 outline-none focus:border-ink"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>

        {submit.isError && <p className="text-sm text-risk">Something went wrong. Please try again.</p>}

        <button
          type="submit"
          disabled={submit.isPending || description.trim().length < 10}
          className="rounded-md bg-ink px-4 py-2.5 text-sm font-medium text-on-ink disabled:opacity-60"
        >
          {submit.isPending ? "Submitting…" : "Submit report"}
        </button>
      </form>
    </div>
  );
}
