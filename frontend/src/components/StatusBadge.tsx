// components/StatusBadge.tsx
import type { DetectionStatus } from "@/types/detection";

interface Props {
  status: DetectionStatus | null;
}

const CONFIG: Record<
  DetectionStatus,
  { label: string; dot: string; badge: string; pulse: boolean }
> = {
  NORMAL: {
    label: "Normal",
    dot:   "bg-[#30d158]",
    badge: "bg-[#30d158]/10 text-[#30d158] ring-[#30d158]/30",
    pulse: false,
  },
  ALERT: {
    label: "Alert",
    dot:   "bg-[#ff9f0a]",
    badge: "bg-[#ff9f0a]/10 text-[#ff9f0a] ring-[#ff9f0a]/30",
    pulse: false,
  },
  CRITICAL: {
    label: "Critical",
    dot:   "bg-[#ff3b30]",
    badge: "bg-[#ff3b30]/10 text-[#ff3b30] ring-[#ff3b30]/30",
    pulse: true,
  },
  NO_FACE: {
    label: "No Face",
    dot:   "bg-[#636366]",
    badge: "bg-[#636366]/10 text-[#636366] ring-[#636366]/30",
    pulse: false,
  },
};

export default function StatusBadge({ status }: Props) {
  if (!status) {
    return (
      <div className="flex flex-col items-center gap-2">
        <span className="text-xs font-medium uppercase tracking-widest text-[#48484a]">
          Status
        </span>
        <span className="inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-sm font-semibold ring-1 ring-inset bg-[#1c1c1e] text-[#48484a] ring-[#2c2c2e]">
          <span className="h-2 w-2 rounded-full bg-[#48484a]" />
          Idle
        </span>
      </div>
    );
  }

  const cfg = CONFIG[status];

  return (
    <div className="flex flex-col items-center gap-2">
      <span className="text-xs font-medium uppercase tracking-widest text-[#8e8e93]">
        Status
      </span>
      <span
        className={`inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-sm font-semibold ring-1 ring-inset ${cfg.badge}`}
      >
        <span
          className={`h-2 w-2 rounded-full ${cfg.dot} ${
            cfg.pulse ? "animate-pulse" : ""
          }`}
        />
        {cfg.label}
      </span>
    </div>
  );
}
