---
title: gestures.py
tags: [module, detection, gestures]
---

# `gestures.py` — Pinch Detection Pipeline

**Location:** `src/detection/gestures.py`

Derives high-level gestures from raw MediaPipe landmarks. The only gesture currently implemented is a **pinch** between the thumb tip and the index fingertip, but the module is designed to be the home of any future hand-shape recognisers (fist, point, open palm, …).

The pipeline uses the techniques production hand-tracking stacks (Ultraleap, Meta) use:

1. **Per-frame snapshot.** `update_pinches()` advances one state machine per hand **exactly once per rendered frame** (called at the top of `UIManager.update`); every consumer — buttons, spheres, experiments — then reads the same snapshot through `pinch_state(hand_id)` / `pinch_info(hand_id)`. The previous design mutated a shared ratio history on *every* read, so each additional live widget shrank the detector's effective time window and made pinching progressively harder (4 widgets → a "10-frame" window actually spanned 2.5 frames).
2. **Hand-relative scale** (`hand_scale`). The thumb–index distance is normalized by the hand's own size: `max(knuckle span |5–17|, 0.75 × palm length |0–9|)`. Those segments do not move when the fingers close, so a fist cannot collapse the reference; the ratio tracks camera distance automatically; and — unlike the old shoulder-width scale — the pinch works **without any pose detection** (shoulders out of frame no longer disable interaction).
3. **3D pinch distance.** The tip distance mixes in the landmark `z` difference (wrist-relative, ~x-normalized units, scaled by `frame_w` × `PINCH_Z_WEIGHT`), so rotating the hand until the tips visually overlap no longer fakes a close. Missing/zero `z` (synthetic tests, degraded shims) degrades gracefully to pure 2D. `hand_scale` stays 2D on purpose — noisy z in the *denominator* would jitter every ratio.
4. **Edge-triggered state machine with hysteresis** (Ultraleap's pinch/unpinch split). The machine *closes* when the ratio drops below `PINCH_CLOSE_RATIO` (0.45) and only *reopens* above the looser `PINCH_RELEASE_RATIO` (0.90), so jitter at the threshold cannot flicker the state. The `pinching` **event** fires exactly once, on the open→closed transition. A hand that enters the frame already closed is initialised in the closed state *without* firing — a fist sliding over a button still cannot click it (this replaces the old "rapid-close window" heuristic, which also rejected legitimate slow pinches).
5. **Debounce.** The state flips only after consecutive agreeing frames: `PINCH_DEBOUNCE_CLOSE_FRAMES` (2) to close, `PINCH_DEBOUNCE_RELEASE_FRAMES` (4) to release — tracking gives brief false negatives exactly while the user pinches and moves at the same time, so releasing demands more evidence than closing.
6. **One-Euro filtering** ([Casiez, Roussel & Vogel, CHI 2012](https://dl.acm.org/doi/10.1145/2207676.2208639)) on both the pinch ratio and the cursor: an adaptive low-pass whose cutoff rises with signal speed — heavy smoothing at rest (kills jitter), light during fast motion (no perceptible lag).
7. **Thumb-anchored cursor.** The cursor rides the **thumb tip** (landmark 4). In a thumb-index pinch the index does most of the closing travel while the thumb stays comparatively still, so the dot tracks the finger the user actually aims with and moves very little through the close; the residual thumb travel is covered by the press-latched `press_cursor`, which buttons hit-test instead of the live position. `PINCH_CURSOR_THUMB_OFFSET_X` / `_Y` optionally offset the anchor in the **thumb's own frame** — X along the thumb ray (MCP 2 → tip 4: positive past the tip, negative toward the knuckle), Y perpendicular to it (positive always toward the **index side**, the sign is resolved per hand against the index MCP so Left/Right mirror correctly) — both as fractions of that segment, hand-scaled and rotation-following, so the offset means the same thing at any distance or orientation. (Replaces two earlier designs: a progress-sliding blend and a rigid MCP-midpoint "predicted pinch point" — both read as anchored to the index/palm rather than to the finger the user pinches with.) Both fingertips (4, 8) still drive the *ratio*.
8. **Close counter-movement** (`PINCH_CURSOR_COMPENSATE`, 0..1). The thumb itself travels toward the index as the fingers close, dragging a thumb-anchored cursor with it. The cursor point is expressed in a **rigid hand frame** — origin at the wrist, basis wrist→index MCP and its perpendicular (segments the fingers cannot move) — and its coordinates in that frame are tracked at rate `1 − progress`: fully while open, frozen when closed. The drawn cursor is pulled toward where the remembered coordinates land in the *current* frame — a counter-movement that grows with the pinch progress and cancels the thumb's own close travel (verified sub-pixel once fully closed), while real hand motion — translation, rotation, zoom — still moves the cursor 1:1 because the rigid frame moves with the hand. `1.0` = full compensation (default), `0.0` = off.
9. **Latency compensation.** The cursor is extrapolated forward by the One-Euro filter's own velocity estimate times the detection result's age (`received_t` from `detectors.latest_hand_packet`), capped at `PINCH_EXTRAP_MAX_S` (0.10 s). Simple linear extrapolation — [at short horizons it beats Kalman on jitter](https://web.cs.wpi.edu/~claypool/papers/lag-taxonomy/Extrapolation.html). Only the *output* is extrapolated, never the filter state. Note the canonical One-Euro derivative measures against the previous *filtered* value, so the lead also compensates the filter's own lag — intended.
10. **Tracking-dropout grace.** A hand missing from the current frame keeps its machine warm for `PINCH_TRACK_GRACE_S` (0.5 s), so a brief dropout resumes mid-hold instead of cold-starting; its one-frame `pinching` event is cleared immediately (nothing may consume it late). Past the grace period the machine is dropped and a reappearing hand re-enters through the no-fire-if-already-closed rule.

The detector exposes two booleans per hand:

- `pinching` (edge event, one frame) → use to **trigger** actions (button click, grab initiation).
- `held` (level state, hysteresis + debounce) → use to **maintain** an already-triggered gesture.

The One-Euro-smoothed thumb-tip cursor is always returned for cursor use.

---

## Module-Level Constants

| Constant | Default | Description |
|---|---|---|
| `PINCH_LANDMARK_A` | `4` | Thumb tip — hand landmark index; also the cursor anchor |
| `PINCH_LANDMARK_B` | `8` | Index finger tip — hand landmark index |
| `THUMB_MCP` | `2` | Thumb MCP — base of the thumb ray used by `PINCH_CURSOR_THUMB_OFFSET_X/_Y` |
| `HAND_SCALE_KNUCKLE_A` / `_B` | `5` / `17` | Index MCP / pinky MCP — the knuckle span |
| `HAND_SCALE_PALM_A` / `_B` | `0` / `9` | Wrist / middle MCP — the palm length |
| `HAND_SCALE_PALM_FACTOR` | `0.75` | Palm length → knuckle-span equivalent |
| `POSE_SCALE_A` / `_B` | `11` / `12` | Shoulders — kept for future *pose-relative* gestures (`pose_scale`), no longer used by the pinch |
| `POSE_SCALE_MIN_VISIBILITY` | `0.5` | Per-shoulder visibility floor for `pose_scale` |

Tunable thresholds (`PINCH_CLOSE_RATIO`, `PINCH_RELEASE_RATIO`, `PINCH_DEBOUNCE_*`, `PINCH_TRACK_GRACE_S`, `PINCH_CURSOR_THUMB_OFFSET_X/_Y`, `PINCH_CURSOR_COMPENSATE`, `PINCH_EXTRAP_MAX_S`, `PINCH_Z_WEIGHT`, One-Euro parameters) live in [[config]].

---

## Functions

### `hand_id(hand_result, i) → str`

Returns a stable id for the *i*-th hand in a `HandLandmarkerResult`, preferring MediaPipe's handedness category (`"Left"` / `"Right"`) over the iteration index. The per-hand state machines are keyed on this id, so using handedness keeps tracking stable even when MediaPipe reorders hands between frames. Falls back to `"hand_{i}"` when handedness is unavailable.

---

### `hand_scale(hand_landmarks, frame_w, frame_h) → float`

Pixel-size proxy of one hand from segments the fingers cannot move: `max(knuckle span, 0.75 × palm length)`. The `max` keeps the scale usable when hand rotation foreshortens one of the two segments. Needs no pose detection.

---

### `pose_scale(pose_landmarks, frame_w, frame_h) → float`

Shoulder-to-shoulder pixel distance — a body-sized scale reference retained for future *pose-relative* gestures (arm raises, body-scaled distances). Returns `0.0` when either shoulder is missing or below `POSE_SCALE_MIN_VISIBILITY`. **The pinch no longer uses this.**

---

### `update_pinches(hand_result, frame_w, frame_h, now=None, received_t=None)`

Advances every hand's pinch machine. **Call exactly once per rendered frame** — `UIManager.update` does this before any widget updates. `now` (monotonic seconds) is injectable for tests. `received_t` is the monotonic instant the detection result arrived (from `detectors.latest_hand_packet`); the derived age (clamped to 1 s) drives the cursor extrapolation and is exposed via `result_age_s()`. `None` disables extrapolation. Per-hand `dt` is derived from the machine's last update and clamped to `[1/120, 0.25]` s, so filters behave across dropouts and startup.

### `pinch_state(hand_id) → (pinching, held, (mx, my))`

Read-only snapshot for one hand. Reading never mutates state, so any number of widgets can query the same hand in one frame. Unknown ids return `(False, False, (0.0, 0.0))`.

| Field | Meaning | Use it for |
|---|---|---|
| `pinching` | Edge event — True only on the frame the machine transitioned open→closed (after close debounce) | **Trigger** actions: button click, grab initiation. A statically-closed hand never fires. |
| `held` | Level state — True while the machine is closed (hysteresis + release debounce keep it stable) | **Maintain** an already-triggered action: keep dragging while the fingers stay roughly shut |
| `(mx, my)` | Thumb-tip-anchored, One-Euro-smoothed, latency-compensated cursor (px) | Cursor position (always provided, even when open) |

### `pinch_info(hand_id) → _HandPinch | None` / `pinch_infos()`

The full per-hand machine, handed out **read-only** (it only mutates inside `update_pinches`; returning the object costs zero copies for many consumers per frame). Richer than `pinch_state` — extra fields for the cursor overlay ([[cursor]]), hover-latch buttons ([[interactableUI]]) and the debug HUD ([[debug_hud]]):

| Field | Meaning |
|---|---|
| `ratio` | Filtered pinch ratio (`None` until first seen) |
| `progress` | Continuous pinch strength 0→1 between the release and close thresholds (Meta-style) |
| `state` | `"open"` / `"closing"` / `"closed"` / `"releasing"` |
| `press_cursor` | Cursor latched where the close gesture *started* (close debounce 0→1) — hit-test clicks against this so drift during the close can't slide a click off (or onto) a target |
| `last_seen` | Monotonic time of the last advance (staleness check for overlays) |

`pinch_infos()` returns a `(hand_id, machine)` list for every tracked hand, including grace-window survivors. `result_age_s()` returns the detection age used by the last `update_pinches` call.

#### Detection rule

```
dz     = (z4 - z8) * frame_w * PINCH_Z_WEIGHT
ratio  = OneEuro( sqrt(dx^2 + dy^2 + dz^2) / hand_scale(hand) )
ray    = lm4 - lm2                                # thumb MCP -> tip
perp   = rot90(ray), signed toward the index MCP  # +Y faces the index side
point  = lm4 + OFFSET_X * ray + OFFSET_Y * perp
ref    = point in rigid frame (lm0, lm5-lm0), tracked at rate 1-progress
point  = lerp(point, reconstruct(ref), PINCH_CURSOR_COMPENSATE)  # counter-movement
cursor = OneEuro( point )
         + velocity * min(result_age, PINCH_EXTRAP_MAX_S)

open  --[ratio < PINCH_CLOSE_RATIO for 2 frames]-->  closed   (fires `pinching` once)
closed --[ratio > PINCH_RELEASE_RATIO for 4 frames]--> open
first sight: closed = (ratio < PINCH_CLOSE_RATIO), no event   (fist can't click)
```

---

## Consumers

| Caller | Uses `pinching` for | Uses `held` for |
|---|---|---|
| [[interactableUI]] (`Button.update`) | Click activation | — |
| [[interactables]] (`BouncingSphere.update`) | Grab initiation (within `GRAB_RADIUS`) | Keeping the grab alive — **owner hand only** (latched at initiation) |
| [[interactables]] (`BlackHole.update`) | Drag initiation (within `BH_GRAB_RADIUS`) | Keeping the drag alive — owner hand only |
| [[interactables]] (`Slingshot.update`) | Aim initiation (near the anchor) | Keeping the pull alive — owner hand only |

All consumers read the snapshot with `pinch_state(hand_id(hand_result, i))`; [[ui_manager]] guarantees `update_pinches` ran first this frame.

---

## Adding a New Gesture

1. Add a per-hand state machine advanced from `update_pinches` (or a sibling `update_*` hook called once per frame from `UIManager.update`), and expose a read-only accessor like `pinch_state`.
2. Express hand-shape thresholds **relative to `hand_scale(...)`** (finger-invariant) and body-pose thresholds relative to `pose_scale(...)`. Never raw pixels — that's the only way the gesture survives changes in camera distance.
3. Trigger on **state transitions** (edge), never on static shapes, and give the release threshold hysteresis + debounce.
4. Smooth anything jittery with `_OneEuroFilter` before thresholding.
5. Put tunable constants in [[config]]; document here and link from the consuming module's doc.

See also: [[modules/detectors]], [[modules/interactableUI]], [[modules/interactables]], [[architecture#Hand Interaction Model]]
