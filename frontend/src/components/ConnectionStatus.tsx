import type { ConnectionStatus } from "@/types/detection";

interface ConnectionStatusProps {
  status: ConnectionStatus;
}

const CONFIG: Record<
  ConnectionStatus,
  { label: string; dot: string; text: string }
> = {
  disconnected: {
    label: "Disconnected",
    dot: "bg-[#48484a]",
    text: "text-[#636366]",
  },
  connecting: {
    label: "Connecting...",
    dot: "bg-[#ff9f0a] animate-pulse",
    text: "text-[#ff9f0a]",
  },
  connected: {
    label: "Connected",
    dot: "bg-[#30d158]",
    text: "text-[#30d158]",
  },
  error: {
    label: "Connection Error",
    dot: "bg-[#ff3b30]",
    text: "text-[#ff3b30]",
  },
};

export default function ConnectionStatus({ status }: ConnectionStatusProps) {
  const config = CONFIG[status];

  return (
    <div className="flex items-center gap-2 rounded-full border border-[#2c2c2e] bg-[#1c1c1e] px-3 py-1.5">
      <span className={`h-2 w-2 rounded-full ${config.dot}`} />
      <span className={`text-xs font-medium ${config.text}`}>{config.label}</span>
    </div>
  );
}
