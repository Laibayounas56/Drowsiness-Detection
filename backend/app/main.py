"""FastAPI application for real-time drowsiness detection."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import MAX_PROCESSING_FPS, MODEL_PATH, THRESHOLD_PATH
from .detector import DrowsinessDetector
from .schemas import HealthResponse, ModelInfoResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@dataclass
class FramePayload:
    frame_id: int
    client_sent_at: float
    image: str
    server_received_at: float


class LatestFrameBuffer:
    """Single-slot latest-frame buffer. New frames replace old pending frames."""

    def __init__(self) -> None:
        self.latest: FramePayload | None = None
        self.lock = asyncio.Lock()
        self.new_frame_event = asyncio.Event()
        self.closed = False

    async def put(self, frame_payload: FramePayload) -> None:
        async with self.lock:
            if self.closed:
                return
            self.latest = frame_payload
            self.new_frame_event.set()

    async def get_latest(self) -> FramePayload | None:
        while True:
            await self.new_frame_event.wait()
            async with self.lock:
                if self.latest is not None:
                    payload = self.latest
                    self.latest = None
                    if not self.closed:
                        self.new_frame_event.clear()
                    return payload

                if self.closed:
                    return None

                self.new_frame_event.clear()

    async def close(self) -> None:
        async with self.lock:
            self.closed = True
            self.latest = None
            self.new_frame_event.set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the model on startup, but keep health endpoints available if absent."""
    logger.info("=" * 60)
    logger.info("  Driver Drowsiness Detection API - starting")
    logger.info("=" * 60)

    try:
        DrowsinessDetector.load_model(MODEL_PATH, THRESHOLD_PATH)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        logger.warning(
            "Server started without model files. /ws/detect will reject connections "
            "until backend/models/eye_cnn_best.h5 and backend/models/eye_threshold.json "
            "are present and the server is restarted."
        )
    except Exception as exc:
        logger.exception("Failed to load model: %s", exc)

    yield
    logger.info("Server shutting down.")


app = FastAPI(
    title="Drowsiness Detection API",
    description="Real-time driver drowsiness detection via WebSocket",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["Status"])
async def health() -> HealthResponse:
    """Return backend and model readiness."""
    cls = DrowsinessDetector
    return HealthResponse(
        status="ok",
        model_loaded=cls._model_ready,
        mediapipe_ready=True,
        threshold_loaded=cls._threshold is not None and cls._model_ready,
    )


@app.get("/model-info", response_model=ModelInfoResponse, tags=["Status"])
async def model_info() -> ModelInfoResponse:
    """Return model threshold and input metadata."""
    cls = DrowsinessDetector
    if not cls._model_ready:
        return ModelInfoResponse(
            threshold=0.0,
            input_shape=[],
            model_params=0,
            message=(
                "Model is not loaded. Place eye_cnn_best.h5 and eye_threshold.json "
                "inside backend/models/ and restart the backend."
            ),
        )

    return ModelInfoResponse(
        threshold=cls._threshold,
        input_shape=list(cls._model.input_shape),
        model_params=int(cls._model.count_params()),
        message=None,
    )


def _now_ms() -> float:
    return time.time() * 1000.0


def _parse_payload(message: dict[str, Any]) -> FramePayload:
    frame_id = message.get("frame_id")
    client_sent_at = message.get("client_sent_at")
    image = message.get("image")

    if not isinstance(frame_id, int):
        raise ValueError("Payload must include integer 'frame_id'.")
    if not isinstance(client_sent_at, (int, float)):
        raise ValueError("Payload must include numeric 'client_sent_at'.")
    if not isinstance(image, str) or not image:
        raise ValueError("Payload must include a non-empty 'image' string.")

    return FramePayload(
        frame_id=frame_id,
        client_sent_at=float(client_sent_at),
        image=image,
        server_received_at=_now_ms(),
    )


def _decode_frame(payload: FramePayload) -> np.ndarray:
    image_value = payload.image
    if "," in image_value:
        image_value = image_value.split(",", 1)[1]

    image_bytes = base64.b64decode(image_value, validate=True)
    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

    if frame is None:
        raise ValueError("Could not decode image bytes as a JPEG frame.")

    return frame


