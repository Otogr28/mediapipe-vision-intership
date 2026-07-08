---
title: web/state.py — Per-frame state serialization (web mode)
tags: [module, web, serialization]
---

# `src/web/state.py` — Per-Frame State Serialization

In **web mode** (`HALL_OUTPUT=web`) the backend stops drawing anything with
cv2 and instead publishes one compact JSON document per rendered frame — the
complete contract between Python (authoritative for the state machine,
hit-testing and physics) and the browser frontend (a pure renderer, see
[[frontend]]). `build_state()` assembles it; `output.WebSink` pushes it to
clients over the `/state` SSE endpoint.

## Conventions

| Data | Space | Rounding |
| --- | --- | --- |
| Scene geometry (cursors, button rects, object positions) | **frame pixels** | 1 dp |
| Landmarks (pose 33, hands 21×N) | **normalized [0, 1]** (as MediaPipe emits) | 4 dp |
| Physics (forces, energies) | SI units | 3 dp |

Compact separators; worst case (slingshot + 8 projectiles + 2 hands + debug)
≈ 5 KB × 30 Hz ≈ 1.2 Mbit/s — a fraction of the MJPEG stream itself.

## Document shape

```jsonc
{
  "seq": 123, "t": 812.418, "frame": {"w": 1920, "h": 1080},
  "session": {"state": "menu|interactables|experiments",
              "experiment": null, "hint": {"visible": false}},
  "hands":  [ /* per-hand pinch snapshot + landmarks, see below */ ],
  "pose":   [[nx, ny, vis] /* ×33 */] | null,
  "pose_world": [[mx, my, mz] /* ×33, meters */] | null,
  "buttons": [{"id": "menu.interactables", "label": "...",
               "rect": [x, y, w, h], "hovered": false, "pressed": false}],
  "speed":  {"rect": [x, y, w, h], "text": "1x"} | null,
  "objects": [ /* typed dicts: sphere | sixseven | black_hole | slingshot */ ],
  "debug":  { /* render/hand fps, age, backend, thresholds */ } | null
}
```

- **hands** — from `gestures.pinch_infos()`: `cursor`, `press_cursor` (px),
  `state` (`open|closing|closed|releasing`), `progress`, `ratio`,
  `pinching` (one-frame edge), `held`, `seen_ms` (staleness — the client
  hides ghosts past ~200 ms like `cursor.py` does), the raw normalized 2D
  `landmarks` (null for grace-window survivors), and — for the vtuber rig —
  `world` (21 metric `[x,y,z]` from `hand_world_landmarks`, wrist origin) +
  `handedness` (`"Left"|"Right"`). `world`/`handedness` are present on both
  hand backends (mediapipe + the gpu shim); the avatar drives hand orientation
  + finger curl from `world` and matches hands to sides by image-x (not the
  `handedness` label, which is unreliable on the mirrored feed).
- **pose** — 33 image-space landmarks `[nx, ny, vis]` (normalized), drives the
  2D skeleton overlay and the vtuber head. `null` unless pose is running.
- **pose_world** — the same 33 joints as MediaPipe's metric `pose_world_landmarks`
  `[x, y, z]` in **meters**, origin at the hips midpoint, gravity-aligned and
  camera-independent (axes: +x image-right, +y down, +z away from camera). This
  is the real 3D skeleton that drives the vtuber rig's per-bone orientation
  (`web/src/gl/VrmAvatar.tsx`); visibility is *not* repeated — the rig gates a
  joint on `pose[i][2]`. `null` unless pose is running.
- **session / buttons / speed / objects** — from `UIManager.to_state()`,
  which mirrors the per-state branching of `UIManager.draw()`: only what
  the cv2 path would draw this frame is included. Button ids are stable
  strings (`menu.*`, `spawn.*`, `exp.*`, `speed.minus/plus`, `reset`).
- **objects** — each interactable serializes itself (`to_state()` methods in
  [[interactables]]):
  - `sphere`: `x, y, r, grabbed` (physics stays in Python).
  - `sixseven`: `count`, `flash` (0..1 decay of the count animation).
  - `black_hole`: centre + all disk parameters + `disk_t` (rotation clock).
    The lensing itself is a browser WebGL shader in web mode — the backend
    never creates a GL context (`UIManager(gpu_effects=False)`).
  - `slingshot`: anchor, aim state (`pull`, `readout`, predicted `arc`) and
    per-projectile `id, x, y, resting, sliding` + live forces `f_w/f_d/f_c`
    (newtons). **Trails are not streamed** — the stable `id` lets the client
    accumulate one point per snapshot per ball, reconstructing the trail.
- **debug** — only when `HALL_DEBUG=1`: render-loop fps (EMA over
  `build_state` calls), `detectors.hand_fps()`, result age, backend and the
  pinch thresholds. Drives the browser debug HUD (hotkey `d`).

## Transport (`output.WebSink`)

`WebSink(MjpegSink)` adds to the MJPEG server:

- `GET /state` — SSE; pushes the latest snapshot at up to `STATE_FPS`
  (default 30) events/s per client. Latest-only, same pattern as the MJPEG
  loop: slow clients skip snapshots instead of building a backlog.
  `EventSource` on the client reconnects automatically.
- Static serving of the built frontend (`WEB_DIST_DIR`, default `web/dist`)
  at `/` — path-traversal-safe, with a friendly "frontend not built" page
  when `dist/` is missing.
- `present()` still streams `/stream.mjpg`, but `main.py` passes the **raw**
  flipped frame (no skeleton, no UI) in web mode.

Web mode also defaults the bind to `0.0.0.0` (instead of the Tailscale IP)
so the Jetson kiosk browser can reach `http://localhost:8092/`, and paces
the main loop to `STATE_FPS` (without cv2 drawing it would spin far past
the camera rate re-encoding duplicate frames).

## Adding a field

1. Serialize it: `to_state()` on the object (or `build_state` for globals).
2. Mirror the type in `web/src/state/types.ts`.
3. Render it in the frontend layer that owns it (see [[frontend]]).
