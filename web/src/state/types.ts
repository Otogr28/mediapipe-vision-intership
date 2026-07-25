/**
 * TypeScript mirror of the per-frame state document built by
 * `src/web/state.py` and pushed over the `/state` SSE endpoint.
 *
 * Conventions (see state.py):
 * - scene geometry (cursors, rects, positions) is in FRAME PIXELS
 * - landmarks (pose + hands) are NORMALIZED [0, 1]
 * - forces are in newtons
 */

export type Vec2 = [number, number];
export type Vec3 = [number, number, number];

export type PinchPhase = "open" | "closing" | "closed" | "releasing";

export interface HandState {
  id: string;
  cursor: Vec2;
  press_cursor: Vec2;
  state: PinchPhase;
  progress: number;
  /** the combined ratio the state machine ran on, always in PINCH units
   *  whichever gesture produced it (see gestures._combined_ratio) */
  ratio: number | null;
  /** each gesture in its own units, for the debug HUD's tuning readout */
  pinch_ratio?: number | null;
  fist_ratio?: number | null;
  pinching: boolean;
  held: boolean;
  /** ms since this hand was last seen; > ~200 means a grace-window ghost */
  seen_ms: number;
  /** 21 normalized [x, y] landmarks, or null while in the grace window */
  landmarks: Vec2[] | null;
  /** 21 metric [x, y, z] hand-world landmarks (wrist origin, meters) — drives
   *  the vtuber's hand orientation + finger curl. null while in the grace
   *  window (or if a backend omits them). */
  world?: Vec3[] | null;
  /** raw MediaPipe handedness label; the avatar matches hands by image-x, so
   *  this is a fallback only (unreliable on the mirrored feed). */
  handedness?: "Left" | "Right" | null;
}

/** 33 pose landmarks as [x, y, visibility], normalized (image space). */
export type PoseState = [number, number, number][];

/**
 * 33 metric 3D pose landmarks as [x, y, z] in meters, origin at the hips
 * midpoint (MediaPipe `pose_world_landmarks`). Camera-independent and
 * gravity-aligned — this is what drives the vtuber rig's per-bone 3D
 * orientation. Visibility is not repeated; index into `pose[i][2]`.
 * MediaPipe axes: +x image-right, +y down, +z away from camera.
 */
export type PoseWorld = [number, number, number][];

export interface ButtonState {
  id: string;
  label: string;
  rect: [number, number, number, number];
  hovered: boolean;
  pressed: boolean;
  /** radio-style "chosen" flag (Orbitals body-type palette); optional so
   *  older/other button states without it still parse. */
  selected?: boolean;
}

export interface SpeedPill {
  rect: [number, number, number, number];
  text: string;
}

export interface SphereObject {
  type: "sphere";
  id: number;
  x: number;
  y: number;
  r: number;
  grabbed: boolean;
}

export interface SixSevenObject {
  type: "sixseven";
  count: number;
  flash: number;
}

export interface BlackHoleObject {
  type: "black_hole";
  x: number;
  y: number;
  einstein_px: number;
  disk_inner_px: number;
  disk_outer_px: number;
  disk_tilt_rad: number;
  disk_brightness: number;
  rotation_speed: number;
  disk_t: number;
  grabbed: boolean;
}

export interface SlingshotProjectile {
  id: number;
  x: number;
  y: number;
  resting: boolean;
  sliding: boolean;
  f_w: Vec2;
  f_d: Vec2;
  f_c: Vec2;
}

export interface SlingshotObject {
  type: "slingshot";
  anchor: Vec2;
  ball_r: number;
  aiming: boolean;
  time_scale: number;
  pull: Vec2 | null;
  readout: {
    angle: number;
    v0: number;
    draw_n: number;
    e_j: number;
    ke_j: number;
  } | null;
  arc: Vec2[];
  projectiles: SlingshotProjectile[];
}

export type OrbitalKind = "star" | "planet" | "moon" | "comet";

export interface OrbitalsBody {
  id: number;
  x: number;
  y: number;
  r: number;
  rgb: [number, number, number];
  kind: OrbitalKind;
  /** mass (sim units) — bodies collide by momentum, so mass is meaningful */
  m: number;
  /** transient impact/merge glow (1→0), drawn as an expanding ring */
  flash: number;
}

