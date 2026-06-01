"""Core drowsiness detection logic.

The Keras model is loaded once and shared read-only. Every WebSocket connection
gets its own ``DrowsinessDetector`` instance, including MediaPipe resources and
fatigue history, so client state is never shared.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

import cv2
import mediapipe as mp
import numpy as np

from .config import (
    ALERT_MIN_HOLD_FRAMES,
    ALERT_RECOVERY_THRESHOLD,
    ALERT_THRESHOLD,
    BLINK_COOLDOWN_FRAMES,
    CRITICAL_MIN_HOLD_FRAMES,
    CRITICAL_RECOVERY_THRESHOLD,
    CRITICAL_THRESHOLD,
    EAR_BASELINE_MAX,
    EAR_BASELINE_MIN,
    EAR_BASELINE_MIN_SAMPLES,
    EAR_BASELINE_PERCENTILE,
    EAR_BORDERLINE_FALLBACK,
    EAR_BORDERLINE_MAX,
    EAR_BORDERLINE_MIN,
    EAR_BORDERLINE_RATIO,
    EAR_CALIBRATION_WINDOW,
    EAR_CLOSED_FALLBACK,
    EAR_CLOSED_MAX,
    EAR_CLOSED_MIN,
    EAR_CONSEC_MIN,
    EAR_CLOSED_RATIO,
    EAR_MIN_GAP,
    EMA_ALPHA,
    EYE_CLOSED_DECISION_MIN,
    EYE_CNN_WEIGHT,
    EYE_CLOSURE_RATE_MAX,
    EYE_EAR_WEIGHT,
    EYE_OPEN_GUARD_PROB,
    EYE_STRONG_CLOSED_EAR_MARGIN,
    FATIGUE_WINDOW_SECONDS,
    FPS_LOG_INTERVAL,
    MAR_HIGH_THRESHOLD,
    MAR_CONSEC_MIN,
    MAR_THRESHOLD,
    MAX_BLINK_DEV,
    MILD_EYE_CLOSURE_RATE_CAP,
    MILD_PERCLOS_CAP,
    MILD_STATE_SCORE_CAP,
    NORMAL_BLINK_RATE,
    PERCLOS_ALERT,
    PERCLOS_CEIL,
    RECENT_YAWN_RATE_MAX,
    RECENT_YAWN_WINDOW_SECONDS,
    RESIZE_HEIGHT,
    RESIZE_WIDTH,
    SCORE_EMA_ALPHA,
    SUSTAINED_EYE_CLOSED_GAIN,
    SUSTAINED_EYE_CLOSED_MAX_BONUS,
    SUSTAINED_EYE_CLOSED_START_SECONDS,
    SUSTAINED_EYE_CLOSED_TAU_SECONDS,
    UNCERTAINTY_MARGIN,
    WINDOW_SIZE,
    YAWN_RATE_MAX,
)

logger = logging.getLogger(__name__)

# MediaPipe Face Mesh landmark indices.
_R_EYE_EAR: List[int] = [33, 160, 158, 133, 153, 144]
_L_EYE_EAR: List[int] = [362, 385, 387, 263, 373, 380]

_R_EYE_CROP: List[int] = [
    33,
    7,
    163,
    144,
    145,
    153,
    154,
    155,
    133,
    173,
    157,
    158,
    159,
    160,
    161,
    246,
]
_L_EYE_CROP: List[int] = [
    362,
    382,
    381,
    380,
    374,
    373,
    390,
    249,
    263,
    466,
    388,
    387,
    386,
    385,
    384,
    398,
]

_MOUTH_CORNERS: List[int] = [61, 291]
_MOUTH_TB: List[int] = [13, 14]


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def compute_ear(lm_px: np.ndarray, indices: List[int]) -> float:
    """Compute Eye Aspect Ratio from six eye landmark indices."""
    points = lm_px[indices]
    numerator = _dist(points[1], points[5]) + _dist(points[2], points[4])
    denominator = 2.0 * _dist(points[0], points[3])
    return numerator / denominator if denominator > 1e-6 else 0.0


def compute_mar(
    lm_px: np.ndarray,
    corner_idx: List[int],
    tb_idx: List[int],
) -> float:
    """Compute Mouth Aspect Ratio from mouth corner and top/bottom landmarks."""
    horizontal = _dist(lm_px[corner_idx[0]], lm_px[corner_idx[1]])
    vertical = _dist(lm_px[tb_idx[0]], lm_px[tb_idx[1]])
    return vertical / horizontal if horizontal > 1e-6 else 0.0


def extract_eye_crop(
    frame: np.ndarray,
    lm_px: np.ndarray,
    indices: List[int],
    pad_x: float = 0.18,
    pad_y_top: float = 0.08,
    pad_y_bottom: float = 0.20,
) -> Optional[np.ndarray]:
    """Extract an eye crop while limiting eyebrow-dominant top padding."""
    points = lm_px[indices].astype(int)
    x1, y1 = points.min(axis=0)
    x2, y2 = points.max(axis=0)
    width = x2 - x1
    height = y2 - y1
    pad_x_px = int(width * pad_x)
    pad_y_top_px = int(height * pad_y_top)
    pad_y_bottom_px = int(height * pad_y_bottom)
    frame_h, frame_w = frame.shape[:2]

    x1 = max(0, x1 - pad_x_px)
    y1 = max(0, y1 - pad_y_top_px)
    x2 = min(frame_w, x2 + pad_x_px)
    y2 = min(frame_h, y2 + pad_y_bottom_px)

    if x2 <= x1 or y2 <= y1:
        return None

    return frame[y1:y2, x1:x2].copy()


def _window_count(timestamps: Deque[float], window_seconds: float) -> int:
    now = time.time()
    while timestamps and now - timestamps[0] > window_seconds:
        timestamps.popleft()
    return sum(1 for value in timestamps if now - value <= window_seconds)


class FatigueScoreEngine:
    """Sliding-window fatigue metrics for a single client session."""

    def __init__(
        self,
        window_size: int = WINDOW_SIZE,
        window_seconds: float = FATIGUE_WINDOW_SECONDS,
        perclos_alert: float = PERCLOS_ALERT,
        perclos_ceil: float = PERCLOS_CEIL,
        normal_blink_rate: float = NORMAL_BLINK_RATE,
        max_blink_dev: float = MAX_BLINK_DEV,
        eye_closure_rate_max: float = EYE_CLOSURE_RATE_MAX,
        yawn_rate_max: float = YAWN_RATE_MAX,
        recent_yawn_rate_max: float = RECENT_YAWN_RATE_MAX,
    ) -> None:
        self._eye_closed_samples: Deque[Tuple[float, bool]] = deque(maxlen=window_size)
        self._cnn_conf_hist: Deque[float] = deque(maxlen=window_size)
        self._eye_closure_timestamps: Deque[float] = deque(maxlen=300)
        self._blink_timestamps: Deque[float] = deque(maxlen=200)
        self._yawn_timestamps: Deque[float] = deque(maxlen=100)
        self._window_seconds = window_seconds
        self._perclos_alert = perclos_alert
        self._perclos_ceil = perclos_ceil
        self._normal_blink_rate = normal_blink_rate
        self._max_blink_dev = max_blink_dev
        self._eye_closure_rate_max = eye_closure_rate_max
        self._yawn_rate_max = yawn_rate_max
        self._recent_yawn_rate_max = recent_yawn_rate_max
        self._score_ema = 0.0
        self._status = "NORMAL"
        self._alert_streak = 0
        self._critical_streak = 0
        self.blink_count = 0
        self.yawn_count = 0
        self.eye_closure_count = 0

    def record_frame(
        self,
        *,
        eye_closed: bool,
        closed_confidence: float,
        eye_closure_started: bool,
        blink_occurred: bool,
        yawn_occurred: bool,
    ) -> None:
        now = time.time()
        self._eye_closed_samples.append((now, eye_closed))
        self._cnn_conf_hist.append(closed_confidence)

        if eye_closure_started:
            self.eye_closure_count += 1
            self._eye_closure_timestamps.append(now)

        if blink_occurred:
            self.blink_count += 1
            self._blink_timestamps.append(now)

        if yawn_occurred:
            self.yawn_count += 1
            self._yawn_timestamps.append(now)

    def perclos(self) -> float:
        self._trim_samples()
        if not self._eye_closed_samples:
            return 0.0
        closed_samples = sum(1 for _, eye_closed in self._eye_closed_samples if eye_closed)
        return float(closed_samples) / len(self._eye_closed_samples)

    def blink_rate(self) -> float:
        return float(_window_count(self._blink_timestamps, self._window_seconds))

    def eye_closure_rate(self) -> float:
        return float(_window_count(self._eye_closure_timestamps, self._window_seconds))

    def yawn_rate(self, window_seconds: float | None = None) -> float:
        window = self._window_seconds if window_seconds is None else window_seconds
        return float(_window_count(self._yawn_timestamps, window))

    def _trim_samples(self) -> None:
        now = time.time()
        while self._eye_closed_samples and now - self._eye_closed_samples[0][0] > self._window_seconds:
            self._eye_closed_samples.popleft()

    def _avg_cnn_conf(self) -> float:
        if not self._cnn_conf_hist:
            return 0.0
        return float(np.mean(list(self._cnn_conf_hist)))

    def _continuous_eye_closure_seconds(self) -> float:
        """Return ongoing continuous closed-eye duration in seconds."""
        self._trim_samples()
        if not self._eye_closed_samples or not self._eye_closed_samples[-1][1]:
            return 0.0

        start_ts = self._eye_closed_samples[-1][0]
        for ts, eye_closed in reversed(self._eye_closed_samples):
            if not eye_closed:
                break
            start_ts = ts

        return max(0.0, time.time() - start_ts)

    def compute_score(self) -> Tuple[float, str]:
        """Return fatigue score in [0, 100] and status label."""
        if len(self._eye_closed_samples) < 5:
            self._score_ema = 0.0
            self._status = "NORMAL"
            self._alert_streak = 0
            self._critical_streak = 0
            return 0.0, "NORMAL"

        perclos = self.perclos()
        perclos_score = float(
            np.clip(
                (perclos - self._perclos_alert)
                / max(self._perclos_ceil - self._perclos_alert, 1e-6),
                0.0,
                1.0,
            )
        )
        blink_score = min(
            abs(self.blink_rate() - self._normal_blink_rate) / self._max_blink_dev,
            1.0,
        )
        eye_closure_rate = self.eye_closure_rate()
        eye_closure_score = min(eye_closure_rate / self._eye_closure_rate_max, 1.0)
        yawn_rate = self.yawn_rate()
        yawn_score = min(yawn_rate / self._yawn_rate_max, 1.0)
        recent_yawn_score = min(
            self.yawn_rate(RECENT_YAWN_WINDOW_SECONDS) / self._recent_yawn_rate_max,
            1.0,
        )
        cnn_score = min(self._avg_cnn_conf(), 1.0)
        continuous_closed_seconds = self._continuous_eye_closure_seconds()

        weighted_score = (
            perclos_score * 0.38
            + yawn_score * 0.18
            + recent_yawn_score * 0.10
            + eye_closure_score * 0.14
            + blink_score * 0.10
            + cnn_score * 0.10
        )

        if perclos < self._perclos_alert and yawn_rate == 0:
            weighted_score *= 0.7

        raw_score = float(np.clip(weighted_score * 100.0, 0.0, 100.0))

        if continuous_closed_seconds > SUSTAINED_EYE_CLOSED_START_SECONDS:
            sustained_over = (
                continuous_closed_seconds - SUSTAINED_EYE_CLOSED_START_SECONDS
            )
            sustained_bonus = SUSTAINED_EYE_CLOSED_GAIN * (
                np.exp(sustained_over / SUSTAINED_EYE_CLOSED_TAU_SECONDS) - 1.0
            )
            raw_score += min(sustained_bonus, SUSTAINED_EYE_CLOSED_MAX_BONUS)

        if (
            continuous_closed_seconds <= SUSTAINED_EYE_CLOSED_START_SECONDS
            and perclos < MILD_PERCLOS_CAP
            and eye_closure_rate < MILD_EYE_CLOSURE_RATE_CAP
        ):
            raw_score = min(raw_score, MILD_STATE_SCORE_CAP)

        raw_score = float(np.clip(raw_score, 0.0, 100.0))

        self._score_ema = float(
            np.clip(
                SCORE_EMA_ALPHA * raw_score + (1.0 - SCORE_EMA_ALPHA) * self._score_ema,
                0.0,
                100.0,
            )
        )

        if self._score_ema >= ALERT_THRESHOLD:
            self._alert_streak += 1
        else:
            self._alert_streak = 0

        if self._score_ema >= CRITICAL_THRESHOLD:
            self._critical_streak += 1
        else:
            self._critical_streak = 0

        if self._status == "CRITICAL":
            if self._score_ema < CRITICAL_RECOVERY_THRESHOLD:
                self._status = "ALERT" if self._score_ema >= ALERT_THRESHOLD else "NORMAL"
        elif self._critical_streak >= CRITICAL_MIN_HOLD_FRAMES:
            self._status = "CRITICAL"
        elif self._status == "ALERT":
            if self._score_ema < ALERT_RECOVERY_THRESHOLD:
                self._status = "NORMAL"
        elif self._alert_streak >= ALERT_MIN_HOLD_FRAMES:
            self._status = "ALERT"

        return self._score_ema, self._status


class DrowsinessDetector:
    """Per-session detector: MediaPipe landmarks, CNN eye state, fatigue score."""

    _model: Any = None
    _threshold: float = 0.5
    _input_h: int = 64
    _input_w: int = 64
    _input_ch: int = 1
    _model_ready: bool = False
    _model_outputs_closed_probability: bool = False

    @classmethod
    def load_model(cls, model_path: Path, threshold_path: Path) -> None:
        """Load model and threshold, failing clearly if files are missing."""
        if not model_path.exists():
            raise FileNotFoundError(
                f"\n{'-' * 64}\n"
                f"Missing model file: {model_path}\n"
                "Place eye_cnn_best.h5 inside backend/models/ and restart.\n"
                f"{'-' * 64}"
            )

        if not threshold_path.exists():
            raise FileNotFoundError(
                f"\n{'-' * 64}\n"
                f"Missing threshold file: {threshold_path}\n"
                "Place eye_threshold.json inside backend/models/ and restart.\n"
                f"{'-' * 64}"
            )

        import tensorflow as tf

        logger.info("Loading CNN model from %s", model_path)
        cls._model = tf.keras.models.load_model(str(model_path), compile=False)
        cls._configure_input_shape(cls._model.input_shape)

        with open(threshold_path, encoding="utf-8") as threshold_file:
            threshold_data = json.load(threshold_file)

        if isinstance(threshold_data, dict):
            raw_threshold = threshold_data.get("threshold", threshold_data.get("value"))
            output_label = str(
                threshold_data.get(
                    "positive_class",
                    threshold_data.get("output_label", threshold_data.get("class_label", "")),
                )
            ).lower()
            cls._model_outputs_closed_probability = (
                output_label == "closed"
                or "closed_precision" in threshold_data
                or "closed_recall" in threshold_data
                or "closed_fbeta" in threshold_data
            )
        elif isinstance(threshold_data, list):
            raw_threshold = threshold_data[0] if threshold_data else None
            cls._model_outputs_closed_probability = False
        else:
            raw_threshold = threshold_data
            cls._model_outputs_closed_probability = False

        if raw_threshold is None:
            raise ValueError(
                "eye_threshold.json must contain a number or an object with 'threshold'."
            )

        cls._threshold = float(raw_threshold)
        if not 0.0 <= cls._threshold <= 1.0:
            raise ValueError("Eye threshold must be between 0 and 1.")

        logger.info(
            "Model ready: input_shape=%s threshold=%.4f output=%s params=%s",
            cls._model.input_shape,
            cls._threshold,
            "closed_probability" if cls._model_outputs_closed_probability else "open_probability",
            f"{int(cls._model.count_params()):,}",
        )
        cls._model_ready = True

    @classmethod
    def _configure_input_shape(cls, raw_shape: Any) -> None:
        shape = raw_shape[0] if isinstance(raw_shape, list) else raw_shape
        if not shape:
            raise ValueError(f"Could not inspect model input shape: {raw_shape}")

        if len(shape) == 4 and shape[-1] in (1, 3):
            cls._input_h = int(shape[1])
            cls._input_w = int(shape[2])
            cls._input_ch = int(shape[3])
            return

        if len(shape) == 3:
            cls._input_h = int(shape[1])
            cls._input_w = int(shape[2])
            cls._input_ch = 1
            return

        if len(shape) == 4 and shape[1] in (1, 3):
            raise ValueError(
                f"Unsupported channels-first model input shape {shape}. "
                "Use a channels-last model such as (None, 64, 64, 1)."
            )

        raise ValueError(f"Unsupported model input shape: {shape}")

    def __init__(self, debug: bool = False) -> None:
        if not self.__class__._model_ready:
            raise RuntimeError("Model is not loaded. Restart after placing model files.")

        self.debug = debug
        self._mp_fm = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._fatigue = FatigueScoreEngine()
        self._smooth_prob = 0.5
        self._ear_recent_samples: Deque[float] = deque(maxlen=EAR_CALIBRATION_WINDOW)
        self._open_ear_baseline: float | None = None

        self._closed_frames = 0
        self._open_frames = 0
        self._in_blink = False
        self._blink_cooldown = 0

        self._yawn_frames = 0
        self._yawning = False

        self._fps_start = time.time()
        self._fps_frames = 0
        logger.info("Created DrowsinessDetector instance.")

    def close(self) -> None:
        try:
            self._mp_fm.close()
        except Exception:
            logger.debug("MediaPipe close failed", exc_info=True)

    def _preprocess(self, crop: np.ndarray) -> np.ndarray:
        cls = self.__class__
        resized = cv2.resize(crop, (cls._input_w, cls._input_h))

        if cls._input_ch == 1:
            if resized.ndim == 2:
                gray = resized
            elif resized.shape[-1] == 1:
                gray = resized[..., 0]
            else:
                gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            arr = gray.astype(np.float32) / 255.0
            arr = arr[..., np.newaxis]
        else:
            if resized.ndim == 2:
                rgb = cv2.cvtColor(resized, cv2.COLOR_GRAY2RGB)
            else:
                rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            arr = rgb.astype(np.float32) / 255.0

        return arr[np.newaxis]

    def _predict_eye(self, crop: Optional[np.ndarray]) -> Optional[float]:
        if crop is None or crop.size == 0:
            return None

        try:
            batch = self._preprocess(crop)
            prediction = self.__class__._model.predict(batch, verbose=0)
            return float(np.asarray(prediction).reshape(-1)[0])
        except Exception as exc:
            logger.warning("Eye CNN prediction failed: %s", exc)
            return None

    def _combine_eye_probabilities(self, probabilities: List[float]) -> float:
        """Combine per-eye model probabilities with light outlier resistance."""
        if not probabilities:
            return 0.5
        if len(probabilities) == 1:
            return float(np.clip(probabilities[0], 0.0, 1.0))

        values = [float(np.clip(value, 0.0, 1.0)) for value in probabilities]
        hi = max(values)
        lo = min(values)
        if hi - lo >= 0.35:
            return float(np.clip(0.7 * hi + 0.3 * lo, 0.0, 1.0))
        return float(np.mean(values))

    def _update_blink(self, eye_closed: bool) -> Tuple[bool, bool]:
        if self._blink_cooldown > 0:
            self._blink_cooldown -= 1

        eye_closure_started = eye_closed and self._closed_frames == 0

        if eye_closed:
            self._closed_frames += 1
            self._open_frames = 0
            if not self._in_blink and self._closed_frames >= EAR_CONSEC_MIN:
                self._in_blink = True
            return eye_closure_started, False

        self._open_frames += 1
        self._closed_frames = 0
        if self._in_blink and self._blink_cooldown == 0:
            self._in_blink = False
            self._blink_cooldown = BLINK_COOLDOWN_FRAMES
            return False, True

        return False, False

    def _update_yawn(self, mar: float) -> bool:
        if mar > MAR_HIGH_THRESHOLD and not self._yawning:
            self._yawn_frames = max(self._yawn_frames, MAR_CONSEC_MIN)
            self._yawning = True
            return True

        if mar > MAR_THRESHOLD:
            self._yawn_frames += 1
            if self._yawn_frames >= MAR_CONSEC_MIN and not self._yawning:
                self._yawning = True
                return True
        else:
            self._yawn_frames = 0
            self._yawning = False

        return False

    def _ear_thresholds(self, ear: float) -> Tuple[float, float]:
        """Return calibrated closed/borderline EAR thresholds for this session."""
        if np.isfinite(ear) and 0.05 <= ear <= 0.7:
            self._ear_recent_samples.append(float(ear))

        if len(self._ear_recent_samples) >= EAR_BASELINE_MIN_SAMPLES:
            candidate = float(
                np.percentile(self._ear_recent_samples, EAR_BASELINE_PERCENTILE)
            )
            self._open_ear_baseline = float(
                np.clip(candidate, EAR_BASELINE_MIN, EAR_BASELINE_MAX)
            )

        baseline = self._open_ear_baseline
        if baseline is None:
            return EAR_CLOSED_FALLBACK, EAR_BORDERLINE_FALLBACK

        closed_threshold = float(
            np.clip(baseline * EAR_CLOSED_RATIO, EAR_CLOSED_MIN, EAR_CLOSED_MAX)
        )
        borderline_threshold = float(
            np.clip(
                baseline * EAR_BORDERLINE_RATIO,
                EAR_BORDERLINE_MIN,
                EAR_BORDERLINE_MAX,
            )
        )
        borderline_threshold = max(borderline_threshold, closed_threshold + EAR_MIN_GAP)
        return closed_threshold, borderline_threshold

    def _classify_eye_state(
        self,
        *,
        raw_model_probability: float,
        ear: float,
    ) -> Tuple[bool, float, float]:
        """Fuse CNN confidence with EAR and return closed/open state metrics."""
        if self.__class__._model_outputs_closed_probability:
            raw_open_probability = 1.0 - raw_model_probability
        else:
            raw_open_probability = raw_model_probability

        raw_open_probability = float(np.clip(raw_open_probability, 0.0, 1.0))

        self._smooth_prob = (
            EMA_ALPHA * raw_open_probability + (1.0 - EMA_ALPHA) * self._smooth_prob
        )

        closed_ear_threshold, borderline_ear_threshold = self._ear_thresholds(ear)
        cnn_closed_confidence = 1.0 - self._smooth_prob
        if ear <= closed_ear_threshold:
            ear_closed_score = 1.0
        elif ear >= borderline_ear_threshold:
            ear_closed_score = 0.0
        else:
            ear_closed_score = float(
                np.clip(
                    (borderline_ear_threshold - ear)
                    / max(borderline_ear_threshold - closed_ear_threshold, 1e-6),
                    0.0,
                    1.0,
                )
            )

        fused_closed_confidence = float(
            np.clip(
                cnn_closed_confidence * EYE_CNN_WEIGHT
                + ear_closed_score * EYE_EAR_WEIGHT,
                0.0,
                1.0,
            )
        )

        model_closed_boundary = (
            self.__class__._threshold
            if self.__class__._model_outputs_closed_probability
            else 1.0 - self.__class__._threshold
        )
        model_closed_boundary = float(np.clip(model_closed_boundary, 0.35, 0.75))
        closed_decision_boundary = max(EYE_CLOSED_DECISION_MIN, model_closed_boundary)
        strong_ear_closed = ear <= (closed_ear_threshold - EYE_STRONG_CLOSED_EAR_MARGIN)
        open_guard = (
            self._smooth_prob >= EYE_OPEN_GUARD_PROB
            and ear > closed_ear_threshold
            and fused_closed_confidence < (closed_decision_boundary + 0.08)
        )

        if strong_ear_closed:
            eye_closed = True
        elif ear >= borderline_ear_threshold:
            eye_closed = False
        elif open_guard:
            eye_closed = False
        else:
            eye_closed = fused_closed_confidence >= closed_decision_boundary

        return eye_closed, self._smooth_prob, fused_closed_confidence

    def _draw_debug_landmarks(self, frame: np.ndarray, lm_px: np.ndarray) -> None:
        for index in set(_R_EYE_CROP + _L_EYE_CROP + _MOUTH_CORNERS + _MOUTH_TB):
            x, y = lm_px[index].astype(int)
            cv2.circle(frame, (x, y), 2, (0, 255, 0), -1)

    def _no_face_result(self) -> Dict[str, Any]:
        return {
            "face_detected": False,
            "status": "NO_FACE",
            "fatigue_score": None,
            "ear": None,
            "mar": None,
            "eye_closed": None,
            "open_probability": None,
            "closed_confidence": None,
            "blink_count": self._fatigue.blink_count,
            "blink_rate": round(self._fatigue.blink_rate(), 2),
            "yawn_count": self._fatigue.yawn_count,
            "yawn_detected": False,
            "perclos": round(self._fatigue.perclos(), 4),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def detect(self, frame_bgr: np.ndarray) -> Dict[str, Any]:
        """Process one BGR frame and return a detection payload."""
        self._fps_frames += 1
        elapsed = time.time() - self._fps_start
        if elapsed >= FPS_LOG_INTERVAL:
            logger.info(
                "Detector FPS %.1f, blinks=%s, yawns=%s",
                self._fps_frames / elapsed,
                self._fatigue.blink_count,
                self._fatigue.yawn_count,
            )
            self._fps_start = time.time()
            self._fps_frames = 0

        frame_small = cv2.resize(frame_bgr, (RESIZE_WIDTH, RESIZE_HEIGHT))
        frame_h, frame_w = frame_small.shape[:2]
        rgb = cv2.cvtColor(frame_small, cv2.COLOR_BGR2RGB)
        gray = cv2.cvtColor(frame_small, cv2.COLOR_BGR2GRAY)
        results = self._mp_fm.process(rgb)

        if not results.multi_face_landmarks:
            return self._no_face_result()

        face_landmarks = results.multi_face_landmarks[0]
        lm_px = np.array(
            [[landmark.x * frame_w, landmark.y * frame_h] for landmark in face_landmarks.landmark],
            dtype=np.float32,
        )

        if self.debug:
            self._draw_debug_landmarks(frame_small, lm_px)

        right_ear = compute_ear(lm_px, _R_EYE_EAR)
        left_ear = compute_ear(lm_px, _L_EYE_EAR)
        ear = (right_ear + left_ear) / 2.0
        mar = compute_mar(lm_px, _MOUTH_CORNERS, _MOUTH_TB)

        right_crop = extract_eye_crop(gray, lm_px, _R_EYE_CROP)
        left_crop = extract_eye_crop(gray, lm_px, _L_EYE_CROP)
        right_prob = self._predict_eye(right_crop)
        left_prob = self._predict_eye(left_crop)
        available_probs = [prob for prob in (right_prob, left_prob) if prob is not None]

        if not available_probs:
            logger.warning("Face detected but no valid eye crops were available.")
            return self._no_face_result()

        raw_model_probability = self._combine_eye_probabilities(available_probs)
        eye_closed, open_probability, closed_confidence = self._classify_eye_state(
            raw_model_probability=raw_model_probability,
            ear=ear,
        )
        uncertain = abs(closed_confidence - 0.5) < UNCERTAINTY_MARGIN
        effective_closed_confidence = closed_confidence * (0.5 if uncertain else 1.0)

        eye_closure_started, blink_occurred = self._update_blink(eye_closed)
        yawn_occurred = self._update_yawn(mar)

        self._fatigue.record_frame(
            eye_closed=eye_closed,
            closed_confidence=effective_closed_confidence,
            eye_closure_started=eye_closure_started,
            blink_occurred=blink_occurred,
            yawn_occurred=yawn_occurred,
        )
        fatigue_score, status = self._fatigue.compute_score()

        return {
            "face_detected": True,
            "status": status,
            "fatigue_score": round(fatigue_score, 2),
            "ear": round(float(ear), 4),
            "mar": round(float(mar), 4),
            "eye_closed": eye_closed,
            "open_probability": round(float(open_probability), 4),
            "closed_confidence": round(float(effective_closed_confidence), 4),
            "blink_count": self._fatigue.blink_count,
            "blink_rate": round(self._fatigue.blink_rate(), 2),
            "yawn_count": self._fatigue.yawn_count,
            "yawn_detected": self._yawning,
            "perclos": round(self._fatigue.perclos(), 4),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }