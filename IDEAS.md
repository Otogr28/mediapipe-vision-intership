
# Ideas

## Shipped

- [x] **Orbitals — astro simulator** — SHIPPED 2026-07-07. Experiments →
  "Orbitals". Velocity-Verlet (leapfrog, 1 force-eval/step), Plummer
  softening, perfectly-inelastic merges, pinch-drag-release launch (pull-
  opposite, live-field arc preview), grab-to-fling, body-type palette
  (star/planet/moon/comet) + presets (Solar / Binary / Figure-8) + Clear,
  shared sim-speed stepper (adds 8×). Renders on Canvas2D (glow bodies,
  client-side trails, blackbody-ish colours); a merge past
  `ORB_COLLAPSE_MASS` renders as a black hole (dark disk + accretion ring —
  the *lightweight* in-renderer version; the full lensing-shader collapse
  below is still open). Code: `Orbitals` in `ui/interactables.py`,
  `drawOrbitals` in `web/src/overlay/scene.ts`, `ORB_*` in `config.py`.
- [x] **Vtuber mode** — SHIPPED 2026-07-07. Interactable Figures → "Vtuber".
  A cosmic-mascot avatar (`Puppet` in `ui/interactables.py`, `drawPuppet` in
  `scene.ts`): paws ride the tracked hands, mouth opens with the pinch, eyes
  track the hands, arms follow shoulder→elbow→wrist when `HALL_POSE=1` (soft
  curved arms when pose is off, the default). Dims the camera + hides the raw
  skeleton so the character stands alone. Pure frontend render + a cv2
  fallback; no new detector (so no FaceLandmarker cost yet — see below).

## Next up

- [ ] **Orbitals v2 candy** *(follow-ups to the shipped experiment)*
  - Real lensing on collapse: spawn the existing `BlackHole` / WebGL lensing
    layer when a merger passes `ORB_COLLAPSE_MASS`, instead of the current
    flat dark-disk render — the shader already exists, but the web path gates
    the lensing layer on a `black_hole` object, so it needs the orbitals
    object to opt a body into that layer.
  - Bloom on the bodies via the WebGL layer; Roche-limit breakup.

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