async def _receiver(
    websocket: WebSocket,
    buffer: LatestFrameBuffer,
    send_lock: asyncio.Lock,
    client: str,
) -> None:
    """Continuously drain WebSocket messages and keep only the newest frame."""
    try:
        while True:
            try:
                message = await websocket.receive_json()
                payload = _parse_payload(message)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                logger.warning("[WS] Bad payload from %s: %s", client, exc)
                async with send_lock:
                    await websocket.send_json({"error": "invalid_frame", "detail": str(exc)})
                continue

            await buffer.put(payload)
    except WebSocketDisconnect:
        logger.info("[WS] Receiver disconnected: %s", client)
    finally:
        await buffer.close()


async def _processor(
    websocket: WebSocket,
    buffer: LatestFrameBuffer,
    detector: DrowsinessDetector,
    send_lock: asyncio.Lock,
    client: str,
) -> int:
    """Process only the latest available frame and send detection results."""
    processed_frames = 0
    min_interval = 1.0 / MAX_PROCESSING_FPS if MAX_PROCESSING_FPS > 0 else 0.0
    last_started = 0.0

    while True:
        payload = await buffer.get_latest()
        if payload is None:
            return processed_frames

        elapsed_since_last = time.monotonic() - last_started
        if min_interval > 0 and elapsed_since_last < min_interval:
            await asyncio.sleep(min_interval - elapsed_since_last)

        last_started = time.monotonic()
        processing_start = _now_ms()

        try:
            frame = await asyncio.to_thread(_decode_frame, payload)
            result = await asyncio.to_thread(detector.detect, frame)
            server_processed_at = _now_ms()
            processed_frames += 1

            result.update(
                {
                    "frame_id": payload.frame_id,
                    "client_sent_at": payload.client_sent_at,
                    "server_received_at": payload.server_received_at,
                    "server_processed_at": server_processed_at,
                    "processing_ms": round(server_processed_at - processing_start, 2),
                }
            )

            async with send_lock:
                await websocket.send_json(result)

        except (ValueError, binascii.Error) as exc:
            logger.warning("[WS] Bad frame from %s: %s", client, exc)
            async with send_lock:
                await websocket.send_json(
                    {
                        "error": "invalid_frame",
                        "detail": str(exc),
                        "frame_id": payload.frame_id,
                    }
                )
        except Exception as exc:
            logger.exception("[WS] Detection failed for %s: %s", client, exc)
            async with send_lock:
                await websocket.send_json(
                    {
                        "error": "detection_failed",
                        "detail": str(exc),
                        "frame_id": payload.frame_id,
                    }
                )


@app.websocket("/ws/detect")
async def ws_detect(websocket: WebSocket) -> None:
    """Latest-frame-wins WebSocket detection endpoint."""
    await websocket.accept()
    client = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "unknown"
    logger.info("[WS] Connected: %s", client)

    if not DrowsinessDetector._model_ready:
        await websocket.send_json(
            {
                "error": "model_not_loaded",
                "message": (
                    "The backend model is not loaded. Place eye_cnn_best.h5 and "
                    "eye_threshold.json in backend/models/ and restart the server."
                ),
            }
        )
        await websocket.close(code=1011)
        return

    detector: DrowsinessDetector | None = None
    receiver_task: asyncio.Task[None] | None = None
    processor_task: asyncio.Task[int] | None = None
    buffer = LatestFrameBuffer()
    send_lock = asyncio.Lock()

    try:
        detector = DrowsinessDetector()
        receiver_task = asyncio.create_task(_receiver(websocket, buffer, send_lock, client))
        processor_task = asyncio.create_task(
            _processor(websocket, buffer, detector, send_lock, client)
        )

        done, pending = await asyncio.wait(
            {receiver_task, processor_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in done:
            task.result()

        await buffer.close()
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        processed = processor_task.result() if processor_task.done() and not processor_task.cancelled() else 0
        logger.info("[WS] Disconnected: %s (processed %s frames)", client, processed)

    except Exception as exc:
        logger.exception("[WS] Unexpected error for %s: %s", client, exc)
    finally:
        await buffer.close()
        if receiver_task and not receiver_task.done():
            receiver_task.cancel()
        if processor_task and not processor_task.done():
            processor_task.cancel()
        await asyncio.gather(
            *[task for task in (receiver_task, processor_task) if task is not None],
            return_exceptions=True,
        )

        if detector is not None:
            detector.close()
        logger.info("[WS] Detector cleaned up for %s", client)
