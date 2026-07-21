# SHARED.md — Agent Coordination File

This file is the coordination space between AI agents (Claude, Codex, or others) working on this project. Use it to leave useful context for the next agent, including:

- current project status
- important decisions made
- files changed
- commands run
- bugs found
- assumptions
- unfinished tasks
- warnings or things to avoid
- next recommended steps

## How to use

1. **Before starting any new task**, read this file in full and treat it as project context.
2. **After completing meaningful work**, append a short update at the bottom of the file using the format below.
3. **Do not overwrite another agent's notes.** Only remove context that is clearly outdated and is being replaced with better information.
4. Keep updates concise — link to files and commits instead of pasting long content.

## Update format

```
## Update - YYYY-MM-DD HH:MM - [Agent Name]

### What I did
- ...

### Files changed
- ...

### Important context for the other agent
- ...

### Next steps / unfinished work
- ...
```

## Project overview

This repository supports a 10-week Physics Department internship. Main focus areas:

- Learning **Autodesk Inventor 2027** (not AutoCAD).
- Learning **safe 3D printing workflows** (regular and resin). For resin work, never suggest unsafe shortcuts — always respect PPE, ventilation, resin handling, curing, cleaning, and disposal procedures.
- Building a **secure and maintainable Physics Department website** with:
  - Student Research Expo
  - Physics Hall Exhibits / Curiosity Gallery with QR-linked pages
  - A real admin system with secure authentication practices (no hardcoded passwords, no fake auth).

Coding values: clean, beginner-friendly, secure, and maintainable.

---

## Update - 2026-05-20 14:41 - Claude (Opus 4.7)

### What I did
- Created this `SHARED.md` to start the AI-agent coordination workflow.
- Appended a "Shared Agent Context Rule" section to `AGENTS.md` pointing here.

### Files changed
- `SHARED.md` (new)
- `AGENTS.md` (appended rule section)

### Important context for the other agent
- Repo currently holds a near-empty `uv`-managed Python project: `main.py` is a hello-world stub, dependencies are pinned in `uv.lock`, and there is no test suite yet.
- The internship has three parallel tracks (Inventor 2027, 3D printing, Physics Dept website). None of them have code in this repo yet — this repo so far only contains the MediaPipe/Python scaffold.
- Safety reminder for the human collaborator: **resin printing workflows must always include PPE, ventilation, proper curing, cleaning, and disposal** — do not suggest shortcuts.
- Security reminder for the website work: **no hardcoded passwords or fake authentication**. Use a real auth approach when that work begins.

### Next steps / unfinished work
- Clarify with the user how the MediaPipe Python work relates to the three internship tracks (is it for a Curiosity Gallery exhibit? a 3D-printing helper? something else?).
- Decide where the Physics Department website will live (this repo vs. a separate repo) before scaffolding it.
- Add a `tests/` directory + first `pytest` smoke test once real code lands in `main.py`.

## Update - 2026-05-20 14:42 - Codex

### What I did
- Read `SHARED.md` before making changes.
- Verified that `SHARED.md` already exists and contains the required AI-agent coordination instructions.
- Verified that `AGENTS.md` already contains the Shared Agent Context Rule.

### Files changed
- `SHARED.md` (appended this update)

### Important context for the other agent
- No project code changes were made in this step.
- The shared-context workflow is already installed and should continue to be followed.

### Next steps / unfinished work
- Continue using `SHARED.md` as required before and after meaningful work.

## Update - 2026-05-20 14:49 - Codex

### What I did
- Added a Codex-specific startup rule to `AGENTS.md`.
- Clarified that `AGENTS.md` is the project-level instruction hook for Codex and that Codex must read `SHARED.md` first at session start.
- Avoided modifying any Claude-specific configuration.

### Files changed
- `AGENTS.md`
- `SHARED.md`

### Important context for the other agent
- Do not add or modify Claude hooks/settings for this requirement unless the user explicitly asks.
- For Codex, enforce the shared-context workflow through `AGENTS.md`.

### Next steps / unfinished work
- On future Codex sessions, read `SHARED.md` first before planning, inspecting unrelated files, or editing.

## Update - 2026-05-20 15:10 - Claude (Opus 4.7)

### What I did
- Created `src/main_beta.py` as a minimal-diff variant of `src/main.py` that switches both `PoseLandmarker` and `HandLandmarker` from `RunningMode.VIDEO` (blocking `detect_for_video`) to `RunningMode.LIVE_STREAM` (non-blocking `detect_async` + `result_callback`). Goal: reduce perceived camera delay caused by running two synchronous inferences per frame.
- Kept `main.py` untouched so the user can A/B compare.

### Files changed
- `src/main_beta.py` (new)

