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
  ratio: number | null;
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

export interface VtuberObject {
  type: "vtuber";
  /** spawn-relative clock (s), wrapped — drives the idle bob */
  t: number;
  /** max pinch progress across hands [0, 1] — drives the mouth */
  mouth: number;
}

export type SceneObject =
  | SphereObject
  | SixSevenObject
  | BlackHoleObject
  | SlingshotObject
  | OrbitalsObject
  | VtuberObject;

export interface DebugState {
  render_fps: number;
  hand_fps: number;
  age_ms: number;
  backend: string;
  close_ratio: number;
  release_ratio: number;
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
    experiment: "black_hole" | "slingshot" | "orbitals" | null;
    hint: { visible: boolean };
  };
  buttons: ButtonState[];
  speed: SpeedPill | null;
  objects: SceneObject[];
  debug: DebugState | null;
}
