
# Ideas

## Shipped

- [x] **Charges — electrostatic field** — SHIPPED 2026-07-15. Experiments →
  "Charges". Pinch empty space to drop a point charge (palette -2q/-q/+q/+2q),
  pinch one to drag it and watch the field reorganise live; a "Dipole" preset
  drops the textbook +/- pair in one press. Shows field LINES (density encodes
  |q| — a 2q sprouts twice as many), EQUIPOTENTIAL contour bands, the dipole,
  and the null point between like charges.
  **Design note (why it isn't Orbitals with signs):** the charges are STATIC.
  With inverse-square attraction and no orbital velocity a +/- pair would just
  collide instantly; real exhibits pin the charges because the FIELD is the
  subject. So there is NO time integration at all — the potential is analytic
  (`V = k*sum(q/r)`), evaluated per pixel in a single stateless shader pass
  (`web/src/gl/charges.frag.glsl`), which also makes it the cheapest experiment
  on the GPU and immune to the dt/divergence class of bug. Field lines are
  traced client-side in JS from the charge list (`web/src/overlay/scene.ts`,
  memoised on charge positions so a static scene costs nothing), the same
  trick as the Orbitals trails; the backend ships only ~8 charges. cv2
  window/stream fallback does both in numpy. Code: `Charges` in
  `ui/interactables.py`, `CHG_*` in `config.py`.
  - *2026-07-15:* the lines are ANIMATED — arrowheads march along the same
    traced polylines (geometry untouched), out of + charges and into - ones.
    Each arrow's size/opacity comes from the LOCAL |E|, so cancellation shows
    for free: at the null point between like charges |E| is exactly 0 and the
    arrows there vanish on their own, no special case. The flow is pure
    decoration so it runs on the renderer's own clock — no state contract
    change. Both renderers do it (`CHG_ARROW_*`).

- [x] **Waves — interactive ripple tank** — SHIPPED 2026-07-14. Experiments →
  "Waves". Pinch on empty water drops an oscillating point source (palette
  picks Low/Mid/High frequency), pinch a source to DRAG it — the wake
  compresses ahead / stretches behind (real Doppler), two sources show
  textbook two-slit interference fringes, and the frame edges REFLECT like
  tank walls. All of it emerges from a damped 2D wave-equation FDTD (9-point
  isotropic Laplacian; the 5-point stencil goes visibly square): the browser
  integrates it in a WebGL2 ping-pong RG16F texture at frame/4 res
  (`web/src/gl/WavesLayer.tsx` + `waves_step/render.frag.glsl`), the cv2
  window/stream fallback runs the same scheme in numpy at `WAVE_GRID_PX`
  (~8 ms/frame at 720p via a grid-res colour + one SIMD blendLinear).
  Python owns sources/palette/clock only (`Waves` in `ui/interactables.py`,
  `WAVE_*` in `config.py`); the -/+ stepper scales oscillation + propagation
  together. Also SHIPPED same day: **GPU-hand ROI tracking** (see SHARED.md)
  — edge-crossing landmark error 11.2 → 4.7 px.
  - *Fixed 2026-07-15 (v1 was unusable — see SHARED.md):* the field DIVERGED
    to ~1e32 in 5 s (read as "the screen saturates") because the leapfrog was
    fed a **varying dt** (the frame's leftover time) — it assumes a constant
    dt, so the time levels mismatched and pumped energy. Both renderers now
    bank time and step in whole `WAVE_PHYS_DT` chunks (the Orbitals
    discipline). Visibility: the display alpha is now `tanh`-toned, steep near
    zero and saturating, so one source reads clearly AND six don't white out.
    `WAVE_DECAY_TAU_S` 1.6 → 0.9 s keeps ripples local to their source (the
    far field stays calm so the camera shows through, interference stays
    crisp). An absorbing "beach" border was tried and rejected — measured only
    ~16% far-field change, since damping already kills reflections.

- [x] **Orbitals — astro simulator** — SHIPPED 2026-07-07. Experiments →
  "Orbitals". Symplectic velocity-Verlet (leapfrog, 1 force-eval/step),
  small Plummer softening, and a **physically-accurate collision-OUTCOME
  model** (Leinhardt & Stewart 2012, per request): the impact speed vs the
  mutual escape velocity `v_esc = √(2 G M_tot / R_tot)` decides — **merge**
  (perfect accretion, fuse into one, flash) below `v_esc`, **bounce**
  (hit-and-run momentum impulse, deflect by mass ratio) up to
  `ORB_FRAG_VESC_FACTOR·v_esc`, and **fragment** (catastrophic disruption:
  shatter into a largest remnant + debris that fly out and re-accumulate)
  above it. Mass + momentum conserved EXACTLY in every regime (verified).
  Pinch-drag-release launch (arc previewed through the LIVE gravity field),
  grab-to-fling, body-type palette (masses shown) + presets (Solar / Binary /
  Figure-8, bound 60 s) + Clear, shared sim-speed stepper (adds 8×). Canvas2D
  render (glow bodies, client trails, impact-flash rings). Code: `Orbitals`
  in `ui/interactables.py`, `drawOrbitals` in `web/src/overlay/scene.ts`,
  `ORB_*` in `config.py`.
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

- [~] **GPU pose backend** — BUILT + validated local 2026-07-08 (round 10),
  **deploy pending**. `HALL_POSE_INFERENCE=gpu` runs BlazePose person-det
  (OpenCV zoo onnx) + pose-landmark (tf2onnx-converted from the .task's own
  tflite) on onnxruntime/TensorRT — `detection/gpu_pose.py` +
  `_zoo/mp_persondet.py` + `_zoo/mp_poselandmark.py`, models in `models/gpu/`.
  The model-sourcing blocker is solved: the landmark tflite converts cleanly to
  ONNX, and the detector (which tf2onnx CAN'T convert) comes pre-converted from
  the OpenCV zoo. Validated to mean 0.027 landmark error vs MediaPipe on a clip
  (no camera needed). Remaining: deploy to the Jetson + confirm the fps win and
  memory fit on-device (see CONTINUE.md / SHARED.md round 10).