export interface OrbitalsObject {
  type: "orbitals";
  bodies: OrbitalsBody[];
  count: number;
  /** currently selected spawn type (for the aim ghost + preview) */
  kind: OrbitalKind;
  kind_r: number;
  kind_rgb: [number, number, number];
  kind_m: number;
  time_scale: number;
  aiming: boolean;
  spawn: Vec2 | null;
  pull: Vec2 | null;
  arc: Vec2[];
  readout: { v0: number; angle: number; kind: string; mass: number } | null;
}

export interface WaveSource {
  id: number;
  x: number;
  y: number;
  /** oscillation frequency (Hz) */
  freq: number;
  /** source amplitude (field units) */
  amp: number;
  /** experiment-clock time the source appeared (s) — phase reference */
  born: number;
  grabbed: boolean;
}

export interface WavesObject {
  type: "waves";
  /** experiment clock (s) — the wave field's time base */
  t: number;
  /** propagation speed (frame px / s at 1x) */
  c: number;
  time_scale: number;
  /** palette selection for the next placed source */
  kind: "low" | "mid" | "high";
  count: number;
  sources: WaveSource[];
}

export interface PointCharge {
  id: number;
  x: number;
  y: number;
  /** charge in palette units; the SIGN is the physics (+1, -2, ...) */
  q: number;
  grabbed: boolean;
}

export interface ChargesObject {
  type: "charges";
  /** Coulomb constant in screen units (px), sets the V scale */
  k: number;
  /** core softening radius (px) — keeps 1/r finite at a charge's centre */
  soften: number;
  /** volts between equipotential contour bands */
  equipot_step: number;
  /** field lines a unit charge emits (a 2q charge emits twice as many) */
  lines_per_q: number;
  /** palette selection for the next placed charge */
  kind: "neg2" | "neg1" | "pos1" | "pos2";
  count: number;
  charges: PointCharge[];
}

export interface BarMagnet {
  id: number;
  x: number;
  y: number;
  /** magnetization along +x: +1 puts the N pole on the RIGHT face */
  m: number;
  grabbed: boolean;
}

export interface MagnetsObject {
  type: "magnets";
  /** bar half-length a (px) — pole faces sit at x = +/- a */
  half_len: number;
  /** bar half-height b (px) */
  half_h: number;
  /** smoothing width (px) of the inside-the-bar +M term */
  edge_smooth: number;
  /** |B| that maps to a fully opaque needle, alpha = tanh(|B|/b_ref) */
  b_ref: number;
  /** needle grid cell (px) */
  needle_spacing: number;
  /** needle length (px) */
  needle_len: number;
  /** palette selection for the next placed bar */
  kind: "sn" | "ns";
  count: number;
  magnets: BarMagnet[];
  /** fixed pickup coil (px); its plane is vertical, flux is Bx through it */
  coil: { x: number; y: number; r: number; loops: number };
  /** normalized induced current in [-1, 1] — bulb glow + galvanometer */
  current: number;
  /** raw EMF (screen units), informational */
  emf: number;
  /** induced EMF in real millivolts (signed, smoothed) — see the
   *  calibration note on config.MAG_EMF_TO_V */
  emf_mv: number;
  /** induced current in real milliamps (signed): emf / MAG_CIRCUIT_OHM */
  current_ma: number;
}

export type SpacetimeKind = "sun" | "neutron" | "bh" | "orbiter";

export interface SpacetimeMass {
  id: number;
  x: number;
  y: number;
  /** mass in palette units */
  m: number;
  /** Schwarzschild radius (px) — the sheet's throat AND the Kerr potential pole */
  rs: number;
  rgb: [number, number, number];
  /** horizon-sized body: drawn as a black disk of radius r_horizon */
  compact: boolean;
  kind: SpacetimeKind;
  /** transient glow (1→0) when it swallows an orbiter */
  flash: number;
  grabbed: boolean;
  /** dimensionless Kerr spin a* = Jc/(GM²), [0, 0.998] */
  spin: number;
  /** accumulated rotation angle (rad) — drives the spin marker */
  phase: number;
  /** Kerr outer horizon r+ = M(1+√(1−a*²)) px: shrinks rs → rs/2 with spin */
  r_horizon: number;
  /** the body's SURFACE radius (px). Outside it the sheet is Flamm's
   *  paraboloid; inside, the interior Schwarzschild spherical cap. A hole has
   *  no surface (r_body = rs), so its funnel runs to a vertical throat. */
  r_body: number;
  /** equatorial ergosphere r_E = 2M = rs px — spin-independent, so the GAP
   *  between this and r_horizon is the spin made visible (zero at a* = 0) */
  r_ergo: number;
}

