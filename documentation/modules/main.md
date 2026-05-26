---
title: main.py
tags: [module, entrypoint]
---

# `main.py` — Entry Point

**Location:** `src/main.py`


The application entry point. Owns the camera capture loop and orchestrates detection, drawing, and UI. Contains no UI logic itself — that all lives in [[ui_manager]].

---

## Responsibilities

- Open and configure the webcam via OpenCV
- Maintain a monotonically increasing timestamp for MediaPipe's LIVE_STREAM mode
- Call `detect_async` on both detectors each frame
- Read the latest results from the `detectors` module globals
- Draw pose and hand landmarks/connections onto the frame
- Delegate UI update and draw to `UIManager`
- Handle the `q` key to quit cleanly

---

## Module-Level State

| Name | Type | Purpose |
|---|---|---|
| `start_time` | `float` | Monotonic clock origin, set at import time |
| `last_timestamp_ms` | `int` | Prevents duplicate timestamps sent to MediaPipe |

---

## `main()`

```python
def main() -> None
```

Full camera loop. Blocking — runs until the user presses `q`.

### Startup sequence

1. Build `pose_detector` and `hand_detector` via [[detectors]]
2. Open `cv2.VideoCapture(SELECTED_CAMERA)`
3. Request the capture resolution with `WINDOW_WIDTH` / `WINDOW_HEIGHT` (see [[config]])
4. Read back the effective `frame_w` / `frame_h` from the capture device (drivers may snap to the nearest supported mode)
5. Instantiate `UIManager(frame_w, frame_h)`

### Per-frame sequence

1. `camera.read()` → raw BGR frame
2. `cv2.flip(flipCode=1)` → mirror-correct for front-facing camera
3. `toMpImage()` → convert to `mp.Image` (RGB)
4. Compute `timestamps_ms` (strictly increasing)
5. `pose_detector.detect_async(...)` and `hand_detector.detect_async(...)`
6. Read `detectors.latest_pose_result` / `detectors.latest_hand_result`
7. Draw pose landmarks and connections (if pose detected)
8. Draw hand landmarks, connections, and thumb–index line (per hand)
9. Extract `pose_landmarks` (first pose, or `None`) for downstream gesture scaling
10. `ui.update(hand_result, pose_landmarks)` → process hand interaction
11. `ui.draw(frame)` → render UI overlay
11. `cv2.imshow("Camera", frame)`

12. `cv2.imshow("Camera", frame)`

### Cleanup

`camera.release()`, `pose_detector.close()`, `hand_detector.close()`, `cv2.destroyAllWindows()`

---

## Dependencies

| Import | From |
|---|---|
| `SELECTED_CAMERA` | [[config]] |
| `detectors` module (for globals), `build_pose_detector`, `build_hand_detector` | [[detectors]] (`detection/detectors.py`) |
| `toMpImage`, `draw_landmarks`, `draw_connections`, `draw_line` | [[drawing]] (`rendering/drawing.py`) |
| `UIManager` | [[ui_manager]] (`ui/manager.py`) |
