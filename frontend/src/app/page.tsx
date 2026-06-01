"use client";

import { useEffect, useRef } from "react";
import AlertPanel from "@/components/AlertPanel";
import ConnectionStatus from "@/components/ConnectionStatus";
import EyeStateIndicator from "@/components/EyeStateIndicator";
import FatigueScore from "@/components/FatigueScore";
import MetricCard from "@/components/MetricCard";
import StatusBadge from "@/components/StatusBadge";
import { useDetection } from "@/hooks/useDetection";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/detect";
const ALARM_SCORE_THRESHOLD = 85;

type AlarmNodes = {
  masterGain: GainNode;
  sirenLfo: OscillatorNode;
  sirenLfoGain: GainNode;
  ampLfo: OscillatorNode;
  ampLfoGain: GainNode;
  carrierA: OscillatorNode;
  carrierB: OscillatorNode;
  carrierC: OscillatorNode;
};

export default function DashboardPage() {
  const {
    videoRef,
    canvasRef,
    isDetecting,
    connectionStatus,
    result,
    error,
    start,
    stop,
  } = useDetection(WS_URL);
  const audioContextRef = useRef<AudioContext | null>(null);
  const alarmNodesRef = useRef<AlarmNodes | null>(null);

  const stopAlarm = () => {
    const nodes = alarmNodesRef.current;
    if (!nodes) return;

    const now = audioContextRef.current?.currentTime ?? 0;
    nodes.masterGain.gain.cancelScheduledValues(now);
    nodes.masterGain.gain.setTargetAtTime(0.0001, now, 0.06);

    const stopAt = now + 0.18;
    nodes.sirenLfo.stop(stopAt);
    nodes.ampLfo.stop(stopAt);
    nodes.carrierA.stop(stopAt);
    nodes.carrierB.stop(stopAt);
    nodes.carrierC.stop(stopAt);

    alarmNodesRef.current = null;
  };

  const startAlarm = async () => {
    if (alarmNodesRef.current) return;

    const AudioCtx =
      window.AudioContext ||
      (window as Window & { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!AudioCtx) return;

    if (!audioContextRef.current) {
      audioContextRef.current = new AudioCtx();
    }
    const context = audioContextRef.current;
    if (context.state === "suspended") {
      await context.resume();
    }

    const now = context.currentTime;

    const highPass = context.createBiquadFilter();
    highPass.type = "highpass";
    highPass.frequency.setValueAtTime(620, now);
    highPass.Q.setValueAtTime(0.9, now);

    const compressor = context.createDynamicsCompressor();
    compressor.threshold.setValueAtTime(-26, now);
    compressor.knee.setValueAtTime(14, now);
    compressor.ratio.setValueAtTime(12, now);
    compressor.attack.setValueAtTime(0.003, now);
    compressor.release.setValueAtTime(0.12, now);

    const masterGain = context.createGain();
    masterGain.gain.setValueAtTime(0.0001, now);
    masterGain.gain.exponentialRampToValueAtTime(0.26, now + 0.12);
    masterGain.connect(context.destination);
    compressor.connect(masterGain);
    highPass.connect(compressor);

    const sirenLfo = context.createOscillator();
    sirenLfo.type = "triangle";
    sirenLfo.frequency.setValueAtTime(2.1, now);

    const sirenLfoGain = context.createGain();
    sirenLfoGain.gain.setValueAtTime(340, now);
    sirenLfo.connect(sirenLfoGain);

    const ampLfo = context.createOscillator();
    ampLfo.type = "square";
    ampLfo.frequency.setValueAtTime(6.4, now);

    const ampLfoGain = context.createGain();
    ampLfoGain.gain.setValueAtTime(0.09, now);
    ampLfo.connect(ampLfoGain);
    ampLfoGain.connect(masterGain.gain);

    const carrierA = context.createOscillator();
    carrierA.type = "square";
    carrierA.frequency.setValueAtTime(980, now);
    sirenLfoGain.connect(carrierA.frequency);
    carrierA.connect(highPass);

    const carrierB = context.createOscillator();
    carrierB.type = "sawtooth";
    carrierB.frequency.setValueAtTime(1320, now);
    sirenLfoGain.connect(carrierB.frequency);
    carrierB.connect(highPass);

    const carrierC = context.createOscillator();
    carrierC.type = "triangle";
    carrierC.frequency.setValueAtTime(680, now);
    sirenLfoGain.connect(carrierC.frequency);
    carrierC.connect(highPass);

    sirenLfo.start(now);
    ampLfo.start(now);
    carrierA.start(now);
    carrierB.start(now);
    carrierC.start(now);

    alarmNodesRef.current = {
      masterGain,
      sirenLfo,
      sirenLfoGain,
      ampLfo,
      ampLfoGain,
      carrierA,
      carrierB,
      carrierC,
    };
  };

  useEffect(() => {
    return () => {
      stopAlarm();
      if (audioContextRef.current) {
        void audioContextRef.current.close();
        audioContextRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    const score = result?.fatigue_score;
    const shouldAlarm =
      isDetecting && score != null && score > ALARM_SCORE_THRESHOLD;

    if (!shouldAlarm) {
      stopAlarm();
      return;
    }

    void startAlarm();
  }, [isDetecting, result]);

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 md:px-6">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-white">
            Real-Time Fatigue Detection
          </h1>
          <p className="mt-0.5 text-sm text-[#8e8e93]">
            Real-time fatigue detection - MediaPipe + CNN
          </p>
        </div>
        <ConnectionStatus status={connectionStatus} />
      </header>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(560px,1.35fr)_minmax(420px,0.9fr)]">
        <div className="flex flex-col gap-4">
          <div className="overflow-hidden rounded-xl border border-[#2c2c2e] bg-black">
            <div className="relative aspect-video w-full bg-black">
              <video
                ref={videoRef}
                autoPlay
                muted
                playsInline
                className="mirror h-full w-full object-contain"
              />

              {!isDetecting && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/60">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full border-2 border-[#2c2c2e]">
                    <svg
                      className="h-5 w-5 text-[#636366]"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={1.5}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9A2.25 2.25 0 0013.5 5.25h-9A2.25 2.25 0 002.25 7.5v9A2.25 2.25 0 004.5 18.75z"
                      />
                    </svg>
                  </div>
                  <p className="text-xs text-[#636366]">Camera inactive</p>
                </div>
              )}

              {isDetecting && (
                <div className="absolute left-3 top-3 flex items-center gap-1.5 rounded-full bg-black/60 px-2.5 py-1 backdrop-blur-sm">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#ff3b30]" />
                  <span className="text-[10px] font-medium uppercase tracking-widest text-white">
                    Live
                  </span>
                </div>
              )}
            </div>
          </div>

          <div className="flex gap-3">
            <button
              id="btn-start"
              onClick={start}
              disabled={isDetecting}
              className="btn btn-primary flex-1"
            >
              Start Detection
            </button>
            <button
              id="btn-stop"
              onClick={stop}
              disabled={!isDetecting}
              className="btn btn-secondary flex-1"
            >
              Stop Detection
            </button>
          </div>

          {error && (
            <div
              role="alert"
              className="rounded-xl border border-[#ff3b30]/30 bg-[#ff3b30]/10 px-4 py-3"
            >
              <p className="text-sm text-[#ff3b30]">{error}</p>
            </div>
          )}

          {result && (
            <div className="rounded-xl border border-[#2c2c2e] bg-[#1c1c1e] px-4 py-3">
              <div className="flex items-center justify-between text-xs text-[#636366]">
                <span>Last update</span>
                <span className="font-mono">
                  {new Date(result.timestamp).toLocaleTimeString()}
                </span>
              </div>
              <div className="mt-1.5 flex items-center justify-between text-xs text-[#636366]">
                <span>Face detected</span>
                <span
                  className={`font-mono font-medium ${
                    result.face_detected ? "text-[#30d158]" : "text-[#ff3b30]"
                  }`}
                >
                  {result.face_detected ? "Yes" : "No"}
                </span>
              </div>
            </div>
          )}
        </div>

        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <FatigueScore score={result?.fatigue_score ?? null} />
            <div className="flex min-h-[150px] items-center justify-center rounded-xl border border-[#2c2c2e] bg-[#1c1c1e] px-4 py-5">
              <StatusBadge status={result?.status ?? null} />
            </div>

            <EyeStateIndicator
              eyeClosed={result?.eye_closed ?? null}
              yawnDetected={result?.yawn_detected ?? false}
              mode="eye"
            />
            <EyeStateIndicator
              eyeClosed={result?.eye_closed ?? null}
              yawnDetected={result?.yawn_detected ?? false}
              mode="yawn"
            />
          </div>

          <div className="flex items-center gap-3">
            <div className="h-px flex-1 bg-[#2c2c2e]" />
            <span className="text-[10px] font-medium uppercase tracking-widest text-[#48484a]">
              Fatigue Indicators
            </span>
            <div className="h-px flex-1 bg-[#2c2c2e]" />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <MetricCard
              label="PERCLOS"
              value={result?.perclos != null ? result.perclos * 100 : null}
              unit="%"
              precision={1}
            />
            <MetricCard
              label="Blink Rate"
              value={result?.blink_rate ?? null}
              unit="/min"
              precision={1}
            />
            <MetricCard
              label="Yawn Count"
              value={result?.yawn_count ?? null}
              precision={0}
            />
          </div>

          {!result && (
            <div className="rounded-xl border border-[#2c2c2e] bg-[#1c1c1e] px-5 py-6 text-center">
              <p className="text-sm font-medium text-[#8e8e93]">
                Click <span className="text-white">Start Detection</span> to begin
              </p>
              <p className="mt-1 text-xs text-[#636366]">
                Allow camera access when prompted. Start the backend on port 8000 first.
              </p>
            </div>
          )}
        </div>
      </div>

      {result && (result.status === "ALERT" || result.status === "CRITICAL") && (
        <AlertPanel status={result.status} fatigueScore={result.fatigue_score} />
      )}

      <canvas ref={canvasRef} className="hidden" aria-hidden="true" />
    </div>
  );
}
