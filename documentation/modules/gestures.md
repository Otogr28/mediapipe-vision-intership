---
title: gestures.py
tags: [module, detection, gestures]
---

# `gestures.py` — Pose-Scaled Pinch Detection

**Location:** `src/detection/gestures.py`

Derives high-level gestures from raw MediaPipe landmarks. The only gesture currently implemented is a **pinch** between the thumb tip and the index fingertip, but the module is designed to be the home of any future hand-shape recognisers (fist, point, open palm, …).

Pinch detection combines three ideas:

1. **Pose-scaled threshold** — the pinch is "closed" when the thumb–index distance is below `PINCH_RATIO * pose_scale`. `pose_scale` is the shoulder-to-shoulder pixel distance from the pose landmarks, which shrinks in lock-step with the hand's pixel size as the user moves away from the camera, so a single ratio works at any distance. Using the pose (not the hand) for scale also keeps the reference stable when the user closes their fingers — a hand-based scale would collapse into a fist and false-fire the threshold.
2. **Rapid-close requirement** — a *closed* hand only counts as a *pinch event* if the ratio dropped by at least `PINCH_CLOSE_DROP` from its peak within the last `PINCH_HISTORY_LEN` frames. This is the difference between the gesture (open → close) and the static shape (already closed). A fist sliding across a button will not register a click because the ratio history shows no closing motion.
3. **Hysteresis** — a separate (looser) `hold_ratio` decides whether a gesture is still *held*. Once a grab has been triggered by a tight pinch, the user's fingers can drift partially open without dropping the gesture; only crossing `hold_ratio` releases it. This avoids the "fragile grab" problem where slight finger jitter makes the sphere fall out of your hand.

So the detector returns two booleans:

- `pinching` (event, strict + rapid close) → use to **trigger** new gestures.
- `held` (state, loose threshold) → use to **maintain** gestures already triggered.

The midpoint of the two pinch landmarks is always returned for cursor use.

---

## Module-Level Constants

| Constant | Default | Description |
|---|---|---|
| `PINCH_LANDMARK_A` | `4` | Thumb tip — hand landmark index |
| `PINCH_LANDMARK_B` | `8` | Index finger tip — hand landmark index |
| `POSE_SCALE_A` | `11` | Left shoulder — pose landmark index |
| `POSE_SCALE_B` | `12` | Right shoulder — pose landmark index |
| `POSE_SCALE_MIN_VISIBILITY` | `0.5` | Per-shoulder visibility floor; below this, scale is treated as unavailable |

Tunable thresholds (`PINCH_RATIO`, `PINCH_HISTORY_LEN`, `PINCH_CLOSE_DROP`) live in [[config]].

---

## Functions

### `hand_id(hand_result, i) → str`

Returns a stable id for the *i*-th hand in a `HandLandmarkerResult`, preferring MediaPipe's handedness category (`"Left"` / `"Right"`) over the iteration index. The per-hand ratio history is keyed on this id, so using handedness keeps tracking stable even when MediaPipe reorders hands between frames. Falls back to `"hand_{i}"` when handedness is unavailable.

---

### `pose_scale(pose_landmarks, frame_w, frame_h) → float`

Returns the **shoulder-to-shoulder pixel distance** from a pose landmark list.

| Parameter | Type | Description |
|---|---|---|
| `pose_landmarks` | `list[NormalizedLandmark] \| None` | One pose's landmarks (i.e. `pose_result.pose_landmarks[0]`), or `None` |
| `frame_w`, `frame_h` | `int` | Frame dimensions in pixels |

**Returns:** shoulder distance in pixels, or `0.0` when no pose is detected or either shoulder has visibility below `POSE_SCALE_MIN_VISIBILITY`. Callers should treat `0.0` as *"no scale available — skip gesture detection"*.

---

### `pinch_state(hand_landmarks, pose_landmarks, frame_w, frame_h, ratio, hold_ratio=None, hand_id="default", a_idx=4, b_idx=8) → (bool, bool, (float, float))`

