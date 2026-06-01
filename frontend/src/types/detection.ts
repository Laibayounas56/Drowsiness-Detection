export type DetectionStatus = "NORMAL" | "ALERT" | "CRITICAL" | "NO_FACE";

export interface DetectionResult {
  frame_id: number;
  client_sent_at: number;
  server_received_at: number;
  server_processed_at: number;
  processing_ms: number;
  face_detected: boolean;
  status: DetectionStatus;
  fatigue_score: number | null;
  ear: number | null;
  mar: number | null;
  eye_closed: boolean | null;
  open_probability: number | null;
  closed_confidence: number | null;
  blink_count: number;
  blink_rate: number;
  yawn_count: number;
  yawn_detected: boolean;
  perclos: number;
  timestamp: string;
}

export interface DetectionStats {
  framesSent: number;
  framesSkipped: number;
  lastProcessedFrameId: number | null;
  roundTripLatencyMs: number | null;
  backendProcessingMs: number | null;
  currentFps: number | null;
}

export interface WsError {
  error: string;
  detail?: string;
  message?: string;
}

export type ConnectionStatus =
  | "disconnected"
  | "connecting"
  | "connected"
  | "error";
