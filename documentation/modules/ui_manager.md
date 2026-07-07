---
title: ui_manager.py
tags: [module, ui, state-machine]
---

# `ui_manager.py` — UI State Machine

**Location:** `src/ui/manager.py`

Owns all UI state and orchestrates which buttons and objects are active per frame. The only class here is `UIManager`, instantiated once by `main.py`.

See [[architecture]] for the state machine diagram.

---

## Constants

| Constant | Value | Description |
|---|---|---|
| `MENU_BTN_W` | `260` | Width of main menu buttons (px) |
| `MENU_BTN_H` | `70` | Height of main menu buttons (px) |
| `RESET_W` | `130` | Width of the Reset button (px) |
| `RESET_H` | `50` | Height of the Reset button (px) |
| `SPEED_BTN` | `46` | Side of the square `-` / `+` sim-speed buttons (px) |
| `SPEED_LABEL_W` | `92` | Width of the sim-speed readout pill between them (px) |

---

## `UIManager`

### `__init__(frame_w, frame_h)`

| Parameter | Type | Description |
|---|---|---|
| `frame_w` | `int` | Camera frame width in pixels |
| `frame_h` | `int` | Camera frame height in pixels |

Initialises state to `"menu"`, empty sphere list, and builds all buttons.

### State

| Attribute | Type | Values | Description |
|---|---|---|---|
| `state` | `str` | `"menu"`, `"interactables"`, `"experiments"` | Current UI mode |
| `spheres` | `list[BouncingSphere]` | — | Active physics spheres in `"interactables"` mode |
| `_sixseven` | `SixSevenCounter \| None` | — | Active 6 7 counter in `"interactables"` mode (single-instance — `None` until spawned) |
| `_active_experiment` | `BlackHole \| Slingshot \| None` | — | The single experiment running in `"experiments"` mode (`None` while the picker row is shown) |
| `_lensing_renderer` | `LensingRenderer \| None` | — | Lazy-created on first BH spawn; reused across BH lifecycles to avoid repeated GL-context creation |

---

### `update(hand_result, pose_landmarks)`

Signature: `update(hand_result, pose_landmarks, hand_received_t=None)`. First advances every hand's pinch state machine exactly once via `gestures.update_pinches(...)` — buttons and interactables then read the shared per-frame snapshot through `pinch_state(hand_id)` / `pinch_info(hand_id)` (reads never mutate, so any number of live widgets can share one hand). `hand_received_t` is the monotonic instant the hand result arrived (from `detectors.latest_hand_packet`, passed down by `main.py`) — it drives the cursor's latency extrapolation. Then dispatches per-frame interaction updates based on the current `state`. `pose_landmarks` is the first detected pose's landmark list (or `None`) — still forwarded to interactables for pose-driven features (e.g. the 6 7 counter), though the pinch no longer needs it.

| State | Objects updated |
|---|---|
| `"menu"` | `_menu_interactables_btn`, `_menu_experiments_btn` |
| `"interactables"` | `_sphere_btn`, `_sixseven_btn`, all `spheres`, `_sixseven` (if active), `_reset_btn` |
| `"experiments"` (picker) | every button in `_experiment_btns`, `_reset_btn` |
| `"experiments"` (active) | `_active_experiment`, `_reset_btn`, and — when the experiment exposes a `time_scale` (the slingshot) — the top-right `-` / `+` sim-speed buttons |

The Experiments state swaps the picker row for the chosen experiment once spawned — the experiment replaces the buttons rather than coexisting with them, so reset is the only way to despawn.

### `draw(frame)`

Dispatches per-frame draw calls based on current `state`. Same routing as `update`. In Experiments mode, the active experiment draws **before** the buttons (e.g. the BH's full-frame lensing pass) so Reset and the sim-speed stepper stay readable on top; `_draw_speed_label` renders the current `time_scale` (e.g. `0.5x`) in a pill between `-` and `+`.

Overlay order after the scene: the always-on **pinch cursor** ([[cursor]]) → onboarding overlays (intro splash / pinch hint) → the **debug HUD** ([[debug_hud]], only when `HALL_DEBUG=1`) dead-last above everything.

---

### Private Methods

| Method | Description |
|---|---|
| `_build_buttons()` | Constructs and positions all `Button` instances |
| `_set_state(new_state)` | Sets `self.state` — used as button `on_click` callback |
| `_add_sphere()` | Appends a new `BouncingSphere` to `self.spheres` |
| `_spawn_sixseven()` | Assigns a fresh `SixSevenCounter` to `self._sixseven`. Re-pressing the button while a counter is active zeroes the tally without leaving the mode. |
| `_spawn_black_hole()` | Lazy-creates the shared `LensingRenderer` on first call, then assigns a fresh `BlackHole` to `self._active_experiment` |
| `_spawn_slingshot()` | Assigns a fresh `Slingshot` to `self._active_experiment` |
| `_speed_control_active()` | True while the active experiment exposes an adjustable `time_scale` (duck-typed via `hasattr`, so any future experiment gains the stepper for free) |
| `_change_sim_speed(direction)` | Steps the active experiment's `time_scale` up (`+1`) or down (`-1`) through its speed table |
| `_draw_speed_label(frame)` | Renders the current sim speed (e.g. `0.5x`) between the `-` / `+` buttons |
| `_reset()` | Clears `self.spheres`, drops `self._sixseven` and `self._active_experiment` (the lensing renderer is retained for reuse), and returns to `"menu"` |

---

### Button Layout

| Button | Position | Action |
|---|---|---|
| "Interactable Figures" | Horizontally centred, above centre | `_set_state("interactables")` |
| "Experiments" | Horizontally centred, below centre | `_set_state("experiments")` |
| "Sphere" | Top-left `(20, 20)` | `_add_sphere()` |
| "6 7 Counter" | Top-left, right of Sphere `(150, 20)` | `_spawn_sixseven()` (spawn or zero the counter) |
| "Black Hole" | Top-left `(20, 20)` (picker row, shown only while no experiment is active) | `_spawn_black_hole()` |
| "Slingshot" | Top-left, right of Black Hole `(180, 20)` (picker row) | `_spawn_slingshot()` |
| "-" / "+" | Top-right corner, flanking the speed readout pill (shown only while the active experiment has a `time_scale`) | `_change_sim_speed(∓1)` |
| "Reset" | Bottom-right corner | `_reset()` |

---

## Extending

To add a new mode:

1. Add a new string value and handle it in both `update()` and `draw()`.
2. Add a menu button in `_build_buttons()` that calls `_set_state("new_mode")`.
3. Add any new objects/buttons needed for that mode. For GPU-backed effects, reuse `_lensing_renderer` (or extend it) so the GL context is shared.

See also: [[modules/interactableUI]], [[modules/interactables]], [[gl_lensing]], [[architecture]]
