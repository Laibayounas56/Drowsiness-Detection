interface MetricCardProps {
  label: string;
  value: number | null;
  unit?: string;
  precision?: number;
  highlight?: boolean;
}

export default function MetricCard({
  label,
  value,
  unit = "",
  precision = 3,
  highlight = false,
}: MetricCardProps) {
  const display =
    value === null ? "-" : value.toFixed(precision) + (unit ? ` ${unit}` : "");

  return (
    <div
      className={`rounded-xl border px-5 py-4 transition-colors ${
        highlight
          ? "border-[#2c2c2e] bg-[#1c1c1e]/80"
          : "border-[#2c2c2e] bg-[#1c1c1e]"
      }`}
    >
      <p className="text-[10px] font-medium uppercase tracking-widest text-[#636366]">
        {label}
      </p>
      <p className="mt-2 font-mono text-xl font-semibold leading-none text-white">
        {display}
      </p>
    </div>
  );
}
