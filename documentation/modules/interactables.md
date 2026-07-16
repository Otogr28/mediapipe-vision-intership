---
title: interactables.py
tags: [module, physics, interactables]
---

# `interactables.py` — Physics Objects

**Location:** `src/ui/interactables.py`

Scene objects that can be spawned by the UI. `BouncingSphere` lives in the `"interactables"` mode and has full collision physics; `SixSevenCounter` also lives in `"interactables"` and is a pose-driven gesture counter (no physics, no hand interaction); `BlackHole` and `Slingshot` live in the `"experiments"` mode — the BH is a pinch-draggable lensing effect with no physics, the Slingshot is a pinch-to-launch projectile with full CPU physics. Only one experiment is active at a time, so they never coexist.

---

## Module-Level Constants

| Constant | Default | Description |
|---|---|---|
| `FINGERTIP_INDICES` | `[0, 4, 8, 12, 16, 20]` | Hand landmark indices used as collision points for push interaction |
| `FINGER_RADIUS` | `14 px` | Collision radius of each fingertip point |
| `PUSH_FORCE` | `18.0` | Base impulse applied when a fingertip overlaps the sphere |
| `MAX_SPEED` | `22.0` | Speed cap (px/frame) |
| `FRICTION` | `0.985` | Velocity multiplier applied each frame when not grabbed (near-1 = low friction) |
| `GRAB_RADIUS` | `80 px` | Max distance from pinch cursor to sphere centre to initiate a grab |
| `POSE_LEFT_ELBOW` / `POSE_RIGHT_ELBOW` | `13` / `14` | Pose landmark indices used by `SixSevenCounter` |
| `POSE_LEFT_WRIST` / `POSE_RIGHT_WRIST` | `15` / `16` | Pose landmark indices used by `SixSevenCounter` |

The grab-trigger pinch is delegated to [[gestures]]: `UIManager.update` advances the per-hand pinch machines once per frame (`update_pinches`), and interactables just read the snapshot with `pinch_state(hand_id)`. Thresholds (`PINCH_CLOSE_RATIO` / `PINCH_RELEASE_RATIO`) live in [[config]]; the landmark indices for the pinch (thumb tip = 4, index tip = 8) are defined in [[gestures]].

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
| `grab_hand` | `str \| None` | Owner: the `hand_id` that initiated the grab; only this hand can maintain/move it |
| `grab_offset_x/y` | `float` | Offset from pinch cursor to sphere centre at grab initiation |

---

### `update(hand_result, pose_landmarks)`

Per-frame physics step. `pose_landmarks` is the first pose's landmark list (or `None`); the pinch itself no longer needs it (the [[gestures]] pipeline scales by the hand's own knuckle span).

#### Grab phase

The grab is **owner-latched**. While not grabbed, each detected hand's per-frame snapshot `pinch_state(hand_id(hand_result, i))` is checked for the initiation condition; the hand that succeeds is latched as the owner (`grab_hand`). While grabbed, **only the owner's machine is read** — directly via `pinch_state(grab_hand)`, whether or not that hand appears in this frame's result. The two signals split as everywhere else:

- `pinching` (edge event) — fires once, on the open→closed transition; used to **initiate** a new grab. A hand that is already closed when it enters the scene cannot pick up the sphere; the user must actually perform the close motion over it.
- `held` (level state) — used to **maintain** the owner's grab. The state machine only reopens above the looser `PINCH_RELEASE_RATIO` sustained for several frames ([hysteresis](https://en.wikipedia.org/wiki/Hysteresis) + debounce), so finger drift or a one-frame tracking blip can't drop the sphere. Only a clear release by the owner — or the owner's machine expiring past `PINCH_TRACK_GRACE_S` — ends the drag.

```
if grabbed:                                  ← owner latch
  (_, held, cursor) = pinch_state(grab_hand)
  held  → move sphere to cursor + grab_offset; derive velocity from the
          position delta (preserves momentum on release)
  !held → release (fingers opened, or hand expired past the grace window)
if not grabbed:
  for each hand: pinching AND sphere within GRAB_RADIUS
                 → latch grab_hand, record grab_offset_x/y, zero velocity
```

This trigger/hold/owner split is the reference pattern for any future interactable that needs a sustained gesture: edge event to start, hysteresis state to continue, owner latch so a second hand can't steal it, hand-scaled thresholds throughout.

