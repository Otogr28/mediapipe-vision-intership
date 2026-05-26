---
title: detectors.py
tags: [module, mediapipe, detection]
---

# `detectors.py` — Detector Factories & Shared Results

**Location:** `src/detection/detectors.py`

Builds the MediaPipe `PoseLandmarker` and `HandLandmarker` instances and exposes their latest results as module-level globals so `main.py` can read them each frame without callbacks leaking into the render loop.

---

## Module-Level Globals

| Name | Type | Initial value | Purpose |
|---|---|---|---|
| `latest_pose_result` | `PoseLandmarkerResult \| None` | `None` | Written by `on_pose_result` callback on every detection event |
| `latest_hand_result` | `HandLandmarkerResult \| None` | `None` | Written by `on_hand_result` callback on every detection event |

These are the **only** shared mutable state in the project. `main.py` reads them directly after calling `detect_async`.

---

## Callbacks

### `on_pose_result(result, output_image, timestamp_ms)`

MediaPipe LIVE_STREAM callback. Writes `result` to `latest_pose_result`.

### `on_hand_result(result, output_image, timestamp_ms)`

MediaPipe LIVE_STREAM callback. Writes `result` to `latest_hand_result`.

---

## Factory Functions

### `build_pose_detector() → PoseLandmarker`

Creates and returns a `vision.PoseLandmarker` configured from [[config]] constants.

| Option | Source |
|---|---|
| `model_asset_path` | `POSE_MODEL_PATH` |
| `running_mode` | `LIVE_STREAM` |
| `num_poses` | `NUM_POSES` |
| `min_pose_detection_confidence` | `MIN_POSE_DETECTION_CONFIDENCE` |
| `min_pose_presence_confidence` | `MIN_POSE_PRESENCE_CONFIDENCE` |
| `min_tracking_confidence` | `MIN_POSE_TRACKING_CONFIDENCE` |
| `result_callback` | `on_pose_result` |

### `build_hand_detector() → HandLandmarker`

Creates and returns a `vision.HandLandmarker` configured from [[config]] constants.

| Option | Source |
|---|---|
| `model_asset_path` | `HAND_MODEL_PATH` |
| `running_mode` | `LIVE_STREAM` |
| `num_hands` | `NUM_HANDS` |
| `min_hand_detection_confidence` | `MIN_HAND_DETECTION_CONFIDENCE` |
| `min_hand_presence_confidence` | `MIN_HAND_PRESENCE_CONFIDENCE` |
| `min_tracking_confidence` | `MIN_HAND_TRACKING_CONFIDENCE` |
| `result_callback` | `on_hand_result` |

---

## Notes

- Both detectors **must be closed** when the application exits (`detector.close()`). `main.py` handles this in its cleanup block.
- LIVE_STREAM mode requires strictly increasing timestamps. See [[modules/main]] for how the timestamp is managed.
- The global-variable pattern is intentional: it avoids passing callbacks or queues across module boundaries while keeping the render loop simple.
