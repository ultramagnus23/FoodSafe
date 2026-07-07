"use client";

import { useEffect, useRef, useState } from "react";

interface TimeScrubberProps {
  quarters: string[];
  value: string;
  onChange: (quarter: string) => void;
  /** Runs through the range once on mount, then stops on the latest quarter.
   *  Used for the landing-page hero moment. Reduced-motion shows the final
   *  state immediately, per the brief. */
  autoPlayOnce?: boolean;
}

function usesReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function TimeScrubber({ quarters, value, onChange, autoPlayOnce }: TimeScrubberProps) {
  const [playing, setPlaying] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const index = Math.max(0, quarters.indexOf(value));

  useEffect(() => {
    if (!autoPlayOnce || quarters.length < 2) return;
    if (usesReducedMotion()) {
      onChange(quarters[quarters.length - 1]);
      return;
    }
    let i = 0;
    onChange(quarters[0]);
    const step = () => {
      i += 1;
      if (i >= quarters.length) return;
      onChange(quarters[i]);
      if (i < quarters.length - 1) timerRef.current = setTimeout(step, 550);
    };
    timerRef.current = setTimeout(step, 550);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoPlayOnce, quarters.length]);

  useEffect(() => {
    if (!playing) return;
    if (index >= quarters.length - 1) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => onChange(quarters[index + 1]), 500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, index, quarters.length]);

  if (quarters.length === 0) return null;

  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={() => setPlaying((p) => !p)}
        className="register rounded border border-line px-2.5 py-1 text-[11px] uppercase tracking-wide text-provenance hover:border-line-strong hover:text-ink"
      >
        {playing ? "Pause" : "Play"}
      </button>
      <input
        type="range"
        min={0}
        max={quarters.length - 1}
        step={1}
        value={index}
        onChange={(e) => onChange(quarters[Number(e.target.value)])}
        className="h-1 flex-1 cursor-pointer appearance-none rounded-full bg-line accent-ink"
        aria-label="Quarter"
      />
      <span className="register w-16 shrink-0 text-xs text-provenance">{value}</span>
    </div>
  );
}