> **✔ Fixed (2026-07-06) — two-hand grab steal.**
> `grabbed` used to be an ownerless object-level flag: the maintenance path `can_grab = (grabbed and held) or …` was evaluated per hand in iteration order, so one hand pinch-holding *in the air* while the *other* hand grabbed the object won the maintenance check on the next frame and the object **teleported** to it. All three sites (`BouncingSphere.grabbed`, `BlackHole.grabbed`, `Slingshot.aiming`) now latch the owner `hand_id` at initiation (`grab_hand` / `aim_hand`) and only that hand can maintain/move the gesture. Side benefit: because the owner's machine is read directly, a grab now also survives a short tracking dropout (frozen in place, ≤ `PINCH_TRACK_GRACE_S`) and releases normally once the hand expires past the grace window — the slingshot then fires with the pull it had. Verified synthetically (owner-latch suite: steal repro, owner-follow, dropout/grace, release).

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
| `grab_hand` | `str \| None` | Owner: the `hand_id` that initiated the drag; only this hand can move it |
| `grab_offset_x/y` | `float` | Offset from pinch cursor to BH centre at grab initiation |

### `update(hand_result, pose_landmarks)`

Pinch grab + drag, no physics. Reuses the same trigger/hold/owner split as `BouncingSphere`:

- `pinching` (fresh close event) initiates a grab when the cursor is within `BH_GRAB_RADIUS` of the BH centre; that hand is latched as the owner (`grab_hand`).
- `held` (hysteresis state) of the **owner's** machine keeps the grab alive while the user drifts the hand. A clear release (past `PINCH_RELEASE_RATIO`, debounced) — or the owner expiring past the tracking grace window — ends the drag; another held hand cannot steal it.

While grabbed, the BH centre tracks the owner's pinch cursor plus the captured offset. No velocity, no friction, no collisions — the BH does **not** push or absorb other interactables and (per the project's state-machine design) cannot coexist with a sphere in the first place.

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

## `Slingshot`

A projectile-motion experiment (the second entry in the `"experiments"` picker, alongside `BlackHole`), simulated in **SI units** (metres, seconds, kilograms, newtons). A ball rests on a fixed anchor near the bottom-centre of the frame. A pinch *near the anchor* grabs it; while the hand stays closed the ball is pulled back — a rubber-band aim clamped at `SLING_MAX_PULL_PX` — a dotted arc previews the shot, and a two-line HUD above the anchor reads out the live **launch angle (°) and speed (m/s)** plus the band's **draw force (N)** and its **stored vs. delivered energy (J)**. Releasing launches the ball under real gravity (9.81 m/s²) with quadratic air drag; it bounces off the walls and floor with restitution and Coulomb friction, **collides elastically with every other shot**, leaves a fading trail, and continuously draws the **force vectors acting on it** (weight, drag, contact/normal, and their vector sum). Up to `SLING_MAX_PROJECTILES` shots coexist (the oldest is dropped past the cap). Like `BlackHole`, aiming reuses `pinch_state`, so it needs the pose scale — the shoulders must be visible.

### Simulation techniques

Standard real-time-physics techniques, deliberately textbook:

