---
title: HalLMediaPipe — Documentation Hub
tags: [index, overview]
---

# HalLMediaPipe

Real-time hand and pose interaction system built with MediaPipe and OpenCV. Detects body and hand landmarks from a webcam feed and renders an interactive UI overlay controlled entirely by hand gestures (pinch to click, grab to drag).

---

## Quick Links

| Area                     | File                       |
| ------------------------ | -------------------------- |
| Architecture & data flow | [[architecture]]           |
| Setup & running          | [[setup]]                  |
| `main.py`                | [[modules/main]]           |
| `config.py`              | [[modules/config]]         |
| `detectors.py`           | [[modules/detectors]]      |
| `gestures.py`            | [[modules/gestures]]       |
| `drawing.py`             | [[modules/drawing]]        |
| `gl_lensing.py`          | [[modules/gl_lensing]]     |
| `ui_manager.py`          | [[modules/ui_manager]]     |
| `interactableUI.py`      | [[modules/interactableUI]] |
| `interactables.py`       | [[modules/interactables]]  |
| `hints.py`               | [[modules/hints]]          |
| `cursor.py`              | [[modules/cursor]]         |
| `debug_hud.py`           | [[modules/debug_hud]]      |
| `web/state.py` (web mode)| [[modules/web_state]]      |
| `web/` React frontend    | [[modules/frontend]]       |

---

## Project Layout

```
HalLMediaPipe/
├── src/
│   ├── main.py                    Entry point: camera loop
│   ├── capture.py                 FreshestFrame — threaded latest-frame reader (low latency)
│   ├── config.py                  Global constants and thresholds
│   ├── detection/
│   │   ├── detectors.py           MediaPipe detector factories + shared result state
│   │   └── gestures.py            Pinch pipeline (update_pinches, pinch_state, hand_scale)
│   ├── rendering/
│   │   ├── drawing.py             Landmark and connection rendering helpers
│   │   ├── gl_lensing.py          ModernGL renderer (Schwarzschild lensing shader)
│   │   └── shaders/               GLSL shader sources (fullscreen.vert, black_hole.frag)
│   ├── ui/
│   │   ├── manager.py             UI state machine, button layout, scene objects
│   │   ├── button.py              Button widget (pinch interaction, sticky targets)
│   │   ├── interactables.py       Scene objects (BouncingSphere, BlackHole)
│   │   ├── hints.py               Onboarding overlays (intro splash + pinch hint)
│   │   ├── cursor.py              Always-on pinch cursor (progress ring + click flash)
│   │   └── debug_hud.py           HALL_DEBUG=1 pinch-pipeline HUD
│   └── web/
│       └── state.py               Web mode: per-frame UI/gesture state → JSON (SSE)
├── web/                           React frontend (HALL_OUTPUT=web) — browser renders all UI
│   ├── src/                       state hook, Canvas2D overlays, WebGL black hole, HUD
│   └── scripts/                   mock_backend.py (camera-less scenes), shot.mjs (screenshots)
├── models/
│   ├── pose_landmarker_lite.task
│   └── hand_landmarker.task
├── documentation/                 ← you are here
└── pyproject.toml
```

---

## Tech Stack

| Dependency | Purpose |
|---|---|
| `mediapipe >= 0.10.35` | Pose and hand landmark detection (LIVE_STREAM mode) |
| `opencv-python >= 4.13` | Camera capture and frame rendering |
| `moderngl >= 5.10` | GPU rendering for the Schwarzschild lensing shader (`gl_lensing.py`) |
| Python `3.12` | Runtime |
| Vite + React + TypeScript (`web/`, dev-only toolchain) | Browser frontend for `HALL_OUTPUT=web`; built `dist/` is served by the Python backend |

---

> **Maintenance note:** Keep this documentation in sync with code changes. When a module's API, constants, or behaviour changes, update the corresponding file in `documentation/modules/`.