export interface SpacetimeOrbiter {
  id: number;
  x: number;
  y: number;
}

/**
 * Relativistic gravity sandbox. The backend owns the masses, the orbiters,
 * the camera angles and the integration; the renderer derives the picture.
 *
 * The sheet is Flamm's paraboloid summed per mass and the projection is a
 * yaw/pitch/perspective camera — both mirrored from `ui/interactables.py`
 * (`_flamm_depth` / `_project`) into `overlay/scene.ts`. Keep them in sync.
 */
export interface SpacetimeObject {
  type: "spacetime";
  /** camera yaw (rad), spun by the two-hand rotate gesture */
  yaw: number;
  /** camera elevation above the sheet (rad): π/2 = straight down */
  pitch: number;
  zoom: number;
  /** perspective focal length (px) */
  focal: number;
  /** true while two pinches are driving the camera */
  rotating: boolean;
  /** radius (px) at which each well is declared flat again */
  reach: number;
  /** vertical exaggeration of the sheet (display only — orbits never see it) */
  depth_gain: number;
  /** [cols, rows, samplesPerLine, extentAsFractionOfFrame] */
  grid: [number, number, number, number];
  /** false = the 2D embedding sheet, true = the 3D volumetric lattice */
  view_3d: boolean;
  /** [cols, rows, layers, samplesPerLine, extentFrac, boxDepthPx] */
  lattice: [number, number, number, number, number, number];
  lattice_verticals: boolean;
  /** display exaggeration of the radial pull (the lattice's ST_DEPTH_GAIN) */
  lattice_gain: number;
  /** draw a vertical strut only every Nth node */
  vert_stride: number;
  /** speed of light in screen px/s — derived, not tuned (rs = 2GM/c²) */
  c: number;
  /** gravitational constant in screen units */
  g: number;
  /** Lense–Thirring twist amplitude + cap (rad) */
  lt_gain: number;
  lt_max: number;
  /** backdrop dim alpha + colour — darkens the camera image under the grid */
  dim: number;
  dim_rgb: [number, number, number];
  kind: SpacetimeKind;
  time_scale: number;
  count: number;
  masses: SpacetimeMass[];
  orbiters: SpacetimeOrbiter[];
  orbiter_rgb: [number, number, number];
  /** client-accumulated trail length, in snapshots */
  trail_len: number;
  /** sim clock (s) — the wave's time base */
  sim_t: number;
  /** trace-free mass quadrupole, 2nd derivative: [Ixx, Iyy, Ixy]. ONE sample
   *  per frame; the browser accumulates the history and does its own retarded
   *  lookup (same trick as the trails). null when there are no bodies. */
  quad: [number, number, number] | null;
  /** centre of mass (px) — the wave's origin */
  com: [number, number] | null;
  /** display amplification of the strain (h is ~1e-4: real, and invisible) */
  gw_gain: number;
  gw_max: number;
  gw_hist_s: number;
  /** where a release would drop the next object; null unless armed */
  ghost: { x: number; y: number } | null;
}

export interface VtuberObject {
  type: "vtuber";
  /** spawn-relative clock (s), wrapped — drives the idle bob */
  t: number;
  /** max pinch progress across hands [0, 1] — drives the mouth */
  mouth: number;
}

/**
 * Schrodinger's cat measurement game, staged as the 1935 apparatus: an alpha
 * gun fires at the Geiger tube on the steel chamber; hammer + HCN flask live
 * inside. The backend owns the phase machine and the Born-rule dice; ALL
 * geometry travels here (nothing hand-mirrored). Ghost-pulse/gas/LED clocks
 * are renderer-local decoration on the `now` clock.
 */
