import type { DetectionStatus } from "@/types/detection";

interface AlertPanelProps {
  status: DetectionStatus;
  fatigueScore: number | null;
}

const MESSAGES: Record<"ALERT" | "CRITICAL", { title: string; body: string }> = {
  ALERT: {
    title: "Fatigue Warning",
    body: "Elevated fatigue indicators detected. Consider taking a short break.",
  },
  CRITICAL: {
    title: "Critical Fatigue Level",
    body: "High drowsiness risk detected. Stop driving and rest immediately.",
  },
};

export default function AlertPanel({ status, fatigueScore }: AlertPanelProps) {
  if (status !== "ALERT" && status !== "CRITICAL") return null;

  const message = MESSAGES[status];
  const isCritical = status === "CRITICAL";

  return (
    <div
      role="alert"
      className={`mt-4 flex items-start gap-4 rounded-xl border px-5 py-4 ${
        isCritical
          ? "border-[#ff3b30]/30 bg-[#ff3b30]/10"
          : "border-[#ff9f0a]/30 bg-[#ff9f0a]/10"
      }`}
    >
      <div
        className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold ${
          isCritical
            ? "bg-[#ff3b30]/20 text-[#ff3b30]"
            : "bg-[#ff9f0a]/20 text-[#ff9f0a]"
        }`}
      >
        !
      </div>

      <div className="flex-1">
        <p
          className={`text-sm font-semibold ${
            isCritical ? "text-[#ff3b30]" : "text-[#ff9f0a]"
          }`}
        >
          {message.title}
          {fatigueScore !== null && (
            <span className="ml-2 font-mono font-normal opacity-70">
              score: {fatigueScore.toFixed(1)}
            </span>
          )}
        </p>
        <p className="mt-0.5 text-sm text-[#8e8e93]">{message.body}</p>
      </div>
    </div>
  );
}
