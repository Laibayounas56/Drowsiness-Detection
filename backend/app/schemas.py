"""Pydantic models for API contracts."""

from typing import Any, List, Optional

from pydantic import BaseModel


class DetectionResult(BaseModel):
    frame_id: int
    client_sent_at: float
    server_received_at: float
    server_processed_at: float
    processing_ms: float
    face_detected: bool
    status: str
    fatigue_score: Optional[float]
    ear: Optional[float]
    mar: Optional[float]
    eye_closed: Optional[bool]
    open_probability: Optional[float]
    closed_confidence: Optional[float]
    blink_count: int
    blink_rate: float
    yawn_count: int
    yawn_detected: bool
    perclos: Optional[float]
    timestamp: str


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    mediapipe_ready: bool
    threshold_loaded: bool


class ModelInfoResponse(BaseModel):
    threshold: float
    input_shape: List[Any]
    model_params: int
    message: Optional[str] = None
