
# Ideas

## Shipped

- [x] **Orbitals — astro simulator** — SHIPPED 2026-07-07. Experiments →
  "Orbitals". Symplectic velocity-Verlet (leapfrog, 1 force-eval/step),
  small Plummer softening, and **realistic hard-sphere collisions** (updated
  2026-07-07 per request): bodies do NOT merge — they exchange a momentum
  impulse `j = -(1+e)·v_rel_n / (1/m₁+1/m₂)` (restitution `ORB_RESTITUTION`)
  so a light asteroid deflects a heavy planet by the mass ratio and is flung
  itself; momentum is conserved exactly (verified). Pinch-drag-release launch
  (pull-opposite, arc previewed through the LIVE gravity field), grab-to-
  fling, body-type palette (star/planet/moon/comet, masses shown) + presets
  (Solar / Binary / Figure-8, all verified bound 60 s) + Clear, shared
  sim-speed stepper (adds 8×). Canvas2D render (glow bodies, client trails).
  Code: `Orbitals` in `ui/interactables.py`, `drawOrbitals` in
  `web/src/overlay/scene.ts`, `ORB_*` in `config.py`.
- [x] **Vtuber mode — real VRM avatar** — SHIPPED 2026-07-07. Interactable
  Figures → "Vtuber". A CC0 VRoid **VRM** model (`web/public/avatar.vrm`,
  from madjin/vrm-samples) rendered with **three.js + @pixiv/three-vrm**
  (`web/src/gl/VrmAvatar.tsx`, lazy-loaded so three.js stays out of the main
  bundle). Rigged by a hand-written image-plane mapping from the app's own
  landmarks (arms aimed shoulder→elbow→wrist, mouth `aa` from the pinch,
  idle sway + blink) — no Kalidokit, no contract change. Selecting Vtuber
  now **turns pose inference on on-demand** (`ui.wants_pose()` → `main.py`
  builds/runs the pose detector only while Vtuber is active, so the default
  hand UI stays pose-free). The Canvas2D mascot (`drawPuppet`) is the
  automatic fallback while the model loads or if it fails; the cv2 puppet is
  the window/stream fallback. Stretch still open: a FaceLandmarker for real
  facial expression, and finger rigging.

## Next up

- [ ] **Vtuber polish** *(follow-ups to the shipped VRM avatar)*
  - Finger rigging from the hand landmarks (currently the model's rest hands).
  - FaceLandmarker (a 3rd detector) → real mouth/eye/brow expression instead
    of the pinch→mouth stand-in; open question is the CPU cost on the Jetson.
  - Tune the arm-rig mirror/damping on-device with a real camera (the rig
    was validated on synthetic mock pose only — headless, no camera here).
- [ ] **Orbitals candy**: bloom on the bodies via a WebGL layer; optional
  Roche-limit breakup; a "sticky" (perfectly-inelastic) collision mode toggle
  for accretion demos alongside the default elastic bounce.

## Backlog

- [ ] **Orbitals — original design notes** *(kept for reference)*
  An n-body gravity sandbox as a new entry in the Experiments state, built on
  the machinery the app already has (slingshot fixed-timestep sim + aiming
  gesture, per-experiment sim-speed stepper, web state contract).

  **Gesture design (reuses the existing pinch language):**
  - *Add static body*: pinch on empty space → place body at cursor.
  - *Add with initial velocity*: pinch-drag-release → velocity vector from
    the drag, exactly like aiming the slingshot (same muscle memory, and
    `_predicted_arc`-style preview of the initial trajectory).
  - *Grab a body*: pinch near it to drag/reposition (BouncingSphere grab).
  - A small property palette (buttons) selects what the next pinch spawns:
    star / planet / moon / comet — each with preset mass, radius, color.

  **Physics (Python-side, same pattern as the slingshot):**
  - Newtonian n-body with **velocity-Verlet / leapfrog** (symplectic —
    orbits stay stable over long runs, unlike RK4 which slowly gains
    energy), fixed 1/120 s sub-steps banked per frame; the existing
    `time_scale` stepper works unchanged (0.25×–4×, maybe add 16× for
    slow orbits).
  - **Plummer softening** `F ∝ m₁m₂/(r²+ε²)` so close passes don't explode.
  - **Merge collisions**: bodies that touch coalesce conserving mass +
    momentum (v1). Roche-limit breakup as a later flourish.
  - Per-body properties: mass, radius, temperature/color (blackbody ramp —
    reuse the disk temperature palette from the black-hole shader), trail.
  - Presets to spawn in one pinch: Sun+planets, binary star, figure-8
    (the stable 3-body choreography), random asteroid belt.

  **Rendering (browser, per the web contract):**
  - New `"orbitals"` object type in `src/web/state.py` ⇄ `types.ts`:
    per-body id/x/y/vx/vy/mass/radius/temp + trails accumulated client-side
    by id (the slingshot trick — nothing heavy on the wire).
  - Canvas2D v1: glowing bodies (radial gradients), fading trails,
    velocity-vector preview while aiming.
  - v2 candy: bloom via the WebGL layer, gravitational lensing when a body
    collapses into a black hole above a mass threshold — the shader already
    exists; spawning the existing BlackHole on merge-overflow would be a
    spectacular payoff with ~zero new GPU code.

  **Why it fits:** UIManager just needs one more experiment branch; physics
  slots into the `update(hand_result, pose)` / `to_state()` interface;
  the frontend needs one renderer module. No new infrastructure.

- [x] **Vtuber mode** — SHIPPED 2026-07-07 (see the Shipped section). Built
  hand-anchored so it works with pose off (the Jetson default), adding
  pose-driven arms when `HALL_POSE=1`. A real mouth/expression from a
  MediaPipe FaceLandmarker (a third detector, CPU cost on the Jetson TBD)
  is still the open stretch.

- [ ] **GPU pose backend** *(perf, unblocks smoother skeleton — the one
  optimization NOT delivered on 2026-07-07: blocked on a model)*: pose still
  runs MediaPipe CPU at ~13 fps and is the choppiest thing on screen. Hands
  already run TensorRT FP16 at ~28 fps. Needs a BlazePose-landmark ONNX
  sourced/converted (the OpenCV zoo only ships the person detector; only
  palm + handpose ONNX are vendored) — the runtime path (onnxruntime + TRT
  cache) is already proven on the board, so this is purely a model-sourcing
  task, not a code task.
