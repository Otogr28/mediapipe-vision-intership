# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

HalLMediaPipe is a real-time gesture UI: a webcam feed with a MediaPipe pose + hand
skeleton overlay, driven entirely by pinch gestures (pinch to click, grab to drag).
It runs on a laptop for development and deploys to a Jetson Orin Nano edge device.

## Commands

Requires **Python 3.12** — MediaPipe has no 3.13+ wheel, and `pyproject.toml` pins
`>=3.12,<3.13`. `uv` manages the environment; no `pip`/venv steps needed.

```bash
uv sync                       # create/update the .venv from uv.lock
uv run python src/main.py     # run locally (opens a window; press 'q' or Ctrl-C to quit)
uv add <package>              # add a dependency + update the lockfile
uv run isort src/             # sort imports (isort is the only formatter wired up)
```

Web frontend (`HALL_OUTPUT=web` — the browser renders all UI; Node needed on
the laptop only, never on the Jetson):

```bash
HALL_OUTPUT=web uv run python src/main.py   # backend: raw MJPEG + /state SSE on :8092
cd web && npm install && npm run dev        # dev server on :5173, proxies to :8092
cd web && npm run build                     # → web/dist, served by the backend at :8092/
uv run python web/scripts/mock_backend.py slingshot   # fake any scene, no camera needed
node web/scripts/shot.mjs http://localhost:5173/ out.png 3000  # headless screenshot check
```

**`web/dist` is committed on purpose** — the Jetson auto-updates by `git pull` and never
runs Node, so the built frontend must travel in the repo (`.gitignore` has an explicit
`!web/dist/` negation re-including it past the generic `dist/` rule; that rule was once
silently dropping it, so frontend changes never reached the device). After any change
under `web/src/`, **run `npm run build` and commit `web/dist` too** — otherwise the laptop
dev server shows your change and the exhibit never does.

To verify UI work without a camera, use `mock_backend.py` (it fakes any scene) plus
`shot.mjs`, rather than pointing the app at a real webcam.

**Always run from the repo root**, never from inside `src/`. The model paths in
`config.py` are relative to the repo root, and Python puts `src/` on `sys.path[0]`
so the modules import as top-level (`from detection import ...`, not `from src...`).

There is **no test suite** yet (`AGENTS.md` describes an aspirational `tests/` layout).

### Jetson deploy (from the laptop, over Tailscale SSH)

```bash
deploy/hall-app/deploy.sh          # rsync src/+models/, install `hallrun` launcher + moderngl
deploy/hall-app/remote-infer.sh    # laptop webcam → Jetson infers → laptop browser; auto-teardown
```

**The Jetson is an appliance that updates itself from git — pushing to `main` deploys.**
`setup-boot.sh` (one-time, on the device) converts `~/HalLMediaPipe` into a git checkout
and installs two *user* systemd units: `hallkiosk.service` (starts with the graphical
session — with GDM autologin, straight after boot) and `hall-update.timer` (polls
`origin/main` every ~60 s; on a new commit it does `git reset --hard` and restarts the
kiosk). So a push to `main` reaches the exhibit within a minute, with no deploy step.
Treat pushes accordingly. `hall-update.sh` also carries a health watchdog that restarts a
kiosk whose HTTP server stops answering (a wedged V4L2 reopen can freeze the process
holding the GIL, leaving systemd reading "active").

On the device, `hallrun` runs the backend alone; `hallkiosk` runs the exhibit pair
(backend + fullscreen browser, kept always-on-top via `wmctrl`) and exits non-zero if
either half dies so systemd restarts both. Firefox must be the **deb** from the Mozilla
apt repo — snap-confine is broken on this L4T kernel, so snap browsers cannot launch.
`kiosk-lockdown.sh` (sudo, one-time) prepares the desktop for unattended duty.

Note `deploy/hall-app/README.md` still opens by describing the app as manual-launch-only
("not a service … camera LED only on while it runs"); that intro predates appliance mode
and is contradicted by its own "Appliance mode" section further down.
`deploy/camera-stream/` is a *separate* headless MJPEG feed and `deploy/net-watchdog/`
keeps WiFi power-save from dropping Tailscale; only one thing can hold the C920 at a time
(`camctl off` releases it).

## Runtime configuration

The app is configured entirely through **environment variables read by `src/config.py`**
(there are no CLI flags). This is what makes the same binary run as a local windowed app
or a headless inference appliance. Key knobs:

