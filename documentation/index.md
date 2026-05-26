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

---

## Project Layout

```
HalLMediaPipe/
├── src/
│   ├── main.py                    Entry point: camera loop
│   ├── config.py                  Global constants and thresholds
│   ├── detection/
│   │   ├── detectors.py           MediaPipe detector factories + shared result state
│   │   └── gestures.py            Pose-scaled pinch detection (pose_scale, pinch_state)
│   ├── rendering/
│   │   ├── drawing.py             Landmark and connection rendering helpers
│   │   ├── gl_lensing.py          ModernGL renderer (Schwarzschild lensing shader)
│   │   └── shaders/               GLSL shader sources (fullscreen.vert, black_hole.frag)
│   └── ui/
│       ├── manager.py             UI state machine, button layout, scene objects
│       ├── button.py              Button widget (pinch interaction)
│       └── interactables.py       Scene objects (BouncingSphere, BlackHole)
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

---

> **Maintenance note:** Keep this documentation in sync with code changes. When a module's API, constants, or behaviour changes, update the corresponding file in `documentation/modules/`.
