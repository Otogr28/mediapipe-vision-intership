---
title: interactableUI.py
tags: [module, ui, button, interaction]
---

# `interactableUI.py` — Button Widget

**Location:** `src/ui/button.py`

Provides the `Button` class: a rectangular UI element that responds to hand pinch gestures. No mouse/keyboard input.

---

## Constants

All button tunables live in [[config]]: `BUTTON_COOLDOWN_FRAMES` (`8` — the pinch edge-trigger + release debounce is the real double-fire guard, this only absorbs tracking glitches) and `BUTTON_STICKY_PAD_FRAC` (`0.15` — sticky-target inflation, see below). The pinch thresholds (`PINCH_CLOSE_RATIO` / `PINCH_RELEASE_RATIO`) are consumed inside [[gestures]] — buttons just read the per-frame snapshot via `pinch_info(hand_id)`.

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

Processes one frame of hand detection results. `pose_landmarks` and the frame dimensions are no longer used by the pinch (the pipeline is a per-frame snapshot in [[gestures]], scaled by the hand's own knuckle span); the signature is kept uniform with the other per-frame updates.

**Logic per detected hand:**

1. Derive a stable `hand_id` via `gestures.hand_id(hand_result, i)` and read the full snapshot: `pinch_info(hand_id)` (skip `None`). `UIManager.update` has already advanced the machines this frame via `update_pinches(...)`.
2. **Sticky target**: if the button was hovered last frame, the hit rect inflates by `int(BUTTON_STICKY_PAD_FRAC × height)` per side — cursor jitter at the border can't flicker the hover or drop a click. *Entering* still requires the base rect (hysteresis). The pad comes from the height so it stays under every button gap (layout constraint: keep gaps > 0.15 × button height).
3. If the live cursor (`info.cursor`) is inside the (possibly inflated) rect → `hovered = True`.
4. **Hover-latch click**: on `info.pinching` (fires exactly once, on the open→closed transition) with `_cooldown == 0`, the click is hit-tested against **`info.press_cursor`** — the cursor where the close gesture *started* — so the hand drifting during the close cannot slide the click off its target, nor fake one onto it (a close begun outside doesn't count even if it ends inside). On success: `on_click()`, `pressed = True`, start cooldown, `break`.

Cooldown decrements by 1 each frame regardless of hand presence. A fist sliding across the button is rejected because a hand that appears already closed is initialised in the closed state without firing the transition event.

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
  was_hovered = hovered
  hovered = False; pressed = False
  cooldown -= 1 (if > 0)
  pad = int(BUTTON_STICKY_PAD_FRAC * height) if was_hovered else 0

  for i in range(len(hands)):
    info = pinch_info(hand_id(hand_result, i))   # read-only snapshot
    if info.cursor inside rect+pad:
      hovered = True
    # click is tested where the close STARTED, not where it fired:
    if info.pinching and cooldown == 0 and info.press_cursor inside rect+pad:
      pressed = True
      cooldown = BUTTON_COOLDOWN_FRAMES
      on_click()
      break
```

See also: [[modules/ui_manager]], [[modules/gestures]], [[architecture#Hand Interaction Model]]
