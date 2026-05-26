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
| `_black_hole` | `BlackHole \| None` | — | Active black hole in `"experiments"` mode (single-instance — `None` until spawned) |
| `_lensing_renderer` | `LensingRenderer \| None` | — | Lazy-created on first BH spawn; reused across BH lifecycles to avoid repeated GL-context creation |

---

### `update(hand_result, pose_landmarks)`

Dispatches per-frame interaction updates based on current `state`. `pose_landmarks` is the first detected pose's landmark list (or `None`) — it is forwarded unchanged to every button and interactable so [[gestures]] can use shoulder width as the pinch scale reference.

| State | Objects updated |
|---|---|
| `"menu"` | `_menu_interactables_btn`, `_menu_experiments_btn` |
| `"interactables"` | `_sphere_btn`, all `spheres`, `_reset_btn` |
| `"experiments"` (no BH) | `_black_hole_btn`, `_reset_btn` |
| `"experiments"` (BH active) | `_black_hole` (drag), `_reset_btn` |

The Experiments state swaps the spawn button for the BH once spawned — the BH replaces its own button rather than coexisting with it, so reset is the only way to despawn.

### `draw(frame)`

Dispatches per-frame draw calls based on current `state`. Same routing as `update`. In Experiments mode, the BH's lensing pass runs **before** the reset button is drawn so the button stays readable on top of the distorted background.

---

### Private Methods

| Method | Description |
|---|---|
| `_build_buttons()` | Constructs and positions all `Button` instances |
| `_set_state(new_state)` | Sets `self.state` — used as button `on_click` callback |
| `_add_sphere()` | Appends a new `BouncingSphere` to `self.spheres` |
| `_spawn_black_hole()` | Lazy-creates the shared `LensingRenderer` on first call, then assigns a fresh `BlackHole` to `self._black_hole` |
| `_reset()` | Clears `self.spheres`, drops `self._black_hole` (the renderer is retained for reuse), and returns to `"menu"` |

---

### Button Layout

| Button | Position | Action |
|---|---|---|
| "Interactable Figures" | Horizontally centred, above centre | `_set_state("interactables")` |
| "Experiments" | Horizontally centred, below centre | `_set_state("experiments")` |
| "Sphere" | Top-left `(20, 20)` | `_add_sphere()` |
| "Black Hole" | Top-left `(20, 20)` (shown only while no BH is active in Experiments) | `_spawn_black_hole()` |
| "Reset" | Bottom-right corner | `_reset()` |

---

## Extending

To add a new mode:

1. Add a new string value and handle it in both `update()` and `draw()`.
2. Add a menu button in `_build_buttons()` that calls `_set_state("new_mode")`.
3. Add any new objects/buttons needed for that mode. For GPU-backed effects, reuse `_lensing_renderer` (or extend it) so the GL context is shared.

See also: [[modules/interactableUI]], [[modules/interactables]], [[gl_lensing]], [[architecture]]
