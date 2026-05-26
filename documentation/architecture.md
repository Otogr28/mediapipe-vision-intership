---
title: Architecture & Data Flow
tags: [architecture, design]
---

# Architecture & Data Flow

## Module Dependency Graph

```
main.py
├── config.py                    (constants)
├── detection/detectors.py       (build detectors, read shared results)
├── detection/gestures.py        (scale-aware pinch detection)
├── rendering/drawing.py         (toMpImage, draw_landmarks, draw_connections, draw_line)
└── ui/manager.py
    ├── ui/button.py                  (Button)            ──▶ detection/gestures.py
    ├── ui/interactables.py           (BouncingSphere)    ──▶ detection/gestures.py
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

### Key design decisions

- **Async detection** — Both detectors run in `LIVE_STREAM` mode. Results land in module-level globals (`latest_pose_result`, `latest_hand_result`) via callbacks, decoupling detection latency from the render loop.
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
       │      interactables      │  spawnable spheres
       └─────────┬───────────────┘
                 │ pinch "Reset"
                 ▼
       ┌─────────────────────────┐
       │           menu          │
       └─────────────────────────┘

       ┌─────────────────────────┐
       │       experiments       │  spawn slot for "Black Hole"
       │                         │  → on spawn, the button is replaced
       │                         │    by a draggable Schwarzschild BH
       └─────────┬───────────────┘
                 │ pinch "Reset"
                 ▼
              menu
```

State is a plain string (`"menu"` | `"interactables"` | `"experiments"`) owned by `UIManager`. The Experiments state has two visual sub-modes — spawn button visible vs. BH active — toggled by whether `_black_hole` is `None`. Reset always returns to `menu` regardless of sub-mode.

---

## Hand Interaction Model

Hand interaction uses two hand landmarks and two pose landmarks:

| Landmark | Index | Source | Role |
|---|---|---|---|
| Thumb tip | 4 | hand | First pinch point |
| Index finger tip | 8 | hand | Second pinch point |
| Left shoulder | 11 | pose | Scale reference |
| Right shoulder | 12 | pose | Scale reference |

**Cursor position** = midpoint between hand landmarks 4 and 8.

**Pinch distance** = Euclidean pixel distance between hand landmarks 4 and 8.

**Pose scale** = shoulder-to-shoulder pixel distance (pose landmarks 11 & 12). This is the depth-invariant size proxy: it shrinks proportionally with the pinch distance as the body moves away from the camera, so a single ratio threshold works at any distance. Using the *pose* for scale instead of the hand prevents a closed fist from collapsing the reference.

**Pinch event vs. held state** — `pinch_state(...)` returns two flags backed by two thresholds (a Schmitt-trigger pattern):

- `pinching` (event, strict) — fingers are closed below `PINCH_RATIO` AND the ratio dropped by ≥ `PINCH_CLOSE_DROP` in the last `PINCH_HISTORY_LEN` frames. Used to *trigger* actions. A statically closed hand sliding over a button will **not** fire.
- `held` (state, loose) — fingers are within `PINCH_HOLD_RATIO` (looser than `PINCH_RATIO`). Used to *maintain* an already-triggered action (e.g. a sphere drag continues as long as `held`). The looser threshold is hysteresis — a grabbed object stays grabbed under minor finger drift; only an obvious release ends it.

When no pose is detected (or shoulders are occluded) both flags are suppressed.

| Interaction | Trigger condition |
|---|---|
| Button hover | Cursor midpoint inside button rect |
| Button click | `pinching` (rapid close) + cursor inside rect + cooldown elapsed |
| Sphere grab — initiate | `pinching` (rapid close) + cursor within `GRAB_RADIUS` (80 px) of sphere centre |
| Sphere grab — maintain | `held` + previously grabbed |
| Sphere push | Any fingertip overlaps sphere collision radius |
| BH grab — initiate | `pinching` (rapid close) + cursor within `BH_GRAB_RADIUS` (100 px) of BH centre |
| BH grab — maintain | `held` + previously grabbed |

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