Detects a thumb–index pinch with a rapid-close requirement and optional hysteresis between triggering and holding.

| Parameter | Type | Description |
|---|---|---|
| `hand_landmarks` | `list[NormalizedLandmark]` | One hand's landmarks |
| `pose_landmarks` | `list[NormalizedLandmark] \| None` | Pose landmarks for the scale reference |
| `frame_w`, `frame_h` | `int` | Frame dimensions in pixels |
| `ratio` | `float` | Trigger threshold. Usually `PINCH_RATIO` from [[config]]. |
| `hold_ratio` | `float \| None` | Hold threshold for hysteresis. Defaults to `ratio` (no hysteresis) when `None`. Pass a larger value (e.g. `PINCH_HOLD_RATIO`) to make holds more forgiving than triggers. |
| `hand_id` | `str` | Stable id keying the per-hand ratio history. Use `hand_id(hand_result, i)`. |
| `a_idx`, `b_idx` | `int` | Landmark indices to compare. Defaults to thumb tip (4) and index tip (8). |

**Returns:** `(pinching, held, (midpoint_x, midpoint_y))`.

| Field | Meaning | Use it for |
|---|---|---|
| `pinching` | True only when fingers are closed **strictly** (below `ratio`) **and** the ratio dropped by at least `PINCH_CLOSE_DROP` within the last `PINCH_HISTORY_LEN` frames | **Trigger** actions — button click, grab initiation. A statically-closed hand will not fire. |
| `held` | True whenever the fingers are within `hold_ratio` (looser threshold when `hold_ratio > ratio`) | **Maintain** an already-triggered action — keep dragging a grabbed sphere even if the fingers drift slightly open |
| `(midpoint_x, midpoint_y)` | Pixel midpoint of the two pinch landmarks | Cursor position (always provided, even when not pinching) |

#### Detection rule

```
pinch_dist     = distance(hand[a_idx], hand[b_idx])              (pixels)
scale          = pose_scale(pose_landmarks, frame_w, frame_h)    (pixels)
current_ratio  = pinch_dist / scale
recent_max     = max(ratio_history[hand_id])    over last PINCH_HISTORY_LEN frames
closing_drop   = recent_max - current_ratio

held     = (scale > 0)  and (current_ratio < hold_ratio)
pinching = (scale > 0)  and (current_ratio < ratio)
                       and (closing_drop >= PINCH_CLOSE_DROP)
```

`held` and `pinching` are independent — when `hold_ratio == ratio` they collapse into a single condition (no hysteresis). When `hold_ratio > ratio`, every `pinching` frame is also `held`, but `held` extends further as the fingers open.

When `scale == 0` (no pose / shoulders occluded), both flags are `False` but the midpoint is still returned so hover-only interactions keep working.

---

## Consumers

| Caller | Uses `pinching` for | Uses `held` for |
|---|---|---|
| [[interactableUI]] (`Button.update`) | Click activation | — |
| [[interactables]] (`BouncingSphere.update`) | Grab initiation (with sphere within `GRAB_RADIUS`) | Keeping an existing grab alive |

Both pass `PINCH_RATIO` from [[config]] so the threshold is centrally tunable, and both pull `pose_landmarks` plumbed down from `main.py` via [[ui_manager]].

---

## Adding a New Gesture

1. Add the detection function to this module. Take `hand_landmarks`, `pose_landmarks`, `frame_w`, `frame_h`, and any tuning parameters; return both a trigger signal (event) and, if relevant, a held signal (state).
2. Express all distance thresholds **relative to `pose_scale(...)`**, never as raw pixels. This is the only way the gesture survives changes in camera distance, and the only way to stay robust to finger-pose changes.
3. If your gesture needs an "actual motion" check (not just a static shape), maintain per-hand history keyed on `hand_id(...)` and require a drop/rise of the right magnitude over the window.
4. Put any tunable constants in [[config]].
5. Document it in this file and link from the consuming module's doc.

See also: [[modules/detectors]], [[modules/interactableUI]], [[modules/interactables]], [[architecture#Hand Interaction Model]]
