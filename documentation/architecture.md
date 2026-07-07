---
title: Architecture & Data Flow
tags: [architecture, design]
---

# Architecture & Data Flow

## Module Dependency Graph

```
main.py
├── config.py                    (constants)
├── capture.py                   (FreshestFrame — threaded latest-frame reader)
├── detection/detectors.py       (build detectors, read shared results + receive time)
├── detection/gestures.py        (pinch pipeline: snapshot, state machine, filters)
├── rendering/drawing.py         (toMpImage, draw_landmarks, draw_connections)
└── ui/manager.py
    ├── ui/button.py                  (Button)            ──▶ detection/gestures.py
    ├── ui/cursor.py                  (PinchCursor)       ──▶ detection/gestures.py
    ├── ui/debug_hud.py               (DebugHUD, HALL_DEBUG=1) ──▶ gestures + detectors
    ├── ui/interactables.py           (BouncingSphere)    ──▶ detection/gestures.py
    │                                  (SixSevenCounter)  ──▶ (pose landmarks only)
    │                                  (Slingshot)        ──▶ detection/gestures.py
    │                                  (BlackHole)        ──▶ rendering/gl_lensing.py
    └── rendering/gl_lensing.py       (LensingRenderer)   ──▶ shaders/black_hole.frag
                                                              shaders/fullscreen.vert
```

`config.py` is a pure constant module — no imports from other project files.
`detection/detectors.py`, `detection/gestures.py`, and `rendering/drawing.py` only import from `config.py` (or stdlib).
`rendering/gl_lensing.py` imports `moderngl` + `numpy` only — no project-internal deps; the shaders are loaded from `src/rendering/shaders/` at construction.

---

## Per-Frame Data Flow

```
camera.read()
    │
    ▼
cv2.flip()  →  toMpImage()
                    │
         ┌──────────┴──────────┐
         ▼                     ▼
 pose_detector            hand_detector
 .detect_async()          .detect_async()
         │                     │
         └─────── async ────────┘
                     │  (callbacks write to detectors module globals)
                     ▼
         detectors.latest_pose_result
         detectors.latest_hand_result
                     │
         ┌───────────┴────────────┐
         ▼                        ▼
  draw_landmarks()          ui.update(hand_result, pose_landmarks)
  draw_connections()        ui.draw(frame)
         │
         ▼
  cv2.imshow()
```

### Web mode (`HALL_OUTPUT=web`) — browser-rendered UI

The same loop, but the drawing half moves to the browser (see
[[modules/web_state]] and [[modules/frontend]]):

```
camera.read() → cv2.flip() → detect_async → ui.update()   (NO cv2 drawing,
    │                                           │           NO gl_lensing)
    ▼                                           ▼
sink.present(raw frame)              sink.publish_state(build_state())
    │                                           │
    ▼                                           ▼
/stream.mjpg  ──────────────▶  browser  ◀────── /state (SSE, ~30 Hz JSON)
                                 │
                                 ├─ <img> video layer
                                 ├─ WebGL2 black-hole shader (only while BH active)
                                 ├─ Canvas2D: skeleton, cursor, sphere, slingshot
                                 └─ DOM HUD: buttons, panels, onboarding
```

Python remains authoritative for ALL logic — the UIManager state machine,
button hit-testing (pixel rects in frame coords) and the physics sims; the
browser is a pure renderer of the per-frame snapshot (positions interpolated
between snapshots for display-rate smoothness). `UIManager` runs with
`gpu_effects=False`, so the backend never creates a GL context — the
Schwarzschild shader runs in the browser instead. The loop is paced to
`STATE_FPS` in this mode (without cv2 drawing it would spin far past the
camera rate re-encoding duplicate frames). `window` and `stream` modes are
unchanged.

### Key design decisions

