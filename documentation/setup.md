---
title: Setup & Running
tags: [setup, installation, quickstart]
---

# Setup & Running

## Prerequisites

| Requirement | Version |
|---|---|
| Python | `3.12.x` (3.13+ is **not** supported by MediaPipe) |
| [uv](https://github.com/astral-sh/uv) | any recent version |
| Webcam | USB or built-in |

---

## First-time Setup

```bash
# 1. Clone or enter the project directory
cd HalLMediaPipe

# 2. Create the virtual environment and install dependencies
uv sync

# 3. Verify the models directory exists
ls models/
# Expected:
#   hand_landmarker.task
#   pose_landmarker_lite.task
```

> **Models** are not included in the repository. Download them from the [MediaPipe Model Cards page](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker) and place the `.task` files under `models/`.

---

## Running

```bash
uv run python src/main.py
```

A window titled **"Camera"** will open showing the webcam feed with skeleton overlay and UI buttons.

### Controls

| Action | Effect |
|---|---|
| Pinch (thumb + index close together) over a button | Activates the button |
| Pinch near a sphere | Grabs and drags it |
| Move fingertip into a sphere | Pushes it |
| `q` | Quit |

### Web mode (browser-rendered UI)

The same app can run as a backend for the React frontend in `web/` — the
browser then renders everything (skeleton, cursor, buttons, WebGL black
hole). Requires Node on the dev machine (one-time `npm install`):

```bash
# terminal 1 — backend: raw frames + state JSON on :8092, no cv2 window
HALL_OUTPUT=web uv run python src/main.py

# terminal 2 — dev frontend with hot reload on :5173
cd web && npm install && npm run dev
```

For a self-contained run (no Node needed afterwards): `cd web && npm run
build`, then `HALL_OUTPUT=web uv run python src/main.py` and open
`http://localhost:8092/`. Details: [[modules/frontend]] and
[[modules/web_state]]. On the Jetson, `hallkiosk` wraps this in a
fullscreen Chromium kiosk (see `deploy/hall-app/`).

---

## Configuration

All tuneable parameters live in `src/config.py`. See [[modules/config]] for the full reference.

Common changes:

| Parameter | Default | Change when… |
|---|---|---|
| `SELECTED_CAMERA` | `0` | You have multiple cameras and want to select a different one |
| `MIN_POSE_DETECTION_CONFIDENCE` | `0.5` | Detection is too noisy (raise) or too slow to trigger (lower) |
| `PINCH_CLOSE_RATIO` | `0.45` | Close threshold, as a fraction of the hand's own knuckle span. **Higher → fires more easily.** |
| `PINCH_RELEASE_RATIO` | `0.90` | Release threshold (hysteresis). Raise it to make grabs even harder to drop; lower it toward `PINCH_CLOSE_RATIO` for faster releases. |
| `PINCH_DEBOUNCE_RELEASE_FRAMES` | `4` | Frames of sustained opening required to release. Raise if drags still drop during fast movement. |
| `PINCH_CURSOR_MIN_CUTOFF` | `1.5` | One-Euro cursor smoothing (Hz). Lower = steadier cursor at rest, slightly laggier. |
| `PINCH_CURSOR_THUMB_OFFSET_X` / `_Y` | `0.0` / `0.0` | 2D cursor offset from the thumb tip, in thumb-frame units (fractions of the MCP→tip segment). X: + ahead of the tip / − toward the knuckle. Y: + toward the index side / − toward the outer edge (mirrors correctly on both hands). Keep small — large values move the cursor during the close. |
| `PINCH_CURSOR_COMPENSATE` | `1.0` | Counter-movement that cancels the thumb's own travel while the pinch closes (cursor holds still; hand motion still tracks 1:1). Lower toward `0` if you *want* the cursor to ride the raw thumb. |
| `PINCH_EXTRAP_MAX_S` | `0.10` | Latency-compensation cap. Lower it if the cursor overshoots on fast direction reversals. |
| `PINCH_Z_WEIGHT` | `0.5` | 3D-distance z weight. Lower toward 0 if pinches stopped triggering (noisy depth inflates the ratio). |
| `BUTTON_STICKY_PAD_FRAC` | `0.15` | How much a hovered button's hit area grows (fraction of its height, per side). |

**Seeing what the detector sees:** run with `HALL_DEBUG=1` to draw the pinch-pipeline HUD (live ratio vs thresholds, machine state, detection age/FPS) — tune with evidence, not feel.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Cant access to camera #0` | Camera index wrong or camera in use | Change `SELECTED_CAMERA` in `config.py` |
| `FileNotFoundError` on `.task` file | Model files missing | Download and place under `models/` |
| Buttons never fire | Close threshold too strict, hand half-out of frame (landmarks degrade at the edges), or z noise inflating the 3D ratio | Run `HALL_DEBUG=1` and watch the ratio bar; keep the whole hand in frame; raise `PINCH_CLOSE_RATIO`; lower `PINCH_Z_WEIGHT` toward 0 |
| Buttons fire when I just move my closed hand across them | A fist entering the frame initialises *closed* and cannot fire — if this still happens, the hand is flickering between tracked/untracked past the grace period | Improve lighting; raise `PINCH_TRACK_GRACE_S` |
| Grabbed sphere drops when fingers drift slightly | Release threshold/debounce too tight | Raise `PINCH_RELEASE_RATIO` and/or `PINCH_DEBOUNCE_RELEASE_FRAMES` |
| Cursor not exactly where the fingers touch | The cursor rides the **thumb tip** (by design — the thumb is the stable side of a pinch; the index travels to meet it) | Offset it in the thumb frame with `PINCH_CURSOR_THUMB_OFFSET_X` (± along the thumb) and `_Y` (± toward the index side); if it jitters at rest, lower `PINCH_CURSOR_MIN_CUTOFF` |
| Cursor overshoots when I reverse direction fast | Latency extrapolation | Lower `PINCH_EXTRAP_MAX_S` |
| Jerky/laggy detection | Slow CPU | Use `pose_landmarker_lite.task` (already selected) — it is the fastest variant |