| Var | Default | Meaning |
| --- | --- | --- |
| `HALL_CAMERA` | `0` | Local device index, **or a stream URL** (`http://host:8091/stream.mjpg`) to infer on a remote camera |
| `HALL_OUTPUT` | `window` | `window` (on-screen cv2 window), `stream` (headless MJPEG server), or `web` (React frontend: raw frames + per-frame state JSON over SSE; serves `web/dist`; backend does NO drawing) |
| `HALL_INFERENCE` | `mediapipe` | Hand backend: `mediapipe` (CPU `.task`) or `gpu` (onnxruntime CUDA/TensorRT). `hallrun` defaults this to `gpu`. |
| `HALL_POSE_INFERENCE` | `mediapipe` | Body-pose backend: `mediapipe` (CPU `.task`, ~13 fps) or `gpu` (onnxruntime BlazePose person-det + pose-landmark, CUDA/TensorRT — `detection/gpu_pose.py`, models under `models/gpu/`). `hallrun` defaults this to `gpu`. Only runs when a feature needs pose (Vtuber, or `HALL_POSE=1`). |
| `HALL_POSE` | `0` | Body-pose inference is OFF by default (the UI is fully hand-driven; pose cost ~1.5 CPU cores at ~13 fps). `1` re-enables it + the pose-driven 6-7 counter. |
| `HALL_ONNX_PROVIDERS` | `CUDA,CPU` | onnxruntime provider priority. `hallrun` prepends `TensorrtExecutionProvider` (~2.9x faster; first launch pays a ~2 min engine build, then cached to `.trt_cache/`) |
| `HALL_DEBUG` | `0` | `1` draws the pinch-pipeline debug HUD (live ratio vs thresholds, machine state, detection age/FPS) — for tuning gesture constants |
| `HALL_CAPTURE_W/H` | `1920`/`1080` | Requested capture size. Inference cost does **not** scale with it (models resize internally) but JPEG encode/decode and canvas work do — `hallkiosk` drops to 1280x720 to keep the Orin from saturating |
| `HALL_STREAM_BIND/PORT/QUALITY` | `auto`(`0.0.0.0` in web)/`8092`/`80` | MJPEG server. Web mode binds all interfaces because the kiosk browser hits `localhost`, which a Tailscale-resolved bind would refuse |
| `HALL_CAMERA_STALL_S` | `10` | Web mode: exit if no new frame for this long, so the supervisor restarts with a fresh handle. `0` disables; window/stream never self-exit |
| `HALL_START_VTUBER` | `0` | Dev: boot straight into the Vtuber scene with the puppet alive, so a recorded video file (`HALL_CAMERA=<file>`) can drive it without live pinches. Implies pose |
| `HALL_POSE_SMOOTH` | `1` | One-Euro + velocity extrapolation on every pose landmark. `0` = raw passthrough (the stutter/lag the smoother exists to hide) |
| `HALL_HAND_ROI_TRACK` | `1` | GPU hand backend: re-crop a tracked hand from its own landmarks instead of re-running palm detection. A/B knob — `0` restores palm-detect-every-frame |
| `HALL_TRT_MAX_WORKSPACE` | unset (`512` in `hallrun`) | Cap each TensorRT engine's build workspace (MiB). The Orin's 8 GB is shared CPU/GPU and the Vtuber runs four engines alongside the browser |

## Architecture

The full data-flow diagrams, UI state machine, and gesture math live in
`documentation/architecture.md` and `documentation/modules/*.md` — **read those before
non-trivial changes** and keep them in sync when you change a module's API or behaviour.
The big picture:

- **Async detection.** Both detectors run in MediaPipe `LIVE_STREAM` mode. Results are
  delivered by callbacks into module-level globals (`detectors.latest_pose_result`,
  `detectors.latest_hand_result`), decoupling inference latency from the render loop —
  `main.py` reads whatever the latest result is each frame rather than blocking.
- **Low-latency capture.** The camera is wrapped in `capture.FreshestFrame`, a background
  thread that keeps only the newest frame and drops the backlog — so when the loop runs
  slower than the camera (CPU-bound pose), capture latency stays ~1 frame instead of the
  driver queue growing. This is the fix for the "camera delay".
- **Two backends behind one interface, per pipeline.** `HALL_INFERENCE` selects the hand
  backend: MediaPipe (CPU `.task`) vs. the onnxruntime/TensorRT path in
  `detection/gpu_hands.py`. `HALL_POSE_INFERENCE` does the same for the body:
  MediaPipe vs. the BlazePose ONNX pipeline in `detection/gpu_pose.py`. Models live under
  `models/gpu/`, vendored zoo wrappers in `detection/_zoo/`. Both GPU backends emit a
  result object drop-in compatible with the MediaPipe one (`pose_landmarks`,
  `hand_landmarks`, …), so the smoother, rig, gestures and state layers never branch on
  the backend — that compatibility is the contract to preserve when touching either.
