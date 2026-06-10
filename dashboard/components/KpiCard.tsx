// KpiCard — a single labeled metric tile (label, value, optional hint +
// accent highlight) used on the Overview KPI grid.
export function KpiCard({
  label,
  value,
  hint,
  accent = false,
}: {
  label: string;
  value: string;
  hint?: string;
  accent?: boolean;
}) {
  return (
    <div className="border border-border rounded-md bg-bg-surface px-4 py-3">
      <div className="text-[10px] uppercase tracking-widest text-fg-subtle">{label}</div>
      <div
        className={`mt-1 text-2xl font-mono font-medium ${
          accent ? "text-accent" : "text-fg"
        }`}
      >
        {value}
      </div>
      {hint && <div className="text-xs text-fg-muted mt-1">{hint}</div>}
    </div>
  );
}
