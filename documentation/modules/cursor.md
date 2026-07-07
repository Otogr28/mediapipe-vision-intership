---
title: cursor.py
tags: [module, ui, overlay]
---

# `cursor.py` — Pinch Cursor Overlay

**Location:** `src/ui/cursor.py`

Always-on visual feedback for the pinch pipeline: one cursor per tracked hand, drawn at the exact point the detector uses (thumb-tip-anchored, One-Euro-smoothed, latency-compensated — see [[gestures]]). This closes the feedback loop that made pinching feel rough — the user steers the dot they can see, and every machine state is visible the frame it happens.

## Visual language

| Element | Meaning |
|---|---|
| Faint gray ring + dot | Cursor position, hand open |
| Amber arc filling clockwise from 12 o'clock | Continuous pinch **progress** (0 at the release threshold → 1 at the close threshold; the Meta "pinch strength" idea as UI) |
| Green filled dot + full ring | Pinch **held** |
| White expanding ring (~6 frames) | Click registered (`pinching` event) |

All strokes carry a dark under-stroke so they read on any video content (same trick as the slingshot force arrows).

## `PinchCursor(frame_w, frame_h)` / `draw(frame)`

Draw-only; reads `gestures.pinch_infos()` and never mutates gesture state. Owned by [[ui_manager]], drawn **after the scene, before the onboarding overlays**. Machines whose `last_seen` is older than `STALE_S` (0.2 s) are skipped — otherwise a hand inside the tracking-grace window would freeze a ghost cursor on screen. Per-hand click-flash counters are pruned when the hand departs.

Palette and geometry are module-local constants (visuals stay out of [[config]]; thresholds live there).

See also: [[gestures]], [[ui_manager]], [[debug_hud]]
