"use client";

import { useMemo, useState } from "react";
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Bar,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  CartesianGrid,
} from "recharts";
import { useDistrictTrend } from "@/lib/api/trends";

type Range = "1Y" | "2Y" | "5Y" | "All";
const RANGE_MONTHS: Record<Range, number | null> = { "1Y": 12, "2Y": 24, "5Y": 60, All: null };

interface TrendChartProps {
  districtId: number;
  commodityId: number;
  fssaiLimitPpb?: number | null;
  codexLimitPpb?: number | null;
}

export function TrendChart({ districtId, commodityId, fssaiLimitPpb, codexLimitPpb }: TrendChartProps) {
  const [range, setRange] = useState<Range>("2Y");
  const trend = useDistrictTrend(districtId, commodityId);

  const data = useMemo(() => {
    if (!trend.data) return [];
    const months = RANGE_MONTHS[range];
    const series = months ? trend.data.series.slice(-months) : trend.data.series;
    // Approximate a +-1 SD band around mean using max_ppb as a rough upper
    // bound proxy (the API doesn't return per-month SD — this is a visual
    // aid, not a statistical claim; see disclaimer).
    return series.map((p) => ({
      month: p.month.slice(0, 7),
      mean_ppb: p.mean_ppb,
      band_low: Math.max(0, p.mean_ppb - (p.max_ppb - p.mean_ppb) * 0.3),
      band_high: p.mean_ppb + (p.max_ppb - p.mean_ppb) * 0.3,
      n_records: p.n_records,
    }));
  }, [trend.data, range]);

  if (trend.isLoading) return <p className="text-sm text-muted">Loading trend…</p>;
  if (!trend.data || trend.data.trend === "insufficient_data") {
    return (
      <p className="text-sm text-muted">
        Not enough monthly data yet to detect a trend (needs 6+ months with a statistically significant
        Mann-Kendall result).
      </p>
    );
  }

  const { trend: direction, trend_pvalue, trend_magnitude } = trend.data;
  const arrow = direction === "worsening" ? "▲" : direction === "improving" ? "▼" : "→";
  const color = direction === "worsening" ? "var(--red)" : direction === "improving" ? "var(--sage)" : "var(--muted)";

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm" style={{ color }}>
          <span className="text-lg">{arrow}</span>
          <span className="font-medium capitalize">{direction}</span>
          {trend_magnitude != null && (
            <span className="font-mono text-xs text-muted">
              ({trend_magnitude > 0 ? "+" : ""}
              {trend_magnitude.toFixed(2)} PPB/month, p={trend_pvalue?.toFixed(3)})
            </span>
          )}
        </div>
        <div className="flex rounded-lg border border-border p-0.5">
          {(Object.keys(RANGE_MONTHS) as Range[]).map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setRange(r)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                range === r ? "bg-forest text-white" : "text-muted"
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="month" fontSize={11} stroke="var(--muted)" />
          <YAxis yAxisId="ppb" fontSize={11} stroke="var(--muted)" />
          <YAxis yAxisId="n" orientation="right" fontSize={11} stroke="var(--muted)" />
          <Tooltip
            contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", fontSize: 12 }}
          />
          <Area
            yAxisId="ppb"
            dataKey="band_high"
            stroke="none"
            fill="var(--forest-pale)"
            fillOpacity={0.6}
            isAnimationActive={false}
          />
          <Bar yAxisId="n" dataKey="n_records" fill="var(--border)" barSize={10} />
          <Line yAxisId="ppb" type="monotone" dataKey="mean_ppb" stroke="var(--forest)" strokeWidth={2} dot={false} />
          {fssaiLimitPpb != null && (
            <ReferenceLine yAxisId="ppb" y={fssaiLimitPpb} stroke="var(--red)" strokeDasharray="4 4" />
          )}
          {codexLimitPpb != null && (
            <ReferenceLine yAxisId="ppb" y={codexLimitPpb} stroke="var(--amber)" strokeDasharray="4 4" />
          )}
        </ComposedChart>
      </ResponsiveContainer>
      <div className="mt-2 flex gap-4 text-xs text-muted">
        <span>
          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-forest" /> Mean PPB
        </span>
        {fssaiLimitPpb != null && (
          <span>
            <span className="mr-1 inline-block h-0.5 w-3 bg-red align-middle" /> FSSAI limit
          </span>
        )}
        {codexLimitPpb != null && (
          <span>
            <span className="mr-1 inline-block h-0.5 w-3 bg-amber align-middle" /> Codex limit
          </span>
        )}
      </div>
    </div>
  );
}