### Important context for the other agent
- The async results are stored in two module-level globals (`latest_pose_result`, `latest_hand_result`) written from MediaPipe's callback threads. No lock is used — relies on the GIL making single-reference assignment atomic. If callbacks grow to do more than a single assignment, add a `threading.Lock`.
- `main_beta.py` snapshots both globals into locals at the top of each frame before drawing, so a callback firing mid-frame can't swap the object out from under the drawing loop.
- First 1–2 frames render without landmarks (callbacks haven't fired yet) — the `is not None` guards handle this.
- While editing, I noticed two bugs in `main.py`'s cleanup path that would crash on quit: `main.py:109` calls undefined `detector.close()` (should be `pose_detector.close()` + `hand_detector.close()`), and `main.py:110` has `v2.destroyAllWindows()` (typo, missing `c`). I fixed both in `main_beta.py` but **left `main.py` as-is** since the user only asked for the LIVE_STREAM beta.
- Other efficiency levers we discussed but did NOT apply (saved for later iteration): (a) downscale the frame before sending to MediaPipe and scale landmarks back when drawing, (b) run the hand detector every N frames instead of every frame.

### Next steps / unfinished work
- User to test `src/main_beta.py` vs `src/main.py` and compare perceived latency / FPS.
- If LIVE_STREAM helps, fold the changes back into `main.py` and delete `main_beta.py`.
- Independently, fix the two cleanup bugs in `main.py` (`detector.close()` and `v2.destroyAllWindows()`).

## Update - 2026-06-08 18:26 - Claude (Opus 4.8)

### What I did
- Added onboarding overlays: a ~3s startup splash (Nintendo-style) that
  demonstrates the pinch gesture, and a bottom-right hint ("Close your hand
  to interact") shown while a person is detected and hasn't interacted yet.
- Created `src/ui/hints.py` with `IntroOverlay`, `PinchHint`, and a shared
  `draw_pinch_hand()` (a stylized hand animating the thumb-index pinch).
- Wired both into `UIManager` (no changes to `main.py` — it stays thin).
- Added config constants and a documentation module to match repo conventions.

### Files changed
- `src/ui/hints.py` (new)
- `src/ui/manager.py` (instantiate + update + draw overlays; `_detect_interaction()`)
- `src/config.py` (intro/hint constants section)
- `documentation/modules/hints.md` (new) + `documentation/index.md` (links)

### Important context for the other agent
- The intro plays once at startup regardless of detection; the bottom-right
  hint shows only while `pose_landmarks is not None` and the user hasn't
  interacted. `UIManager._has_interacted` latches on the first button press
  or grab — so in practice the hint lives in the `menu` state only, which is
  why it never collides with the Reset button.
- Note: `main_beta.py` referenced in earlier updates no longer exists; the
  LIVE_STREAM changes are already folded into `main.py` and the cleanup bugs
  (`pose_detector.close()`/`hand_detector.close()`, `cv2.destroyAllWindows()`)
  are already fixed there. Those earlier "next steps" are done.
- Verified imports + headless drawing on a dummy frame; not run with a real
  camera/GUI (no webcam in this environment).
- Local uncommitted change in `config.py`: `SELECTED_CAMERA = 1` (was 0).

### Next steps / unfinished work
- User to run `uv run python src/main.py` and visually tune sizes/timing
  (`INTRO_DURATION_S`, `HINT_PINCH_PERIOD_S`, panel size in `PinchHint`).

## Update - 2026-06-29 - Claude (Opus 4.8)

### What I did
- Deployed the full interactive app to the **Jetson Orin Nano** (was only the
  camera MJPEG stream before). New kit: `deploy/hall-app/` (deploy.sh, hallrun,
  README). Code+models live at `~/HalLMediaPipe` on the device; launcher at
  `~/.local/bin/hallrun`.
- Added **configurable camera input + output sink** so the Jetson can act as a
  headless remote-inference appliance: laptop webcam → Jetson (infer+render) →
  laptop browser. New `src/output.py` (WindowSink / MjpegSink). `main.py` and
  `config.py` now read env vars `HALL_CAMERA`, `HALL_OUTPUT`, `HALL_STREAM_*`.
- Laptop-side helpers: `deploy/hall-app/laptop-camera.sh` (reuses the existing
  `camera-stream/camera_stream.py` to expose the laptop webcam) and
  `remote-infer.sh` (one command: starts everything, opens the viewer).
- Verified end-to-end on hardware: headless stream serves a valid annotated
  1920×1080 JPEG; Jetson pulls the laptop's MJPEG URL over Tailscale and reads
  frames. GL lensing context runs on the Tegra Orin GPU even headless.

### Files changed
- `src/output.py` (new), `src/main.py`, `src/config.py`, `CLAUDE.md`
- `deploy/hall-app/` (new): `deploy.sh`, `hallrun`, `laptop-camera.sh`,
  `remote-infer.sh`, `README.md`

### Important context for the other agent
- The Jetson runs on **system Python 3.10** (mediapipe 0.10.18 + cv2 4.10 ship
  in the image; `moderngl` added via `pip install --user`). It deliberately
  does NOT use `uv`/the pyproject pins (3.12 / mediapipe 0.10.35 have no
  prebuilt aarch64 wheel). Don't `uv sync` on the device.
- **MediaPipe inference is CPU-only** on the Jetson — its Python Tasks API has
  no CUDA/TensorRT path. Only the moderngl shader uses the GPU. TensorRT 10.7,
  onnxruntime-gpu 1.20, torch 2.5+CUDA are already installed for the planned
  "make it GPU-accelerated" follow-up (would mean exporting the models to
  ONNX→TensorRT, leaving the Tasks API).
- Jetson Tailscale IP `100.91.206.114`; laptop `100.105.148.27`. Output stream
  port 8092 (camera-stream uses 8090; laptop camera uses 8091).
- Nothing auto-starts; camera privacy preserved (C920 LED + manual launch).

### Next steps / unfinished work
- GPU-accelerate MediaPipe inference (the "extra compatible" task): ONNX→TensorRT
  or onnxruntime-gpu, benchmark vs current CPU FPS with `tegrastats`.
- Optionally add a systemd/.desktop autostart for a true kiosk (deferred for
  privacy).

## Update - 2026-06-30 - Claude (Opus 4.8)

### GPU investigation → the real bottleneck was the CAMERA, not inference
- Built a working CUDA hand-inference backend (onnxruntime palm+handpose from the
  OpenCV Model Zoo) behind `HALL_INFERENCE=gpu`: `src/detection/gpu_hands.py`,
  `src/detection/_zoo/`, `models/gpu/*.onnx`. Confirmed it runs on CUDA (palm 22 ms,
  handpose 10 ms vs 38–41 ms CPU).
- BUT profiling the *local* app showed inference was NEVER the bottleneck
  (`detect_async` enqueue ≈ 1.6 ms; CPU mostly idle at 10 fps). The bottleneck was
  **camera capture**: `main.py` opened the C920 with OpenCV's default **GStreamer**
  backend, which ignores FOURCC/FPS and opens it raw at full res → ~2 fps
  (89–500 ms/read). `cv2.CAP_PROP_FPS` read back as 2.0.
- **FIX (deployed):** open a local device with `cv2.CAP_V4L2` + MJPG + `FPS=30`
  (exactly what `deploy/camera-stream/camera_stream.py` already did). Result:
  end-to-end app **10 → 25.5 FPS @1080p (2.5×)**. See `src/main.py` camera-open block.

### Device change on the Jetson
- Uninstalled a stray **user-site `onnxruntime` (CPU 1.22.1)** that was shadowing the
  system **`onnxruntime-gpu` 1.20.0** → `CUDA`/`TensorRT` EP now active by default.
  (Don't reinstall plain `onnxruntime` in the user site or it'll shadow again.)

### Status
- GPU hand backend works but is **synchronous + detection-every-frame**, so it's
  slightly SLOWER than MediaPipe and is NOT the perf fix. Kept behind
  `HALL_INFERENCE` (default `mediapipe`). Shelved further GPU work (pose port,
  TensorRT) — inference isn't the bottleneck. The `*.onnx` are gitignored but
  rsync'd by deploy.sh. All changes uncommitted.

## Update - 2026-06-30 (later) - Claude (Opus 4.8)

### GPU hand inference is now the default on the Jetson (it IS the inference-latency fix)
- User reported the app "lentísimo", clarified the **camera is fine (async) — the
  slow part is inference**. Benchmarked on-board with the camera free:
  - Camera capture + the whole main loop (async enqueue) = **28 fps** (not the bottleneck).
  - Each MediaPipe model (pose, hand) = **~75 ms / 13 fps on CPU**; app pinned **~318% CPU**.
  - **Downscaling input does NOT help** (75 ms @1080p == @640x360 — MediaPipe resizes internally).
  - MediaPipe wheel has **no GPU build** (`BaseOptions.Delegate.GPU` raises "GPU processing
    is disabled in build flags") — so the Tasks GPU delegate is out.
  - The existing onnxruntime-CUDA hand backend is actually **async** (the old note above
    is stale) and **~2x faster**: GPU palm 21.6 ms, ~27 fps; real app in GPU mode =
    **214% CPU + GR3D 70-90%**, no errors, drop-in with the gesture/pinch code.
- **Change:** `deploy/hall-app/hallrun` now `export HALL_INFERENCE="${HALL_INFERENCE:-gpu}"`
  (override `=mediapipe` to A/B). Deployed to the Jetson (`~/HalLMediaPipe/hallrun`,
  symlinked at `~/.local/bin/hallrun`). **Uncommitted** in the repo.

### Files changed
- `deploy/hall-app/hallrun` (default HALL_INFERENCE=gpu) — uncommitted.

### TensorRT FP16 for the hand nets + Ctrl-C fix (same session, later)
- **TRT-FP16 is now the default hand EP** on the Jetson. `hallrun` sets
  `HALL_ONNX_PROVIDERS=TensorrtExecutionProvider,CUDAExecutionProvider,CPUExecutionProvider`;
  `config.py` attaches `trt_fp16_enable` + a persistent engine cache (repo-root
  `.trt_cache`, gitignored, survives deploys). Raw nets **~2.9x vs CUDA**
  (palm 10.2->3.5 ms, handpose 6.7->2.9 ms). Real app: **CPU 214->181%, GR3D ~0%**
  (GPU idle -> headroom for the black-hole shader). Engine build slow ONCE
  (palm ~17s, handpose ~100s) then cached. Validated end-to-end, no errors, cache reused.
  **BUT hands were already camera-capped (28 fps), so TRT is NOT felt as smoother
  hands** — it's headroom + latency. The hallrun comment claims deploy.sh pre-warms
  the cache; it does NOT yet (cache is built + persists, first-ever launch on a fresh
  cache eats the ~2 min build) — adding a deploy pre-warm step is a clean TODO.
- **Ctrl-C fix:** running `ssh jetson '...hallrun'` without `-t` never delivered SIGINT
  to the remote python, so Ctrl-C "didn't work" and left the app holding the camera.
  Cheat now uses `ssh -t`. (Watch out killing the app over SSH: `pkill -f "src/main.py"`
  matches the remote shell running your own command and kills your session — use a
  pattern like `pkill -f "main[.]py"` that doesn't self-match.)

### Files changed (this part)
- `src/config.py` (TRT provider options + engine cache), `deploy/hall-app/hallrun`
  (HALL_INFERENCE=gpu + HALL_ONNX_PROVIDERS=TRT...), `deploy/hall-app/hall-app.cheat`
  (`ssh -t`). All **uncommitted**.

### Next steps / unfinished work
- **POSE is now the real (felt) bottleneck**: MediaPipe CPU ~13 fps, choppy body
  skeleton. No cheap fix — needs a GPU pose backend (onnxruntime/TRT + a BlazePose
  landmark ONNX that must be sourced/verified; OpenCV zoo only ships the person
  *detector*). TRT-FP16 now proven on-board, so the runtime side is de-risked.
- Optional: add a TRT engine pre-warm step to deploy.sh so a fresh device doesn't
  eat the ~2 min build on first user launch (and make the hallrun comment true).
- Optional: hand ROI tracking (skip palm det while tracking) — but hands are already
  camera-capped, so low marginal value now.

## Update - 2026-07-01 18:40 - Claude (Opus)

### What I did
- Added a new **Slingshot** physics experiment (projectile motion) to the
  `"experiments"` mode: pinch near the anchor, pull back (rubber-band aim,
  clamped, with a dotted trajectory preview), release to launch. Then pure CPU
  Newtonian physics — gravity, wall/floor bounces with restitution, air drag,
  fading motion trail, up to 8 coexisting shots. Reuses the existing
  `pinch_state` grab/hold split (so it needs shoulders visible, like the BH).
- Refactored the `"experiments"` state from a single hardcoded Black-Hole slot
  into a **generic experiment picker**: `_active_experiment` holds the one
  running experiment (BlackHole | Slingshot), each just needs
  `update/draw/grabbed`. Adding a 3rd experiment now = new class + one button.
- Verified headless: physics sim (launch dir, gravity, bounce, rest, dead-fire,
  cap, predicted arc) + UIManager integration (picker/spawn/update/draw/reset)
  all pass. Did NOT run the live GUI app (no camera driven here).
- Kept docs in sync: `documentation/architecture.md` (state machine + dep graph)
  and `documentation/modules/interactables.md` (new Slingshot section). Also
  rewrote the root `CLAUDE.md` earlier this session (added run/deploy commands,
  the HALL_* env-var config, dual hand backend, pointers to docs/SHARED).

### Files changed (uncommitted)
- `src/ui/interactables.py` (+`Slingshot`, `_Projectile`, `SLING_*` consts; new
  `math`/`deque` imports)
- `src/ui/manager.py` (`_active_experiment` slot + `_experiment_btns` picker +
  `_spawn_slingshot`)
- `documentation/architecture.md`, `documentation/modules/interactables.md`,
  `CLAUDE.md`

### Next steps / ideas on the table
- More experiments proposed (not yet built): double pendulum (chaos), rope/cloth
  (Verlet), elastic sphere-sphere collisions, N-body/orbital sandbox, charged
  particles (Coulomb); GPU-shader ones: stir-a-fluid, water-ripple refraction of
  the live frame, reaction-diffusion. The picker refactor makes CPU ones cheap
  to slot in.
- Slingshot physics constants (`SLING_*`) are gut-tuned for 1920x1080; may want
  a live playtest pass on the actual camera to dial in feel.

## Update - 2026-07-01 19:05 - Claude (Opus)

### What I did
- **Slingshot ball-vs-ball collisions:** spawned balls now interact with each
  other — equal-mass 2-D elastic collisions (`_resolve_collisions`): positional
  separation + normal-component velocity exchange with
  `SLING_COLLISION_RESTITUTION` (0.85). Real impacts wake resting balls (piles
  can be knocked apart); gentle touches between settled balls only separate (no
  jitter). Verified over a 1200-frame multi-ball sim: no crashes, in-bounds,
  settles to rest, no interpenetration.
- **Angle/power HUD:** while aiming, a translucent readout above the anchor
  shows launch angle (deg from horizontal, +90 = up) and power (% of full-pull
  max) via `_aim_readout()`/`_draw_readout()`.
- **Camera-delay mitigation:** set `CAP_PROP_BUFFERSIZE=1` on the local webcam in
  `main.py` so `read()` favours the freshest frame. NOTE: this is a partial fix —
  V4L2 often ignores it. The real cure for the growing "camera delay" is a
  drop-stale-frames grabber (capture on its own thread, main loop always takes
  the latest). Not done yet; flagged to the user as the next option.

### Why the camera delay exists (for the next agent / the user asked)
- Detection is async (`detect_async`, LIVE_STREAM) so inference does NOT block
  the loop — good for throughput, but the skeleton overlay *lags* the live image
  by one inference (landmark trail). Separate from capture lag.
- The dominant "camera delay" is **capture-buffer backlog**: when the per-frame
  work (draw + UI + BH shader, and on Jetson the CPU-bound ~13 fps pose) is
  slower than the camera's 25-30 fps, unread frames pile up in the V4L2/OpenCV
  queue and `read()` returns ever-older frames. Fix = drop stale frames, not a
  bigger buffer.

### Files changed (uncommitted, this part)
- `src/ui/interactables.py` (collisions, HUD, `SLING_COLLISION_RESTITUTION`)
- `src/main.py` (`CAP_PROP_BUFFERSIZE=1` + comment)
- `documentation/modules/interactables.md`

### Next steps
- Offered: threaded latest-frame grabber (definitive latency fix) and/or
  detect-every-Nth-frame. Awaiting user's pick.

## Update - 2026-07-01 19:20 - Claude (Opus)

### What I did
- **Camera-delay real fix:** new `src/capture.py` `FreshestFrame` — a background
  thread that continuously drains the VideoCapture and keeps ONLY the latest
  frame. `main.py` now wraps the capture with it after the size-probe read. When
  the loop is slower than the camera (CPU-bound pose), stale frames are dropped
  instead of queued, so latency stays ~1 frame. Verified with a fake fast
  producer: a slow consumer skips ~40 frames between reads (dropped, not queued)
  and release() tears down the underlying cap. (`CAP_PROP_BUFFERSIZE=1` stays as
  a cheap belt-and-suspenders; V4L2 often ignores it.)
- **Slingshot rewritten in SI units** (metres/s/kg/N). Two bridge constants:
  `SLING_PX_PER_M=100` (100 px = 1 m) and `SLING_DT=1/30 s` fixed timestep. Real
  gravity 9.81 m/s^2, mass 1.0 kg, linear drag F=-b*v (b=0.15). Answered the
  user's "what is power %?" — the HUD now shows **launch angle (deg), speed
  (m/s), and KE (J)** instead of a made-up %.
- **Force-vector overlay:** every ball draws its live force vectors in newtons —
  weight (amber), drag (cyan), contact/normal (green), and net (white) — via
  `_draw_force_arrow` scaled `SLING_FORCE_PX_PER_N`. Contact force is recorded
  from wall/floor bounces and ball-ball impulses (impulse/dt) with a per-frame
  decay so impact arrows flash then fade; a resting ball shows a steady normal
  that cancels weight (net = 0). Plus a top-left legend with the SI constants.
- Verified: free-fall accel = 9.81; drag lowers accel at speed (6.81 @ 20 m/s);
  full pull ~14 m/s; collisions conserve momentum + record equal/opposite N;
  resting normal cancels weight; 400-frame multi-ball UI update+draw no crash;
  rendered a preview PNG that looks right (legend, HUD, arrows).

### Files changed (uncommitted, this part)
- NEW `src/capture.py`; `src/main.py` (wrap capture in FreshestFrame + import)
- `src/ui/interactables.py` (full SI Slingshot rewrite: constants, `_Projectile`
  with `cfx/cfy`, SI `_step`/`_resolve_collisions`/`_predicted_arc`, SI HUD,
  `_draw_force_arrow`, `_draw_legend`)
- docs: `documentation/architecture.md`, `documentation/index.md`,
  `documentation/modules/interactables.md`, `CLAUDE.md`

### Notes / knobs for the next agent
- `SLING_PX_PER_M=100` was chosen so real Earth gravity lands at ~1.09 px/frame^2
  — nearly the old hand-tuned 0.9 "feel" — while staying honest SI. Bumping it
  makes the arena smaller and the fall visually faster.
- Angle shown in **degrees** (accepted-for-use-with-SI); everything else strict
  SI. If a stickler wants radians, `_aim_readout` already computes in radians
  internally.
- Force arrows can look busy with 8 balls; `SLING_FORCE_PX_PER_N` / the min-draw
  threshold tune density. Drag arrow is short at low speed (physically correct).

## Update - 2026-07-06 10:30 - Claude (Fable)

### What I did
Reworked the Slingshot to use standard real-time simulation techniques, fixed
the two reported UI issues (legend text overflowing its box, ugly force
arrows), and added the top-right sim-speed control.

- **Fixed-timestep accumulator:** each frame banks `time_scale * SLING_FRAME_DT`
  (1/30 s) of sim time; the world advances in whole `SLING_PHYS_DT` (1/120 s)
  sub-steps, capped at `SLING_MAX_SUBSTEPS`. Speed changes alter the step
  COUNT, never the step size, so stability is identical at every speed.
- **RK4 integration** (`_rk4_step`) replaces semi-implicit Euler for free
  flight; the aim-preview arc uses the same step, so it matches the flight.
- **Quadratic aerodynamic drag** `F = -1/2 rho Cd A |v| v` (rho 1.225, Cd 0.47,
  A = pi r^2) replaces the linear `-b v`; terminal velocity ~15 m/s, shown in
  the legend. `SLING_DRAG_COEF`/`SLING_DT` are gone.
- **Legend box** is now sized from `cv2.getTextSize` measurements — nothing can
  overflow; footer lists g/m/r, Cd/rho/vt, and "RK4 @ 120 Hz".
- **Force arrows** redrawn: start at the ball's edge, dark under-stroke +
  fixed-size filled head, length capped at `SLING_FORCE_MAX_PX=130` (bounce
  impulses used to draw 1000+ px arrows across the screen). Contact impulses
  are averaged over the frame's simulated time.
- **Sim-speed stepper:** `Slingshot.time_scale` property + `speed_up/down`
  through `SLING_TIME_SCALES` (0.25-4x); `UIManager` shows `[-] 1x [+]`
  top-right for any experiment exposing `time_scale` (duck-typed).
- Ran `uv run python -m isort src/` (project formatter) — it also re-sorted
  imports in untouched files; those hunks are import-order only.

### Verification
Scratchpad test (RK4 vs analytic parabola: error <1e-9 over 1 s; terminal
velocity sim 14.97 vs sqrt(mg/k) 14.97; substeps/frame 1/2/4/8/16 at
0.25/0.5/1/2/4x; UIManager button wiring) + rendered aim/flight/bounce/UI
PNGs and inspected them. `main.py` imports clean.

### Files changed
- `src/ui/interactables.py` (Slingshot physics + drawing)
- `src/ui/manager.py` (speed buttons, `_draw_speed_label`, cv2 import)
- docs: `documentation/modules/interactables.md`, `modules/ui_manager.md`
  (also refreshed the stale `_black_hole` -> `_active_experiment` rows),
  `documentation/architecture.md`
- import-sort-only: everything else isort touched under `src/`

### Notes / knobs for the next agent
- The venv's bin scripts still carry shebangs from the repo's old path
  (`/home/oto/Intership2026/...`) — `uv run isort` fails to spawn; use
  `uv run python -m isort src/` or recreate `.venv`.
- Ball is 1 kg / 0.22 m -> light-foam-ball density; drag is strong near max
  launch (14 m/s ~ vt). Raise `SLING_BALL_MASS` to make shots more ballistic.
- 0.25x is genuinely useful for reading the force arrows during a bounce.

## Update - 2026-07-06 10:45 - [Claude (Fable 5)]

### What I did
Upgraded the Slingshot to research-grounded physics and fixed the force-vector
readability the user flagged:

- **Launch = slingshot energy model** (Yeats, arXiv:1604.00049): Hooke band
  `F = k·x`, stores `E = ½kx²`, delivers `SLING_BAND_EFF` (75%) as KE
  (latex hysteresis + band inertia), so `v0 = x·√(k·eff/m)`. `SLING_BAND_K`
  = 44.2 N/m is a real latex-band constant. Replaces the ad-hoc
  `SLING_LAUNCH_GAIN` (feel is nearly identical: full pull ~15 m/s vs ~14).
- **Coulomb friction** (Gaffer On Games collision-response model): bounces
  now apply a tangential friction impulse capped by the cone |jt| <= mu*|jn|
  (`SLING_FRICTION_MU` 0.5); spent bounces become a `sliding` state with
  kinetic friction mu*m*g until rest. Replaces `SLING_GROUND_FRICTION`
  (the old "keep 80% of vx per bounce" hack).
- **Force arrows**: tag letters at the tips (W/D/N/net) matching the legend;
  net-force arrow is now dashed — before, in free fall it drew solid white
  exactly on top of the weight arrow (the "ugly vectors" complaint). Sliding
  balls show tilted N (normal+friction) and net = pure friction.
- **Aim HUD**: two lines — angle + v0, and `DRAW N / E J -> KE J` showing the
  band energy chain; box clamps on-screen at small resolutions.
- Legend gained the band row (`k / eff / mu`); docs updated
  (`documentation/modules/interactables.md`).

### Verification
- Numeric checks (scratchpad `physics_check.py`, all PASS): v0 matches
  x·√(k·eff/m); KE/E == 0.75; terminal velocity 14.97 m/s reached in 20 s
  fall; floor skid rests in ~0.9 s (Coulomb estimate 0.96); KE+PE monotone
  non-increasing in flight; bounce friction impulse respects the cone.
- Rendered aim/flight/640x480 PNGs headlessly and inspected: legend and
   two-line HUD fit their boxes at 1280x720 and 640x480; W/net tags no longer
  collide (net tag offset further out).

### Files changed
- `src/ui/interactables.py` (constants, `_Projectile.sliding`, `_step`
  friction, `_launch_velocity`, `_aim_readout`/`_draw_readout`,
  `_draw_force_arrow` tags+dash, legend)
- `documentation/modules/interactables.md`

### Important context for the other agent
- The user's report "legend text overflows the box" does NOT reproduce on
  the current code (verified by rendering at 1280x720 and 640x480) — the
  measured-extents legend from the previous update already fixed it.
- `uv run isort` still fails (stale venv shebangs, see previous update);
  `uv run python -m isort src/` works and reports the tree clean.

### Next steps / unfinished work
- Ball-vs-ball collisions still exchange only the normal component (no
  tangential friction impulse between balls) — fine visually, noted here
  for completeness.
- Optional: nonlinear band force curve (Yeats Fig. 1 shows real latex is
  non-Hookean above ~3x stretch) if the internship wants more fidelity.

## Update - 2026-07-06 11:05 - [Claude (Fable 5)]

### What I did
- **Button edge margin** (user report: pressing edge buttons forces the hand
  to the frame border, where the landmark model degrades and pinches fail):
  added `EDGE_MARGIN_FRAC = 0.12` in `src/ui/manager.py` — all corner-anchored
  buttons (picker rows, sphere/6-7 row, menu row, speed stepper, Reset) now
  sit `int(0.12*fh)` px from the edges (~86 px at 720p). Verified by
  headless renders of the menu/picker/slingshot states.
- **Pinch research** (user asked for investigation + proposal BEFORE changes):
  found a real bug — `detection/gestures.py` keeps `_ratio_history` per hand
  and `pinch_state()` appends on EVERY call, but in the experiments state the
  same hand gets 4 calls per frame (experiment + speed-/+ buttons + Reset), so
  the 10-sample "rapid close" window really spans ~2.5 frames and the
  `PINCH_CLOSE_DROP >= 0.15` trigger becomes near-impossible — more UI on
  screen = harder to pinch. Proposal delivered to the user (edge-triggered
  hysteresis state machine, One-Euro filter, debounce buffer, knuckle-span
  scale); awaiting their pick before touching gesture code.
- Saved all web sources used in this chat to `../sources/index.md`
  (new "Web sources — HalLMediaPipe" section: slingshot physics + pinch UX).

### Files changed
- `src/ui/manager.py` (EDGE_MARGIN_FRAC + button positions)
- `../sources/index.md` (vault sources index)

### Next steps / unfinished work
- Implement whichever pinch improvements the user approves (see proposal in
  chat); the history-pollution bug fix should be first regardless.

## Update - 2026-07-06 11:40 - [Claude (Fable 5)]

### What I did
User approved all 4 pinch improvements — implemented the full pipeline rework
in `src/detection/gestures.py` (complete rewrite):

1. **Per-frame snapshot** (bug fix): `update_pinches(hand_result, fw, fh)`
   advances one state machine per hand ONCE per frame (called at the top of
   `UIManager.update`); consumers read via `pinch_state(hand_id)` which never
   mutates. Kills the history-pollution bug (4 widgets = 4 appends/frame).
2. **Edge-triggered state machine + hysteresis** (Ultraleap model): closes
   below `PINCH_CLOSE_RATIO` (0.45), reopens above `PINCH_RELEASE_RATIO`
   (0.90); `pinching` fires exactly once on open->closed; a hand entering
   the frame already closed starts closed WITHOUT firing (fist can't click).
   Replaces the rapid-close-drop window (which rejected slow pinches).
3. **Debounce**: 2 frames to close, 4 to release (tracking false-negatives
   happen while pinch-moving). Plus `PINCH_TRACK_GRACE_S` = 0.5 s keeps a
   lost hand's machine warm across dropouts.
4. **One-Euro filters** (Casiez CHI 2012) on ratio + cursor midpoint.
5. **Hand-relative scale**: `hand_scale = max(|5-17| knuckle span,
   0.75*|0-9| palm)` replaces the shoulder-width scale — pinch now works
   with NO pose/shoulders visible.

Callers updated: `ui/button.py`, `ui/interactables.py` (sphere/BH/slingshot)
now call `pinch_state(hand_id(hand_result, i))`; old constants
(PINCH_RATIO/HOLD_RATIO/HISTORY_LEN/CLOSE_DROP) replaced in `config.py` by
CLOSE/RELEASE ratios, debounce frames, grace, One-Euro params.

### Verification
`test_pinch.py` (scratchpad) — 10/10 PASS with synthetic 21-landmark hands:
slow close fires once; no flicker at the release threshold; clear open
releases; re-close refires once; entering fist never fires; multi-read
idempotence; knuckle scale exact; cursor jitter variance -85%; dropout
grace/purge; Button integration clicks once. Physics + UI renders unchanged.

### Docs synced
`modules/gestures.md` (rewritten), `architecture.md` (Hand Interaction
Model), `modules/config.md`, `setup.md` (tuning + troubleshooting),
`modules/interactableUI.md`, `modules/interactables.md`, `index.md`,
`modules/ui_manager.md`.

### Important context for the other agent
- `pose_scale()` is retained but unused by the pinch — kept for future
  pose-relative gestures.
- Thresholds 0.45/0.90 (knuckle-span units) are first-pass values from
  hand geometry (~3 cm close, ~6 cm release); tune on-camera if needed.
- Button.update / interactable update signatures unchanged (pose args now
  unused there) to keep the manager call sites stable.

## Update - 2026-07-06 12:20 - [Claude (Fable 5)]

### What I did
Implemented the approved "Pinch Smoothness v3" plan (plan file:
~/.claude/plans/curious-wiggling-sifakis.md) — full package, all tiers:

- **Tier 0 — Debug HUD** (`src/ui/debug_hud.py`, `HALL_DEBUG=1` -> config
  `DEBUG_HUD`): bottom-left panel with per-hand state/ratio bar (ticks at
  both thresholds)/progress/cursor/staleness + detection age ms, detector
  FPS (`detectors.hand_fps()`), render FPS, backend. ROI-halving blend
  (Jetson-friendly), drawn dead-last by UIManager.
- **Tier 1 — Pinch cursor** (`src/ui/cursor.py`): per-hand dot + progress
  ring (arc = continuous pinch strength between RELEASE and CLOSE), state
  colors (idle/closing/held), expanding click flash; skips machines stale
  >0.2 s (grace ghosts). Removed the raw green thumb-index line + px label
  from main.py (helper kept in rendering/drawing.py). Sticky buttons:
  hovered hit-rect inflates 15% of HEIGHT per side (`BUTTON_STICKY_PAD_FRAC`,
  entering still needs the base rect); cooldown 25 -> 8 and moved to config
  (`BUTTON_COOLDOWN_FRAMES`).
- **Tier 2 — Latency compensation**: detectors.py publishes
  `latest_hand_packet = (result, time.monotonic())` in one atomic
  assignment (covers the GPU worker thread) + `hand_fps()`; main passes
  `hand_received_t` -> `ui.update(...)` -> `update_pinches(received_t=...)`.
  Cursor = filtered + OneEuro-velocity * min(age, `PINCH_EXTRAP_MAX_S`=0.10).
  Output-only extrapolation (never fed back into the filter); ratio NOT
  extrapolated. Note: the canonical 1-euro derivative measures against the
  previous filtered value, so the lead also compensates the filter's own
  lag (intended; documented in gestures.md).
- **Tier 3 — Robustness**: (a) stable cursor anchored to thumb/index MCPs
  (lm 2 & 5, `PINCH_STABLE_CURSOR_BLEND`=1.0; tips 4/8 still drive the
  ratio); (b) hover-latch clicks — Button hit-tests `info.press_cursor`
  (cursor latched when the close debounce started) so drift during the
  close can't slide a click off/onto a target; (c) 3D pinch distance with
  `PINCH_Z_WEIGHT`=0.5 (z*frame_w; getattr default keeps z-less shims 2D).
- Introspection layer in gestures.py: `pinch_info(hand_id)` (read-only
  machine: ratio/progress/state/press_cursor/last_seen), `pinch_infos()`,
  `result_age_s()`; `pinch_state()` 3-tuple unchanged. Fixed latent D4 bug:
  machines not advanced this frame get `pinching=False` (was frozen True
  through the 0.5 s grace after a dropout-on-fire).

### Verification
24/24 synthetic checks PASS (scratchpad test_pinch.py): the 10 v2 checks +
progress 0/0.5/1, press-latch (drift 143 px live-vs-press), D4 clear,
result age, extrapolation lead proportional to age (x2.00) and clamped at
cap, stable anchor <2 px during close vs ~40 px tips-anchored, z blocks
phantom close (weight 0 restores 2D), sticky hysteresis, hover-latch both
directions, cooldown-8 double-click. Slingshot physics 7/7 PASS. Rendered
pinch_ui.png (4 cursor states + HUD 2 hands) and UI states — inspected.
compileall + isort clean; HALL_DEBUG=1 wiring asserted headless.
NOT yet tested live on camera — next session should run
`HALL_DEBUG=1 uv run python src/main.py` and exercise menu/sphere/BH/
slingshot/speed-stepper, and if possible `HALL_INFERENCE=gpu` (z path +
packet write from the GPU callback thread).

### Files changed
- `src/detection/gestures.py` (introspection + stable anchor + extrapolation
  + 3D ratio + D4), `src/detection/detectors.py` (packet + fps)
- `src/config.py` (DEBUG_HUD + 3 pinch knobs + 2 button knobs)
- `src/ui/cursor.py`, `src/ui/debug_hud.py` (NEW), `src/ui/manager.py`
  (owns both overlays; update signature), `src/ui/button.py` (sticky +
  latch + config cooldown), `src/main.py` (packet read, green line removed)
- docs: gestures.md, config.md, setup.md, architecture.md, ui_manager.md,
  interactableUI.md, main.md, drawing.md, index.md, NEW cursor.md +
  debug_hud.md; CLAUDE.md env table (+HALL_DEBUG row)

### Important context for the other agent
- Tuning knobs and their failure modes are in setup.md's tables (cursor
  offset -> lower PINCH_STABLE_CURSOR_BLEND; pinch won't fire -> lower
  PINCH_Z_WEIGHT; overshoot on reversals -> lower PINCH_EXTRAP_MAX_S).
- Interactables still initiate grabs on the live cursor (not press_cursor)
  by design — with the stable anchor the cursor barely moves during a
  close; flip them to press_cursor only if grabs still feel slippery.

## Update - 2026-07-06 16:40 - [Claude (Fable 5)]

### What I did
- **Cursor forward bias** (user feedback: the knuckle-anchored cursor felt
  glued to the palm): replaced `PINCH_STABLE_CURSOR_BLEND` with
  `PINCH_CURSOR_TIP_MIN` (0.35) / `PINCH_CURSOR_TIP_MAX` (1.0) in config.
  The cursor now sits 35% of the way from the MCP-knuckle midpoint toward
  the fingertip midpoint while open, and the tip weight slides with the
  (filtered) pinch progress up to 1.0 — a full pinch lands the cursor
  EXACTLY between the touching fingertips ("en medio"). Rigid mode (0/0)
  retains the old <2 px close-stability; press-latched clicks unaffected.
  Docs updated (gestures.md, config.md, setup.md, architecture.md).

### KNOWN BUG — reported by the user, documented, deliberately NOT fixed
- **Two-hand grab steal**: `BouncingSphere.grabbed` / `BlackHole.grabbed` /
  `Slingshot.aiming` are object-level flags with NO owner hand. The
  maintenance path `(grabbed and held)` is evaluated per hand in iteration
  order, so if one hand pinch-holds in the air while the OTHER hand grabs
  the object, the next frame the first held hand wins the maintenance
  check and the object TELEPORTS to it. Reproduced synthetically (check
  #27 in the scratchpad suite): sphere grabbed by "Right" at x=890 jumps
  to air-pinching "Left" (x=187) one frame later.
- Fix direction when someone tackles it: latch `hand_id` at grab/aim
  initiation and only let that hand maintain/move it until release; wake
  the normal release path if that hand disappears past the grace window.
- Documented in `documentation/modules/interactables.md` (Known bug
  callout) and `Logs/interactive-display/2026-07-06.md`.

### Verification
27/27 synthetic checks PASS (suite updated for the new cursor semantics:
forward bias open / between-tips closed / rigid mode; + the bug repro).
Slingshot physics 7/7. compileall + isort clean.

## Update - 2026-07-06 17:05 - [Claude (Fable 5)]

### What I did (supersedes the cursor part of the 16:40 entry)
- **Cursor no longer moves during the pinch** (user feedback: the
  progress-sliding cursor looked great but was counterintuitive — you aim
  at the pre-pinch position and the click lands elsewhere). Replaced
  `PINCH_CURSOR_TIP_MIN/_MAX` with a single `PINCH_CURSOR_FORWARD` (0.6):
  the cursor is now a RIGID predicted-pinch point — MCP-knuckle midpoint
  (lm 2,5) pushed forward along the palm axis (wrist 0 -> middle MCP 9) by
  0.6 of that segment. Only finger-invariant landmarks -> 0.00 px cursor
  motion during a full close (asserted in the suite); sits roughly where
  the fingertips meet. Palm-axis direction chosen over extrapolating the
  short wrist->knuckle lever for noise (unit coefficients ~1.1x landmark
  noise vs ~1.7x). The progress RING animation is untouched (that part the
  user liked). Docs updated (gestures.md, config.md, setup.md,
  architecture.md, Logs/interactive-display/2026-07-06.md).

### Verification
27/27 synthetic checks PASS, including new: cursor at the expected
forward point, 0.00 px displacement over a full close, forward=0
collapses to the knuckle midpoint; jitter test re-based to the composite
raw signal (raw var 16.6 -> filtered 2.0). compileall + isort clean.

## Update - 2026-07-06 17:20 - [Claude (Fable 5)]

### What I did (cursor placement, 4th iteration — user-tested on camera)
- User screenshot showed the palm-axis cursor landing ON TOP of the index
  finger on a rotated hand. Changed the rigid push direction from the palm
  axis (0 -> 9) to the INDEX-forward axis (0 -> 5): starting at mid(2,5)
  (halfway toward the thumb knuckle) and moving parallel to the index
  keeps the cursor in the middle of the thumb-index gap at any hand
  rotation. Still 100% finger-invariant landmarks: 0.00 px motion during
  a full close (asserted). `PINCH_CURSOR_FORWARD` unchanged (0.6, now a
  fraction of |wrist->index MCP|). Docs + log synced.
- Iteration history for the record: knuckles-only (glued to palm) ->
  progress-sliding blend (counterintuitive: aim point moved) -> palm-axis
  push (covered the index when rotated) -> index-axis push (current).

### Verification
27/27 checks PASS (expected anchor point updated; 0.00 px close motion;
forward=0 collapses to knuckles; jitter raw 17.6 -> filtered 2.4).

## Update - 2026-07-06 17:35 - [Claude (Fable 5)]

### What I did
- **FIXED the two-hand grab-steal ("teleport") bug** from the 16:40 entry:
  `BouncingSphere` / `BlackHole` / `Slingshot` now latch the owner hand at
  grab/aim initiation (`grab_hand` / `aim_hand`) and, while grabbed, read
  ONLY that hand's machine directly via `pinch_state(grab_hand)` — an
  air-pinching second hand can no longer move or steal the object. Bonus:
  the grab survives a tracking dropout frozen in place (<= grace window)
  and releases normally when the machine expires; the slingshot fires
  with the pull it had.
- **Cursor re-anchored to the THUMB TIP (lm 4)** (user request, 5th
  cursor iteration): replaces the rigid index-axis predicted-pinch point.
  The thumb is the stable side of a pinch (the index travels to meet it),
  so the dot tracks the aiming finger and barely moves during a close.
  `PINCH_CURSOR_FORWARD` REMOVED from config; One-Euro filtering,
  latency extrapolation and the press_cursor click latch unchanged.

### Verification
New synthetic owner-latch suite 21/21 PASS (steal repro: sphere stays
with Right while Left air-holds and iterates first; owner-follow with
offset; release-not-stolen; grace freeze + expiry release; push-physics
regression; BH + slingshot owner paths; cursor == thumb tip with 0.00 px
close motion). compileall + python -m isort --check clean.
NOT yet tested live on camera (same pending item as before).

### Files changed
- `src/detection/gestures.py` (thumb-tip cursor; PINCH_STABLE_A/B and
  PINCH_CURSOR_FORWARD import removed), `src/config.py` (knob removed)
- `src/ui/interactables.py` (owner latch in all three grab/aim sites)
- `src/ui/cursor.py` (docstring)
- docs: gestures.md, config.md, setup.md, architecture.md,
  interactables.md (bug callout -> fixed), cursor.md;
  `Logs/interactive-display/2026-07-06.md` (follow-up section)

### Important context for the other agent
- Grab/aim maintenance no longer iterates hand_result: while grabbed the
  owner's machine is read even if the hand missed this frame's result.
  Release paths: fingers open (debounced) OR machine expiry past
  PINCH_TRACK_GRACE_S. Initiation is unchanged (pinching edge + radius).
- If the thumb-tip cursor jitters on real hands, tune
  PINCH_CURSOR_MIN_CUTOFF down (the forward-offset knob is gone).

## Update - 2026-07-06 17:50 - [Claude (Fable 5)]

### What I did
- **NEW config knob `PINCH_CURSOR_THUMB_OFFSET` (0.0)** (user request):
  slides the cursor along the thumb ray (MCP 2 -> tip 4) as a fraction
  of that segment — hand-scaled and rotation-following, so the offset
  means the same at any camera distance/orientation. 0 = exactly at the
  thumb tip (default, unchanged behavior); positive floats past the tip,
  negative pulls back toward the knuckle. Applied to the RAW cursor
  before the One-Euro filter in `gestures.py` (`THUMB_MCP = 2` module
  constant). Caveat documented: the thumb ray rotates a little during a
  close, so large values reintroduce cursor motion while pinching.
- Docs synced: gestures.md (bullet, constants, rule, tunables),
  config.md, setup.md (tuning + troubleshooting rows).

### Verification
Suite extended to 24/24 PASS (offset 0.5 lands at tip + 0.5*(tip-MCP);
negative offset pulls back; offset 0 == exact thumb tip). compileall +
isort clean (isort re-wrapped the gestures.py import block).

## Update - 2026-07-06 18:05 - [Claude (Fable 5)]

### What I did
- **Cursor offset upgraded to 2D**: `PINCH_CURSOR_THUMB_OFFSET` renamed to
  `PINCH_CURSOR_THUMB_OFFSET_X` (same along-the-ray semantics) + new
  `PINCH_CURSOR_THUMB_OFFSET_Y` perpendicular to the thumb ray. +Y always
  points toward the INDEX side of the thumb — the sign is resolved per
  hand against the index MCP (lm 5), so Left/Right hands mirror correctly
  instead of the offset flipping sides. Both axes are fractions of the
  thumb segment (MCP 2 -> tip 4). The user is live-tuning the values in
  config.py (currently X=0.0, Y=0.5) — don't reset them.

### Verification
Suite 27/27 PASS (new: Y-axis math, mirrored-hand symmetry — same Y
offset lands at the mirrored point on a flipped hand — and X+Y additive
composition). compileall + isort clean.
Docs synced: gestures.md, config.md, setup.md, log addendum.

## Update - 2026-07-06 18:25 - [Claude (Fable 5)]

### What I did
- **NEW `PINCH_CURSOR_COMPENSATE` (1.0, 0..1)** — close counter-movement
  (user request: the cursor must counter-move to compensate the thumb's
  own travel while the pinch progresses). Mechanism: the (offset) cursor
  point is expressed in a rigid hand frame (origin wrist 0, basis
  wrist->index MCP 5 + its perpendicular — finger-invariant segments);
  its coordinates are tracked at rate (1 - progress) — fully while open,
  frozen when closed — and the drawn cursor is lerped toward where the
  remembered coordinates land in the CURRENT frame. Result: the thumb's
  close travel is cancelled (sub-pixel once fully closed), while hand
  translation/rotation/zoom still moves the cursor 1:1. Applied BEFORE
  the One-Euro filter; extrapolation and press_cursor unchanged.
- Per-hand state: `_HandPinch._cursor_ref` (survives the grace window).

### Verification
Suite 32/32 PASS (new: gradual thumb-moving close mostly cancelled;
+20 px thumb travel while fully closed -> sub-pixel cursor motion;
+100 px hand translation while pinched -> cursor follows 1:1;
compensate=0 -> cursor rides the raw thumb). compileall + isort clean.
Docs synced: gestures.md (new pipeline item 8 + rule), config.md,
setup.md, architecture.md.

### Important context for the other agent
- The reference tracks at 1-progress (not a hard open/closed gate), so a
  half-closed resting hand still slowly re-syncs — no permanent drift.
- If a user reports the cursor "sticking" when they wiggle the thumb
  without pinching: that's this feature (thumb motion toward the index
  raises progress); lower PINCH_CURSOR_COMPENSATE.

## Update - 2026-07-06 22:04 - [Claude (Fable 5)]

### What I did
**Web frontend (HALL_OUTPUT=web): the browser now renders ALL UI.** Python
becomes a pure vision/simulation backend; a new React+Vite+TS app in `web/`
draws everything. User-driven redesign ("la UI de cv2 se ve horrible").

- Backend: `WebSink(MjpegSink)` in `output.py` — raw frames on
  `/stream.mjpg`, per-frame UI/gesture state JSON over SSE `/state`
  (~30 Hz, latest-only), static serving of `web/dist` at `/`. Zero new
  Python deps (stdlib SSE — works on the Jetson's system 3.10).
- Serialization: `src/web/state.py` (`build_state`) + `to_state()` on
  UIManager/Button/Sphere/SixSeven/BlackHole/Slingshot. Schema doc:
  `documentation/modules/web_state.md`; TS mirror `web/src/state/types.ts`.
- `main.py`: web branch skips ALL cv2 drawing + paces the loop to
  STATE_FPS; `UIManager(gpu_effects=False)` → no GL context on backend.
  `_Projectile` gained a stable `id` (client accumulates trails).
- Frontend: MJPEG `<img>` + Canvas2D overlay (skeleton, cursor rings,
  sphere, slingshot w/ force arrows) + DOM HUD (buttons = pure display of
  backend hit-testing, pointer-events:none) + **WebGL2 port of the black
  hole shader** (`web/src/gl/blackhole.frag.glsl`: BGR→RGB, top-left UVs,
  edge-fade fix — no more black crescents at frame edges — photon ring
  at 0.53E). Redesigned onboarding: articulated SVG pinch hand with a
  0.7 s dwell at the closed pose + the real cursor-ring affordance.
- Deploy: `deploy.sh` builds+rsyncs `web/dist`; new `hallkiosk` launcher
  (backend web + Chromium --kiosk on the Jetson monitor).
- Dev tools: `web/scripts/mock_backend.py` (all scenes, no camera) and
  `web/scripts/shot.mjs` (headless screenshots; needs
  --enable-unsafe-swiftshader for WebGL, already wired in).

### Verification
- `HALL_OUTPUT=web`: /state ≈30 ev/s (curl), raw un-annotated stream,
  window mode unchanged (10 s run). isort + `bash -n` clean; tsc clean.
- Screenshot-verified via mock scenes: menu buttons (hover=amber glow),
  sphere, 6-7 card, slingshot aim (band/arc/readout) + flight (trails +
  W/D/N/net arrows), intro splash, hint panel, debug HUD (hotkey `d`),
  and the black hole on REAL GPU (hardware WebGL, non-headless Chrome):
  shadow + photon ring + churning disk + warped grid, no edge voids.
- Production path: `vite build` → backend serves dist at :8092 ✓.

### Important context for the other agent
- CONTRACT: `src/web/state.py` ⇄ `web/src/state/types.ts` ⇄ the renderers
  must stay in sync — update all three when touching UI state.
- The cv2 path (window/stream) is UNTOUCHED and remains the fallback;
  ui/*.draw() code still exists and must keep working.
- Headless-Chrome WebGL (SwiftShader) is flaky → false negatives; trust
  hardware Chrome. shot.mjs + mock_backend.py are the fast check loop.
- Jetson: deploy.sh was run from this session (rsync + hallkiosk); kiosk
  needs an on-device browser check (chrome://gpu → hardware WebGL2).

## Update - 2026-07-07 12:40 - [Claude (Fable 5)]

### What I did
Jetson kiosk deployed and VERIFIED on the physical monitor (screengrab via
ffmpeg x11grab): fullscreen browser UI, live C920 feed, menu buttons.

- `deploy.sh` run (code + models + web/dist + launchers). Tailscale SSH
  needed the check-mode browser re-approval first (URL changes per
  attempt; keep ONE ssh pending and approve that one).
- **Snap is broken on this L4T kernel**: snap-confine dies with
  "cap_dac_override ... Function not implemented" → snap chromium (150)
  installs but can NEVER launch (even via systemd-run --user). Solution:
  **Firefox 152 native deb** from packages.mozilla.org (apt repo + pin
  installed on the Jetson) and `hallkiosk` now prefers firefox.
- Firefox enterprise policies at /etc/firefox/policies/policies.json
  (SkipTermsOfUse, no first-run page, no update prompts) so the kiosk
  boots unattended.
- `hallkiosk` trap fix: killing the hallrun wrapper orphaned the python
  (bash|tee pipeline) — the trap now also pkills `python3 -u src/main.py`.

### Important context for the other agent
- Never `sudo snap install` browsers on the yahboom Jetson — deb only.
- pkill in ssh'd compound commands self-matches the remote wrapper too
  (exit 255) — same bracket-trick + separate-call rule as locally.
- Kiosk usage: `hallkiosk` on the Jetson (or
  `ssh jetson@100.91.206.114 'DISPLAY=:0 ~/.local/bin/hallkiosk'`);
  laptop can co-view at http://100.91.206.114:8092/.

## Update - 2026-07-07 17:15 - [Claude (Fable 5)]

### What I did
**The Jetson is now a boot-to-kiosk, self-updating appliance** (user has no
peripherals on it — everything is remote now).

- Pushed the whole web-frontend feature to main (748abde): includes
  `web/dist` COMMITTED on purpose — the device updates via git and never
  runs Node. Push to main = deploy.
- `~/HalLMediaPipe` on the Jetson is now a git checkout of origin/main
  (setup-boot.sh converted it; models/ + .trt_cache/ untracked, survive).
- systemd user units (deploy/hall-app/systemd/): `hallkiosk.service`
  (WantedBy=graphical-session.target → starts at boot via the GDM
  autologin that was already enabled) and `hall-update.timer` → every 60 s
  `hall-update.sh` fetches origin/main, hard-resets on new commits and
  restarts the kiosk. Linger enabled; screen blanking/lock disabled.
- VERIFIED end-to-end: test push 5dae635 → journal shows
  "hall-update: 748abde -> 5dae635", kiosk restarted, screengrab OK.

### Important context for the other agent
- **Workflow now: edit → (npm run build if web/ changed) → commit → push
  to main → Jetson live in ≤60 s.** deploy.sh (rsync) is legacy/provision.
- Launchers on the device point INTO the checkout
  (~/HalLMediaPipe/deploy/hall-app/); the rsync-era copies at the repo
  root were removed.
- Kiosk control: `systemctl --user {status,restart,stop} hallkiosk` on
  the Jetson (XDG_RUNTIME_DIR=/run/user/1000 when over ssh).
- Remember: the git working tree on the device is sacred-ish — the
  updater hard-resets it; never hand-edit files there.

## Update - 2026-07-07 18:20 - [Claude (Fable 5)]

### What I did (perf/reliability afternoon — all live on the Jetson)
- 720p kiosk profile (HALL_CAPTURE_W/H); polkitd runaway restarted.
- Self-healing: camera-free wait in hallkiosk; hall-update watchdog FIXED
  (mawk %d int32-truncated µs → negative ages → never fired; now pure-bash
  seconds); backend self-exits after 10 s without a NEW camera frame
  (HALL_CAMERA_STALL_S; FreshestFrame.frame_age); hallkiosk dies with
  either half and the unit is Restart=always; units auto-refresh on update.
- MJPEG serving rewritten: clients block on a Condition and get each frame
  EXACTLY once (no duplicate re-sends, no fixed-clock latency) — measured
  30 fps exact delivered on-device (was ~19 with jitter). Kiosk JPEG q60.
- **Body pose inference OFF by default (HALL_POSE=0)** — UI is fully
  hand-driven; frees ~1.5 cores. 6-7 counter button hides (pose-driven);
  onboarding hint presence now comes from tracked hands. HALL_POSE=1
  restores. python: 158% → ~112% CPU.
- IDEAS.md expanded: "Orbitals" n-body astro simulator designed as the
  next experiment (velocity-Verlet, merge collisions, pinch-drag-release
  launch reusing slingshot aiming, BH collapse reusing the shader).
- Session report: vault Logs/interactive-display/2026-07-07.md.

### Important context for the other agent
- NEVER start the app with the LAPTOP camera unless the user asks — they
  explicitly said not to activate it. Use web/scripts/mock_backend.py.
- The felt slowness was NOT the camera (C920 negotiated MJPG 720p@30):
  it was duplicate-frame serving + 1080p pixel costs + pose CPU.

## Update - 2026-07-07 20:05 - [Claude (Opus 4.8)]

### What I did
Implemented BOTH open IDEAS.md features + an optimization, and fixed a
latent deploy bug so it actually reaches the Jetson via git.

- **Orbitals** (Experiments → "Orbitals"): n-body gravity sandbox.
  `Orbitals` in `ui/interactables.py`. Symplectic velocity-Verlet
  (optimized to ONE force-eval per step by carrying a(t+dt) → next a(t):
  measured 2.305 → 1.178 ms/frame at 40 bodies), Plummer softening,
  inelastic merges (mass+momentum conserved, colour/volume combined),
  collapse→black-hole look past `ORB_COLLAPSE_MASS`. Pinch-drag-release
  launch (pull-opposite, arc previewed through the LIVE gravity field),
  grab-to-fling, body-type palette + presets (Solar/Binary/Figure-8 — all
  verified bound for 60 s; Solar planets are near-massless and Binary is
  bare 2-star, both on purpose for on-screen stability) + Clear, shared
  sim-speed stepper (adds 8×). Frontend `drawOrbitals` in
  `web/src/overlay/scene.ts`; trails accumulated client-side by body id.
- **Vtuber** (Interactable Figures → "Vtuber"): `Puppet` in
  `ui/interactables.py` + `drawPuppet` in `scene.ts`. Cosmic-mascot avatar,
  paws on the hands, mouth from pinch, eyes track hands, pose-driven arms
  when HALL_POSE=1 (soft arms when off). Dims camera + hides raw skeleton
  (skeleton.ts gate). cv2 fallback puppet included.
- Generic experiment-palette plumbing in `ui/manager.py`
  (`_experiment_palette()` reads `exp.palette` — the experiment owns its
  buttons). `Button.selected` flag (radio look) + CSS `.gbtn.selected`.
- Contract kept in sync: `types.ts` (OrbitalsObject/VtuberObject,
  ButtonState.selected), `interp.ts` (orbital body lerp), mock_backend
  scenes `orbitals`/`orbaim`/`vtuber` (+ picker now has Orbitals).

### Important context for the other agent
- **DEPLOY BUG FIXED:** root `.gitignore` `dist/` was silently ignoring
  `web/dist` despite `web/.gitignore` saying it's committed — so the
  git-pull auto-updater NEVER carried the frontend (it survived only via an
  old rsync'd untracked copy on the device). Added `!web/dist/` negation;
  `web/dist` is now tracked (65 files) and travels via `git pull`. Verify
  future frontend changes with `git status web/dist` before pushing.
- Workflow reminder: web/ change → `npm run build` → commit dist → push.
- Verified headlessly (no camera, per the user's rule): mock_backend +
  shot.mjs screenshots for orbitals/orbaim/vtuber/picker (no console
  errors), UIManager to_state across all states, physics stability.
- NOT done: GPU pose backend (IDEAS backlog) — blocked on a BlazePose
  landmark ONNX (only palm+handpose are vendored). Purely model-sourcing.

## Update - 2026-07-07 21:40 - [Claude (Opus 4.8)]

### What I did (round 2, per user follow-up)
- **Orbitals collisions are now REALISTIC** (were merges). Hard-sphere
  impulse response with restitution (`ORB_RESTITUTION=0.6`, unequal masses,
  positional correction) resolved per sub-step in `Orbitals._resolve_collisions`.
  An asteroid deflects a planet by the mass ratio; momentum conserved
  EXACTLY (verified: 750.0→750.0). Softening dropped to 2 px (collisions
  stop overlap, so gravity is ~exact). Removed merge + collapse-to-BH. Mass
  now shown per body + in the aim readout. Contract updated (types.ts:
  body `m`, `kind_m`, readout `mass`; removed `collapsed`).
- **Vtuber is now a real open-source VRM avatar.** `web/src/gl/VrmAvatar.tsx`
  loads a CC0 VRoid model (`web/public/avatar.vrm`, madjin/vrm-samples) via
  three.js + @pixiv/three-vrm and rigs it from our own landmarks (arms
  shoulder→elbow→wrist, mouth from pinch, idle sway/blink). NO Kalidokit and
  NO state-contract change (2D image-plane rig). Lazy-loaded (three.js in a
  separate chunk, out of the main bundle). Canvas mascot (`drawPuppet`) is
  the fallback (module flag `gl/vrmState.ts`). Verified rendering in headless
  Chrome (arms follow synthetic pose, face lip-syncs).
- **Pose inference activates on demand.** `UIManager.wants_pose()` (True when
  the puppet is live) drives `main.py`, which now lazily builds + runs the
  pose detector only while needed — default hand UI stays pose-free, Vtuber
  lights the skeleton up so the avatar's arms track.

### Important context for the other agent
- New npm deps: `three`, `@pixiv/three-vrm`, `@types/three` (dev). `avatar.vrm`
  (~12 MB) is committed in BOTH web/public/ and web/dist/ — vite empties dist
  on build, so the public source must stay committed or a rebuild wipes the
  served copy. It travels to the Jetson via git (web/dist tracked).
- Jetson perf: entering Vtuber now runs pose (~1.5 CPU cores) + a three.js
  VRM scene (GPU). Watch fps on-device; it's on-demand so other modes are
  unaffected. The arm rig was tuned on synthetic mock pose only (no camera
  here) — MIRROR_X / ARM_DAMP in VrmAvatar.tsx may want on-device tweaking.
- The cv2 window/stream path still works (Puppet.draw + Orbitals.draw).

## Update - 2026-07-07 22:55 - [Claude (Opus 4.8)]

### What I did (round 3, per user follow-up)
- **Orbital collisions -> physically-accurate OUTCOME model** (Leinhardt &
  Stewart 2012). Impact speed vs mutual escape velocity `v_esc =
  sqrt(2 G M_tot / R_tot)` picks the regime in `Orbitals._resolve_collisions`:
  MERGE (accrete + flash) below v_esc, BOUNCE (hit-and-run impulse) up to
  `ORB_FRAG_VESC_FACTOR*v_esc`, FRAGMENT (shatter into largest remnant +
  debris that re-accumulate) above. Mass + momentum conserved EXACTLY in all
  three (verified: merge 2->1, bounce 2->2, fragment 2->N). Impact/merge
  `flash` field added (expanding ring, cv2 + web). `_step` re-seeds accel
  after a merge/fragment changes the body list.
- **Vtuber skeleton diagnosis + fix.** The backend pose activation WORKS —
  device log shows "pose inference enabled on demand" when Vtuber is picked,
  and the pose model loads fine on the Jetson. The likely cause of "only
  hands" was the VRM camera framing being too TIGHT (raised arms left frame);
  widened it (span*4.5, was 3.1) + added a spine lean so the body visibly
  follows. Added a small on-screen status readout in vtuber mode ("avatar ●
  / body ●", green when the VRM is loaded / pose is arriving) so the failure
  mode is visible.

### Important context / OPEN QUESTION for the other agent
- **UNVERIFIED on the device:** I cannot drive the gesture UI into Vtuber
  remotely (no camera here) and headless WebGL is unreliable, so whether the
  VRM actually renders in the Jetson's FIREFOX is unconfirmed. The VRM does
  render in headless Chrome. If the on-device status shows "avatar ○" (not
  loaded) the three-vrm/Firefox path needs debugging with the device browser
  console — the Canvas mascot (hand-anchored) is the fallback and would
  explain "only hands". First thing to check on-device: does the anime VRM
  appear, or the cream Canvas mascot?
- Collision cascade: a catastrophic hit can chain (debris re-shatter) but it
  terminates (fragments stop below ORB_FRAG_MIN_MASS) and is capped at
  ORB_MAX_BODIES; verified it settles (2->16), doesn't run away.

## Update - 2026-07-07 23:55 - [Claude (Opus 4.8)]

### What I did (round 4, per user follow-up)
- **Proved the VRM works in FIREFOX** (the kiosk engine): drove it with
  puppeteer BiDi + Firefox 152 (same major as the Jetson) — the avatar loads,
  both arms track the pose, mouth lip-syncs, status dots green. So the code +
  body inference are correct; the earlier "only hands" was the tight framing
  (fixed round 3) and/or the fallback mascot showing during model load.
  New tool: `web/scripts/ff_shot.mjs` (Firefox screenshot harness).
- **New avatar model:** swapped to **Sendagaya Shino** (school uniform,
  clean/clothed) — embedded VRM license is **CC0** (verified in the file's
  meta; commercial allowed). Replaces the underwear-ish `female vroid`.
  `web/public/avatar.vrm` + `web/dist/avatar.vrm` (~15 MB).
- **Removed the "beta model" (Canvas mascot) at startup.** `drawPuppet` in
  `overlay/scene.ts` no longer draws a placeholder puppet — just the dim
  backdrop + a loading spinner ("summoning avatar…") until the VRM is live.
  Deleted the mascot helpers (handAnchors/drawStar/PUP_* ~230 lines); main
  bundle shrank. The cv2 window-mode `Puppet.draw` is untouched.

### Important context for the other agent
- Body inference DOES run on the device (log "pose inference enabled on
  demand" + pose model loads). If a user still sees no body movement, it's a
  tracking-quality issue (stand back so shoulders/elbows are in frame), not a
  code bug — the status readout ("body ●" green) confirms pose is arriving.
- Model swap left the old `female vroid` blob in git history (unavoidable);
  repo is heavier. To change avatars: drop a CC0 .vrm at web/public/avatar.vrm,
  `npm run build`, commit web/public + web/dist, push.

## Update - 2026-07-08 01:10 - [Claude (Opus 4.8)]

### What I did (round 5 — the vtuber rig was actually broken)
User reported arms crossing / model not following. ROOT CAUSE found: the arm
rig was inverted because `VRMUtils.rotateVRM0` rotates the model 180° about Y,
so a bone's parent-local +Z points to world -Z — my "rotate about Z" swung the
arms the WRONG way (and the old mirror sign compounded it). Rewrote the rig:
- Arms are posed by rotating about the TRUE world-Z axis (world Z expressed in
  the bone's parent frame via the parent's inverse world quaternion), with the
  rest angle recomputed from the current parent each frame (so the forearm
  follows the rotated upper arm). Single-axis -> no twist, no 180° flips.
- MIRROR is now by IMAGE POSITION, not anatomical MediaPipe label: the
  shoulder with the larger image-x drives the avatar's screen-right arm. Robust
  to however MediaPipe labels L/R on the flipped feed; can't cross.
- Added head-yaw/pitch (nose) + spine lean. Debugged via console angles piped
  through the Firefox harness.
VERIFIED in Firefox 152 with an ASYMMETRIC mock pose (right arm up, left arm
horizontal): the avatar mirrors it exactly, arms don't cross.

### Important context
- `web/scripts/ff_shot.mjs` now also forwards any `VRMDBG`-tagged console line
  (used it to read live rest/target angles). Handy for future rig tuning.
- If on real hardware the arms still mirror the wrong way, the position-based
  assignment should prevent it — but the head-yaw sign is unverified (centred
  nose in the mock), so tune HEAD in VrmAvatar.tsx if the head turns wrong.

## Update - 2026-07-08 - [Claude (Opus 4.8)]

### What I did (round 6 — vtuber rig is now FULL 3D, not a flat swing)
User: the avatar "only leans and only moves hands, without moving any joint —
each landmark is 3D, why not drive every joint from a point?" Correct diagnosis.
The old rig swung arms about a single screen-plane axis and threw away depth —
`src/web/state.py` only serialized `[x, y, vis]`, never the metric z.

Root fix — use MediaPipe's real 3D skeleton:
- Backend now also emits `pose_world_landmarks` as **`state.pose_world`** (33
  `[x,y,z]` meters, hips origin). Plumbed: `src/main.py` → `src/web/state.py`
  (`_pose_world_state`) → `web/src/state/types.ts` (`PoseWorld`). 2D `pose`
  still drives the skeleton overlay + head; visibility gate reuses `pose[i][2]`.
- `web/src/gl/VrmAvatar.tsx` fully rewritten: `aimBone()` orients EACH bone
  (spine, both upper/lower arms, wrists, both legs) along its body-segment
  direction with `setFromUnitVectors` (minimal-rotation, full 3D → reaches
  toward camera, twists, bends), solved parent-first so children follow. Delta
  measured from the bone's REST world direction (keeps rest roll, no 180° flip).
  Per-segment relax when a joint's visibility drops; legs gated at 0.55 (they're
  usually off the head-to-hips framing). Head (nose yaw/pitch) + mouth unchanged.
- Kept the round-5 mirror-by-image-x arm assignment (anti-crossing) verbatim.
- MediaPipe→three axis map `(x, -y, -z)` = const `AXIS` in the file.

### GOTCHA that cost a debug cycle
The vector helpers (`segDir`/`midPoint`) use module-level scratch. First version
reused `_p`/`_q` as BOTH internal scratch AND caller output → the two spine
midpoints aliased and the torso bent ~90°. Fixed with private `_s0`/`_s1` that
are never passed as `out`. If you add more helpers, keep that separation.

### Verified
Mock `vtuber` scene extended with `vtuber_world(t)` (3D, raised arm reaches
toward camera on a cycle). `uv run python web/scripts/mock_backend.py vtuber`
+ vite dev + `shot.mjs` → avatar stands upright, right arm up-diagonal, left arm
horizontal, all joints articulating, no console errors. `npm run build` clean;
**web/dist rebuilt + committed-ready**. NOTE: only X/Y confirmed from the front
view + mock; the z-depth sign (`AXIS.z`) and leg behavior should get a final
eyeball on the real Jetson camera feed — flip one const if depth looks inverted.
Tip: `?nointro=1` skips the splash (it covers the avatar for the first ~4 s).

## Update - 2026-07-08 - [Claude (Opus 4.8)]

### Round 7 — vtuber rig v2 (uses ALL the 3D inference; commit 38cbdc3)
User: the avatar didn't follow their screen position, hands had no orientation
(palm toward/away didn't show), and it still felt delayed — "you have MediaPipe's
3D inference, you're wasting it." All three fixed by spending the rest of the 3D
output. Chosen (via AskUserQuestion): full-mirror framing (translate + scale) and
full 30-bone finger tracking.

- **Backend hand 3D (`src/web/state.py`):** `_hands_state` now also emits per-hand
  `world` (21 metric `[x,y,z]` from `hand_world_landmarks`) + `handedness`. Both
  backends produce these (mediapipe + gpu_hands shim) — only state.py was dropping
  them. Mirrored in `web/src/state/types.ts` (Vec3, HandState.world/handedness);
  `interp.ts` needs no change (the `...h` spread passes them as newest).
- **Body follows screen (`VrmAvatar.tsx` `rigBodyTransform`):** translate+scale
  `vrm.scene` from the shoulder-midpoint of `state.pose` (2D). GOTCHA fixed during
  bring-up: scaling `vrm.scene` grows from its origin (feet) → pushed the head out
  of frame. Fix = pivot the scale at the CHEST via `position.y += pivotY*(1-s)`,
  and pull the camera back (span*4.6 → *5.6) for follow/scale margin.
- **Hands (`rigHandOrientation` + `rigFingers`):** hand bone gets the full palm
  orientation via a palm basis (wrist/index-MCP/middle-MCP/pinky-MCP →
  setFromRotationMatrix) + a captured `palmToBone` rest offset; 30 finger bones
  aim along their segments (reuse `aimBone`). Hands matched to avatar sides by
  image-x (NOT handedness). Rides the fast hand stream → snappier than arms.
- **Responsiveness (`FAST_FOREARM`):** the forearm's screen plane tracks the fast
  hand wrist (2D), depth stays from pose. Upper arm tau raised (pose-bound).
- **Flags/knobs:** FOLLOW_POSITION / DRIVE_HAND_ORIENT / DRIVE_FINGERS /
  FAST_FOREARM, and sign knobs AXIS / HAND_AXIS / HAND_N_SIGN{left,right}.

### Still to confirm ON THE JETSON CAMERA (synthetic mock can't validate these)
1. `HAND_AXIS.z` — palm-depth sign (palm toward camera should face camera).
2. `HAND_N_SIGN.{left,right}` — palm-normal chirality per hand (wrong = back of
   hand faces camera). The Jetson gpu-backend `hand_world_landmarks` were never
   validated in-app before this — finger/palm quality is the main unknown.
3. Thumb curl direction (most chirality-sensitive); body-follow X sign.
If any looks wrong: flip the one knob, or set its flag false, rebuild+push.

### Verified headless (mock `vtuber` + shot.mjs, `?nointro=1`)
Mock extended with a moving/scaling body + synthetic 3D hands (palm roll + finger
curl). Avatar translates across the frame with position, stays well-framed, arms
mirror correctly, hands show articulated fingers, no console errors. `npm run
build` clean; web/dist committed; Jetson updated to 38cbdc3, backend healthy.

## Update - 2026-07-08 - [Claude (Opus 4.8)]

### Round 8 — wrist candy-wrapper + body delay + a real-inference test harness (ca2da7d)
User (testing live on the Jetson): body inference had a "HORRIBLE" delay, and
rotating the wrist collapsed the mesh ("splits into two lobes with a node").

- **Wrist candy-wrapper:** unbounded wrist twist with no forearm-twist bone.
  `orientBone` now clamps the hand's deviation from rest (relative to the
  forearm) to `WRIST_MAX_RAD ≈ 72°`, capping the twist below the collapse.
- **Body delay:** most of it was client smoothing, not just the ~13 fps CPU
  pose. Cut body/root taus hard (UPPER_ARM 0.06→0.035, SPINE→0.04, HEAD→0.035,
  root BODY_MOVE 0.12→0.055 / SCALE→0.12). Residual = pose fps (GPU-pose is the
  real fix, still future work).

### NEW reusable capability: drive the avatar from a VIDEO FILE (no camera)
So the rig can be tested against REAL inference without the webcam (user rule)
or a person at the Jetson:
- `capture.py` `FreshestFrame(loop=, fps=)` loops + paces a video FILE to its
  native fps (webcam/stream unaffected); `main.py` auto-enables it for non-URL
  string sources.
- `HALL_START_VTUBER=1` (config/manager) boots straight into the Vtuber scene
  and keeps the puppet alive.
- Get a clip: mixkit CDN is curl-able (Pexels is Cloudflare-blocked) —
  `curl https://assets.mixkit.co/videos/<id>/<id>-360.mp4`. Run:
  `HALL_OUTPUT=web HALL_POSE=1 HALL_START_VTUBER=1 HALL_INFERENCE=mediapipe
   HALL_CAMERA=<clip> uv run python src/main.py`, then vite dev + shot.mjs.
- VERIFIED the whole rig on a real "person shrugging, palms up" clip: arms,
  hands, fingers all track; the ~90° wrist supination renders clean (candy-
  wrapper gone). NOTE: the laptop pose is fast, so this harness does NOT
  reproduce the Jetson's pose-fps delay — only the client-smoothing part.

## Update - 2026-07-08 - [Claude (Opus 4.8)]

### Round 9 — body pose smoothing: One-Euro + extrapolation (3f24f99)
User: body inference still "too slow"/jumpy while hands feel responsive; wants
teleport-jumps eased into realistic glides. ROOT CAUSE: the hand CURSOR is
One-Euro filtered + velocity-extrapolated (that's why it feels good); the body
pose went RAW to the rig. At the Jetson's ~13 fps CPU pose that's a stuttering
"staircase" with zero latency compensation.

- **`detection/pose_smoother.py` (PoseSmoother):** One-Euro filter on every pose
  landmark (2D image + 3D world) + output extrapolated by filtered velocity ×
  result age (capped POSE_EXTRAP_MAX_S). Fed on each NEW pose result
  (`detectors.latest_pose_packet` = result+receive-time), sampled every frame in
  main.py. Reset on a >0.4s gap so pose on/off doesn't snap. `HALL_POSE_SMOOTH=0`
  bypasses. Config: POSE_MIN_CUTOFF=0.8, POSE_BETA=0.4, POSE_EXTRAP_MAX_S=0.12.
- **VrmAvatar.tsx:** lighter body taus (UPPER_ARM 0.035→0.025, SPINE→0.03, root
  BODY_MOVE 0.055→0.04) now that upstream smooths — avoids double-lag.

### How I tuned it (rigorous, offline — the video harness paid off)
Drove the app from a real clip (mixkit man shrugging), captured the pose_world
trajectory, then REPLAYED it offline through the real _OneEuroFilter at the
Jetson's 13 fps rate and swept (min_cutoff, beta, extrap) vs the 30 fps ground
truth. Metric = max per-frame jump (stutter) + lag + range. Chosen params cut
the worst jump ~2.9x (0.169→0.059) for ~5% more lag (extrapolation offsets it).
Laptop pose is too fast to feel the win live — the offline 13fps replay is how
to validate/tune this without the Jetson.

### Note on the "crash"
Not a real crash — each `git push` restarts the kiosk (~10s white screen); the
user caught one. Backend verified stable (healthz 200). If you deploy several
times fast, expect brief kiosk blinks.

### Still open / next levers if body still lags
Hands' world landmarks (fingers/palm) are still RAW — same smoother could apply
(needs per-hand filter identity). And the real pose-fps fix remains GPU pose.

## Update - 2026-07-08 - [Claude (Opus 4.8)]

### Round 10 — GPU BODY POSE backend (the real body-lag fix; built + validated local, NOT yet deployed)
User: "mira si podes correr el body en el gpu también, capaz ajusta la vram."
Delivered lever #3 from CONTINUE.md — pose no longer has to run MediaPipe CPU.

- **New `detection/gpu_pose.py` (`GpuPoseDetector`):** two-stage ONNX BlazePose
  (person-det -> pose-landmark) through onnxruntime, drop-in for MediaPipe's
  PoseLandmarker (same `detect_async`/`close`, same async worker-thread design as
  `gpu_hands.py`, emits a `pose_landmarks`/`pose_world_landmarks`-compatible
  result). Selected by **`HALL_POSE_INFERENCE=gpu`** (config `POSE_INFERENCE`);
  MediaPipe stays the default. `hallrun` now defaults it to `gpu` (like hands).
- **Vendored `_zoo/mp_persondet.py`:** OpenCV Model Zoo BlazePose person detector
  (Apache-2.0, 224x224 NCHW, 2254 anchors), cv.dnn swapped for onnxruntime like
  `mp_palmdet.py`. Returns `[box(4), 4 keypoints(8), score]`; kp0=hip-center,
  kp1=full-body point.
- **New `_zoo/mp_poselandmark.py`:** landmark stage — ROI geometry
  (`detections_to_rect`/`rect_transformation`, ported from geaxgx/depthai_blazepose,
  MIT) + the 195/117 tensor decode (39x[x,y,z,vis,pres] image + 39x[x,y,z] world,
  take 33). **GOTCHA that cost a debug cycle:** geaxgx does the ROI math in
  square-NORMALIZED coords; our frame is 16:9 and the detector returns keypoints in
  PIXELS — normalizing x/w, y/h stretched the ROI ~3.5x (mean err 0.22). Fixed by
  doing all ROI math in **pixels (isotropic)** -> mean err 0.027. Also: the
  pose-flag score is already a probability (person 1.0 / blank 0.0), so NO sigmoid
  on it (matches geaxgx); visibility IS a logit -> sigmoid (kept).
- **Models (gitignored, in `models/gpu/`):** `person_detection_mediapipe_2023mar.onnx`
  (OpenCV zoo, git-lfs via media.githubusercontent.com) + `pose_landmark_lite.onnx`
  (tf2onnx-converted from the `pose_landmarks_detector.tflite` INSIDE
  `models/pose_landmarker_lite.task` — so it's the SAME landmark model the MediaPipe
  path used). NB: the DETECTOR tflite would not convert via tf2onnx
  (`cannot reshape 96 into (16,1,1,24)`) — that's why the detector comes from the
  zoo's pre-converted onnx instead.
- **Added `detectors.pose_fps()`** (mirrors `hand_fps()`) + `pose_fps` in the web
  debug state — CONTINUE.md lever #1 (measure the real pose rate) is now free.
- **VRAM lever (user's ask):** `HALL_TRT_MAX_WORKSPACE` (MiB) caps each TRT engine's
  build workspace. Opt-in (unset = TensorRT default, hand setup unchanged). The Orin
  now runs 4 TRT engines when Vtuber is active (palm+handpose+pose-det+pose-lm) on 8
  GB shared memory — set this if it OOMs.

### VALIDATED (local, no camera, no Jetson) — the video harness + a local NVIDIA GPU
Ran the whole GPU pipeline (onnxruntime CPU) on a real clip and compared every
frame's 33 landmarks to MediaPipe ground truth: **mean 2D error 0.027 (~17px @
640w), world err ~0.08 m** — skeletons overlap tightly, no flips (saved an overlay
PNG). Full async `GpuPoseDetector` smoke-tested: 33 lms + 33 world, drop-in result.

### DEPLOYED 2026-07-09 — and it works: pose_fps 13 -> 30 on the Jetson GPU
Shipped (commit 38eb955 + the hallrun workspace-cap follow-up). Measured on-device
with the video-file harness (Vtuber + gpu pose + gpu hands): **pose_fps ~30.2**
(was ~13 on CPU) at render 30 / hand_fps ~26-29 — **the body now matches the hands'
rate, so the speed mismatch the user complained about is gone.** Memory held ~2.6 GB
free with everything running; the two pose TRT engines built in ~2 min each under a
512 MiB `HALL_TRT_MAX_WORKSPACE` cap (no OOM), then load from `.trt_cache` in ~12 s.
The live kiosk is healthy (healthz 200) in the default hand-UI scene; GPU pose
engages at 30 fps with no build delay the moment Vtuber is selected (engines cached).

### Permanent Jetson SSH — no more Tailscale browser check (set up this session)
`ssh yahboom` (in `~/.ssh/config`) now key-auths over **Tailscale port 2222** — the
Jetson's real sshd listens on 22 + 2222 (drop-in `/etc/ssh/sshd_config.d/
tailscale-altport.conf`), and Tailscale forwards non-22 ports transparently instead
of intercepting them with Tailscale SSH check-mode. Port 22 (Tailscale SSH) stays as
a fallback. So deploys no longer need the `login.tailscale.com/a/...` browser step.

### (historical) what the deploy needed
Was blocked on: (1) a one-time Tailscale SSH browser auth (now bypassed by the 2222
key path above); (2) go-ahead to push (done).

## Update - 2026-07-09 - [Claude (Opus 4.8)]

### Round 11 — forearm-twist distribution (fix the "wrist looks broken" on roll)
User (GPU pose feels great now): "sigue el problemita con la muñeca — el brazo no
rota con la mano, se ve roto en esa parte." ROOT CAUSE: the forearm (`lowerArm`) was
oriented by DIRECTION only (`setFromUnitVectors`, elbow→wrist) with no roll, so any
palm roll (pronation/supination) piled entirely onto the wrist joint — which is
clamped to `WRIST_MAX_RAD≈72°` (round 8's candy-wrapper fix). Past the clamp the hand
turned but the forearm didn't → visible break.

- **`VrmAvatar.tsx` `aimBone` now takes an optional `childWorld`** (the hand's desired
  world orientation). When present it swing-twist-decomposes the hand-relative-to-
  forearm rotation about the forearm's own axis (`rest.childLocalPos`) and folds a
  fraction (`FOREARM_TWIST_GAIN=0.65`, capped `FOREARM_TWIST_MAX_RAD=110°`) of that
  TWIST into the forearm's local target — so the forearm rolls WITH the wrist and the
  hand-joint clamp barely engages. Computed off the aim TARGET (not the live bone
  quat) and applied in a single slerp → no inter-frame feedback/wobble.
- **`rigArm` computes the hand's world orientation once** (`palmBasis × handRest`, the
  same target `rigHandOrientation` uses) and passes it to the forearm aim. `side`
  derived from the bone name.

### Verified (local video harness + headless WebGL render)
Drove the avatar from the shrugging clip (real hands w/ palm roll), `npm run build`
clean, captured 3 frames (palms up / palms forward / fingers spread): the forearm
now rotates with the palm, the wrist-forearm junction is continuous — no break, no
candy-wrapper, no console errors. web/dist rebuilt + committed (rides the git
auto-update; no model change so no rsync). Tune `FOREARM_TWIST_GAIN` (0=old behavior,
1=forearm takes all the roll) if the user wants more/less forearm follow.

**DEPLOY GOTCHA — the models don't ride the git auto-update.** `hall-update.sh`
does `git reset --hard origin/main` (tracked content only) and the `.onnx` under
`models/gpu/` are **gitignored**, so pushing the code is NOT enough — the two new
pose ONNX files must be rsync'd separately (they reach the Jetson only via
`deploy.sh`, which rsyncs `models/`, or a targeted
`rsync -az models/gpu/ jetson@…:~/HalLMediaPipe/models/gpu/`). If they're missing
the app degrades SAFELY to hand-only (`pose detector build failed; staying
hand-only`) — no crash, but GPU pose won't actually run. So: **push code + rsync
`models/gpu/` + let first launch build 2 FP16 TRT engines (~1-2 min each, cached).**
ON DEVICE, then: confirm `pose_fps` jumped from ~13, watch `tegrastats`/`free -h`
for the 8 GB ceiling (`HALL_TRT_MAX_WORKSPACE` caps it), and A/B the body-vs-hand
feel the user complained about. Laptop pose is too fast to feel the win — the Jetson
is the real test.

## Update - 2026-07-09 12:20 - [Claude (Opus 4.8)]

### What I did
- **Multi-avatar switcher for the Vtuber.** The rig loaded a hardcoded
  `/avatar.vrm` (CC0 "Sendagaya Shino"). Added a registry of 6 avatars and a
  switcher pill (top-right) + `v` key + `?avatar=N` deep-link that cycles them
  live. The user dropped 5 VRMs in `~/Downloads/vrm/`; copied them into
  `web/public/avatars/` (CoolAlien, CoolBanana, Milk, Agnes, StitchWitch — all
  VRM 0.x humanoid, 52 bones incl. fingers). The rig is model-agnostic (captures
  each model's rest pose on load), so no rigging code changed.
- `VrmAvatar` now takes a `src` prop; App.tsx keys the component on `src` so a
  switch does a clean dispose→reload. Switcher button needs `pointer-events:auto`
  (the `.hud-layer` is `pointer-events:none`; the pinch cursor drives gesture
  buttons, this one is a plain mouse click).
- Small test-ergonomics knob: `MOCK_NO_POINTS=1` pins the mock's points/skeleton
  toggle off so a specific avatar can be screenshotted without waiting out the 4 s
  cycle. Defaults to old behavior when unset.

### Files changed (uncommitted)
- NEW `web/src/gl/avatars.ts` (registry)
- `web/src/gl/VrmAvatar.tsx` (`src` prop + doc), `web/src/App.tsx` (avatarIdx
  state, switcher button, `v` key, `?avatar=N`), `web/src/styles.css`
  (`.avatar-switcher`), `web/scripts/mock_backend.py` (`MOCK_NO_POINTS`)
- NEW `web/public/avatars/*.vrm` (5 files, ~19 MB) + rebuilt `web/dist/`
  (`npm run build`; dist/avatars mirrors it, +~19 MB)

### Verified
`npm run build` clean (tsc + vite). Mock `vtuber` scene + headless shots of all
6 avatars (`?avatar=0..5`): each VRM loads, rigs (arms/hands/fingers follow the
mock pose), switcher pill shows the right name/index, no console errors.

### Important context for the other agent
- **VRMs DO ride the git auto-update** (unlike the gitignored `.onnx` pose
  models): `.vrm` is not in `.gitignore` and `web/dist` is committed, so once
  committed the avatars reach the Jetson by `git pull` — no rsync needed. Cost:
  ~38 MB added to the repo (public+dist). Precedent: the 15 MB Shino is already
  committed. NOT committed yet — flagged the repo-size tradeoff to the user.
- **Presentation-control request (from the user, this session):** they want the
  presentation web page (being built by another agent) to be MediaPipe-driven on
  the Jetson — show the user's skeleton and advance/go-back slides with a pinch.
  Scoped as a follow-up (task #2). If you're the agent building that presentation,
  coordinate here: the cleanest integration reuses THIS app's pinch pipeline
  (`detection/gestures.py` edge-triggered pinch) + pose skeleton rather than
  re-implementing hand tracking in the slide deck.

### Next steps / unfinished work
- User to pick which avatar should be the default (currently Shino / index 0) and
  whether to commit the 5 VRMs (repo-size call).

## Update - 2026-07-09 ~13:40 - [Claude (Opus 4.8)] — avatar switch is now a PINCH button + DEPLOYED

- **User feedback:** the avatar switcher I first shipped was a DOM/mouse pill jammed
  in the top-right CORNER — violates `EDGE_MARGIN_FRAC=0.12` (hand-landmark model
  degrades at the frame edge → pinch fails) AND isn't pinch-operable on the touchless
  kiosk at all. Reworked it into a real gesture button.
- **Now:** `_avatar_btn` in `ui/manager.py` (Python owns it, like `_points_btn`):
  bottom-left, stacked above Points, rect `[86,518,220,50]` at 720p (x=margin, edge-
  safe). Label `Avatar: <name>` updates on press; `_cycle_avatar` advances
  `_avatar_index` mod 6. Rides `to_state().session.avatar_index` (always present now).
  `AVATAR_NAMES` in manager.py MUST stay in sync with `web/src/gl/avatars.ts` order.
- **Frontend:** `App.tsx` now reads `state.session.avatar_index` (mouse pill + `v`
  key REMOVED); `?avatar=N` kept only as a mock fallback. `web/src/state/types.ts`
  session gained `avatar_index?`. Mock (`mock_backend.py` vtuber scene) emits a
  cycling `avatar_index` for testing.
- **Verified:** UIManager unit check (button edge-safe + in state + cycles/wraps),
  `npm run build` clean, headless shot shows the mock's `avatar_index=4` → Agnes
  renders (state-driven), isort clean.
- **DEPLOYED to the Jetson** via `JETSON_HOST=yahboom deploy/hall-app/deploy.sh`
  (rsyncs src + web/dist incl. the 5 VRMs). SSH alias `yahboom`/`jetson-hall` is on
  **PORT 2222** + key `~/.ssh/id_ed25519` (plain `jetson@100.91.206.114:22` times
  out — that cost me a wrong "device offline" call earlier). Restarted the app with
  `systemctl --user restart hallkiosk` (env `XDG_RUNTIME_DIR=/run/user/$(id-u)`;
  a manual `setsid hallrun &` over SSH did NOT persist). Confirmed from the laptop:
  `http://100.91.206.114:8092/` serves the new build, `/state.session.avatar_index`
  present. The laptop watches the Jetson session at that URL over Tailscale.
- Build the pinch-controlled presentation (task #2) once the other agent's slide
  page exists / its shape is known.

## Update - 2026-07-09 13:00 - [Claude (Opus 4.8)]

### What I did — MediaPipe pinch-swipe control for the Slidev presentation
Built the gesture-controlled presentation the user asked for. The target deck is
`../Presentations/internship-update-2/` (Slidev 0.50, "Research Update II" — the
one the slide-content agent is actively editing). Integration is **add-only** (no
`slides.md` edits, so no collision):

- **HalLMediaPipe = the vision backend.** In `HALL_OUTPUT=web` mode it already
  streams pose + hands + pinch over the `/state` SSE. I added a permissive CORS
  header (`Access-Control-Allow-Origin: *`) to `src/output.py`'s `_send`, MJPEG,
  and `/state` responses (and the mock's `/state`) so a cross-origin Slidev page
  can read it. LAN appliance → wildcard is fine.
- **The deck consumes it** via three new files: `components/GestureNav.vue` (SSE
  subscribe → draw translucent full-frame pose skeleton on a body-teleported
  canvas → fire Slidev's click-aware `useNav().next()/prev()`), `components/
  gestureSwipe.ts` (pure swipe detector), `global-bottom.vue` (mounts it once).
  `GESTURE_CONTROL.md` there has the runbook.
- **Gesture (user's pick):** pinch + horizontal flick. Left → next, right → prev
  (`slide-left` transition). One nav per pinch-hold, debounced. **Skeleton:** full
  translucent overlay over the slides.

### Verified
- Swipe detector: 10/10 unit tests (Node type-strip) incl. a regression for the
  bug below.
- End-to-end in headless Chromium (playwright) against a synthetic swipe SSE:
  cross-origin SSE connects, skeleton renders over a REAL slide with text still
  readable, badge goes live, and a left-flick advances the deck FORWARD, click-
  aware, one step per swipe. Screenshot inspected.

### Bug found + fixed (worth knowing)
`GestureNav.vue` built the detector config with `minDx: undefined` when the
`?swipedx` param was absent; the object spread `{...DEFAULT, ...{minDx:undefined}}`
CLOBBERED the default 0.22 with `undefined`, so `Math.abs(dx) < undefined` → NaN →
always false → it fired on every held frame (dx≈0 → "prev"), i.e. the deck ran
BACKWARDS. Fixed at the call site (only set defined keys) AND hardened the
detector's constructor/`setConfig` to skip `undefined` values (`merge()`), so an
absent param can never wipe a default again.

### Files changed (uncommitted)
- HalLMediaPipe repo: `src/output.py` (CORS ×3), `web/scripts/mock_backend.py`
  (CORS on `/state`; also the `MOCK_NO_POINTS` knob from the avatar work).
- Vault repo (NOT the submodule): `../Presentations/internship-update-2/`
  `components/GestureNav.vue`, `components/gestureSwipe.ts`, `global-bottom.vue`,
  `GESTURE_CONTROL.md` (all new; the whole `internship-update-2/` dir is itself
  still untracked — the slide agent hasn't committed it).

### For the slide-content agent
- I did NOT touch `slides.md` or `global-top.vue`. My overlay is in
  `global-bottom.vue` + `components/`. If you add your own `global-bottom.vue`,
  merge — don't overwrite (mount both components).
- The overlay is invisible/no-op unless the HalLMediaPipe backend is running, so
  it won't affect a normal `slidev build`/export.

### Next steps / on-camera tuning (the presenter must do live)
- Confirm the swipe DIRECTION feels right (mirror/chirality) — flip with
  `?swipeinvert=1` if backwards. Tune sensitivity with `?swipedx=` (lower = easier).
- Run backend with `HALL_POSE=1` (skeleton needs body pose, off by default) —
  on the Jetson: `HALL_OUTPUT=web HALL_POSE=1 hallrun`. Only one process can hold
  the C920, so the deck machine reads `/state`, the Jetson holds the camera.

## Update - 2026-07-14 11:23 - [Claude (Fable 5)]

### What I did — GPU-hand edge fix + new "Waves" experiment

**1. Hand inference near the frame edge (the user's complaint) — FIXED in the
GPU backend via ROI tracking** (`detection/gpu_hands.py`, knob
`HALL_HAND_ROI_TRACK`, default on):
- Root cause: v1 ran palm DETECTION on the full frame every call; a palm
  partially out of frame drops below threshold long before the landmark
  model would lose it → the hand vanished/degraded exactly at the border.
- Now a landmarked hand is re-cropped next frame from its OWN landmarks
  (MediaPipe's scheme, via a synthetic palm-detection row —
  `_palm_from_landmarks`); the palm detector only runs to fill empty hand
  slots, with centre-in-bbox dedup so it can't re-add a tracked hand. With
  both slots tracked the palm net is SKIPPED entirely (perf win).
- Verified headless (no camera, per the no-laptop-camera rule) with a
  synthetic edge-pan bench (scratchpad, real hand photo sliding off-frame):
  edge-crossing error 11.2 → **4.7 px**, tracked at 3–6 px until only ~6/21
  landmarks remain visible (baseline lost the hand at 9 visible). In-frame
  cost: ~+1 px (2.5 → 3.5). Two-hands dedup: stable, no duplicates.
- Two REJECTED approaches, measured worse — don't redo them: (a) fixing
  `mp_handpose._cropAndPadFromPalm`'s clip+recentre geometry (the zoo model
  actually prefers the recentred crop: 10.2 vs 4.7 px), (b) padding the
  frame before palm detection (no acquisition gain, slight in-frame bias).
- `uv add --group gpu onnxruntime` so the GPU backend is testable on the
  laptop (`uv run --group gpu`, CPUExecutionProvider); default sync unchanged.
- NOTE: the MediaPipe (CPU) hand backend already does its own ROI tracking
  internally — this brings the GPU path (what the Jetson kiosk runs) to par.

**2. New experiment: "Waves" — interactive ripple tank** (Experiments →
Waves; see IDEAS.md Shipped for the full description):
- `Waves` in `ui/interactables.py` (sources/palette/clock only — Python
  authoritative), `WAVE_*` in `config.py`, picker button in `ui/manager.py`
  (`exp.waves`), state contract: `"waves"` object with `sources[]`, `t`,
  `c`, `time_scale` (`types.ts` + `interp.ts` mirror it).
- Field rendering: WebGL2 ping-pong FDTD (`web/src/gl/WavesLayer.tsx`,
  `waves_step.frag.glsl` + `waves_render.frag.glsl`, RG16F at frame/4,
  needs EXT_color_buffer_float; keep MAX sources 6 in sync with
  `WAVE_MAX_SOURCES`); cv2 fallback = same scheme in numpy (~14 ms/frame at
  720p). 9-point Laplacian on BOTH paths (5-point renders square ripples).
- Verified: Python smoke (state contract, palette, source cap, clear,
  `build_state` JSON ~1.2 KB), `npm run build` clean (tsc included),
  headless shot of mock scene `waves` (new) shows interference fringes +
  Doppler wake, no console errors.

### Files changed (uncommitted)
- `src/detection/gpu_hands.py`, `src/config.py` (ROI tracking + WAVE_*),
  `src/ui/interactables.py`, `src/ui/manager.py`, `src/web/state.py` (none),
  `web/src/{App.tsx, state/types.ts, state/interp.ts, overlay/scene.ts}`,
  `web/src/gl/{WavesLayer.tsx, waves_step.frag.glsl, waves_render.frag.glsl}`,
  `web/scripts/mock_backend.py` (waves scene), `pyproject.toml`+`uv.lock`
  (gpu group), `documentation/architecture.md`, `IDEAS.md`, this file.

### Next steps / unfinished work
- **Deploy to the Jetson NOT done** — the board is OFFLINE (Tailscale last
  saw it 4 days ago, USB link also down; likely powered off). When it's on:
  `JETSON_HOST=yahboom deploy/hall-app/deploy.sh` then
  `ssh yahboom 'systemctl --user restart hallkiosk'` (alias = port 2222).
  No TRT rebuild expected (models unchanged).
- On-camera validation of both features (edge fix feel, wave placement UX).
- `HALL_HAND_ROI_TRACK=0` is the A/B escape hatch if anything regresses.

## Update - 2026-07-15 00:20 - [Claude (Opus 4.8)] — Jetson "vanishing from Tailscale" FIXED + app deployed

### Root cause of the Jetson dropping off Tailscale (was NOT Tailscale)
WiFi **power-save** on the Realtek `rtl8822ce` (vendor out-of-tree driver):
it sleeps the radio when idle → tears down the Tailscale NAT/DERP mapping →
with no inbound traffic to wake it, the node looks offline for days until a
reboot. `iw dev wlP1p1s0 get power_save` reported `on` while NM's property
read `default` (which resolves to on with this driver). Tailscale itself was
healthy the whole time (`WantRunning:true`, service enabled+active).

### Fix shipped — new repo package `deploy/net-watchdog/` (versioned, travels)
- **Power-save OFF, belt-and-suspenders:** NM property `powersave 2` on every
  saved WiFi conn + a NM dispatcher hook `99-hall-wifi-powersave-off` that
  runs `iw ... set power_save off` on every link-up (the driver ignores the
  NM property alone — the hook is the reliable layer).
- **Connectivity watchdog** `/opt/hall-net-watchdog/net-watchdog.sh` on a
  systemd timer (`hall-net-watchdog.timer`, every 2 min + 30s post-boot):
  re-asserts power-save off, 204-probes the internet (probe traffic also
  keeps the radio awake — doubles as keepalive), heals net (nmcli con up →
  restart NetworkManager) and Tailscale (`tailscale up` → restart tailscaled,
  with a poll-before-escalate so transients don't churn the daemon).
- Install from laptop: `JETSON_HOST=yahboom deploy/net-watchdog/deploy.sh`.
  Needs sudo on the box (interactive; installer uses `sudo`). Logs:
  `journalctl -u hall-net-watchdog.service` + `/var/log/hall-net-watchdog.log`
  (file survives reboots; journald is volatile on this image).
- **VERIFIED on-device:** forced `tailscale down` → watchdog detected + healed
  (`tailscale up` → daemon restart → `OK recovered`) in ~5s; power_save stays
  off across reassoc; timer armed + firing.

### App deployed (the pending edge-fix + Waves from the prior update)
- `deploy/hall-app/deploy.sh` (rsync src + web/dist), then
  `systemctl --user restart hallkiosk` (needed so the running Python picks up
  the new backend — the dist is served fresh from disk, but the process was
  the old code). Rebound :8092 in ~12s, no TRT rebuild (models unchanged).
- **VERIFIED on-device** (Jetson system py3.10 + vendor opencv 4.10.0): the
  `exp.waves` picker button is emitted, Waves spawns/updates/serializes, and
  the cv2 fallback `draw()` runs (`cv2.blendLinear` IS present on their build).
  App healthz `ok`, no import traceback.

### Note for next agent
- `deploy/net-watchdog/deploy.sh` uses `ssh -t … sudo`; from a non-interactive
  shell that has no tty, pipe the sudo password to `sudo -S -p ''` instead
  (password is in gitignored SECRETS.local.md, line 5).
- The whole thing is uncommitted along with the prior update's changes.

## Update - 2026-07-15 01:05 - [Claude (Opus 4.8)] — Waves: fixed the divergence + visibility

User report: waves too faint, and "with 5 sources, after a while the screen
saturates". Both fixed; the second was a real bug, not a tuning issue.

### THE BUG: the field diverged to ~1e32 in 5 s (even with ONE source)
The leapfrog update `u_next = (2-d)u - (1-d)u_prev + s^2*lap` assumes a
**CONSTANT dt** — `u_prev` lives at `t - dt`. Both renderers were deriving the
sub-step from the frame's LEFTOVER time (numpy: `dt = min(dt_max, remainder)`,
shader: `dt = advance/n`), so the last step of every frame used a different dt,
the time levels mismatched, and it pumped energy every frame. Measured: max|u|
0.05 → 1706 (1 s) → 4e32 (5 s), then NaN. More sources just start from a higher
amplitude, which is why 5 made it obvious. (Side effect: the NaN/inf field also
made the numpy path ~40% SLOWER — denormal math.)

**Fix:** both paths now bank time and step in whole `WAVE_PHYS_DT` (1/240 s)
chunks, leaving the sub-chunk remainder banked — exactly the fixed-timestep
discipline `Orbitals` already uses with `ORB_PHYS_DT`. Never derive a sub-step
from a frame remainder in a leapfrog. Verified stable: 1/5/6 sources, 60–180 s,
max|u| 0.52/1.19/1.15, all finite, no drift.

### Visibility + readability (measurement-driven)
- Display alpha is now `MAX_ALPHA * tanh(|u| * GAIN)` (`WAVE_DISPLAY_*`,
  mirrored in `waves_render.frag.glsl`) instead of a linear ramp. The field's
  amplitude scales with source count (max|u| ~0.5 at one, ~1.2 at six), so a
  ramp bright enough for one whites out at six; tanh is steep near zero and
  saturates. One curve serves both ends.
- `WAVE_DECAY_TAU_S` 1.6 → 0.9 s. The decay LENGTH is c*tau; at 1.6 s that's
  544 px against a 1280 px frame, so sources washed the whole screen. Swept it:
  at 2 sources, 1.6 → 0.8 s cuts far-field rms 54% while costing the
  interference zone only 15% (contrast 1.2x → 2.2x). 0.9 s keeps reach for
  interference while the far field stays calm.
- **REJECTED — don't redo:** an absorbing "beach" border (sponge layer). It's
  what real ripple tanks use, but measured only ~16% far-field change here,
  because with this damping reflections already return at ~10%. The screen fill
  was direct radiation, not reflections. Reverted; kept the simpler code.

### Verified
Headless (no camera): numpy field bounded 60–180 s at 1/5/6 sources; cv2
fallback 7.6–7.9 ms/frame at 720p; `npm run build` (tsc) clean; isort clean;
web shots via the mock at 2 and 5 sources — 5 sources at 30 s no longer whites
out and the background reads through, 2 sources shows textbook two-slit fringes.
`web/scripts/mock_backend.py waves` gained a `MOCK_WAVE_N=<1..5>` env knob to
reproduce the 5-source case headless.

## Update - 2026-07-15 01:40 - [Claude (Opus 4.8)] — Waves: one source rendered as TWO (vertical mirror) — FIXED

User report: "cada que pongo un origen se mirrorea" — placing ONE source showed
two wave centres. Real bug, WebGL path only.

### Cause: mixed y-origin conventions in the field shader
`waves_step.frag` indexed the field with `ivec2(v_uv * u_sim)`, but a fragment
WRITES to the texel at `gl_FragCoord`. The shared `fullscreen.vert` makes v_uv
**top-left origin** while `gl_FragCoord.y` is **bottom-origin**, so every step
read row 0 and wrote row simH-1 — flipping the field each step and injecting
each source at its MIRRORED row. One source therefore radiated from (x, y) and
(x, H-y). It also doubled the field's energy, which fed the earlier
"everything is washed out" impression.

**Fix (3 places, must stay in agreement):**
1. `waves_step.frag`: index by `gl_FragCoord.xy` (the texel being written) —
   read and write the same cell. It no longer reads v_uv at all.
2. `WavesLayer.tsx`: source y is converted frame(y-down) -> texel(y-up):
   `simH - s.y / GRID_PX`.
3. `waves_render.frag`: samples `vec2(v_uv.x, 1.0 - v_uv.y)` since v_uv is
   top-origin and the texture is now bottom-origin.

The numpy/cv2 fallback never had this (its array rows are y-down throughout);
verified by measurement: energy near the source row is 5.6x the mirror row.

### Verified (headless, mock)
Single source at an asymmetric (460, 400): ONE wave centre, exactly on the
marker, clean circular rings (was: a second centre at y~320, the mirror).
2 sources: two clean centres + real interference. 5 sources at 30 s: five
centres on their markers, no phantoms, background still readable.
NOTE: the "textbook two-slit fringes" in the previous update's 2-source shot
were partly an artifact of the phantom sources — the current pattern is the
physically correct one.

### Deployed
`deploy/hall-app/deploy.sh` + `systemctl --user restart hallkiosk` on yahboom.

### Lesson for any future ping-pong / FDTD shader here
`fullscreen.vert`'s v_uv is TOP-LEFT origin (it exists to match OpenCV pixel
coords for the black hole). Framebuffer writes are BOTTOM-origin. Never mix the
two in a read-modify-write pass — index by gl_FragCoord and convert inputs.

## Update - 2026-07-15 02:20 - [Claude (Opus 4.8)] — new experiment: Charges (electrostatics)

User picked this from a shortlist (I had flagged it as the one most at risk of
feeling like an Orbitals re-skin — so the work went into making it not that).

### Three decisions that keep it distinct from Orbitals
1. **Charges are STATIC** — they do not accelerate each other. Deliberate: an
   inverse-square attraction with no orbital velocity just slams a +/- pair
   together, which IS Orbitals. Real exhibits pin the charges because the FIELD
   is the subject. The user drags them and the field re-solves.
2. **The field is the star**, not the particles: field LINES + EQUIPOTENTIAL
   bands, vs Orbitals' glowing bodies + trails. Completely different visual.
3. **No time integration at all** — V = k*sum(q/r) is analytic, evaluated per
   pixel in ONE stateless shader pass (no ping-pong, no dt, no CFL). Cheapest
   experiment on the GPU, and structurally immune to the dt-divergence and
   framebuffer-orientation bugs that bit Waves.

### Shape
- `Charges` in `ui/interactables.py` owns only the charge list (place / drag /
  palette / Dipole preset / Clear). `CHG_*` in `config.py`. Picker button
  `exp.charges` in `ui/manager.py`. Gesture is identical to Waves (pinch empty
  = place, pinch a charge = drag), so muscle memory carries.
- State: `"charges"` object (k, soften, equipot_step, lines_per_q, charges[]) —
  ~8 charges, tiny. `types.ts` + `interp.ts` mirror it.
- Render: `web/src/gl/charges.frag.glsl` + `ChargesLayer.tsx` (diverging V tint
  + equipotential bands, fwidth-antialiased so bands stay ~1px). Field LINES are
  traced in JS in `overlay/scene.ts` (RK2 streamlines, + -> -), **memoised on a
  charge-position signature** — tracing is ~1M ops/frame worst case (8 x 2q) and
  the lines only change when a charge moves, so a static scene costs nothing.
  cv2 fallback does both in numpy (~12 ms/frame at 720p).

### Verified (headless, no camera)
Physics: inverse-square ratio |E(100)|/|E(200)| = **3.91** — and that is not
error, it's exactly what the 14 px softening predicts ((40196/10196)^1.5*0.5 =
3.914). Dipole midpoint E points + -> -. Two like charges give an **exact** null
point (0.00e+00 vs 2.12e+01 off-centre). Line density: q -> 12 lines, 2q -> 24.
Contract/palette/cap/clear all asserted. `npm run build` (tsc) + isort clean.
Web shot via the new `mock_backend.py charges` scene. **Deployed + verified
on-device** (Jetson py3.10 + vendor opencv): dipole E=(6.2, 0.0), 12 lines,
state count=2, no import errors.

## Update - 2026-07-15 03:55 - [Claude (Opus 4.8)] — kiosk lockdown: no notifications + always on top

User: "hace q no aparezca notificacion de ningun tipo, q siempre el hallmediapipe
este encima de todo".

### New: `deploy/hall-app/kiosk-lockdown.sh` (run once, `sudo`, idempotent)
Silences every popup source that was actually LIVE on the board (I checked
rather than guessed):
- GNOME banners `show-banners=true` -> false. NOTE: the per-plugin
  `org.gnome.settings-daemon.plugins.*.active` keys were REMOVED in GNOME 42
  (they read `n/a` here), so the global `show-banners` is the only lever —
  don't waste time trying to disable gsd-housekeeping/print-notifications
  individually.
- **apport was `enabled=1`** -> 0 + service disabled (crash dialogs could cover
  the exhibit).
- update-notifier `no-show-notifications` -> true; update-notifier +
  gnome-software autostart masked via `~/.config/autostart` Hidden=true.
- **`idle-dim` was true** -> false (the screen was dimming itself on idle).
  idle-delay 0 / lock disabled were already fine.
- Strict `/etc/firefox/policies/policies.json`: blocks Notifications/Location
  permission prompts, WhatsNew/onboarding/recommendation messaging, Pocket,
  download prompts. (Kept the existing keys, added to them.)
- Installs `wmctrl` (available in the standard jammy arm64 repo; 1 package).

### Always on top — in `hallkiosk` (it owns the browser lifecycle)
`--kiosk` is fullscreen but NOT above. Now the browser window gets
`_NET_WM_STATE_ABOVE` + fullscreen, with a 3 s loop that re-asserts it and
re-activates ONLY when something else holds focus (so it can't flicker/fight).
Session is **X11** (`WaylandEnable=false` in /etc/gdm3/custom.conf) so wmctrl
works; on Wayland it's a silent no-op and the kiosk still runs fullscreen.

### Verified on-device (not just "the script ran")
`_NET_WM_STATE = FULLSCREEN, ABOVE, FOCUSED` on the real window; launched
gnome-calculator as an intruder and read `_NET_CLIENT_LIST_STACKING` — firefox
stayed TOPMOST and kept focus. That test also surfaced a **stale
`update-manager` window already open** on the desktop (very likely part of what
the user was seeing) — killed it; only the kiosk + GNOME's own `gjs` layer
remain.

### ⚠ DEPLOY-PATH GOTCHA (cost me a wrong assumption; fix or remember)
`hallkiosk.service` runs `~/HalLMediaPipe/deploy/hall-app/hallkiosk` (the git
checkout copy), but `deploy/hall-app/deploy.sh` only `scp`s the launcher to the
REPO ROOT `~/HalLMediaPipe/hallkiosk` (which is what `~/.local/bin/hallkiosk`
symlinks to). So a launcher change deployed via deploy.sh takes effect for a
MANUAL `hallkiosk` run but NOT for the systemd service. I scp'd to both paths
for now. Proper fix: either point the unit at the root copy, or have deploy.sh
also write deploy/hall-app/ — or just commit+push (see below), which is the
intended path.

### ⚠⚠ EVERYTHING THIS SESSION IS UNCOMMITTED — and `hall-update.sh` will WIPE it
The Jetson's `~/HalLMediaPipe` IS a git checkout and `hall-update.timer` fires
`hall-update.sh` every 60 s, which does `git fetch origin main` and, **when
origin/main has a new commit**, `git reset --hard origin/main`. It has not
fired only because nothing has been pushed. The moment ANYONE pushes to main,
the checkout hard-resets and every rsync'd uncommitted change on the device
(GPU-hand ROI tracking, Waves + its two fixes, Charges, the hallkiosk
always-on-top) is ERASED, reverting the exhibit to c8e65a1. The rsync deploys
used all session are a dev shortcut; the intended flow is commit+push -> the
device pulls within 60 s (web/dist is committed, so no build runs on-device).
**Recommend committing + pushing the session's work.**

## Update - 2026-07-15 12:20 - [Claude (Opus 4.8)] — Charges: animated flow arrows

User: "me gustaria q las lineas fueran animadas como flechitas saliendo o
entrando, conservando la misma logica de las lineas, y obvio en algunos lados
se cancelan".

- Arrowheads now march along the SAME traced polylines — the tracing logic is
  untouched, as asked. Direction follows the field (out of +, into -); the
  negatives-only fallback traces against E, so `_field_lines` now also returns
  `dir` and the arrows flip with it.
- **Cancellation is emergent, not special-cased:** each arrow's size + opacity
  is `tanh(|E|_local / CHG_ARROW_E_REF)`. At the null point between like
  charges |E| is exactly 0 (measured 0.00e+00), so those arrows shrink to
  nothing by themselves; the far field fades too, which keeps the picture
  clean. |E| per vertex is recorded during tracing — free, the tracer already
  computed it — and cached with the lines.
- O(1) arrow placement: the tracer steps a FIXED CHG_LINE_STEP_PX, so arc
  length is exactly `index * step` and the vertex under an arrow is a divide,
  not a search. Cost stays ~2x the stroke, and the line memo is unchanged.
- The flow runs on the RENDERER's own clock (browser `performance.now()`, cv2
  `time.monotonic()`): it is pure decoration over a static field, so nothing
  was added to the state contract. Python stays authoritative for logic only.
- Also fixed a wart in my own earlier Charges code: the cv2 fallback's
  equipotential bands used a hard threshold at grid resolution and rendered as
  chunky slabs. Now normalised by the local gradient (the numpy equivalent of
  the shader's fwidth), so a band stays ~1 cell wide — the dipole's V=0
  bisector is a crisp line instead of a slab. Fallback also got faster:
  12.4 -> 7.3 ms/frame at 720p.

### Verified
Animation proven by DIFFING two frames, not by eyeballing: web shots 0.7 s
apart show 13.3% of pixels changed in the box around the mock's STATIC +q — a
charge that cannot move, so only the arrow flow can account for it. cv2 same
test, isolated to `Charges.draw` (drawing the whole UI contaminated it at 51%
— the intro/hint overlays animate too): 0.87% changed over 0.7 s vs 0.128%
with no time gap, confirming the tint is static and only the arrows move.
Line density still encodes |q| (q -> 12 lines, 2q -> 24); dipole E unchanged.

## 2026-07-15 — Spacetime experiment (relativistic gravity)

New experiment, sixth in the picker: a rubber sheet that bends under placed
masses, with orbits that precess. Files: `ST_*` block in `config.py`,
`Spacetime`/`_Mass`/`_Orbiter`/`_flamm_depth` in `ui/interactables.py`, picker
wiring in `ui/manager.py`, `SpacetimeObject` in `web/src/state/types.ts`,
renderer + `drawBackdrop` in `web/src/overlay/scene.ts`, interp case in
`state/interp.ts`, `spacetime` scene in `mock_backend.py`. `web/dist` rebuilt.

### Design decisions worth not re-litigating
- ONE geometry drives both halves: `rs = ST_RS_PER_MASS * m` sets the sheet's
  throat AND the orbit potential's pole, so the picture and the physics are the
  same spacetime. That also fixes `c` in screen units — hence no `c` knob.
- SHEET = Flamm's paraboloid (exact Schwarzschild equatorial embedding),
  measured down from `ST_CURV_REACH_PX` so wells are local + finite. Summing
  them is NOT a GR solution (nonlinear); it is the standard visual
  approximation and is exact for one mass. Documented, not accidental.
- ORBITS = Paczynski-Wiita `a = -GM/(r-rs)^2`. Moving the pole to the horizon
  is what buys precession + an ISCO at 3*rs. This is what makes the experiment
  relativistic rather than a sagging mesh. Masses are STATIC (Charges' call).
- DISPLAY-only geometry is kept strictly out of the physics: `ST_DEPTH_GAIN`
  and the `ST_MAX_DEPTH_PX` tanh clamp shape the sheet; `_accel` never calls
  `_depth`. The clamp is not cosmetic fussiness — dz/dr -> inf at the throat,
  so a to-scale compact hole (~310 px deep on a 720 px frame) projects to a
  tangle of near-parallel lines. tanh leaves shallow wells untouched (same
  trick as `WAVE_DISPLAY_GAIN`).
- TWO-HAND gesture is new to this codebase: two simultaneous pinches drive the
  camera and SUPERSEDE place/drag (touchscreen convention). Hence placement
  commits on RELEASE, not on the pinch edge — otherwise a mass appears while
  the user is still reaching for the second pinch. Hands that rotated stay
  inert until they re-pinch. Reuse this if another scene needs two hands.
- Grid is stroked ONE polyline per line (~48 draw calls/frame), not per
  segment (~3500) — deliberate, for the Jetson kiosk. Fog uses a per-line mean
  depth; the well reads from the geometry, not from per-segment shading.
- `ST_GRID_MARGIN = 1.7` is sized for the YAWED case: at 1.25 a ~70 deg yaw
  swung the finite sheet's corner into frame and left a bare triangle.

### Verified (no camera — mock_backend + shot.mjs, per the usual loop)
- Physics: preset spawns at r/rs = 22.2, periapsis 60 px vs ISCO 27 px (stable,
  no plunge); precession measured at 47/47/48/47/47 deg per lap over 6 laps —
  constant, i.e. a genuine apsidal walk, not drift.
- Gestures (stubbed pinch machines): placement waits for release; a second
  pinch promotes to rotate AND cancels the pending placement (mass count stays
  0 through release); midpoint +100 px -> yaw +0.600 rad exactly; span 200->400
  -> zoom 1.0->2.0; pitch clamps at 89 deg under a 60-cycle hammer.
- INFERENCE ISOLATION (the explicit ask): replayed main.py's ordering —
  `toMpImage(frame)` then `Spacetime.draw(frame)` — and asserted the model's
  buffer is byte-identical afterwards (True) while the display frame's mean
  drops 185.3 -> 106.9. Safe because `toMpImage` cvtColors into a NEW array, so
  the async detector never aliases the frame we draw on. Web mode is moot
  (backend draws nothing; `drawBackdrop` dims the browser canvas only, and runs
  before `drawSkeleton` so it darkens the video and not the UI).
- Caught two missing imports (`pinch_infos`, `ST_ROT_*_GAIN`) only because the
  gesture test actually ran the code path — the experiment would have thrown on
  open. Worth a smoke test on any new scene.

### Open / next
- `documentation/modules/interactables.md` now documents Spacetime, but
  Orbitals/Waves/Charges are still undocumented there (pre-existing drift).
- Not yet run on the Jetson. Grid cost is ~3.5k projected points/frame in JS;
  expected fine, but the `?glscale` escape hatch does NOT apply (Canvas2D, not
  a GL layer) — if it bites, drop `ST_LINE_SAMPLES` or the grid counts.

## 2026-07-15 (later) — Spacetime round 2: Kerr spin, 3D lattice, real camera

Feedback was: the 3D control felt "crude/green", the top-down view was
UNREACHABLE, no rotation on the bodies, and space should deform in 3D (user
sent a volumetric-lattice reference) not just as a 2D sheet.

### Camera: v1's incremental drag was structurally wrong, not just badly tuned
Reproduced the top-view bug before touching it: the pitch clamp was NOT the
cause (240 px of travel reaches 89 deg fine). The real cause is that 240 px of
sustained two-pinch travel ENDS near the frame border — exactly where
`manager.EDGE_MARGIN_FRAC` already documents the landmark model degrading. The
pinch drops, the gesture dies half-way. Incremental also has no home: returning
your hands never returned the view, which is the "crude" feel.
Researched rather than guessed (user asked): Zhai & Milgram's 6-DOF taxonomy
says isotonic->position and isometric->rate are the good pairings — a hand is
ISOTONIC, so pure rate control (my first instinct) is a known-bad pairing.
Casiez et al.'s RubberEdge fits exactly: position control inside a disc around
the grab origin, rate control outside it (~20% better than position control
when clutching is significant). Implemented as `Spacetime._rotate`. Pitch cap
raised 89 -> 90 (the projection has no singularity there; the old cap was
timidity). Zoom got a deadzone so yawing can't smuggle in a zoom.
DO NOT "simplify" this back to an incremental drag.

### 3D view = volumetric lattice (the reference), 2D = the old sheet
Toggled by the `st.view` button. The lattice's radial map is Schwarzschild's
ISOTROPIC coordinate relation (`_isotropic_radius`, horizon lands at rs/4), not
an art-directed pull — space gets denser near a mass because distances there
are stretched. This is the honest picture; the sheet is the famous one that
quietly lies (people read "ball rolls downhill" = gravity explaining gravity).
CAVEAT worth knowing: the honest map is TINY — it saturates at rs/2, ~18 px on
a 720 px frame — so it needs `ST_LATTICE_GAIN` (7.0) to read at all, the same
display-only bargain `ST_DEPTH_GAIN` already makes. First render without it was
a uniform hairball; that was the fix.

### Spin: full Kerr, and it cost nothing in regression
PW is Schwarzschild-only, so the force is now Mukhopadhyay (2002)'s Kerr
pseudo-Newtonian potential. Two properties made this an easy call:
  * it collapses to PW at a = 0 to MACHINE PRECISION (measured 3e-16), so a
    spinless scene is bit-identical to before — the 47 deg/lap precession is
    unchanged (re-measured: 47/47/48/47/47).
  * it is constructed to give the exact Kerr ISCO — measured 0.0% error at
    every spin from -0.998 to +0.998.
Spin is signed by the particle's own angular momentum (tanh-blended so a
near-radial plunge doesn't chatter between branches), so the DIRECTIONAL ISCO
falls out: 1.24 r_g prograde / 6.00 static / 8.99 retrograde.
Velocity-Verlet now evaluates `a` at the HALF-STEP velocity — the force reads v,
which makes textbook VV implicit. Fine here because v only enters a saturating
tanh.
Also: `r_horizon` shrinks rs -> rs/2 with spin while the equatorial ergosphere
stays at rs, so the GAP between the two rings IS the spin, and closes by itself
at a* = 0 — no special case. Capture now uses r_horizon, not rs.
Frame dragging appears twice: in the physics (signed spin) and visually
(`_drag_frame`, Lense-Thirring omega = 2GJ/(c^2 r^3), a tight 1/r^3 swirl).

### Verified
- Kerr(a=0) vs PW: 3.01e-16 worst relative error. Precession re-measured
  unchanged at 47/47/48/47/47 deg/lap.
- ISCO vs the exact Kerr formula: 0.0% at a = 0, +-0.3, +-0.5, 0.7, +-0.9,
  +-0.998. (Two of my own test harnesses were buggy first — the ISCO search ran
  BELOW the potential's pole, and the pole finder assumed one sign change when
  sqrt(x)(x-2)+a has two. The model was right both times; check the harness
  before the physics.)
- Frame dragging is VISIBLE: same radius (120 px), same speed, only direction
  differs — a*=0 gives +17.0 vs -17.0 laps (perfect mirror symmetry, as
  Schwarzschild demands); a*=0.9 gives 14.6 laps prograde vs a PLUNGE in 0.15
  laps retrograde (retrograde ISCO 157 px > the 120 px launch, so it must).
- Camera: 200 px push held 3 s -> pitch 90 deg with hands never leaving the
  safe region (top view now reachable); nudge-and-return lands back within
  0.1 deg (v1 could not); no wind-up overshoot after a 10 s absurd push; zoom
  deadzone ignores 5% span drift but still zooms at 80%.
- `_place_mass` was dropping the preset's spin on the floor (every body came
  out a* = 0) — caught only because the state test printed the ergosphere gap.

### Open
- Still not run on the Jetson. The lattice is ~5x the sheet's line work; if the
  kiosk drags, drop ST_LATTICE_LAYERS / ST_LATTICE_SAMPLES or set
  ST_LATTICE_VERTICALS = 0 (Canvas2D, so `?glscale` does NOT apply).
- Light-cone / Penrose causal-structure experiment is now in IDEAS.md "Next up"
  as a SIBLING experiment, with the EF-vs-Penrose call written up.

### 2026-07-15 hotfix — Spacetime shipped BROKEN, and why the tests missed it
`ST_LATTICE_GAIN` / `ST_LATTICE_VERT_STRIDE` were used in `_lattice_offset` and
`to_state()` but never imported: an in-place `sed` patch to the import block
silently no-op'd because isort had already reflowed it, and nothing re-checked.
Caught only by running the real code on the Jetson AFTER pushing. Impact would
have been severe, not cosmetic: in web mode `to_state()` runs every frame inside
`main.py`'s resilient try/except, so a NameError there does not crash the
process — it stops the state publish AND `sink.present`, freezing the kiosk for
anyone who opened Spacetime, with no working Reset to escape (the buttons come
from the state that is no longer being published).

The miss: the pre-push check called `update()` and NOTHING ELSE. Importing the
module proves the class body parses; it does not prove `to_state()` or `draw()`
run, and the bug lived in exactly the entry points that were never called.

Added `tests/smoke_scenes.py` (plain python, no pytest — so it also runs on the
Jetson's 3.10): every scene through update/to_state/draw + JSON-encodability,
including Spacetime in BOTH view modes. Run it before any scene change:

    uv run python tests/smoke_scenes.py
    ssh jetson@100.91.206.114 'cd ~/HalLMediaPipe && python3 tests/smoke_scenes.py'

Verified 9/9 locally AND on the Jetson's Python 3.10 (dry-run: scp'd the fix in,
ran, restored, THEN pushed — verify on the target before shipping, not after).

### 2026-07-15 (round 3) — the physics was wrong, and the camera had a needless cap

Two user-reported problems, both real, both mine.

**1. Every star was secretly a black hole.** I treated masses as POINT masses, so
each got a full Flamm funnel down to its own rs. Real bodies have a SURFACE:
outside it Flamm's paraboloid, inside it the interior Schwarzschild solution,
which embeds as a SPHERICAL CAP of radius A = sqrt(R^3/rs) — a smooth bowl with
NO throat — joining the paraboloid with a common tangent at R
([Schwarzschild 1916b], [MTW 1973 Box 23.2]; verified numerically: both slopes
= sqrt(rs/(R-rs)) to 6 dp). A hole has no surface, so its funnel runs to the
horizon where dz/dr diverges and the sheet goes VERTICAL. That cliff — not
depth — is what "black holes deform space much more" means. Worth being precise:
Flamm depth ~ sqrt(M), so 4x mass is only 2x deeper, and by BIRKHOFF a 1 Msun
star and a 1 Msun hole are geometrically IDENTICAL outside the star's surface.
Compactness is the entire story.
Also REMOVED the two things hiding it: ST_DEPTH_GAIN is now 1.0 (to scale) and
the ST_MAX_DEPTH_PX tanh ceiling is gone. That ceiling was squashing a hole to
189 px against a star's 82 px — a 2.3x difference standing in for bowl-vs-abyss.
Its stated job (taming the "tangle" at the throat) was wrong-headed: the tangle
is a vertical cliff rendered correctly, and now only holes have one.
Palette is the canonical trio from the user's reference figure: Sun (R/rs = 20,
STAGED — real is 2.4e5, at which the sheet is flat and true and useless),
Neutron star (R/rs = 2.9, REAL), Hole (R/rs = 1). Measured depths 69 / 126 /
247 px = 1 : 1.8 : 3.6, matching the figure's ordering.

**2. The pitch cap was pointless.** User wants to orbit freely — 180 deg, under
the sheet, anywhere. Pitch is now UNCLAMPED and accumulates like yaw (do NOT
wrap it: the easing and state/interp.ts lerp both rely on continuity). The
projection has no singularity at 90 or anywhere else; crossing over the top just
shows the well's underside. Added a "Top" button that snaps to the exact XY
view, because an exhibit visitor should not have to earn the one view everyone
asks for by holding a two-hand push. It snaps to the NEAREST 90 deg + 2*pi*n, or
a wound-up camera would spin for seconds getting there.

### Verified
- Tangency: interior slope == exterior slope == sqrt(rs/(R-rs)) to 6 dp for both
  Sun and Neutron. No crease in the sheet.
- Throat: slope at the body's own surface = 0.23 (Sun, cap) / 0.73 (Neutron,
  cap) / 157 (Hole, cliff).
- Mukhopadhyay still collapses to PW at a=0 (<1e-12), so the 47 deg/lap
  precession is untouched by all of this.
- tests/smoke_scenes.py now ASSERTS the tangency, the depth ordering
  (hole > 3x sun), the PW limit, and that no pitch clamp has crept back. 9/9.

## 2026-07-15 (round 4) — post-Newtonian dynamics + the radiated wave

Two asks: make everything interact accurately, and show how SPACE REACTS.

### "Just use numerical relativity" is not on the table — say so with numbers
NR = integrating Einstein's field equations on a 3D grid (BSSN/Z4c, moving
punctures, AMR). A 2025 BNS merger covering 1.5 SECONDS cost 130 MILLION
CPU-hours on Fugaku across 20k-80k cores. This board has 6 cores and needs
30 fps: ~9 orders of magnitude. Nothing crosses that, and it is not Python's
fault. Do not accept a task framed as "port NR to the Jetson".

### What replaced the pseudo-potential: EIH 1PN
The pairwise test-particle pseudo-potential had NO validity for comparable
masses. Now the N-body dynamics are the Einstein-Infeld-Hoffmann 1PN equations
[EIH 1938; Will 1993 eq 6.80] — the same framework JPL's DE440 uses to place
the planets. Includes the many-body terms where every OTHER mass modifies the
i-j interaction: gravity gravitates, which is what makes it GR and not a
two-body patch. Implicit in a_j, so seeded with Newton and iterated
(ST_PN_ITERS = 2).
VALIDATED against the exact GR perihelion precession dphi = 6 pi GM/(c^2 a
(1-e^2)) — the Mercury formula: 2.1% error at v/c = 0.091, and the error grows
as (v/c)^2 exactly as a 1PN truncation must. It converges to GR.

### The regime change that MAKES that claim true (most important line here)
ST_RS_PER_MASS 9.0 -> 2.5. At 9.0 orbits sat ~5 rs out at v/c ~ 0.47, where
the PN series does not converge and the numbers were decoration. At 2.5 orbits
are 20-40 rs out at v/c ~ 0.11-0.16 and 1PN is good to a couple of percent.
The visuals barely pay: depth ~ sqrt(rs) (40% shallower, still hundreds of px),
precession ~ rs/a (~20 deg/lap, still unmistakable). What shrinks is the horizon
disk, which BUYS room for orbits. If anyone retunes rs, re-check v/c.

### Momentum was silently broken and it was subtle
Feeding each body the OTHER's rs (the obvious first cut) breaks Newton's third
law: the pseudo-potential's pole sits at the source's horizon, so F_ij != -F_ji
and total momentum walked ~10%. Fixed by evaluating the pair force in the PAIR's
geometry (rs_i + rs_j, exact since rs is linear in mass). Now 1.5e-7 over 4000
sub-steps. (Superseded by EIH for the main force, but _pair_force still backs
_orbit_velocity.)

### Space reacts: the radiated wave
h_ij^TT = (2G/(c^4 D)) Qddot_ij(t - D/c) — retarded quadrupole, the SAME formula
that sets the energy loss, so the wave and the inspiral are consistent by
construction. Qddot in closed form (Iddot = SUM m (2 v_i v_j + x_i a_j + a_i
x_j)) about the COM, so no numerical differentiation. Only the newest sample
crosses the wire; the browser accumulates history and does its own retarded
lookup (the trails trick) — the retarded window is only ~0.65 s.
VERIFIED: 1/D falloff exact (h*D = 0.1918/0.1919/0.1920 at three distances —
4 significant figures); speed from the arrival-time slope 2000 vs c = 1833 px/s
(one frame of quantisation); quadrupolar lobes vary with angle; h_x = 0 in-plane
(linear polarisation) falls out of the geometry rather than being imposed, which
is why the wave correctly renders as a HEIGHT ripple and not an in-plane wobble.

### The honest number, which IS the lesson
Real strain here is h ~ 5e-4: a 400 px grid line changes length by 0.04 px.
Invisible. ST_GW_STRAIN_GAIN = 4e4 buys the picture (~19 px ripple). LIGO
measures h ~ 1e-21 — 1e17x smaller than ours; hence a century and a Nobel.
(First tried 6e5 and got a 288 px ripple pinned to the cap. Measure, don't
guess — same lesson as ST_GW_GAIN, where I assumed 4e4 was needed to speed up
inspirals and it actually just blew up the integrator: at v/c ~ 0.4 Peters
already merges things in ~1 s of sim time. Both were wrong by orders of
magnitude in OPPOSITE directions.)

### Still approximate, on purpose and on the record
- Radiation reaction is Peters orbit-averaged (2.5PN order) bolted onto
  conservative EIH — a standard hybrid, but a hybrid.
- Peters' P uses the CIRCULAR formula at the instantaneous separation.
- 1PN truncation: honest to ~2% at v/c ~ 0.09, degrading as (v/c)^2.
  ST_PN_VC_WARN = 0.3 marks where it should stop being believed.

### Open
- Bodies now render small (the rs rescale). User wants them drawn BIGGER while
  keeping real properties — the clean way is to split the RENDER radius from
  the physical r_body that feeds the cap/well geometry. Not done yet.

## Update - 2026-07-16 - [Claude (Fable 5)] — Spacetime: off-screen masses now vanish + accuracy audit

User asked for two things: audit Spacetime's physics accuracy (analysis), and
make bodies DISAPPEAR once they leave the renderable screen space (implemented).

### Implemented: `_prune()` now drops masses, not only orbiters
Since round 4 everything gravitates, so a close encounter / merger recoil can
sling a mass off-screen — and it kept pulling the scene from beyond the sheet
with no visible cause, forever. `Spacetime._prune` now removes masses past
`ST_PRUNE_MARGIN` (1.8x frame extent — just past the drawn sheet at 1.7 and the
widest zoom 0.55 ~ 1.82x, so a body vanishes only when no camera setting could
still show it). The grabbed mass is exempt (the hand pins it on-screen).
No state-contract change; no web/dist rebuild needed (the browser derives masses
from the payload each frame, and interp.ts already tolerates vanishing ids).
Verified: smoke check #8 (prune + grabbed exemption) AND an end-to-end run
through `update()` — an ejected sun at 3000 px/s vanishes at the margin, the
remaining hole survives, to_state()/draw() stay healthy incl. the empty scene.
`tests/smoke_scenes.py` 9/9. isort clean (the one pre-existing failure is
`_zoo/mp_persondet.py`, untouched vendored code).

### Audit — verified correct (leave alone)
- `_embed_height` (Flamm + interior cap + common tangent), `_isotropic_radius`,
  `_eih_accel` checked term-by-term against Will 1993 eq. 6.80 — all exact.
- `gw_strain` prefactor G/(c^4 D) is RIGHT (it's 2G/c^4D times the TT
  projector's 1/2). scene.ts:165 using `ixy` where Python uses `qxy` is fine —
  they are equal off-diagonal. TS mirrors (waveHeight/sheetDepth/dragFrame/
  latticeOffset/project) all match Python.

### Audit — real findings (reported to user, NOT changed except docs)
1. **The Kerr sector is no longer in the live dynamics.** `Spacetime._accel`
   (Mukhopadhyay force, signed spin, directional ISCO) is DEAD CODE since the
   EIH round; `_pair_force` (Kerr) survives only inside `_orbit_velocity`
   (spawn speeds). EIH 1PN has no spin terms, so spin currently affects ONLY
   r_horizon (capture), the ergosphere ring, the visual twist and the marker
   phase — not the orbits. Config's long Kerr note + module doc claimed
   otherwise; I updated the class docstring and interactables.md (also removed
   the stale "masses are STATIC" and "ST_MAX_DEPTH_PX" claims). Open decision:
   delete `_accel`, or put spin back via 1.5PN spin-orbit terms.
2. **Wave clock vs physics clock**: `_sim_t += time_scale*dt_real` but the
   integrator banks `time_scale*ST_FRAME_DT` per frame. Equal only at 30 fps;
   at any other rate the retarded lookup samples a skewed history (wave speed
   != c on screen). One-line fix: advance `_sim_t` by `time_scale*ST_FRAME_DT`.
3. **`_step` docstring says "half-step velocity"; code evaluates the new accel
   at the OLD velocity** (no half-kick before `_accelerate()`). Small effect
   (velocity terms are 1PN-suppressed) but claim != code; either switch to
   real KDK or fix the docstring.
4. **Merger + GW mass loss inflates remnant speed ~5%**: p computed with old
   masses then divided by 0.95*m_tot. Physical: remnant keeps COM velocity
   (v = p/m_before); the radiated momentum leaves with the waves.
5. **`ST_PN_VC_WARN` is unimplemented** — config promises "the HUD says so"
   above v/c 0.3; nothing reads the constant anywhere.
6. **COM drift**: placements don't balance momentum, so e.g. the Precess
   preset drifts ~2-3 px/s and would now self-clean via the prune after ~10
   min idle. Possible improvement: subtract COM velocity on placement.
7. Micro: `_view_anim` is write-only state; `_drag_frame`'s "px factors cancel
   to a dimensionless angle" comment is false (the quantity is omega/c, 1/px —
   harmless, display-only); `omega_horizon` carries a redundant m_geom/m_geom.

### Files changed (uncommitted)
- `src/ui/interactables.py` (`_prune` + class docstring), `src/config.py`
  (ST_PRUNE_MARGIN comment), `tests/smoke_scenes.py` (check #8),
  `documentation/modules/interactables.md` (stale claims fixed, prune noted).

### Next steps
- User to commit+push when happy (push deploys to the Jetson kiosk in ~60 s).
- Findings 1-6 above are approved-analysis-only; pick any to implement next.

## Update - 2026-07-16 - [Claude (Fable 5)]

### What I did
- **Renamed the "Vtuber" spawn button to "Rigged Model"** (user TODO from
  `Logs/research/2026-07-15.md`, now checked off): display label only —
  `src/ui/manager.py` (`label="Rigged Model"`, `font_scale=0.6` so the longer
  text fits the same 150 px button; measured 127 px) and the matching mock in
  `web/scripts/mock_backend.py`. All internal ids and the web contract are
  UNCHANGED (`spawn.vtuber`, object type `"vtuber"`, `HALL_START_VTUBER`),
  so nothing under `web/src/` changed and **no `web/dist` rebuild is needed**
  (the frontend renders `btn.label` straight from the state).
- **Logged two new experiment concepts in `IDEAS.md` → Next up** (from the
  user's 07-15 research log):
  1. *Time dilation — moving clocks tick slower*: velocity-based proper time
     (`dτ = dt·√(1−v²/c²)`) with c lowered to exhibit scale; slingshot-style
     launch, per-ship clock faces vs a lab clock, twin preset, muon decay
     bonus.
  2. *Inside the singularity — a hypothesis gallery*: pinch hypothesis cards
     (classical GR / Planck star / fuzzball / gravastar / regular BH / baby
     universe) that morph the interior depth-profile of the embedding sheet;
     exterior stays fixed (Birkhoff) as the punchline.
- Added a dated rename note to the shipped Vtuber entry in `IDEAS.md`.

### Files changed (uncommitted)
- `src/ui/manager.py`, `web/scripts/mock_backend.py`, `IDEAS.md`,
  `../Logs/research/2026-07-15.md` (vault, TODO checked off)

### Verification
- Headless button render (Sphere / Rigged Model / 6 7 Counter row, idle +
  hovered) inspected — label fits. `compileall` + `python -m isort --check`
  clean on the touched files. No camera run (per user rule).

### Next steps / unfinished work
- Both new IDEAS entries are concept-only — nothing built yet.
- Remember: pushing to `main` deploys to the Jetson kiosk in ~60 s; the
  label change is safe to ship (no contract change).

## Update - 2026-07-16 (later) - [Claude (Fable 5)]

### What I did
- **Dropped the two IDEAS entries added earlier today** (time dilation +
  singularity hypothesis gallery) at the user's request — they judged both
  too hard to turn into honest interactive simulations. Removed from
  `IDEAS.md` (the dated "Rigged Model" rename note in the Shipped section
  stays). Don't re-add them without asking.

### Files changed
- `IDEAS.md`

## Update - 2026-07-16 (evening) - [Claude (Fable 5)]

### What I did
- **NEW experiment: Schrodinger's cat** ("Quantum Cat" in the picker, user
  request). `SchrodingerCat` in `ui/interactables.py` + `SCAT_*` in
  `config.py`: a four-phase pinch-driven measurement game — grab the cat
  into the box (owner-latch grab, lid closes) → pinch-pull-release the
  emitter to fire a quantum particle at the box's detector (slingshot
  semantics; misses re-fire) → box shows BOTH cats ghost-overlapped
  (|alive> + |dead>, counter-phase breathing) → pinch the box to look:
  fair-coin collapse + persistent alive/dead tally (converges to 50/50
  across runs). Dice roll on the OPEN pinch, not the detector hit.
- Full web contract: `to_state()` ships ALL geometry (first scene with zero
  hand-mirrored constants), `SchrodingerObject` in `types.ts`,
  `drawSchrodinger` + vector cat in `overlay/scene.ts`, cv2 fallback in the
  class, `schrodinger` scene in `mock_backend.py`, **`web/dist` rebuilt**.
- Extended `tests/smoke_scenes.py`: scene added to the surface sweep +
  `check_schrodinger_logic()` (drop-in-box / twitch / miss+refire /
  detector hit / both collapse branches / tally / all phases
  serialize+draw). 10/10 scenes ok.
- IDEAS.md: cat moved to Shipped; new "Where is the electron? — position
  uncertainty" concept logged in Next up (user wants it as an idea only for
  now).
- Docs synced: `documentation/modules/interactables.md` (new section),
  `CLAUDE.md` scene list.

### Verification
- Smoke suite 10/10 (includes the new logic walk); browser verified with
  `mock_backend.py schrodinger` + 5 timed `shot.mjs` screenshots (place /
  aim / particle / superposed / revealed) — all phases render; cv2 fallback
  rendered to PNG and inspected (3 phases). No camera used (user rule).
- Note: `isort` also re-sorted `detection/_zoo/mp_persondet.py` (1-line
  import hunk, unrelated file — same isort behavior as past sessions).

### Files changed (uncommitted)
- `src/ui/interactables.py`, `src/ui/manager.py`, `src/config.py`,
  `tests/smoke_scenes.py`, `web/src/state/types.ts`,
  `web/src/overlay/scene.ts`, `web/scripts/mock_backend.py`, `web/dist/*`,
  `IDEAS.md`, `CLAUDE.md`, `documentation/modules/interactables.md`,
  `src/detection/_zoo/mp_persondet.py` (isort only)

### Next steps / unfinished work
- Live playtest on camera: pinch reach for the box (it sits centre-right),
  emitter grab radius, and whether the 24 s of captions read well at kiosk
  distance.
- The electron-position idea is concept-only in IDEAS.md — do not build
  without the user's go.

## Update - 2026-07-16 (night) - [Claude (Fable 5)]

### What I did (user feedback on the shipped cat)
- **Moved the emitter off the frame border**: `SCAT_EMITTER` (0.13, 0.78) →
  **(0.35, 0.53)** — next to the box, level with the detector dish, so the
  obvious shot is horizontal and the pull-back hand stays well inside the
  frame. The user reminded: **interactables NEVER sit near the border**
  (EDGE_MARGIN_FRAC is a scene-wide rule, not a buttons-only rule) — now
  stated explicitly in CLAUDE.md ("No interactables near the frame border").
- **Emitter affordance** (the user asked "is the black ball the thing you
  shoot?"): added a barrel stub aimed at the detector + a slow-breathing
  halo while idle (both renderers), and slowed the particle 850 → 550 px/s
  so the shorter flight still reads.
- `mock_backend.py` mirrors the new position; `web/dist` rebuilt; smoke
  suite still 10/10; armed-phase screenshot inspected.

### Files changed (uncommitted)
- `src/config.py`, `src/ui/interactables.py`, `web/src/overlay/scene.ts`,
  `web/scripts/mock_backend.py`, `web/dist/*`, `CLAUDE.md`

## Update - 2026-07-21 11:37 - [Claude (Fable 5)]

### What I did
- Created **`changes.md`** for this repo — the same hook-enforced chronological
  change log the vault root and CircuitsSimulations use, with a status
  vocabulary adapted here (VERIFIED HEADLESS (mock) · SMOKE OK · DIST
  REBUILT/NOT REBUILT · PUSHED/NOT PUSHED · VERIFIED ON JETSON · PENDING
  JETSON TEST) and reminders for the hand-mirrored contracts.
- Adapted both hooks into `.claude/hooks/` (`changes-reminder.sh` PostToolUse
  + `changes-stop-gate.sh` Stop) and wired them in `.claude/settings.json`.
  Exercised with simulated payloads: 9/9 cases pass. Enforcement starts next
  session (hooks snapshot at startup).
- **Fixed the SessionStart hook's stale path**: it looked for SHARED.md at
  `/home/oto/Intership2026/HalLMediaPipe` (the repo's old location), so every
  session was told "SHARED.md not found". Now uses `$CLAUDE_PROJECT_DIR`.

### Files changed
- `changes.md` (new), `.claude/hooks/changes-reminder.sh` (new),
  `.claude/hooks/changes-stop-gate.sh` (new), `.claude/settings.json`

### Important context for the other agent
- From now on, log each batch of work in **both** places: a `changes.md` entry
  (chronological, template + status vocabulary, top of Entries) **and** a
  SHARED.md update (hand-off context). Editing `changes.md` is what clears the
  Stop gate; SHARED.md does not.

### Next steps / unfinished work
- Next session: confirm the gate blocks once when stopping with unlogged
  changes, and that SHARED.md now loads into context at session start.

## Update - 2026-07-21 12:21 - [Claude (Fable 5)]

### What I did
Quantum Cat v2 (user request: real assets + no slingshot + closer to the
original 1935 experiment). Full detail in `changes.md` (12:21 entry); the
short version:
- Researched Schrodinger 1935 + existing sims; restaged the scene as the
  paper's apparatus: steel chamber, Geiger tube, relay hammer, HCN flask.
- Replaced the pinch-pull-release emitter with a CC0 ray-gun + text-labelled
  **FIRE α** button (pinch = shoot, pre-aimed, no misses). State contract
  changed on BOTH sides (`to_state()` ↔ `types.ts`): gun/trigger/geiger/
  recoil replace emitter/detector/aiming/pull.
- CC0 sprites (Wikimedia Commons, Christian Schirm; FreeSVG raygun) under
  `web/src/assets/schrodinger/` + CREDITS.md, drawn by both renderers with
  cv2 vector fallback. `.gitignore` gained `!web/src/assets/**` and
  `!web/dist/**` (the `*.png` rule was about to eat the art, dist included).

### Verification
- `tests/smoke_scenes.py` 10/10 (schrodinger walk rewritten for the trigger).
- mock_backend + shot.mjs (`?nointro=1`): all 4 phases + alive AND dead
  outcomes screenshot-inspected, no console errors. SSE-synced the shots to
  the mock's phase edges (the mock's clock starts after slow imports — don't
  trust wall-clock offsets).
- `npm run build` done, new dist committed-ready (hashed PNGs in dist/assets).

### Important context for the other agent
- Sprite extraction pipeline lives only in this chat's scratchpad; the
  repo keeps final PNGs. Re-deriving: hi-res rsvg render → crop → corner
  floodfill / luminance key → trim (sources in CREDITS.md).
- cv2 trigger label is ASCII ("FIRE alpha") — Hershey fonts have no α; the
  web label says "FIRE α particle". Renderer-local, intentional.

### Next steps / unfinished work
- Live on-camera pass (trigger reach, grab feel), then push → kiosk.
- `HALL_OUTPUT=window` spot-check of the cv2 sprite path.

## Update - 2026-07-21 12:37 - [Claude (Fable 5)]

### What I did
- New **`hallpush`** command (`deploy/hall-app/hallpush`, symlinked at
  `~/.local/bin/hallpush`): the user's one-shot deploy — add + commit
  (message from args or synca-style auto) + pull --rebase + push `main`
  (kiosk self-updates in ~60 s) + `synca` for the vault submodule pointer.
  Flags: `-w` wait for the Jetson to report the commit (+`/healthz` probe),
  `-n` skip synca, `--dry-run`. Never forces; aborts a conflicted rebase
  clean; refuses off-main. README Deploy section updated around it.

### Important context for the other agent
- Only `--dry-run`/`-h` were executed — the real path is untested because
  running it would push the pending Quantum Cat v2 batch to the exhibit.
  The user's first `hallpush` doubles as its live test.

### Next steps / unfinished work
- First real `hallpush -w` run (deploys Quantum Cat v2).