- **Freshest-frame capture** — The `VideoCapture` is wrapped in `capture.FreshestFrame`, a background thread that continuously drains the camera and keeps only the newest frame. When the render loop is slower than the camera (the usual case — CPU-bound pose caps it below the camera's fps), stale frames are *dropped* instead of piling up in the driver queue, so end-to-end latency stays ~1 frame instead of growing without bound. This is the real cure for the "camera delay" (a shallow `CAP_PROP_BUFFERSIZE` alone is often ignored by V4L2).
- **Async detection** — Both detectors run in `LIVE_STREAM` mode. Results land in module-level globals (`latest_pose_result`, `latest_hand_result`) via callbacks, decoupling detection latency from the render loop. (Note: this makes the *skeleton overlay* lag the live frame by one inference — a separate effect from the capture latency above.)
- **Frame timestamp** — A monotonic clock drives timestamps. Each call uses `max(monotonic_ms, last_timestamp_ms + 1)` to guarantee strictly increasing values required by MediaPipe's LIVE_STREAM mode.
- **Frame flip** — The frame is horizontally flipped before processing so coordinates are mirror-corrected (natural for front-facing camera use).

---

## UI State Machine

```
       ┌─────────────────────────┐
       │           menu          │  (default)
       └─────────┬───────────────┘
                 │ pinch "Interactable Figures"
                 ▼
       ┌─────────────────────────┐
       │      interactables      │  spawnable spheres + optional
       │                         │  singleton 6 7 counter (pose-driven)
       └─────────┬───────────────┘
                 │ pinch "Reset"
                 ▼
       ┌─────────────────────────┐
       │           menu          │
       └─────────────────────────┘

       ┌─────────────────────────┐
       │       experiments       │  picker row: "Black Hole" | "Slingshot"
       │                         │  → on pick, the buttons are replaced by the
       │                         │    single active experiment (draggable
       │                         │    Schwarzschild BH, or the projectile
       │                         │    slingshot + top-right -/+ sim-speed
       │                         │    stepper, 0.25x-4x)
       └─────────┬───────────────┘
                 │ pinch "Reset"
                 ▼
              menu
```

State is a plain string (`"menu"` | `"interactables"` | `"experiments"`) owned by `UIManager`. The Experiments state has two visual sub-modes — the experiment picker (a button per experiment) vs. one active experiment — toggled by whether `_active_experiment` is `None`. Only one experiment runs at a time; each object just needs `update(hand_result, pose_landmarks)`, `draw(frame)`, and a `grabbed` flag. An experiment that additionally exposes a `time_scale` (the slingshot) gets the top-right `-`/`+` sim-speed buttons for free. Reset always returns to `menu` regardless of sub-mode.

---

## Hand Interaction Model

Hand interaction uses the hand's own landmarks — no pose needed:

| Landmark | Index | Source | Role |
|---|---|---|---|
| Thumb tip | 4 | hand | First pinch point **and cursor anchor** |
| Index finger tip | 8 | hand | Second pinch point |
| Index MCP / pinky MCP | 5 / 17 | hand | Knuckle-span scale reference |
| Wrist / middle MCP | 0 / 9 | hand | Palm-length scale reference (fallback under rotation) |

**Cursor position** = One-Euro-smoothed **thumb tip** (landmark 4), optionally offset in the thumb's own frame (`PINCH_CURSOR_THUMB_OFFSET_X/_Y`) — the thumb is the stable side of a thumb-index pinch (the index does most of the closing travel), so the cursor tracks the finger the user aims with. As the pinch progresses, `PINCH_CURSOR_COMPENSATE` applies a **counter-movement** — the cursor's open-pose point, remembered in a rigid wrist→index-MCP hand frame, pulls it back against the thumb's own close travel, so the dot holds still through the close while real hand motion still moves it 1:1; buttons additionally hit-test the press-latched `press_cursor`. Finally the cursor is extrapolated forward by the filter's velocity × the detection result's age (capped at `PINCH_EXTRAP_MAX_S`) to compensate inference latency. The always-on [[cursor]] overlay draws it with a pinch-progress ring, so the user steers the dot they can see.

**Pinch ratio** = 3D distance(4, 8) / `hand_scale`, where the z difference joins in weighted by `PINCH_Z_WEIGHT` (blocks phantom closes when hand rotation aligns the tips along the camera axis) and `hand_scale = max(knuckle span, 0.75 × palm length)` — segments the fingers cannot move, so a fist can't collapse the reference and the ratio is depth-invariant. Because the scale comes from the hand itself, the pinch works even when the shoulders/pose are out of frame.

**Per-frame snapshot** — `UIManager.update` calls `update_pinches(...)` exactly once per frame; every widget then reads the same state via `pinch_state(hand_id)` (reads never mutate, so any number of live widgets can share one hand).

**Pinch event vs. held state** — an edge-triggered state machine with hysteresis + debounce (see [[gestures]] for the full pipeline):

- `pinching` (edge event) — fires once, on the open→closed transition (ratio < `PINCH_CLOSE_RATIO` for `PINCH_DEBOUNCE_CLOSE_FRAMES`). Used to *trigger* actions. A hand that enters the frame already closed starts silently in the closed state — a fist sliding over a button will **not** fire.
- `held` (level state) — True while the machine is closed; it only reopens above the looser `PINCH_RELEASE_RATIO` sustained for `PINCH_DEBOUNCE_RELEASE_FRAMES`. Used to *maintain* an already-triggered action (e.g. a sphere drag continues as long as `held`). Hysteresis + debounce mean minor finger drift or a 1-frame tracking blip never drops a grab; only an obvious release ends it.

| Interaction | Trigger condition |
|---|---|
| Button hover | Cursor inside button rect (once hovered, the rect inflates by `BUTTON_STICKY_PAD_FRAC` × height per side — sticky targets) |
| Button click | `pinching` (fresh close) + **`press_cursor`** (the cursor where the close *started*) inside the rect + cooldown elapsed — drifting during the close can't slide a click off, or onto, a button |
| Sphere grab — initiate | `pinching` (fresh close) + cursor within `GRAB_RADIUS` (80 px) of sphere centre |
| Sphere grab — maintain | `held` + previously grabbed |
| Sphere push | Any fingertip overlaps sphere collision radius |
| BH grab — initiate | `pinching` (fresh close) + cursor within `BH_GRAB_RADIUS` (100 px) of BH centre |
| BH grab — maintain | `held` + previously grabbed |
| 6 7 count fire | Per-arm rising edge: wrist crosses above elbow by > `SIXSEVEN_HYSTERESIS` (normalised), with visibility ≥ `SIXSEVEN_MIN_VISIBILITY` on both landmarks. Resets when the wrist falls below the elbow by the same margin. Pose-only — no hand input. |

---

## Adding New Features

| Goal | Where to add |
|---|---|
| New UI scene/mode | New state value + branch in `UIManager.update()` / `UIManager.draw()` |
| New button | Instantiate `Button` in `UIManager._build_buttons()` |
| New physics object | New class in `interactables.py` |
| New GPU effect | New shader pair under `src/rendering/shaders/` + program/method on `LensingRenderer` in [[gl_lensing]] |
| New drawing primitive | New function in `drawing.py` |
| New gesture (e.g. fist, point) | New helper in `detection/gestures.py` |
| New detection threshold | Constant in `config.py` |

See also: [[modules/ui_manager]], [[modules/interactables]], [[modules/interactableUI]], [[modules/gl_lensing]]
