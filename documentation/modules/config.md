---
title: config.py
tags: [module, configuration]
---

# `config.py` — Global Constants

**Location:** `src/config.py`

Single source of truth for all tunable parameters. No logic — only constants. All other modules import from here; nothing imports from other project modules.

---

## Camera

| Constant | Default | Description |
|---|---|---|
| `SELECTED_CAMERA` | `0` | OpenCV camera index passed to `cv2.VideoCapture` |
| `IMAGE_FORMAT` | `mp.ImageFormat.SRGB` | Pixel format expected by `mp.Image` |
| `WINDOW_WIDTH` | `1280` | Requested capture width (px). Applied via `cv2.CAP_PROP_FRAME_WIDTH`; the `cv2.imshow` window inherits it. Some drivers snap to the nearest supported mode, so the effective frame size is re-read after `set(...)`. |
| `WINDOW_HEIGHT` | `720` | Requested capture height (px). Same caveats as `WINDOW_WIDTH`. |

---

## Pose Landmarker

| Constant | Default | Description |
|---|---|---|
| `POSE_MODEL_PATH` | `"models/pose_landmarker_lite.task"` | Path to the MediaPipe Pose model file |
| `NUM_POSES` | `1` | Maximum simultaneous poses to detect |
| `MIN_POSE_DETECTION_CONFIDENCE` | `0.5` | Confidence threshold to declare a new pose detected |
| `MIN_POSE_PRESENCE_CONFIDENCE` | `0.5` | Confidence threshold for pose presence in a frame |
| `MIN_POSE_TRACKING_CONFIDENCE` | `0.5` | Confidence threshold to keep tracking an existing pose |

---

## Hand Landmarker

| Constant | Default | Description |
|---|---|---|
| `HAND_MODEL_PATH` | `"models/hand_landmarker.task"` | Path to the MediaPipe Hand model file |
| `NUM_HANDS` | `2` | Maximum simultaneous hands to detect |
| `MIN_HAND_DETECTION_CONFIDENCE` | `0.5` | Confidence threshold to declare a new hand detected |
| `MIN_HAND_PRESENCE_CONFIDENCE` | `0.5` | Confidence threshold for hand presence in a frame |
| `MIN_HAND_TRACKING_CONFIDENCE` | `0.5` | Confidence threshold to keep tracking an existing hand |

---

## Gesture Detection

| Constant | Default | Description |
|---|---|---|
| `PINCH_RATIO` | `0.09` | **Trigger** threshold. The fingers are "tightly closed" when `distance(thumb_tip, index_tip) < PINCH_RATIO * pose_scale`, where `pose_scale` is the shoulder-to-shoulder pixel distance from the pose. Used (with the rapid-close check) to *trigger* gestures like clicks and grab initiations. **Higher → easier to fire.** |
| `PINCH_HOLD_RATIO` | `0.25` | **Hold** threshold (hysteresis). Once a gesture has been triggered, it remains *held* while `distance(thumb_tip, index_tip) < PINCH_HOLD_RATIO * pose_scale`. Making this looser than `PINCH_RATIO` means a grabbed object survives minor finger drift — only an obvious release motion drops the gesture. Set equal to `PINCH_RATIO` to disable hysteresis. |
| `PINCH_HISTORY_LEN` | `10` | Number of recent frames per hand to retain for the rapid-close check. At ~30 fps this is ~0.33 s. |
| `PINCH_CLOSE_DROP` | `0.15` | A pinch *event* fires only when the ratio dropped by at least this much from its peak within the history window. Stops an already-closed hand from registering a pinch by sliding across the screen — the gesture must include an actual closing motion. |

See [[gestures]] for the implementation and detection rule.

---

## Black Hole

| Constant | Default | Description |
|---|---|---|
| `BH_EINSTEIN_RADIUS_PX` | `80` | Screen-space Einstein radius `E` used by the lensing shader. The lensed source radius is `r_src = r - E²/r`; pixels inside `0.5 · E` render as the event-horizon shadow. Higher → visually heavier BH. |
| `BH_GRAB_RADIUS` | `100` | Max distance (px) from the pinch midpoint to the BH centre to initiate a drag. Larger than the sphere's `GRAB_RADIUS` because the BH visual extends well beyond its centre via the lensing halo. |
| `BH_DEFAULT_POS_FACTOR` | `(0.5, 0.5)` | Initial spawn position as a fraction of frame size — frame centre by default. |
| `BH_DISK_INNER_FACTOR` | `1.5` | Accretion disk inner edge as a multiple of `E`. `1.5 · E` is roughly the innermost stable circular orbit (ISCO) in our screen-space units. |
| `BH_DISK_OUTER_FACTOR` | `4.0` | Accretion disk outer edge as a multiple of `E`. Expressing disk extent as factors of `E` means tuning `BH_EINSTEIN_RADIUS_PX` alone keeps the disk's proportions to the BH intact. |
| `BH_DISK_TILT_RAD` | `1.2` | Disk tilt in radians: `0` = face-on (boring), `π/2` = edge-on (a line). `~1.2 rad (≈69°)` is the "Interstellar" angle that shows both the front of the disk and its lensed back wrapping over the BH. |
| `BH_DISK_BRIGHTNESS` | `1.0` | Overall disk emission multiplier; `0` disables the disk visually for a "lensing only" debug view. |
| `BH_DISK_ROTATION_SPEED` | `0.8` | Angular speed of the disk's *inner* edge in rad/s. Outer rings rotate slower per Kepler's third law (`ω ∝ r^(-3/2)`), so this single knob scales the overall "rotational feel". Set to `0` to freeze the disk's procedural texture (Doppler and other physics still active). |

See [[gl_lensing]] for the shader-side use of these and [[interactables]] for the `BlackHole` class.

---

## 6 7 Counter

| Constant | Default | Description |
|---|---|---|
| `SIXSEVEN_MIN_VISIBILITY` | `0.3` | Minimum pose-landmark `visibility` for both elbow and wrist before a side participates in counting. A side that drops below this leaves its latch unchanged and never fires — a momentary tracking dropout cannot phantom-trigger a count. Set deliberately low so partial occlusions (sleeves, side angles) still count. |
| `SIXSEVEN_HYSTERESIS` | `0.01` | Half-width of the dead band around the elbow line, in normalised image coords (`1.0` = full frame height). The wrist must rise more than this above the elbow to fire, and fall more than this below the elbow before another count can fire on the same side. Tuned tight (~1% of frame height ≈ 7 px at 720p) so small flicks count. Raise toward `0.05+` if you see double-counts from jitter. |
| `SIXSEVEN_FLASH_FRAMES` | `12` | Frames over which the count-flash animation (border colour + slight count-text scale-up) decays back to neutral. At ~30 fps this is ~0.4 s. |

See [[interactables]] for the `SixSevenCounter` class.

---

## Notes

- Per-widget timing constants (e.g. `COOLDOWN_FRAMES`, sphere `GRAB_RADIUS`) live next to their consumers in [[interactableUI]] / [[interactables]], not here. BH constants are kept here because the Einstein radius is the kind of knob that's worth tuning per deployment (e.g. the Jetson install in the hallway may want a different visual scale).
- Model paths are relative to the working directory where the process is launched (i.e., the repo root when running `uv run python src/main.py`).
