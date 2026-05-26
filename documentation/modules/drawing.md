---
title: drawing.py
tags: [module, rendering, opencv]
---

# `drawing.py` — Rendering Helpers

**Location:** `src/rendering/drawing.py`

Pure rendering utilities. No state, no side effects beyond drawing on the provided frame buffer. All functions operate on normalized landmark coordinates (0.0–1.0) and scale them to pixel space using the frame dimensions.

---

## `toMpImage(frame) → mp.Image`

Converts an OpenCV BGR frame to a MediaPipe `mp.Image` (SRGB).

| Parameter | Type | Description |
|---|---|---|
| `frame` | `np.ndarray` | BGR frame from `cv2.VideoCapture` |

**Returns:** `mp.Image` suitable for `detect_async`.

Performs `cv2.cvtColor(BGR → RGB)` then wraps with `mp.Image(image_format=IMAGE_FORMAT, data=...)`.

---

## `draw_landmarks(individual_detection, frame)`

Draws a filled green circle (`radius=4`) at each visible landmark.

| Parameter | Type | Description |
|---|---|---|
| `individual_detection` | list of `NormalizedLandmark` | One pose or hand detection |
| `frame` | `np.ndarray` | Frame to draw onto (modified in place) |

Landmarks with `visibility < 0.5` are skipped. Landmarks where `visibility` is `None` (hand landmarks) are always drawn.

---

## `draw_connections(individual_detection, frame, connections)`

Draws blue lines (`thickness=2`) between connected landmark pairs.

| Parameter | Type | Description |
|---|---|---|
| `individual_detection` | list of `NormalizedLandmark` | One pose or hand detection |
| `frame` | `np.ndarray` | Frame to draw onto (modified in place) |
| `connections` | iterable of `Connection` | Pairs of start/end landmark indices (e.g. `PoseLandmarksConnections.POSE_LANDMARKS`) |

A connection is skipped if either endpoint has `visibility < 0.5`.

---

## `draw_line(individual_detection, frame, startI, endI)`

Draws a green line between two specific landmarks and labels it with the pixel distance at the midpoint.

| Parameter | Type | Description |
|---|---|---|
| `individual_detection` | list of `NormalizedLandmark` | One detection |
| `frame` | `np.ndarray` | Frame to draw onto (modified in place) |
| `startI` | `int` | Landmark index for the start point |
| `endI` | `int` | Landmark index for the end point |

Used in `main.py` to visualise the thumb–index distance (`startI=4`, `endI=8`).

Distance label format: `"{dist:.1f}px"` rendered with `FONT_HERSHEY_SIMPLEX` at the midpoint.

---

## Colour Reference

| Element | BGR colour |
|---|---|
| Landmark dot | `(0, 255, 0)` — green |
| Connection line | `(255, 0, 0)` — blue |
| `draw_line` line | `(0, 255, 0)` — green |
| Distance label | `(255, 255, 255)` — white |
