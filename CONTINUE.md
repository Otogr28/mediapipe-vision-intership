# CONTINUE — Vtuber rig work (handoff)

Pick-up notes for the VTuber avatar work. Read this + `SHARED.md` (rounds 5–9)
to continue. Last deployed commit at handoff: **3f24f99** (+ docs `4bb380b`).

## THE OPEN PROBLEM (what to fix next)

**The body still lags badly, and the hand-vs-body speed mismatch feels weird.**
User's exact words: "el cuerpo se siente mejor pero el delay sigue siendo
increíble, se nota la separación entre la velocidad de captura de manos y cuerpo
y eso hace q se sienta super raro usar el modelo."

Root cause (confirmed): **hands run on the Jetson GPU (~30 fps, TensorRT), body
pose runs on CPU MediaPipe (~13 fps + one inference behind ~77 ms).** The pose
smoother (round 9) removed the *stutter* and hides *some* latency via
extrapolation, but the body still inherits the ~13 fps rate + inference latency,
so it visibly trails the fast hands. This is the core remaining issue.

### Next levers, ranked (for the next session)
1. **Measure the real Jetson pose fps first.** There is no `pose_fps` metric
   today (only `hand_fps`). Add one (mirror `detectors.hand_fps()` for pose) and
   read it in the debug HUD, OR just log it. We *assume* ~13 fps — confirm. If
   it's lower (CPU contention), that changes the fix. The hands are on GPU so the
   6 CPU cores should be mostly free for pose — check `tegrastats` while running.
2. **Push pose extrapolation harder (cheap, try first).** Today it extrapolates
   only by the result *age* (`POSE_EXTRAP_MAX_S=0.12`, config.py). Add a FIXED
   lead to also compensate the inference latency itself (the result is already
   ~77 ms old on arrival). Risk: overshoot/wobble on fast direction changes —
   tune with the offline harness (see below). Could add `POSE_EXTRAP_LEAD_S`
   (~0.05–0.08) added to `lead` in `PoseSmoother.sample()`.
3. **GPU pose (the real fix, big effort).** No GPU pose path exists. Port a pose
   model to ONNX/TensorRT like `detection/gpu_hands.py` did for hands (models in
   `models/gpu/`, zoo wrappers in `detection/_zoo/`). This both speeds pose AND
   frees the ~1.5 CPU cores it eats. Biggest win, most work. This is THE fix for
   the mismatch.
4. **Smooth the hands too (secondary).** Hand world landmarks (fingers/palm) are
   still RAW — a hand teleport jumps. Same `PoseSmoother` idea, but needs
   per-hand filter identity (match by hand id across frames). User did ask for
   this ("aplica al cuerpo también").
5. **Torso twist / shoulder tracking is single-axis** (see rig notes) — the body
   is still a bit "incomplete." Could add shoulder-line twist to the spine.

## HOW TO WORK ON THIS (essential tooling)

### Deploy (= push to main; the Jetson auto-updates in ≤60 s)
```
cd <repo> && (cd web && npm run build) && git add -A && git commit -m '…' && git push
# force it now instead of waiting:
ssh jetson@100.91.206.114 '~/HalLMediaPipe/deploy/hall-app/hall-update.sh'
```
Each push restarts the kiosk (~10 s white screen) — that is NOT a crash. Backend
health: `ssh jetson@100.91.206.114 'curl -s localhost:8092/healthz'`. Jetson
monitor screenshot recipe is in `deploy/hall-app/hall-app.cheat` (navi).

### Drive the avatar from a VIDEO FILE (test WITHOUT a camera) — round 8
```
# get a clip (mixkit CDN is curl-able; Pexels is Cloudflare-blocked):
curl -sL https://assets.mixkit.co/videos/45503/45503-360.mp4 -o clip.mp4
# run the real inference on it, forced into the Vtuber scene:
HALL_OUTPUT=web HALL_POSE=1 HALL_START_VTUBER=1 HALL_INFERENCE=mediapipe \
  HALL_CAMERA=clip.mp4 uv run python src/main.py &
cd web && npm run dev &        # vite proxies /state,/stream to :8092
node web/scripts/shot.mjs 'http://localhost:5173/?nointro=1' out.png 6000
```
`capture.FreshestFrame` now loops+paces a video FILE to its native fps.
`HALL_START_VTUBER=1` boots straight into Vtuber + keeps the puppet alive.
CAVEAT: laptop pose is fast → this does NOT reproduce the Jetson body delay live.

