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
