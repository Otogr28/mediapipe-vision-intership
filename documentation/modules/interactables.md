---
title: interactables.py
tags: [module, physics, interactables]
---

# `interactables.py` — Physics Objects

**Location:** `src/ui/interactables.py`

Scene objects that can be spawned by the UI. `BouncingSphere` lives in the `"interactables"` mode and has full collision physics; `SixSevenCounter` also lives in `"interactables"` and is a pose-driven gesture counter (no physics, no hand interaction); `BlackHole` lives in the `"experiments"` mode and is a pinch-draggable visual effect with no physics interaction (the BH and sphere never coexist in the current state machine, so the BH cannot affect the sphere's bounce).

---

## Module-Level Constants

| Constant | Default | Description |
|---|---|---|
| `FINGERTIP_INDICES` | `[0, 4, 8, 12, 16, 20]` | Hand landmark indices used as collision points for push interaction |
| `FINGER_RADIUS` | `14 px` | Collision radius of each fingertip point |
| `PUSH_FORCE` | `18.0` | Base impulse applied when a fingertip overlaps the sphere |
| `MAX_SPEED` | `22.0` | Speed cap (px/frame) |
| `FRICTION` | `0.985` | Velocity multiplier applied each frame when not grabbed (near-1 = low friction) |
| `GRAB_RADIUS` | `80 px` | Max distance from pinch midpoint to sphere centre to initiate a grab |
| `POSE_LEFT_ELBOW` / `POSE_RIGHT_ELBOW` | `13` / `14` | Pose landmark indices used by `SixSevenCounter` |
| `POSE_LEFT_WRIST` / `POSE_RIGHT_WRIST` | `15` / `16` | Pose landmark indices used by `SixSevenCounter` |

The grab-trigger pinch is delegated to `pinch_state(...)` from [[gestures]] using `PINCH_RATIO` from [[config]] — see those modules for the scale-aware threshold rule. The landmark indices for the pinch (thumb tip = 4, index tip = 8) are also defined there.

---

## `BouncingSphere`

A circle that bounces off frame edges, can be grabbed and dragged, and reacts to fingertip collisions.

### `__init__(frame_width, frame_height, radius=40)`

| Parameter | Type | Description |
|---|---|---|
| `frame_width` | `int` | Frame width in pixels (used for boundary checks) |
| `frame_height` | `int` | Frame height in pixels |
| `radius` | `int` | Sphere radius in pixels (default `40`) |

Spawns at frame centre with a random initial velocity of `±5` px/frame (x) and `±4` px/frame (y).

### State

| Attribute | Type | Description |
|---|---|---|
| `x`, `y` | `float` | Centre position in pixels |
| `vx`, `vy` | `float` | Velocity in pixels per frame |
| `grabbed` | `bool` | Whether the sphere is currently being held |
| `grab_offset_x/y` | `float` | Offset from pinch midpoint to sphere centre at grab initiation |

---

### `update(hand_result, pose_landmarks)`

Per-frame physics step. `pose_landmarks` is the first pose's landmark list (or `None`), used by `pinch_state` to scale the grab threshold against shoulder width.

#### Grab phase

For each detected hand, calls `pinch_state(hand_landmarks, pose_landmarks, w, h, PINCH_RATIO, hold_ratio=PINCH_HOLD_RATIO, hand_id=...)` from [[gestures]] to get `(pinching, held, (mx, my))`. The sphere needs both signals, and uses two different thresholds:

- `pinching` (rapid close, threshold = `PINCH_RATIO` — strict) — used to **initiate** a new grab. A hand that is already closed when it enters the scene cannot pick up the sphere; the user must actually perform the close motion over it.
- `held` (static closed state, threshold = `PINCH_HOLD_RATIO` — looser) — used to **maintain** an existing grab. Because the maintenance threshold is wider than the trigger threshold, the user's fingers can drift partially open without dropping the sphere ([hysteresis](https://en.wikipedia.org/wiki/Hysteresis)). Only a clear release crosses `PINCH_HOLD_RATIO` and ends the drag.

```
can_grab = (already grabbed AND held)   ←  maintenance path (loose threshold)
        OR (pinching AND sphere within GRAB_RADIUS)   ←  initiation path (strict + rapid close)

if can_grab:
  on first grab: record grab_offset_x/y
  move sphere to midpoint + grab_offset
  derive velocity from position delta (preserves momentum on release)
  set grabbed = True; skip push phase
```

When `pose_landmarks` is `None` or the shoulders are occluded, both `pinching` and `held` are `False`; the sphere releases (if grabbed) and falls through to the push phase normally.

This trigger/hold split is the reference pattern for any future interactable that needs a sustained gesture. The sphere is a physics prototype, but the surrounding logic — strict event to start, loose state to continue, pose-scaled thresholds throughout — is meant to carry over to whatever replaces it.

#### Push phase (when not grabbed)

Iterates over `FINGERTIP_INDICES` for all detected hands. If a fingertip overlaps the sphere (`dist < radius + FINGER_RADIUS`):

```
impulse = PUSH_FORCE * (1 + overlap / contact_dist)
vx += nx * impulse
vy += ny * impulse
```

Where `(nx, ny)` is the unit normal from fingertip to sphere centre.

#### Physics step (when not grabbed)

1. Apply friction: `vx *= FRICTION`, `vy *= FRICTION`
2. Clamp speed to `MAX_SPEED`
3. Integrate position: `x += vx`, `y += vy`
4. Bounce off walls: reverse the velocity component and clamp position on boundary contact

---

### `draw(frame)`

Renders the sphere using three concentric circles to create a simple shading effect.

| State | Outer ring | Fill | Highlight |
|---|---|---|---|
| Grabbed | `(0, 200, 80)` outline ring (+10 px) | `(0, 220, 100)` green | `(120, 255, 180)` |
| Free | `(0, 50, 160)` dark shadow (+6 px) | `(0, 120, 255)` blue | `(100, 210, 255)` |

---

## `BlackHole`

A Schwarzschild thin-lens black hole rendered by a GLSL fragment shader. Its visual is a circular region of distortion + a black event-horizon shadow; user input lets the pinch gesture drag it around the frame.

### `__init__(frame_width, frame_height, renderer, einstein_radius_px=…, disk_inner_factor=…, disk_outer_factor=…, disk_tilt_rad=…, disk_brightness=…)`

| Parameter | Type | Description |
|---|---|---|
| `frame_width` | `int` | Frame width in pixels (also used to position the spawn point) |
| `frame_height` | `int` | Frame height in pixels |
| `renderer` | `LensingRenderer` | Shared GPU renderer from [[gl_lensing]]. Owned by [[ui_manager]] so its GL context is created once and reused. |
| `einstein_radius_px` | `int` | Screen-space Einstein radius `E` in pixels (default from `BH_EINSTEIN_RADIUS_PX` in [[config]]) |
| `disk_inner_factor` | `float` | Disk inner radius as a multiple of `E` (default `BH_DISK_INNER_FACTOR`). Scaling vs `E` keeps proportions stable when the BH's "mass" is tuned. |
| `disk_outer_factor` | `float` | Disk outer radius as a multiple of `E` (default `BH_DISK_OUTER_FACTOR`) |
| `disk_tilt_rad` | `float` | Disk tilt in radians; 0 = face-on, π/2 = edge-on (default `BH_DISK_TILT_RAD`) |
| `disk_brightness` | `float` | Disk emission multiplier; 0 hides the disk (default `BH_DISK_BRIGHTNESS`) |
| `disk_rotation_speed` | `float` | Angular speed at the disk's inner edge (rad/s); default `BH_DISK_ROTATION_SPEED`. Outer rings shear slower per Kepler. |

Spawn position defaults to `BH_DEFAULT_POS_FACTOR · (frame_width, frame_height)` — frame centre by default.

### State

| Attribute | Type | Description |
|---|---|---|
| `x`, `y` | `float` | BH centre in OpenCV pixel coords |
| `einstein_radius_px` | `float` | Lensing strength; doubled `E` doubles visual mass |
| `disk_inner_factor` / `disk_outer_factor` | `float` | Disk extent as multiples of `einstein_radius_px` — converted to pixel radii in `draw()` |
| `disk_tilt_rad` | `float` | Disk tilt (radians) |
| `disk_brightness` | `float` | Disk emission multiplier |
| `disk_rotation_speed` | `float` | Angular speed at the disk's inner edge (rad/s); set to `0` to freeze the disk texture while keeping Doppler intact |
| `_spawn_time` | `float` | `time.monotonic()` reading captured at construction. `draw()` wraps elapsed time at 1000 s before passing to the shader so GPU float32 precision stays sharp during long deployments. |
| `grabbed` | `bool` | Whether the BH is currently being dragged |
| `grab_offset_x/y` | `float` | Offset from pinch midpoint to BH centre at grab initiation |

### `update(hand_result, pose_landmarks)`

Pinch grab + drag, no physics. Reuses the same trigger/hold split as `BouncingSphere`:

- `pinching` (rapid close, threshold = `PINCH_RATIO`) initiates a grab when the cursor is within `BH_GRAB_RADIUS` of the BH centre.
- `held` (threshold = `PINCH_HOLD_RATIO`) keeps the grab alive while the user drifts the hand. Releasing the pinch ends the drag.

While grabbed, the BH centre tracks the pinch midpoint plus the captured offset. No velocity, no friction, no collisions — the BH does **not** push or absorb other interactables and (per the project's state-machine design) cannot coexist with a sphere in the first place.

### `draw(frame)`

Converts the disk-factor multipliers to pixel radii (`disk_inner_px = E · disk_inner_factor`, similarly for outer), computes elapsed time from `_spawn_time` wrapped at 1000 s, then delegates to `LensingRenderer.render(...)` with the full disk parameter set including `time_seconds` and `rotation_speed`. The lensed bytes are written back into `frame` via `np.copyto` so the BH stays compatible with the existing UI pipeline that expects `draw(frame)` to mutate the frame in-place.

See [[gl_lensing]] for the shader, orientation, and uniform contract.

---

## `SixSevenCounter`

A pose-driven gesture counter — Python port of [mannygonzalezj7/67counter](https://github.com/mannygonzalezj7/67counter). Counts each time either wrist transitions from below to above its corresponding elbow, with hysteresis to suppress jitter near the elbow line. Renders a centred top-of-frame overlay (label + big count) that flashes green for one beat on every increment.

Lives in the `"interactables"` UI state alongside `BouncingSphere`. Singleton (one active counter at a time); pressing the spawn button again zeroes the count, and the global Reset button drops the counter entirely.

### `__init__(frame_width, frame_height)`

| Parameter | Type | Description |
|---|---|---|
| `frame_width` | `int` | Frame width in pixels — used to centre the overlay box |
| `frame_height` | `int` | Frame height in pixels |

Starts with `count = 0`, both per-arm latches disarmed, and no active flash.

### State

| Attribute | Type | Description |
|---|---|---|
| `count` | `int` | Total fired counts since spawn. Each side contributes independently — a clean alternating pump fires two counts per cycle. |
| `_left_armed` / `_right_armed` | `bool` | Per-side hysteresis latch. `True` means that side is currently "wrist clearly above elbow" and waiting for a reset stroke (wrist clearly below elbow) before it can fire again. |
| `_flash` | `int` | Frames remaining on the count-flash animation. Decays by 1 per `update()`. |

### `update(hand_result, pose_landmarks)`

Reads only `pose_landmarks` (the hand result is accepted for interface symmetry and ignored). Returns early on missing pose so the count is preserved across detection dropouts.

For each side, calls the internal `_side_armed(prev_armed, elbow, wrist)` helper, which implements:

```
require visibility(elbow, wrist) ≥ SIXSEVEN_MIN_VISIBILITY
dy = elbow.y − wrist.y          # >0 when wrist is above elbow (image coords)

if not armed and dy >  SIXSEVEN_HYSTERESIS:  → armed = True, fired = True
if     armed and dy < −SIXSEVEN_HYSTERESIS:  → armed = False, fired = False
otherwise: unchanged, fired = False
```

Each `fired` increments `self.count` and resets `self._flash` to `SIXSEVEN_FLASH_FRAMES`. The two arms maintain independent latches; coordinated alternation is not required (and not enforced) — the counter mirrors the original 67counter behaviour where either side scoring is enough.

Low-visibility frames leave the latch state untouched. This is intentional: an arm that briefly drops out of pose tracking returns in whatever logical state it left in, so a brief occlusion does not phantom-trigger a count.

### `draw(frame)`

Renders a translucent dark box at the top-centre containing the `"6 7"` label and the count number. The box border colour and the count's font scale both lerp toward a brighter / larger state proportional to `self._flash / SIXSEVEN_FLASH_FRAMES`, then decay back to neutral over `SIXSEVEN_FLASH_FRAMES` frames. The overlay is built via `cv2.addWeighted` so it dims rather than blocks the camera feed underneath.

See [[config]] for `SIXSEVEN_*` constants and [[ui_manager]] for the spawn button and singleton slot.

---

## Adding New Interactables

1. Add a new class to this file following the `update(hand_result, pose_landmarks)` / `draw(frame)` interface.
2. Add a spawn button and list (or single-instance slot, like the BH or 6 7 counter) in [[modules/ui_manager]].
3. If the new object uses GPU rendering, reuse the `LensingRenderer`'s ModernGL context or extend it — see [[gl_lensing]].
4. Document it here.