- **GPU rendering.** The black-hole mode (`rendering/gl_lensing.py`) runs a Schwarzschild
  lensing shader (`rendering/shaders/`) via a standalone moderngl EGL context — the one
  piece that genuinely uses the GPU even in headless stream mode.
- **Output is a swappable sink.** `output.make_sink()` returns a window, an MJPEG server,
  or the web sink based on `HALL_OUTPUT`; `main.py` only calls `sink.present()` /
  `sink.should_quit()` (plus `sink.publish_state()` in web mode).
- **Web mode splits render from vision.** With `HALL_OUTPUT=web`, Python does no drawing
  at all: `web/state.py` serializes the per-frame UI/gesture state (built from
  `UIManager.to_state()` + `gestures.pinch_infos()`) and the React app in `web/` renders
  everything — skeleton/cursor/scene on Canvas2D, buttons/HUD in DOM, and the black hole
  as a WebGL2 port of the lensing shader (`web/src/gl/blackhole.frag.glsl`). Python stays
  authoritative for all logic (state machine, hit-testing, physics); the browser is a pure
  renderer. The state payload itself is a hand-mirrored contract: `src/web/state.py` and
  `web/src/state/types.ts` must be changed together (see the sync table below).
- **Resilient loop.** The per-frame body is wrapped so a single bad frame/draw/GPU call
  logs once and continues rather than taking down a long-running headless appliance.
  In web mode only, the app **self-exits** if the camera stops delivering new frames for
  `HALL_CAMERA_STALL_S` — a deliberate crash so the kiosk supervisor restarts it with a
  fresh camera handle.

### The experiments (`ui/interactables.py`, ~2.5k lines — the bulk of the app)

Each scene is one class: `BouncingSphere`, `BlackHole`, `SixSevenCounter`, `Slingshot`,
`Orbitals` (n-body gravity), `Waves` (ripple tank), `Charges` (electrostatic field),
`Spacetime` (relativistic gravity), `Puppet` (VRM Vtuber). They share one contract, and it
is the thing to understand before adding another:

**Python owns the object list and all logic; the renderer derives every visual from it.**
Python holds the charges/sources/bodies and does placement, hit-testing, dragging and
physics-that-must-be-authoritative. It does *not* compute the picture. The browser derives
the visuals: Orbitals' trails accumulate client-side, Waves' field is stepped in a WebGL
ping-pong texture, Charges' potential is an analytic single-pass shader. This keeps the
state payload tiny (a few objects, not a field) and the Jetson's CPU out of pixel work.

**Every scene therefore has two renderers that must agree** — the WebGL/JS path and a
numpy/cv2 fallback for `window`/`stream` mode. Constants are mirrored across files by hand,
and `config.py` marks each with a "keep in sync" comment. When you touch one side, grep the
constant and fix the other:

| Scene | Python | Browser |
| --- | --- | --- |
| Waves | `WAVE_MAX_SOURCES`, display tone curve | `web/src/gl/waves_step.frag.glsl`, `waves_render.frag.glsl` |
| Charges | `CHG_MAX`, arrow constants | `web/src/gl/charges.frag.glsl`, `web/src/overlay/scene.ts` |
| Black hole | `rendering/shaders/black_hole.frag` | `web/src/gl/blackhole.frag.glsl` |
| Spacetime | `_embed_height`, `_embed_depth`, `_isotropic_radius`, `_project`, `_depth`, `_drag_frame`, `_lattice_offset` | `web/src/overlay/scene.ts` (`embedHeight` / `embedDepth` / `isotropicRadius` / `project` / `sheetDepth` / `dragFrame` / `latticeOffset`) |

Two physics lessons already paid for, recorded in `config.py` and worth not re-learning:
the leapfrog integrators (`WAVE_PHYS_DT`, `ORB_PHYS_DT`, `ST_PHYS_DT`) **must** step in
fixed whole chunks — deriving a sub-step from the frame remainder mismatches time levels
and pumps energy (the wave field diverged to ~1e32 in 5 s). And `Charges` has *no* time
integration at all, by design: the charges are static because the field is the subject;
letting them attract would just collapse into Orbitals-with-signs. `Spacetime` pins its
masses for the same reason.

**Display-only vs. physics.** `Spacetime` keeps the two apart: anything that shapes the
sheet belongs in `_depth`, never in `_accel`. But note the sheet is now drawn **to scale**
(`ST_DEPTH_GAIN = 1.0`, no ceiling) — an earlier version exaggerated it *and* tanh-clamped
it, which squashed a black hole into looking like a slightly deeper star. If a well seems
too shallow, the honest fix is compactness (`r_over_rs`), not a gain.