### Tune temporal feel OFFLINE at the Jetson's rate (round 9 — the rigorous way)
Capture a pose_world trajectory from `/state`, replay it through the real
`_OneEuroFilter` at 13 fps, sweep params vs the 30 fps ground truth. Metric =
max per-frame jump (stutter) + lag + range. This is HOW to validate/tune the
smoother without the Jetson (see SHARED.md round 9 for the exact script shape).

## WHAT'S BEEN BUILT (condensed history — see SHARED.md for detail)

The rig went from "only leans + moves hands" to full 3D + follow + hands +
smoothing, across rounds 6–9:

- **Round 6 (ed5c357):** full-3D body rig from `pose_world` (per-bone
  `setFromUnitVectors`, parent-first, mirror-by-image-x).
- **Round "perf" (349dce8):** frame-rate-independent time-constant smoothing
  (`damp(tau)`); let legs move.
- **Round 7 (38cbdc3):** rig v2 — avatar TRANSLATES + SCALES to the person's
  screen position; HAND ORIENTATION (palm basis) + 30 FINGER bones; `state.py`
  now emits per-hand `world` (21×[x,y,z]) + `handedness`; FAST_FOREARM.
- **Round 7b (5aa94ee/7547108):** "skeleton view" — hotkey `k` / `?skeleton=1`
  and a pinch **"Points"** button draw all 33 pose + 21×hand points on the body
  (avatar hidden). `session.show_points`.
- **Round 8 (ca2da7d):** wrist candy-wrapper fix (`orientBone` clamps deviation
  from rest to WRIST_MAX_RAD≈72°); cut body taus; **video-file test harness**.
- **Round 9 (3f24f99):** **body pose One-Euro smoothing + velocity
  extrapolation** (`detection/pose_smoother.py`) — the main fix for
  stutter/jumps; lighter frontend body taus.

## KEY FILES & KNOBS

- `src/detection/pose_smoother.py` — PoseSmoother (One-Euro + extrapolation).
- `src/config.py` — `POSE_MIN_CUTOFF=0.8`, `POSE_BETA=0.4`,
  `POSE_EXTRAP_MAX_S=0.12` (smoother); `HALL_POSE_SMOOTH=0` bypasses.
  `POSE_ENABLED` (HALL_POSE), `START_VTUBER` (HALL_START_VTUBER, dev).
- `src/main.py` — feeds smoother on new pose result, samples every frame.
- `src/detection/detectors.py` — `latest_pose_packet` (result + receive time).
- `web/src/gl/VrmAvatar.tsx` — the whole rig. Tuning knobs at top:
  taus (UPPER_ARM 0.025, LOWER_ARM 0.03, SPINE 0.03, HEAD 0.03, LEG 0.035,
  HAND_ORIENT 0.045, FINGER 0.04, BODY_MOVE 0.04, BODY_SCALE 0.12, RELAX 0.16);
  `WRIST_MAX_RAD≈72°`; flags FOLLOW_POSITION / DRIVE_HAND_ORIENT / DRIVE_FINGERS
  / FAST_FOREARM; sign knobs `AXIS` / `HAND_AXIS` / `HAND_N_SIGN{left,right}`;
  root-follow (`rigBodyTransform`) scale pivots at the chest (`pivotY`).
- `web/scripts/mock_backend.py` — synthetic `vtuber` scene (moving body + 3D
  hands + Points toggle) for camera-less headless checks.

### On-device sign TODOs (mock can't validate — confirm with a real hand)
`HAND_AXIS.z` (palm depth), `HAND_N_SIGN.{left,right}` (palm chirality — wrong =
back of hand faces camera), thumb curl direction, body-follow X sign. Each is a
one-char flip + rebuild + push.

## Jetson quick ref
`ssh jetson@100.91.206.114` (Tailscale) or `192.168.55.1` (USB). Kiosk =
`hallkiosk` systemd --user unit (Firefox `--kiosk` + web backend). Camera = C920,
one holder at a time. Full cheat: `deploy/hall-app/hall-app.cheat`.
