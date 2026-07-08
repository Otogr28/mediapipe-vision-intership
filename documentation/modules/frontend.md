---
title: web/ — React frontend (browser-rendered UI)
tags: [module, web, frontend, react]
---

# `web/` — React Frontend

The browser UI for **web mode** (`HALL_OUTPUT=web`). Python stays a pure
vision/simulation backend; the browser renders *everything visual*: video,
skeleton, pinch cursors, buttons, physics objects, the WebGL black hole and
the onboarding. Input never comes from mouse/touch — the pinch pipeline on
the backend is the only pointer (buttons render with `pointer-events: none`).

**Stack:** Vite + React + TypeScript. IBM Plex (Sans / Sans Condensed /
Mono, bundled via Fontsource — the kiosk may be offline). No other runtime
dependencies. Node is needed on the **laptop only**; the Jetson receives the
built `web/dist` via `deploy/hall-app/deploy.sh`.

## Running

```bash
# dev: backend on :8092 + hot-reloading frontend on :5173
HALL_OUTPUT=web uv run python src/main.py
cd web && npm install && npm run dev        # proxies /state, /stream.mjpg …

# prod: build once; the backend serves web/dist itself at :8092
cd web && npm run build
HALL_OUTPUT=web uv run python src/main.py   # open http://localhost:8092/
```

Dev against a remote backend: `HALL_BACKEND=http://<jetson>:8092 npm run dev`.
The proxy is **required** — a cross-origin `<img>` taints the WebGL canvas
and kills the black-hole shader (`SecurityError` on `texImage2D`).

Useful URL params: `?nointro=1` (skip splash), `?glscale=0.75` (render the
GL canvas at reduced resolution — Jetson escape hatch). Hotkey `d` toggles
the debug HUD (data flows when the backend runs `HALL_DEBUG=1`).

`scripts/shot.mjs` screenshots the app headlessly (puppeteer-core + system
Chrome) and `scripts/mock_backend.py` fakes every scene without a camera:

```bash
uv run python web/scripts/mock_backend.py slingshot   # from the repo root
node web/scripts/shot.mjs http://localhost:5173/ shot.png 3000
```

## Layer stack (bottom → top, all inside one aspect-ratio `.stage`)

| Layer | Tech | Draws |
| --- | --- | --- |
| `<img src=/stream.mjpg>` | MJPEG | raw mirrored camera frames |
| `gl/LensedVideo` | WebGL2 | black-hole shader over the video — **mounted only while a BH exists** (zero GPU cost otherwise) |
| `gl/VrmAvatar` | three.js/WebGL | VRM vtuber avatar — **mounted only while a vtuber object exists** (lazy-loads three-vrm). Rigged in full 3D: body bones aim along their `state.pose_world` segments (`setFromUnitVectors`, parent-first, mirrored by image-x); the whole avatar **translates + scales** to the person's screen position (`state.pose`); hands follow the **full palm orientation** + **30 finger bones** curl from `state.hands[].world` (the GPU-fast hand stream → snappier than the pose-bound arms). Behaviours are flag-gated (FOLLOW_POSITION / DRIVE_HAND_ORIENT / DRIVE_FINGERS / FAST_FOREARM); mirror/depth signs in AXIS / HAND_AXIS / HAND_N_SIGN |
| `overlay/OverlayCanvas` | Canvas2D | skeleton, sphere, slingshot, pinch cursors |
| `hud/HudLayer` | DOM | buttons, counter, readouts, hint, debug HUD |
| `hud/Intro` | DOM | page-load splash (frontend-local clock) |

**Coordinates:** everything works in *frame pixels*. Canvases have
`width/height` = frame resolution and are CSS-scaled by the stage;
`HudLayer` lays out at frame size and applies `transform: scale()` — the
backend's rects/positions pass through with zero transform math anywhere.

**State:** `state/useAppState.ts` subscribes to `/state` (SSE ~30 Hz),
keeps the two latest snapshots, and canvas layers `interpolate()` positions
between them per display frame (`state/interp.ts`) — flags/counters snap,
positions lerp, nothing is re-filtered client-side. React DOM re-renders
per event; canvases run their own rAF loops off a ref (no re-renders).

**Authority:** Python decides everything (state machine, hover/press,
physics). Frontend-local by design: snapshot interpolation, slingshot
trails (accumulated per projectile id), CSS transitions, the intro splash
clock, and the debug-HUD toggle.

## Black hole (`gl/blackhole.frag.glsl`)

GLSL ES 3.00 port of `src/rendering/shaders/black_hole.frag` (see
[[gl_lensing]] for the physics). Intentional differences:

- Colors are RGB (the original is authored in BGR for cv2).
- UVs have a **top-left origin** (matches both browser texture uploads and
  OpenCV pixel coords — no `UNPACK_FLIP_Y`, no per-frame CPU flip).
- **Edge fix:** out-of-frame lensed samples fade the deflection near the
  border + clamp, so the frame edge warps instead of tearing to black
  (the original renders black crescents when the BH nears an edge).
- **Photon ring** sits at `0.53·E` hugging the `0.5·E` shadow (was `0.62·E`)
  and is slightly narrower — closer to the EHT/Gargantua look.
- `u_time` extrapolates the backend `disk_t` between snapshots so the disk
  churns at display rate.

## Design system (`src/styles.css`)

Instrument-panel language over live video: dark-glass panels
(`--glass`, hairline borders, backdrop blur), viewfinder corner brackets
(`.brackets`) as the visual signature, and a semantic accent trio matched
to the gesture language — **amber** = action in progress (closing pinch,
hover, hints), **green** = confirmed (held, press, fresh count),
**blue** = passive traces (skeleton, idle). Type roles: Plex Sans (UI),
Plex Sans Condensed uppercase (labels/buttons), Plex Mono tabular (every
number). The onboarding hand (`hud/PinchHand.tsx`) is an articulated SVG
diagram whose cycle **dwells ~0.7 s in the closed pose** and demos the real
cursor ring, so users recognize the affordance on their own hand.

## File map

```
web/src/
├── App.tsx                 layer stack + intro/debug wiring
├── styles.css              design tokens + all component styles
├── state/{types,useAppState,interp}.ts
├── gl/{LensedVideo.tsx, blackhole.frag.glsl, fullscreen.vert.glsl}
├── overlay/{OverlayCanvas.tsx, skeleton.ts, cursor.ts, scene.ts}
└── hud/{HudLayer, Buttons, SixSeven, Slingshot, PinchHand,
         Intro, HintPanel, DebugHud}.tsx
```
