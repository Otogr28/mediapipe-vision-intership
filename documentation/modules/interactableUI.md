---
title: interactableUI.py
tags: [module, ui, button, interaction]
---

# `interactableUI.py` — Button Widget

**Location:** `src/ui/button.py`

Provides the `Button` class: a rectangular UI element that responds to hand pinch gestures. No mouse/keyboard input.

---

## Module-Level Constants

| Constant | Default | Description |
|---|---|---|
| `COOLDOWN_FRAMES` | `25` | Frames the button cannot fire again after a click (prevents repeat-fire) |

The pinch threshold itself lives in [[config]] as `PINCH_RATIO` and is consumed via `pinch_state(...)` from [[gestures]] — see that module for the scale-aware detection rule.

---

## `Button`

### `__init__(x, y, width, height, label, on_click, font_scale=0.7)`

| Parameter | Type | Description |
|---|---|---|
| `x`, `y` | `int` | Top-left corner position in pixels |
| `width`, `height` | `int` | Button dimensions in pixels |
| `label` | `str` | Text displayed centred in the button |
| `on_click` | `Callable[[], None]` | Zero-argument callback fired on pinch activation |
| `font_scale` | `float` | OpenCV text scale (default `0.7`) |

---

### `update(hand_result, pose_landmarks, frame_w, frame_h)`

Processes one frame of hand detection results. `pose_landmarks` is the first pose's landmark list (or `None` if no pose was detected), supplied so the pinch check can scale against shoulder width.

**Logic per detected hand:**

1. Derive a stable `hand_id` via `gestures.hand_id(hand_result, i)`.
2. Call `pinch_state(hand_landmarks, pose_landmarks, frame_w, frame_h, PINCH_RATIO, hand_id=...)` from [[gestures]] to get `(pinching, _held, (cx, cy))`. Only the `pinching` flag matters for buttons — it is True only on the frames where the user *actively closes* their fingers, not when the hand is already closed and just moving around.
3. If cursor is inside the button rect → `hovered = True`.
4. If additionally `pinching` and `_cooldown == 0` → fire `on_click()`, set `pressed = True`, start cooldown.
5. Only one hand is needed to trigger a click (`break` after first hit).

Cooldown decrements by 1 each frame regardless of hand presence. When `pose_landmarks` is `None` or the shoulders are occluded, `pinching` is always `False` — buttons can still hover but cannot fire. A fist sliding across the button is rejected because the per-hand ratio history shows no recent closing motion.

---

### `draw(frame)`

Renders the button onto `frame` (in place).

| State | Background colour (BGR) |
|---|---|
| `pressed` | `(0, 200, 100)` — green |
| `hovered` | `(50, 130, 220)` — blue |
| idle | `(30, 30, 30)` — dark grey |

Border: `(120, 120, 120)` grey, `thickness=2`.
Label: white, centred horizontally and vertically.

---

## Interaction Model

```
Each frame:
  hovered = False
  pressed = False
  cooldown -= 1 (if > 0)

  for i, hand in enumerate(hands):
    hid = hand_id(hand_result, i)            # "Left" / "Right" / fallback
    pinching, _held, cursor = pinch_state(
        hand, pose, frame_w, frame_h, PINCH_RATIO, hand_id=hid
    )
    # pinching = (closed now) AND (ratio dropped >= PINCH_CLOSE_DROP recently)

    if cursor inside rect:
      hovered = True
      if pinching and cooldown == 0:
        pressed = True
        cooldown = COOLDOWN_FRAMES
        on_click()
        break
```

See also: [[modules/ui_manager]], [[modules/gestures]], [[architecture#Hand Interaction Model]]
