export function Skeleton({ className = "", style }: { className?: string; style?: React.CSSProperties }) {
  return (
    <div
      className={`animate-pulse rounded-lg bg-slate-200 ${className}`}
      style={style}
      aria-hidden="true"
    />
  );
}

export function KpiCardSkeleton() {
  return (
    <div className="bg-white p-6 rounded-xl shadow-card border border-slate-100">
      <Skeleton className="h-4 w-24 mb-3" />
      <Skeleton className="h-8 w-36 mb-3" />
      <Skeleton className="h-5 w-16 rounded-md" />
    </div>
  );
}

export function TableRowSkeleton({ cols = 7 }: { cols?: number }) {
  return (
    <tr>
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="py-4 px-6">
          <Skeleton className={`h-4 ${i === 0 ? "w-8" : i < 3 ? "w-24" : "w-16"}`} />
        </td>
      ))}
    </tr>
  );
}

export function ChartSkeleton() {
  return (
    <div className="bg-white rounded-xl p-6 shadow-card border border-slate-100 h-96 flex flex-col">
      <Skeleton className="h-5 w-32 mb-6" />
      <div className="flex-1 flex items-end gap-4 px-2">
        {[40, 65, 45, 80, 55, 70, 50, 60, 75, 45, 55, 35].map((h, i) => (
          <Skeleton key={i} className="flex-1 rounded-t-md rounded-b-none" style={{ height: `${h}%` }} />
        ))}
      </div>
    </div>
  );
}
