
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
  - *2026-07-16:* the spawn button's on-screen label is now **"Rigged
    Model"** (was "Vtuber") — internal ids and state types (`spawn.vtuber`,
    object type `"vtuber"`) are unchanged, so no web contract change.

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

- [ ] **Light cones & the singularity — a causal-structure experiment**
  *(requested 2026-07-15; sibling to Spacetime, NOT a mode inside it)*
  The other half of the black-hole story: Spacetime shows you the WELL, this
  would show you the CAUSALITY — why you cannot come back out.
  - The classic picture: a spacetime diagram (space horizontal, time vertical)
    with a **light cone** at each event. Far away the cones stand upright and
    you can move anywhere inside them; approaching the hole they TIP toward the
    singularity; at the horizon the outgoing edge goes vertical; inside, the
    whole cone points inward — every future path ends at r=0. "The singularity
    stops being a place and becomes a *time*" is the line the exhibit should
    land, and a tipping-cone diagram is the only way to actually show it.
  - Interaction sketch: pinch to drop an observer/worldline and watch it get
    dragged in; drag the horizon crossing back and forth; maybe a second pinch
    for the infalling-vs-distant-observer split (the one sees a finite proper
    time, the other sees them freeze and redshift forever — same event, two
    stories, which is the whole point).
  - Two candidate renderings, decide before building:
    * **(r, t) diagram in Eddington-Finkelstein coords** — cones tip smoothly,
      no coordinate singularity at the horizon (Schwarzschild's t coordinate
      blows up there and would render as a fake wall). Simpler, honest, and
      the tipping is the star.
    * **Penrose / conformal diagram** — the full causal map (past/future null
      infinity, both exteriors, the r=0 spacelike lines). Prettier and it's the
      "typical graph" of the ask, but conformal compactification is abstract:
      hard to read cold in a 30-second exhibit visit without a guide.
    Leaning EF for the interactive part, with the Penrose diagram as a static
    inset that highlights where you are — get both without teaching topology.
  - Reuse: the same `_project` + camera + two-hand control as Spacetime; this
    is a 2D diagram, so it may not need the 3D lattice at all.

- [ ] **Time dilation — moving clocks tick slower** *(requested 2026-07-16,
  from the 07-15 research log; sibling to Spacetime + light-cones)*
  Spacetime shows gravity bending SPACE; this shows velocity stretching TIME —
  special relativity's other half, and the cheapest physics of any experiment
  yet: no field, no integrator to diverge, just `dτ = dt·√(1−v²/c²)` per body.
  - The exhibit trick: **lower c to exhibit scale** (the Mr Tompkins move —
    c ≈ 20 m/s in slingshot units) so a hand-launched ball is relativistic:
    γ readouts go from 1.00 at walking pace to 3-4× near full pull.
  - Interaction sketch (slingshot muscle memory, zero new gestures):
    pinch-drag-release launches a "ship" carrying its own CLOCK FACE, while a
    lab wall clock ticks coordinate time in the corner. Faster ship = visibly
    slower hands + a live γ readout. The band physically CANNOT launch past c
    — the same pull buys less speed as γ grows (relativistic momentum), so
    the speed limit is *felt in the hand*, not stated in a caption.
  - **Twin preset**: one ship makes a round trip while a stay-home clock
    waits; they meet again showing different elapsed times, side by side —
    the twin "paradox" as a 15-second demo.
  - **Muon bonus**: spawn particles that decay after a fixed PROPER time; the
    fast ones visibly outrun their classical range — the actual experimental
    confirmation (cosmic-ray muons reaching the ground).
  - Rendering: Canvas2D clock faces/labels in both renderers (cv2 arcs +
    text fallback). Python owns the ships + proper-time integration; the
    browser draws clocks from the state — the tiniest state payload yet.
  - Stretch that ties the room together: drop one of these clocks into the
    Spacetime scene's well — gravitational dilation (deeper = slower) next
    to velocity dilation, the two halves of "time is local".

- [ ] **Inside the singularity — a hypothesis gallery** *(requested
  2026-07-16, from the 07-15 research log; pairs with light-cones)*
  GR does not PREDICT what happens at r=0 — it predicts its own breakdown
  there (geodesics just END; Penrose 1965). Nobody knows what actually
  happens, so this scene is honest by construction: a gallery of the leading
  hypotheses, each labelled *as a hypothesis*, morphing one interior picture.
  - Interaction sketch: the black hole in cross-section (embedding-sheet
    view); a palette of hypothesis CARDS; pinch a card and the interior
    below the horizon morphs into that picture, with a 2-sentence caption +
    a status tag. Outside the horizon NOTHING changes when you switch —
    that's Birkhoff, and it's the punchline: no outside observation can
    currently tell these apart, which is exactly why the question is open.
  - Candidate cards (each is one interior depth-profile):
    * **Classical GR** — the funnel runs to a vertical asymptote, curvature
      → ∞, worldlines end. The baseline, drawn with a "theory breaks down
      here" hazard band rather than presented as truth.
    * **Planck star / LQG bounce** (Rovelli & Vidotto) — quantum pressure
      halts collapse at Planck density: the funnel bottoms out in a tiny
      bulb. Stretch: animate the bounce (black hole → white hole).
    * **Fuzzball** (Mathur, string theory) — there IS no interior: the
      funnel ends at a fuzzy, textured surface at the horizon radius.
    * **Gravastar** (Mazur & Mottola) — collapse stalls into a thin shell
      around a dark-energy core: a shallow de Sitter cap inside the shell.
    * **Regular black holes** (Bardeen / Hayward) — metrics with a de Sitter
      core: finite curvature everywhere, a smooth rounded bottom.
    * **Baby universe** (Smolin) — the throat pinches off and opens into a
      second sheet underneath: a new expanding universe.
  - Why it's cheap: the Spacetime sheet machinery (`_embed_height` /
    `_isotropic_radius` / the lattice) already draws exactly this class of
    shape — each hypothesis is just a different `_depth` profile below r_s,
    the same way star-interior vs black-hole is already a profile switch.
    Both renderers inherit it by construction (mind the sync table).
  - More guided gallery than sandbox — pairs with the light-cones experiment
    (which explains WHY we can't just look inside and settle it).

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