- **Fixed-timestep accumulator.** Each video frame banks `time_scale · SLING_FRAME_DT` (1/30 s at 1×) of simulated time and the world advances in whole **`SLING_PHYS_DT`** (1/120 s) sub-steps, capped at `SLING_MAX_SUBSTEPS` (excess debt is dropped, not stalled on). The sim-speed buttons change how *many* steps run per frame — never the step size — so accuracy and stability are identical at every speed.
- **Classic RK4 integration.** Free flight (gravity + velocity-dependent drag) is integrated with a 4th-order Runge-Kutta step (`_rk4_step`), the textbook integrator for projectile motion with drag. The aim preview uses the *same* step, so the dotted arc matches the real flight exactly.
- **Slingshot energy model** (Yeats, ["Physical modeling of real-world slingshots"](https://arxiv.org/abs/1604.00049)). The drawn band stores `E = ½·k·x²` (Hooke's-law draw force `F = k·x`, `SLING_BAND_K` = 44.2 N/m — a real latex-band value) but delivers only `SLING_BAND_EFF` (75%) of it as projectile KE — latex hysteresis plus the band/pouch's own kinetic energy eat the rest (Yeats measures 10–25%). Launch speed follows as `v0 = x·√(k·eff/m)` (`_launch_velocity`), and the aim HUD shows the whole energy chain (`DRAW … N`, `E … J -> KE … J`).
- **Impulse-based collision response with a Coulomb friction cone.** Wall/floor bounces reflect the normal component with restitution (normal impulse `jn = m·(1+e)·|vn|`) and oppose the tangential one with a friction impulse capped at `|jt| ≤ μ·|jn|` (`SLING_FRICTION_MU` = 0.5) — the same model Box2D-style engines use (see Gaffer On Games, ["Collision Response and Coulomb Friction"](https://gafferongames.com/post/collision_response_and_coulomb_friction/)). Once the bounce energy is spent the ball **skids** under kinetic friction `f = μ·m·g` (a `sliding` state) until it drops below `SLING_REST_SPEED` and rests. Ball-vs-ball impacts exchange the normal component with restitution and positional correction (see `_resolve_collisions()` below).

### Units and scale

Physics state is stored in SI; **`SLING_PX_PER_M`** (100 px = 1 m, so a 1920×1080 frame is a ~19.2 × 10.8 m arena) bridges to the video's pixels. The pinch cursor arrives in pixels and is converted to metres at the boundary; `_px(m)` converts back for drawing. Ball mass is `SLING_BALL_MASS` (equal for all → collisions are a clean velocity exchange). Drag is **quadratic aerodynamic drag** `F = −½·ρ·Cd·A·|v|·v` with real constants (`SLING_AIR_DENSITY` 1.225 kg/m³, `SLING_DRAG_CD` 0.47 for a smooth sphere, `A = πr²` from the ball's actual radius) — the correct regime for a ball at m/s speeds; the lumped `½ρCdA` is precomputed as `_drag_k`. The resulting terminal velocity `√(mg/k)` ≈ 15 m/s is shown in the legend.

### `__init__(frame_width, frame_height)`

Stores the frame extent and ball radius in metres, places the anchor at `(0.5·w, 0.82·h)`, precomputes `_drag_k`, and starts with no projectiles, not aiming, at 1× sim speed.

### Sim speed

`time_scale` (property) is the current speed multiplier; `speed_up()` / `speed_down()` step it through **`SLING_TIME_SCALES`** `(0.25, 0.5, 1, 2, 4)`. [[ui_manager]] wires these to the top-right `-` / `+` buttons and readout pill, shown for any experiment that exposes a `time_scale`.

### State

| Attribute | Type | Description |
|---|---|---|
| `aiming` | `bool` | True while a grabbed ball is being pulled back. Exposed read-only via the `grabbed` property (the interface `UIManager` uses to retire the onboarding hint / detect interaction). |
| `aim_hand` | `str \| None` | Owner: the `hand_id` that started the aim; only this hand can pull, and only its release fires. |
| `pull_x` / `pull_y` | `float` | Current (clamped) ball position **in metres** while aiming; equal to the anchor when idle. |
| `projectiles` | `list[_Projectile]` | In-flight and resting balls. Each `_Projectile` (a `__slots__` value object) carries SI `x, y` (m), `vx, vy` (m/s), a bounded pixel `trail`, a `resting` flag (set once it settles on the floor so it stops integrating), a `sliding` flag (skidding along the floor under kinetic friction), and `cfx, cfy` — the net contact force (N) this frame, kept only for the overlay. |

### `update(hand_result, pose_landmarks)`

Two phases. **Aim:** while idle, each hand's `pinch_state` is checked — a fresh `pinching` within `SLING_GRAB_RADIUS_PX` of the anchor starts an aim and latches that hand as the owner (`aim_hand`); while aiming, only the **owner's** `held` sustains the pull (same trigger/hold/owner split as `BouncingSphere` — the other hand pinch-holding in the air cannot yank the shot). Fingers opening (`held` drops) — or the owner's machine expiring past the tracking grace window (pull frozen until then) — fires the shot via `_fire()`, which captures the launch point/velocity *before* resetting the aim, ignores a dead-fire, and enforces the projectile cap. **Integrate:** transient contact-force arrows fade by `SLING_CONTACT_DECAY`; the frame's simulated time (`time_scale · SLING_FRAME_DT`) is banked into the accumulator and the world advances in whole `SLING_PHYS_DT` sub-steps — each sub-step RK4-integrates every non-resting projectile (weight `m·g` + quadratic drag) and resolves wall/floor bounces (restitution + Coulomb-cone friction) or floor skidding via `_step()`, then `_resolve_collisions()` handles every ball pair. Contact impulses are reported as the average force over the frame's simulated time so the overlay reads in steady newtons. Finally resting balls are given the steady floor normal (`−m·g`, so their net force reads zero), sliding balls the normal plus the kinetic-friction force `μ·m·g` opposing the skid (so their net force reads as pure friction), and every ball appends its pixel position to its trail.

`_resolve_collisions()` does equal-mass 2-D elastic collisions: overlapping pairs are separated by splitting the overlap, and pairs that are actually *approaching* (relative velocity along the contact normal `> SLING_REST_SPEED`) exchange that normal component with `SLING_COLLISION_RESTITUTION`, recording the impulse as an equal-and-opposite contact force (N) on both balls. A genuine impact wakes resting balls (`resting = False`) so a settled pile can be knocked apart; a gentle touch between two already-settled balls only separates them, with no impulse, so the pile doesn't jitter. A final clamp keeps every ball inside the frame.

### `draw(frame)`

Draws a colour **legend** (top-left) mapping each arrow tag+colour to its force plus the SI constants in play (`g`, `m`, `r`, `Cd`, `ρ`, terminal velocity, band `k`/`eff`, `μ`, integrator) — the box is sized from the measured text extents (`cv2.getTextSize`), so no row can overflow it; the anchor post; while aiming, the rubber band, the dotted `_predicted_arc()` (same RK4 step as the live physics), the pulled ball, and a translucent two-line HUD above the anchor (clamped on-screen) showing the live **launch angle, speed, draw force and stored → delivered energy** from `_aim_readout()`; otherwise an idle ball. Each projectile renders with a velocity-fading trail and, via `_draw_force_arrow()` (scaled `SLING_FORCE_PX_PER_N` px per newton), the vectors for **weight** (amber, tag `W`), **drag** (cyan, `D`), **contact/normal** (green, `N`) and the **net force** (white, `net`, dashed shaft). Arrows start at the ball's edge (never covering it), carry a dark under-stroke, a fixed-size filled head and a colour-matched tag letter at the tip, and are length-capped at `SLING_FORCE_MAX_PX` so a bounce impulse cannot span the screen. The net arrow is dashed (and its tag pushed further out) because in free fall it coincides exactly with the weight arrow — solid-on-solid was unreadable.

Tuning constants (`SLING_*`) live at the top of `interactables.py` next to the class — following the `BouncingSphere` precedent of keeping a CPU interactable's physics knobs local rather than in [[config]]. See [[ui_manager]] for the experiment picker slot.

---

## `Spacetime`

Relativistic gravity sandbox: a wireframe sheet that bends under the masses you place, and test particles whose orbits **precess**. Tuning constants are `ST_*` in [[config]] (following the newer `ORB_*`/`WAVE_*`/`CHG_*` precedent rather than the module-local `SLING_*` one).

> The three experiments added before this one (`Orbitals`, `Waves`, `Charges`) are not yet written up in this file — see their `ST_*`-style config blocks and class docstrings, which carry the same detail.

### One geometry, everything else

Each mass gets a Schwarzschild radius `rs = ST_RS_PER_MASS * m`, and that same `rs` drives every other part — so the shape on screen and the physics the particles feel are the same spacetime, not unrelated effects. Fixing `rs` per unit mass also fixes `c` in screen units (`rs = 2GM/c²`), which is why there is no separate `c` knob (`_C_SCREEN` is derived).

- **The sheet (2D view)** is Flamm's paraboloid `z(r) = 2·√(rs·(r − rs))`, the exact embedding of the Schwarzschild equatorial slice, measured *downward* from `ST_CURV_REACH_PX` so each well is local and finite (it bottoms out at the throat instead of diverging like a Newtonian 1/r funnel).
- **The lattice (3D view)** is a *volume*, mapped by Schwarzschild's **isotropic** coordinate relation `r = r̄(1 + rs/(4r̄))²`, inverted in `_isotropic_radius`, which lands the horizon at `r̄ = rs/4`. Drawing a uniform lattice at `r̄` compresses space toward each mass — no fake extra dimension and no "downhill", just distances being stretched, which is what curvature actually is. It is the honest picture; the sheet is the famous one.
- **The dynamics** are the post-Newtonian **EIH (1PN)** N-body equations ([EIH 1938], Will 1993 eq. 6.80 — the same framework JPL's DE440 ephemeris uses) plus Peters' gravitational-wave drag, so bound pairs genuinely inspiral and merge. Validated against the exact GR perihelion formula in `tests/smoke_scenes.py`. Mukhopadhyay (2002)'s pseudo-Newtonian **Kerr** force (exact Kerr ISCO; collapses to Paczyński–Wiita at `a* = 0`) survives only in `_pair_force`, which backs the spawn-velocity solver — the live integration carries **no spin terms** (1PN EIH has none).
- **Spin** still shapes the geometry that capture and the renderer read: `r_horizon` shrinks toward `rs/2` with spin while the ergosphere ring stays at `rs`, so the **gap between the two rings is the spin** — and closes by itself at `a* = 0`. Frame dragging is drawn by `_drag_frame`'s Lense–Thirring swirl `ω = 2GJ/(c²r³)` (display-only).

Superposing per-mass geometry is **not** a solution of Einstein's equations — they are nonlinear, so wells and lattices do not really superpose. It is the standard visual approximation, exact for a single mass. **Everything gravitates and moves**, masses included (the old pinned-masses call was reversed — see the `ST_ORB_G` note in [[config]]). A body that leaves the renderable patch of the plane (`ST_PRUNE_MARGIN`, 1.8× the frame — just past the drawn sheet and the widest zoom) is **removed**, grabbed masses exempt: an off-screen mass would keep pulling the scene with no visible cause.

### Display-only geometry

Display-side scaling, kept strictly out of the physics. The sheet is drawn **to scale** (`ST_DEPTH_GAIN = 1.0`; the old `ST_MAX_DEPTH_PX` tanh ceiling is gone — it squashed a hole into looking like a deep star, see the config note). `ST_LATTICE_GAIN` scales the lattice's radial pull because the isotropic map is honest and therefore *tiny*: it saturates at `rs/2`, ~18 px for the Hole against a 720 px frame. `ST_GW_STRAIN_GAIN` amplifies the radiated wave's ripple for the same reason (real `h` here is ~5e-4 — a 0.04 px wiggle). The maps are the metric's; only their amplitude is turned up.

**`_accelerate` never reads `_depth`, `_wave_height` or `_lattice_offset`** — keep it that way, or the art starts changing the physics.

### Gestures and the camera

- one pinch on empty space → arms a placement, committed on **release** (a ghost shows where)
- one pinch on a mass → drag it live; the curvature follows
- **two pinches at once** → 3D camera. This *supersedes* place/drag and cancels any pending placement, so a mass never appears just because the user was reaching for the second pinch. Hands that took part stay inert until they re-pinch.

The camera is a **turntable** (yaw about the sheet's normal + elevation), not an arcball: the scene has a real "up" and preserving it is what keeps the view legible — Blender defaults to turntable for the same reason.

Its transfer function is a **hybrid position/rate** control (RubberEdge, Casiez et al.), and this is load-bearing rather than fussy. v1 was a plain incremental drag and failed twice over: reaching a top-down view needed ~240 px of sustained travel with both pinches held, which ends near the frame border where `EDGE_MARGIN_FRAC` documents tracking degrading — so the gesture died half-way and the top view was effectively unreachable — and incremental mapping has no home, so returning your hands never returned the view. Zhai & Milgram's taxonomy explains why pure rate control is not the fix either: a hand is *isotonic*, and isotonic→rate is a known-bad pairing. So: inside `ST_CAM_POS_RADIUS_PX` of the grab origin, offset maps absolutely to angle (precise, homed); outside, the excess becomes angular velocity (unbounded travel from a small, well-tracked region). Measured: a 200 px push held 3 s reaches pitch 90° without the hands ever leaving the safe zone, and a nudge-and-return lands back within 0.1°.

### View toggle

The `st.view` button swaps the sheet for the lattice and eases the camera to that mode's home angle (the lattice reads a little flatter — it is a box, and a steep angle collapses its layers onto each other). It is also the reliable way back to a sane view after a visitor tumbles the camera.

### Backdrop

`draw()` dims the camera image (`ST_BACKDROP_ALPHA`) so the thin wireframe reads. This is **display-only by construction**: it runs after `toMpImage` has already handed inference its own RGB copy, so the model always sees the raw frame. In web mode the point is moot — the backend draws nothing and the browser dims its own canvas (`drawBackdrop` in `overlay/scene.ts`, before the skeleton so only the video darkens). Do not hoist any of it earlier in the loop.

---

## Adding New Interactables

1. Add a new class to this file following the `update(hand_result, pose_landmarks)` / `draw(frame)` interface.
2. Add a spawn button and list (or single-instance slot, like the BH or 6 7 counter) in [[modules/ui_manager]].
3. If the new object uses GPU rendering, reuse the `LensingRenderer`'s ModernGL context or extend it — see [[gl_lensing]].
4. Document it here.
