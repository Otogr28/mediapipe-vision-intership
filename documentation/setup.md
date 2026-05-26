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

---

## Configuration

All tuneable parameters live in `src/config.py`. See [[modules/config]] for the full reference.

Common changes:

| Parameter | Default | Change when… |
|---|---|---|
| `SELECTED_CAMERA` | `0` | You have multiple cameras and want to select a different one |
| `MIN_POSE_DETECTION_CONFIDENCE` | `0.5` | Detection is too noisy (raise) or too slow to trigger (lower) |
| `PINCH_RATIO` | `0.09` | Trigger threshold ("fingers tightly closed"), as a fraction of shoulder width. **Higher → fires more easily.** |
| `PINCH_HOLD_RATIO` | `0.25` | Hold threshold for sustained gestures (grab). Looser than `PINCH_RATIO` so a grabbed object survives minor finger drift. Set equal to `PINCH_RATIO` to disable hysteresis. |
| `PINCH_CLOSE_DROP` | `0.15` | How much the pinch ratio must drop in the recent history window for a pinch *event* to fire. Raise this if static closed hands keep triggering buttons. |
| `PINCH_HISTORY_LEN` | `10` | Length of the per-hand history window (frames). At ~30 fps this is ~0.33 s. |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Cant access to camera #0` | Camera index wrong or camera in use | Change `SELECTED_CAMERA` in `config.py` |
| `FileNotFoundError` on `.task` file | Model files missing | Download and place under `models/` |
| Buttons never fire | Pinch threshold too strict, shoulders not visible, or the close motion is too slow/small | Ensure your shoulders are in frame; raise `PINCH_RATIO`; lower `PINCH_CLOSE_DROP`; make a more deliberate close motion |
| Buttons fire when I just move my closed hand across them | `PINCH_CLOSE_DROP` too low (any noise counts as a close) | Raise `PINCH_CLOSE_DROP` so a real open→close motion is required |
| Grabbed sphere drops when fingers drift slightly | `PINCH_HOLD_RATIO` too tight | Raise `PINCH_HOLD_RATIO` so more finger drift is tolerated before the grab releases |
| Jerky/laggy detection | Slow CPU | Use `pose_landmarker_lite.task` (already selected) — it is the fastest variant |
