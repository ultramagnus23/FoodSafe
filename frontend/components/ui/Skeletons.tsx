function Shimmer({ className }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-border ${className || ""}`} />;
}

export function SkeletonDistrictCard() {
  return (
    <div className="rounded-lg border border-border bg-bg-card p-6">
      <Shimmer className="mb-3 h-6 w-1/2" />
      <Shimmer className="mb-2 h-4 w-1/3" />
      <Shimmer className="h-16 w-full" />
    </div>
  );
}

export function SkeletonMapLegend() {
  return (
    <div className="flex gap-4">
      <Shimmer className="h-4 w-24" />
      <Shimmer className="h-4 w-24" />
      <Shimmer className="h-4 w-24" />
    </div>
  );
}

export function SkeletonAlertRow() {
  return (
    <div className="rounded-lg border border-border bg-bg-card p-4">
      <Shimmer className="mb-2 h-4 w-2/3" />
      <Shimmer className="h-3 w-1/3" />
    </div>
  );
}