**Bodies have a RADIUS, and it is the whole point.** A star is not a point mass: outside its
surface the sheet is Flamm's paraboloid, inside it is the interior Schwarzschild *spherical
cap* (a smooth bowl, no throat), joined with a common tangent. A black hole has no surface,
so its funnel runs to the horizon and goes vertical. Treating a star as a point mass draws
every star as a black hole — that was the bug. By Birkhoff the far field can't tell them
apart; only compactness can. `tests/smoke_scenes.py` asserts the tangency and the depth
ordering.

**Two-hand gestures.** `Spacetime` is the first scene to use both hands at once: two
simultaneous pinches drive the camera and *supersede* place/drag, the way a two-finger
gesture supersedes a one-finger pan. That is why it places on RELEASE rather than on the
pinch edge — a mass must not appear just because the user was reaching for the second
pinch — and why hands that took part in a rotate stay inert until they re-pinch. Reuse
that pattern rather than inventing a new one if another scene needs two hands.

**Camera control is hybrid position/rate, and the reason is structural** — don't "simplify"
it back to an incremental drag (that was v1, and it was rightly called crude). A hand is an
*isotonic* input with a **bounded** usable workspace: `manager.EDGE_MARGIN_FRAC` documents
that the landmark model degrades near the frame border, so any gesture needing long travel
dies half-way. Incremental drag also has no home — returning your hands doesn't return the
view, so nothing is aimable. Per Zhai & Milgram, isotonic→position is the good pairing but
can't cover unbounded rotation without clutching; Casiez et al.'s RubberEdge resolves it by
blending position control (inside a disc around the grab origin) into rate control (outside
it). So: precise and homed near the centre, push-and-hold to spin forever. Same shape
should be reused for any future free-hand camera.

### Modularity preference

Keep `main.py` thin: camera capture, detector calls, drawing landmarks, and the sink only.
All UI logic (state machine, button layout, scene objects) belongs in `ui/manager.py` or
dedicated modules — never inline in `main.py`. When adding a feature:

- New UI state/mode → add a branch in `UIManager` (`ui/manager.py`)
- New interactable/physics object → new class in `ui/interactables.py`
- New button behavior → `ui/button.py`
- New GPU effect → new shader pair in `rendering/shaders/` + method on `LensingRenderer`
- New gesture → helper in `detection/gestures.py`; new threshold → constant in `config.py`
- New scene → the Python class is only half of it: it also needs serializing in
  `web/state.py`, typing in `web/src/state/types.ts`, a renderer under `web/src/gl/` or
  `web/src/overlay/scene.ts`, and a rebuilt+committed `web/dist`

Models (`.task`, `.onnx`) are **gitignored** — they are not in the repo. Download the
MediaPipe `.task` files into `models/` (see `documentation/setup.md`).

## Hardware — Jetson Orin Nano (deployment target)

The Jetson Orin Nano Developer Kit (Yahboom kit, JetPack 6.2 / L4T 36.4.3) is the edge
device this project runs on. It uses the **system** Python 3.10 with the vendor's aarch64
`mediapipe`/`opencv` builds (not `uv` — the repo's 3.12 pins have no prebuilt aarch64
wheels); the deploy only adds `moderngl`.

- **Boots from the internal NVMe** (Yahboom JetPack 6.2 image). A spare bootable image
  lives on the 128 GB SSK USB SSD, usable as recovery boot via the UEFI Boot Manager (ESC
  at the NVIDIA splash).
- **Login:** user `jetson`, hostname `yahboom`. Vendor-default password (same for `sudo`)
  is in the gitignored `SECRETS.local.md`.
- **Access:** over Tailscale (`ssh jetson@100.91.206.114`), or over USB device-mode
  networking when plugged into the laptop (`ssh jetson@192.168.55.1`, no WiFi needed).
- **WiFi:** Realtek RTL8822CE (`wlP1p1s0`), joined to GordonNET (WPA2-Enterprise, autoconnect
  on). WiFi ships rfkill-blocked; enable once with `sudo rfkill unblock all && sudo nmcli radio wifi on`
  (plain `nmcli` fails with a polkit "Not authorized" error — must use `sudo`).

## Conventions

- **Agent coordination:** this project uses `SHARED.md` as the cross-agent log (per
  `AGENTS.md`). Read it before starting work; append a concise update after meaningful
  work — don't overwrite others' notes or delete context unless clearly outdated.
- All code, comments, commit messages, and docs are written in **English**.
- `HalLMediaPipe` is a git submodule of the `Intership2026` vault.
