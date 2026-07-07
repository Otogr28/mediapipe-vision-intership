---
title: debug_hud.py
tags: [module, ui, debug]
---

# `debug_hud.py` — Pinch Pipeline Debug HUD

**Location:** `src/ui/debug_hud.py` — enabled with the `HALL_DEBUG=1` environment variable (`DEBUG_HUD` in [[config]]).

A bottom-left panel showing exactly what the pinch pipeline sees, so thresholds are tuned with evidence instead of feel:

- **Per hand** (via `gestures.pinch_infos()`): id, machine `state`, filtered `ratio` (numeric + a bar with tick marks at `PINCH_CLOSE_RATIO` / `PINCH_RELEASE_RATIO`), continuous `progress`, cursor position, and staleness (ms since last advance).
- **Global**: render FPS (self-measured EMA of its own draw interval), hand-detector callback FPS (`detectors.hand_fps()`), detection result age in ms (`gestures.result_age_s()` — the same value the cursor extrapolation uses), and the active hand backend (`HALL_INFERENCE`).

## Design notes

- **Owned by [[ui_manager]]** (constructed only when `DEBUG_HUD` is true) and drawn **dead-last**, above every other layer including onboarding overlays.
- Deliberately imports `gestures` and `detectors` directly — it is a debug view of those two modules' internals; routing the values through UIManager would add coupling for no benefit.
- The panel darkens its region with an in-place ROI halving (`roi[:] = roi // 2`) instead of the full-`frame.copy()` blend pattern — it may run on the Jetson every frame.
- Bar tick positions are precomputed (thresholds are constants); no per-line `getTextSize` at draw time.

See also: [[gestures]], [[detectors]], [[cursor]], [[ui_manager]]
