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

## Output (env-driven)

| Constant | Env var | Default | Description |
|---|---|---|---|
| `OUTPUT_MODE` | `HALL_OUTPUT` | `window` | `window` (cv2 window) · `stream` (headless MJPEG server) · `web` (React frontend: raw frames + per-frame state JSON over SSE, serves `web/dist` — see [[web_state]] / [[frontend]]) |
| `STREAM_BIND` | `HALL_STREAM_BIND` | `auto` (`0.0.0.0` in web mode) | `auto` resolves the Tailscale IPv4; web mode defaults to `0.0.0.0` so the on-device kiosk can use `localhost` |
| `STREAM_PORT` | `HALL_STREAM_PORT` | `8092` | HTTP port for stream/web modes |
| `STREAM_QUALITY` | `HALL_STREAM_QUALITY` | `80` | JPEG quality 1–100 |
| `WEB_DIST_DIR` | `HALL_WEB_DIST` | `<repo>/web/dist` | Built frontend served at `/` in web mode |
| `STATE_FPS` | `HALL_STATE_FPS` | `30` | `/state` SSE push rate; also paces the main loop in web mode |

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
| `PINCH_CLOSE_RATIO` | `0.45` | **Close** threshold. The pinch machine closes when `distance(thumb_tip, index_tip) / hand_scale` drops below this (hand_scale = the hand's own knuckle span / palm length — see [[gestures]]). In knuckle units, 0.45 ≈ "tips within ~3 cm". **Higher → easier to fire.** |
| `PINCH_RELEASE_RATIO` | `0.90` | **Release** threshold (hysteresis, Ultraleap-style pinch/unpinch split). A closed machine only reopens above this looser value, so jitter at the close threshold cannot flicker the state. |
| `PINCH_DEBOUNCE_CLOSE_FRAMES` | `2` | Consecutive below-threshold frames required to close (and fire the one-frame `pinching` event). |
| `PINCH_DEBOUNCE_RELEASE_FRAMES` | `4` | Consecutive above-threshold frames required to release — more evidence than closing, because tracking gives brief false negatives while pinching-and-moving. |
| `PINCH_TRACK_GRACE_S` | `0.5` | Seconds a lost hand's state machine stays warm, so a short tracking dropout resumes mid-hold instead of cold-starting. |
| `PINCH_CURSOR_MIN_CUTOFF` / `PINCH_CURSOR_BETA` | `1.5` / `0.01` | One-Euro filter for the cursor (px): cutoff floor in Hz and its growth per unit speed. Lower cutoff = smoother but laggier at rest. |
| `PINCH_RATIO_MIN_CUTOFF` / `PINCH_RATIO_BETA` | `2.0` / `0.5` | One-Euro filter for the pinch ratio — lighter than the cursor's so clicks stay snappy. |
| `PINCH_CURSOR_THUMB_OFFSET_X` / `_Y` | `0.0` / `0.0` | 2D cursor offset in the **thumb's own frame** (origin: the thumb tip), both axes as fractions of the thumb segment (MCP 2 → tip 4) — hand-scaled and rotation-following, so they mean the same at any camera distance or hand orientation. **X** = along the thumb ray: positive floats past the tip (`0.2` ≈ a fingertip ahead), negative pulls back toward the knuckle. **Y** = perpendicular: positive always toward the **index side** of the thumb (sign resolved per hand — Left/Right mirror correctly), negative toward the outer edge. Keep both small — the thumb ray rotates slightly while the fingers close, so large values reintroduce cursor motion during the pinch. |
| `PINCH_CURSOR_COMPENSATE` | `1.0` | Close **counter-movement** (0..1): the cursor's open-pose coordinates in a rigid hand frame (wrist → index MCP) are remembered and, as the pinch progresses, the cursor is pulled back toward that remembered point — cancelling the thumb's own close travel while real hand motion (translation/rotation/zoom) still moves it 1:1. `1.0` = cursor holds still through the close; `0.0` = off (cursor rides the raw thumb tip). |
| `PINCH_EXTRAP_MAX_S` | `0.10` | Cap (s) on the cursor's latency extrapolation (One-Euro velocity × detection-result age). Lower if fast direction reversals overshoot. |
| `PINCH_Z_WEIGHT` | `0.5` | Weight of the landmark z difference in the 3D pinch distance — blocks phantom closes when hand rotation aligns the fingertips along the camera axis. 0 = pure 2D (old behavior); lower it if pinches become hard to trigger. |

## Buttons

| Constant | Default | Description |
|---|---|---|
| `BUTTON_COOLDOWN_FRAMES` | `8` | Frames before a button can fire again (moved here from `button.py`). The pinch edge-trigger + release debounce is the real double-fire guard; this only absorbs tracking glitches. |
| `BUTTON_STICKY_PAD_FRAC` | `0.15` | Sticky targets: while hovered, the hit rect inflates by this fraction of the button **height** per side (height, not width, keeps the inflation under every button gap — keep layout gaps > 0.15 × button height). Entering still requires the base rect. |

## Debug

| Constant | Default | Description |
|---|---|---|
| `DEBUG_HUD` | `False` (`HALL_DEBUG=1` enables) | Draws the [[debug_hud]] pinch-pipeline panel on the frame. |

See [[gestures]] for the full pipeline (per-frame snapshot, edge-triggered state machine, One-Euro filtering, stable anchor, latency extrapolation, 3D distance).

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
