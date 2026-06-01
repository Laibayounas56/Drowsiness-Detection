"use client";

import { useCallback, useRef, useState } from "react";
import type { RefObject } from "react";
import type {
  ConnectionStatus,
  DetectionResult,
  DetectionStats,
  WsError,
} from "@/types/detection";

const FRAME_INTERVAL_MS = 200;
const JPEG_QUALITY = 0.6;
const JPEG_MAX_WIDTH = 640;
const MAX_BUFFERED_BYTES = 750_000;

const EMPTY_STATS: DetectionStats = {
  framesSent: 0,
  framesSkipped: 0,
  lastProcessedFrameId: null,
  roundTripLatencyMs: null,
  backendProcessingMs: null,
  currentFps: null,
};

export interface UseDetectionReturn {
  videoRef: RefObject<HTMLVideoElement | null>;
  canvasRef: RefObject<HTMLCanvasElement | null>;
  isDetecting: boolean;
  connectionStatus: ConnectionStatus;
  result: DetectionResult | null;
  stats: DetectionStats;
  error: string | null;
  start: () => Promise<void>;
  stop: () => void;
}

export function useDetection(wsUrl: string): UseDetectionReturn {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const shouldDetectRef = useRef(false);
  const inFlightRef = useRef(false);
  const nextFrameIdRef = useRef(1);
  const latestDisplayedFrameIdRef = useRef(0);
  const responseTimesRef = useRef<number[]>([]);

  const [isDetecting, setIsDetecting] = useState(false);
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("disconnected");
  const [result, setResult] = useState<DetectionResult | null>(null);
  const [stats, setStats] = useState<DetectionStats>(EMPTY_STATS);
  const [error, setError] = useState<string | null>(null);

  const clearCaptureLoop = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    inFlightRef.current = false;
  }, []);

  const releaseResources = useCallback(() => {
    clearCaptureLoop();

    if (reconnectTimeoutRef.current !== null) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }

    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }

  }, [clearCaptureLoop]);

  const stop = useCallback(() => {
    shouldDetectRef.current = false;
    releaseResources();

    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.close();
      wsRef.current = null;
    }

    setIsDetecting(false);
    setConnectionStatus("disconnected");
    setResult(null);
  }, [releaseResources]);

  const incrementSkipped = useCallback(() => {
    setStats((current) => ({
      ...current,
      framesSkipped: current.framesSkipped + 1,
    }));
  }, []);

  const start = useCallback(async () => {
    if (isDetecting || connectionStatus === "connecting") return;

    setError(null);
    setResult(null);
    setStats(EMPTY_STATS);
    setConnectionStatus("connecting");
    shouldDetectRef.current = true;
    inFlightRef.current = false;
    nextFrameIdRef.current = 1;
    latestDisplayedFrameIdRef.current = 0;
    responseTimesRef.current = [];

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: {
          width: { ideal: 640 },
          height: { ideal: 480 },
          facingMode: "user",
          frameRate: { ideal: 15, max: 30 },
        },
        audio: false,
      });
    } catch {
      setError("Camera access denied. Allow camera permission and try again.");
      setConnectionStatus("error");
      shouldDetectRef.current = false;
      return;
    }

    streamRef.current = stream;
    if (videoRef.current) {
      videoRef.current.srcObject = stream;
    }

    setIsDetecting(true);

    const openSocket = (attempt: number) => {
      if (!shouldDetectRef.current) return;

      let ws: WebSocket;
      try {
        ws = new WebSocket(wsUrl);
      } catch {
        setError(`Invalid WebSocket URL: ${wsUrl}. Check NEXT_PUBLIC_WS_URL.`);
        setConnectionStatus("error");
        shouldDetectRef.current = false;
        setIsDetecting(false);
        releaseResources();
        return;
      }

      wsRef.current = ws;

      ws.onopen = () => {
        setError(null);
        setConnectionStatus("connected");
        clearCaptureLoop();

        intervalRef.current = setInterval(() => {
          const video = videoRef.current;
          const canvas = canvasRef.current;

          if (!video || !canvas || ws.readyState !== WebSocket.OPEN) return;
          if (video.readyState < HTMLMediaElement.HAVE_ENOUGH_DATA) return;

          if (inFlightRef.current || ws.bufferedAmount > MAX_BUFFERED_BYTES) {
            incrementSkipped();
            return;
          }

          const sourceWidth = video.videoWidth || 640;
          const sourceHeight = video.videoHeight || 480;
          const scale = Math.min(1, JPEG_MAX_WIDTH / sourceWidth);
          canvas.width = Math.round(sourceWidth * scale);
          canvas.height = Math.round(sourceHeight * scale);

          const ctx = canvas.getContext("2d");
          if (!ctx) return;

          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

          const frameId = nextFrameIdRef.current;
          const clientSentAt = Date.now();
          const dataUrl = canvas.toDataURL("image/jpeg", JPEG_QUALITY);

          inFlightRef.current = true;
          nextFrameIdRef.current += 1;
          setStats((current) => ({
            ...current,
            framesSent: current.framesSent + 1,
          }));

          ws.send(
            JSON.stringify({
              frame_id: frameId,
              client_sent_at: clientSentAt,
              image: dataUrl,
            })
          );
        }, FRAME_INTERVAL_MS);
      };

      ws.onmessage = (evt: MessageEvent) => {
        inFlightRef.current = false;

        try {
          const data = JSON.parse(evt.data as string) as DetectionResult | WsError;
          if ("error" in data) {
            console.warn("[WS] Backend error:", data.error, data.detail ?? "");
            if (data.error === "model_not_loaded") {
              setError(data.message ?? "Backend model files are missing.");
              stop();
            }
            return;
          }

          if (data.frame_id <= latestDisplayedFrameIdRef.current) {
            return;
          }

          latestDisplayedFrameIdRef.current = data.frame_id;
          const receivedAt = Date.now();
          const roundTripLatencyMs = Math.max(0, receivedAt - data.client_sent_at);

          responseTimesRef.current = [
            ...responseTimesRef.current.filter((value) => receivedAt - value <= 5000),
            receivedAt,
          ];
          const currentFps =
            responseTimesRef.current.length > 1
              ? (responseTimesRef.current.length - 1) /
                ((responseTimesRef.current.at(-1)! - responseTimesRef.current[0]) / 1000)
              : 0;

          setResult(data);
          setStats((current) => ({
            ...current,
            lastProcessedFrameId: data.frame_id,
            roundTripLatencyMs,
            backendProcessingMs: data.processing_ms,
            currentFps: Number.isFinite(currentFps) ? currentFps : 0,
          }));
        } catch {
          console.warn("[WS] Could not parse message:", evt.data);
        }
      };

      ws.onerror = () => {
        setError(
          "Backend connection interrupted. Reconnecting if detection is still running."
        );
        setConnectionStatus("error");
      };

      ws.onclose = () => {
        if (wsRef.current !== ws) return;

        wsRef.current = null;
        clearCaptureLoop();

        if (shouldDetectRef.current && attempt < 3) {
          setConnectionStatus("connecting");
          reconnectTimeoutRef.current = setTimeout(() => {
            reconnectTimeoutRef.current = null;
            openSocket(attempt + 1);
          }, 750 * (attempt + 1));
          return;
        }

        shouldDetectRef.current = false;
        setConnectionStatus("disconnected");
        setIsDetecting(false);
        releaseResources();
      };
    };

    openSocket(0);
  }, [
    clearCaptureLoop,
    connectionStatus,
    incrementSkipped,
    isDetecting,
    releaseResources,
    stop,
    wsUrl,
  ]);

  return {
    videoRef,
    canvasRef,
    isDetecting,
    connectionStatus,
    result,
    stats,
    error,
    start,
    stop,
  };
}
