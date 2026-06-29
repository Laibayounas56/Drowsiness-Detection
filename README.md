# Real-Time Fatigue & Drowsiness Detection System

Production-quality local prototype for ML-powered fatigue and drowsiness monitoring.
The browser captures webcam frames, sends compressed JPEGs to FastAPI over a
WebSocket, and the backend combines MediaPipe face landmarks with a trained
eye-state CNN.

No model training, fake detections, database, auth, or external APIs are used.

## Architecture

```text
frontend/ Next.js dashboard
  webcam -> canvas -> JPEG frames -> WebSocket

backend/ FastAPI
  WebSocket frame decode
  MediaPipe Face Mesh landmarks
  CNN eye open probability
  EAR, MAR, PERCLOS, blink/yawn metrics
  JSON detection result
```

Each WebSocket connection creates its own `DrowsinessDetector`, so fatigue state
is not shared across browser clients.

## Model Files

Place the trained files here before using detection:

```text
backend/models/eye_cnn_best.h5
backend/models/eye_threshold.json
```

`eye_threshold.json` can be:

```json
{ "threshold": 0.5 }
```

The CNN output is interpreted as probability that the eye is open. If
`open_probability < threshold`, the eye is classified as closed.

If files are missing, `/health` still works and `/ws/detect` rejects connections
with a clear `model_not_loaded` error.

## Backend Setup

```bash
cd backend
python -m venv .venv
```

Activate the environment:

```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1

# Windows CMD
.venv\Scripts\activate.bat

# macOS / Linux
source .venv/bin/activate
```

Install dependencies and start:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Check:

```text
http://localhost:8000/health
http://localhost:8000/model-info
```

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:3000
```

Then allow camera permission and click **Start Detection**.

## Environment

Optional frontend variable:

```text
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/detect
```

Create `frontend/.env.local` if you need a non-default WebSocket URL.

## API

### `GET /health`

Returns backend readiness:

```json
{
  "status": "ok",
  "model_loaded": true,
  "mediapipe_ready": true,
  "threshold_loaded": true
}
```

### `GET /model-info`

Returns model threshold, input shape, and parameter count.

### `WS /ws/detect`

Client sends:

```json
{ "image": "data:image/jpeg;base64,..." }
```

Server returns:

```json
{
  "face_detected": true,
  "status": "NORMAL",
  "fatigue_score": 12.5,
  "ear": 0.312,
  "mar": 0.18,
  "eye_closed": false,
  "open_probability": 0.87,
  "closed_confidence": 0.13,
  "blink_count": 4,
  "blink_rate": 12.0,
  "yawn_count": 0,
  "yawn_detected": false,
  "perclos": 0.03,
  "timestamp": "2026-05-29T12:00:00+00:00"
}
```

No-face frames are not counted as closed-eye frames.

## Fatigue Scoring

Sliding-window score:

| Component | Weight |
| --- | --- |
| PERCLOS | 38% |
| Yawn frequency | 18% |
| Recent yawn frequency | 10% |
| Eye-closure frequency | 14% |
| Blink-rate abnormality | 10% |
| CNN closed-eye confidence | 10% |

The score also applies smoothing, status hysteresis, and an added sustained-eye-closure bonus for prolonged closure.

Statuses:

| Status | Score |
| --- | --- |
| `NORMAL` | below alert threshold |
| `ALERT` | sustained elevated fatigue score |
| `CRITICAL` | sustained high fatigue score |
| `NO_FACE` | no face detected |

## Project Structure

```text
backend/
  app/
    config.py
    detector.py
    main.py
    schemas.py
  models/
    PLACE_MODELS_HERE.txt
  requirements.txt

frontend/
  src/
    app/
    components/
    hooks/
    types/
  package.json
```

## Validation Checklist

- Start backend without model files: `/health` works, `/ws/detect` returns `model_not_loaded`.
- Place model files and restart backend: `/health.model_loaded` is `true`.
- Start frontend after backend.
- Click **Start Detection** and confirm live metrics update.
- Send malformed WebSocket payloads and confirm the server returns `invalid_frame` without crashing.
