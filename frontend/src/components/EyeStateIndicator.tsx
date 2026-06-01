interface EyeStateIndicatorProps {
  eyeClosed: boolean | null;
  yawnDetected: boolean;
}

export default function EyeStateIndicator({
  eyeClosed,
  yawnDetected,
}: EyeStateIndicatorProps) {
  const eyeColor =
    eyeClosed === null ? "#48484a" : eyeClosed ? "#ff3b30" : "#30d158";
  const eyeLabel = eyeClosed === null ? "-" : eyeClosed ? "Closed" : "Open";

  return (
    <div className="flex gap-2">
      <div className="flex flex-1 flex-col items-center justify-center rounded-xl border border-[#2c2c2e] bg-[#1c1c1e] py-3">
        <p className="text-[10px] font-medium uppercase tracking-widest text-[#636366]">
          Eye State
        </p>
        <div className="mt-1.5 flex items-center gap-1.5">
          <span
            className="h-2.5 w-2.5 rounded-full"
            style={{ backgroundColor: eyeColor }}
          />
          <span className="text-sm font-semibold" style={{ color: eyeColor }}>
            {eyeLabel}
          </span>
        </div>
      </div>

      <div
        className={`flex flex-1 flex-col items-center justify-center rounded-xl border py-3 transition-colors ${
          yawnDetected
            ? "border-[#ff9f0a]/30 bg-[#ff9f0a]/10"
            : "border-[#2c2c2e] bg-[#1c1c1e]"
        }`}
      >
        <p className="text-[10px] font-medium uppercase tracking-widest text-[#636366]">
          Yawn
        </p>
        <div className="mt-1.5 flex items-center gap-1.5">
          <span
            className={`h-2.5 w-2.5 rounded-full ${
              yawnDetected ? "bg-[#ff9f0a] animate-pulse" : "bg-[#48484a]"
            }`}
          />
          <span
            className={`text-sm font-semibold ${
              yawnDetected ? "text-[#ff9f0a]" : "text-[#636366]"
            }`}
          >
            {yawnDetected ? "Active" : "None"}
          </span>
        </div>
      </div>
    </div>
  );
}
