interface FatigueScoreProps {
  score: number | null;
}

function getScoreColor(score: number): string {
  if (score >= 70) return "#ff3b30";
  if (score >= 40) return "#ff9f0a";
  return "#30d158";
}

function getScoreLabel(score: number): string {
  if (score >= 70) return "Critical";
  if (score >= 40) return "Alert";
  return "Normal";
}

export default function FatigueScore({ score }: FatigueScoreProps) {
  const hasScore = score !== null;
  const color = hasScore ? getScoreColor(score) : "#48484a";
  const label = hasScore ? getScoreLabel(score) : "-";
  const percentage = hasScore ? Math.min(score, 100) : 0;

  const radius = 52;
  const center = 64;
  const circumference = 2 * Math.PI * radius;
  const dash = (percentage / 100) * circumference;

  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded-xl border border-[#2c2c2e] bg-[#1c1c1e] py-4">
      <p className="text-[10px] font-medium uppercase tracking-widest text-[#636366]">
        Fatigue Score
      </p>

      <div className="relative">
        <svg width="128" height="128" viewBox="0 0 128 128">
          <circle
            cx={center}
            cy={center}
            r={radius}
            fill="none"
            stroke="#2c2c2e"
            strokeWidth="8"
          />
          <circle
            cx={center}
            cy={center}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circumference}`}
            strokeDashoffset={0}
            transform={`rotate(-90 ${center} ${center})`}
            style={{
              transition: "stroke-dasharray 0.4s ease, stroke 0.4s ease",
            }}
          />
        </svg>

        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span
            className="font-mono text-2xl font-bold leading-none"
            style={{ color }}
          >
            {hasScore ? score.toFixed(0) : "-"}
          </span>
          <span className="mt-0.5 text-[10px] text-[#636366]">{label}</span>
        </div>
      </div>
    </div>
  );
}
