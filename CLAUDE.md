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

**Always run from the repo root**, never from inside `src/`. The model paths in
`config.py` are relative to the repo root, and Python puts `src/` on `sys.path[0]`
so the modules import as top-level (`from detection import ...`, not `from src...`).

There is **no test suite** yet (`AGENTS.md` describes an aspirational `tests/` layout).

### Jetson deploy (from the laptop, over Tailscale SSH)

```bash
deploy/hall-app/deploy.sh          # rsync src/+models/, install `hallrun` launcher + moderngl
deploy/hall-app/remote-infer.sh    # laptop webcam → Jetson infers → laptop browser; auto-teardown
```

On the Jetson itself the app is launched with `hallrun` (a foreground GUI app, not a
service — the camera LED is only on while it runs). See `deploy/hall-app/README.md`
for the full remote-inference wiring and the CPU-vs-GPU breakdown. `deploy/camera-stream/`
is a *separate* headless MJPEG feed; only one thing can hold the C920 at a time.

## Runtime configuration

The app is configured entirely through **environment variables read by `src/config.py`**
(there are no CLI flags). This is what makes the same binary run as a local windowed app
or a headless inference appliance. Key knobs:

| Var | Default | Meaning |
| --- | --- | --- |
| `HALL_CAMERA` | `0` | Local device index, **or a stream URL** (`http://host:8091/stream.mjpg`) to infer on a remote camera |
| `HALL_OUTPUT` | `window` | `window` (on-screen cv2 window), `stream` (headless MJPEG server), or `web` (React frontend: raw frames + per-frame state JSON over SSE; serves `web/dist`; backend does NO drawing) |
| `HALL_INFERENCE` | `mediapipe` | Hand backend: `mediapipe` (CPU `.task`) or `gpu` (onnxruntime CUDA/TensorRT). `hallrun` defaults this to `gpu`. |
| `HALL_ONNX_PROVIDERS` | `CUDA,CPU` | onnxruntime provider priority. `hallrun` prepends `TensorrtExecutionProvider` (~2.9x faster; first launch pays a ~2 min engine build, then cached to `.trt_cache/`) |
| `HALL_DEBUG` | `0` | `1` draws the pinch-pipeline debug HUD (live ratio vs thresholds, machine state, detection age/FPS) — for tuning gesture constants |

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
- **Two hand backends behind one interface.** `HALL_INFERENCE` selects MediaPipe (CPU)
  vs. the onnxruntime/TensorRT path in `detection/gpu_hands.py` (models under
  `models/gpu/`, vendored zoo wrappers in `detection/_zoo/`). Pose always stays on
  MediaPipe CPU — the Tasks API has no GPU build on the Jetson image.
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
  renderer. Keep `src/web/state.py`, `web/src/state/types.ts` and the shader pair in sync.
- **Resilient loop.** The per-frame body is wrapped so a single bad frame/draw/GPU call
  logs once and continues rather than taking down a long-running headless appliance.

### Modularity preference

Keep `main.py` thin: camera capture, detector calls, drawing landmarks, and the sink only.
All UI logic (state machine, button layout, scene objects) belongs in `ui/manager.py` or
dedicated modules — never inline in `main.py`. When adding a feature:

- New UI state/mode → add a branch in `UIManager` (`ui/manager.py`)
- New interactable/physics object → new class in `ui/interactables.py`
- New button behavior → `ui/button.py`
- New GPU effect → new shader pair in `rendering/shaders/` + method on `LensingRenderer`
- New gesture → helper in `detection/gestures.py`; new threshold → constant in `config.py`

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