export interface SchrodingerObject {
  type: "schrodinger";
  phase: "place" | "armed" | "superposed" | "revealed";
  /** cat position while outside the box (place phase) */
  cat: Vec2;
  /** cat head radius (px) — the scene's size unit */
  cat_r: number;
  cat_grabbed: boolean;
  /** box rect [x, y, w, h] */
  box: [number, number, number, number];
  /** alpha-gun muzzle tip, level with the Geiger tube (armed phase) */
  gun: Vec2;
  /** gun sprite width (px) — trigger/flash sizes derive from it */
  gun_w: number;
  /** centre of the text-labelled FIRE button (pinch = shoot) */
  trigger: Vec2;
  trigger_r: number;
  /** Geiger tube on the box's left wall */
  geiger: Vec2;
  geiger_r: number;
  /** gun kick + muzzle flash 1 → 0 */
  recoil: number;
  /** alpha particle in flight, else null */
  particle: Vec2 | null;
  /** collapse result (revealed phase), else null */
  outcome: "alive" | "dead" | null;
  /** collapse flash 1 → 0 */
  flash: number;
  /** [alive, dead] measurement counts across runs — converges to 50/50 */
  tally: [number, number];
  /** phase caption, ready to draw */
  caption: string;
}

export type SceneObject =
  | SphereObject
  | SixSevenObject
  | BlackHoleObject
  | SlingshotObject
  | OrbitalsObject
  | WavesObject
  | ChargesObject
  | MagnetsObject
  | SpacetimeObject
  | VtuberObject
  | SchrodingerObject;

export interface DebugState {
  render_fps: number;
  hand_fps: number;
  age_ms: number;
  backend: string;
  /** HALL_GESTURE — which gesture(s) close the cursor */
  gesture?: GestureMode;
  close_ratio: number;
  release_ratio: number;
  fist_close_ratio?: number;
  fist_release_ratio?: number;
  /** what attract mode's presence detector currently sees */
  presence?: {
    present: boolean;
    /** fraction of the frame differing from the learned background */
    motion: number;
    source: "hand" | "pose" | "motion" | null;
  } | null;
}

/** HALL_GESTURE: which gesture closes the cursor. */
export type GestureMode = "pinch" | "fist" | "either";

/**
 * Attract phase — one level ABOVE `session.state`:
 * - "attract"  nobody there; the slideshow covers the camera
 * - "greeting" somebody just walked up; "Hi" + the gesture demo
 * - "live"     `session.state` means something
 */
export type SessionPhase = "attract" | "greeting" | "live";

export interface AttractSlide {
  /** served by the backend out of ATTRACT_DIR (see output.WebSink) */
  src: string;
  title: string;
  caption: string;
}

export interface AttractState {
  title: string;
  prompt: string;
  index: number;
  /** slide being faded OUT; equals `index` when there is no fade */
  prev: number;
  /** 1.0 = fully on `index` */
  fade: number;
  slides: AttractSlide[];
}

export interface GreetingState {
  title: string;
  subtitle: string;
  hint: string;
  /** seconds since the greeting started */
  t: number;
  duration: number;
}

export interface AppState {
  seq: number;
  t: number;
  frame: { w: number; h: number };
  hands: HandState[];
  pose: PoseState | null;
  /** metric 3D skeleton for the vtuber rig; null unless pose is running */
  pose_world?: PoseWorld | null;
  session: {
    state: "menu" | "interactables" | "experiments";
    experiment:
      | "black_hole"
      | "slingshot"
      | "orbitals"
      | "waves"
      | "charges"
      | "magnets"
      | "spacetime"
      | "schrodinger"
      | null;
    /** attract phase; absent on backends predating attract mode → "live" */
    phase?: SessionPhase;
    /** non-null only while phase === "attract" */
    attract?: AttractState | null;
    /** non-null only while phase === "greeting" */
    greeting?: GreetingState | null;
    /** which gesture(s) close the cursor, and which one the onboarding
     *  hands should act out. Absent on older backends → pinch. */
    gesture?: GestureMode;
    demo_gesture?: "pinch" | "fist";
    /** `text` rides along so the words match the gesture the detector is
     *  watching for; absent on older backends → the pinch wording. */
    hint: { visible: boolean; text?: string };
    /** vtuber "Points" toggle — hide the avatar + draw the raw skeleton */
    show_points?: boolean;
    /** which vtuber avatar to load (index into AVATARS); set by the backend's
     *  "Avatar" pinch button. Absent on older backends → falls back to 0. */
    avatar_index?: number;
  };
  buttons: ButtonState[];
  speed: SpeedPill | null;
  objects: SceneObject[];
  debug: DebugState | null;
}
