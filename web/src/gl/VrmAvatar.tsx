import {
  VRMLoaderPlugin,
  VRMUtils,
  type VRM,
  type VRMHumanBoneName,
} from "@pixiv/three-vrm";
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { interpolate } from "../state/interp";
import type {
  AppState,
  HandState,
  PoseState,
  PoseWorld,
  Vec3,
  VtuberObject,
} from "../state/types";
import type { SnapshotPair } from "../state/useAppState";
import { setVrmReady } from "./vrmState";

/**
 * Open-source VRM vtuber avatar (CC0 "Sendagaya Shino", at /avatar.vrm),
 * rendered with three.js + @pixiv/three-vrm as a WebGL layer. Mounted only
 * while a vtuber object is present (see App.tsx).
 *
 * The rig spends ALL of MediaPipe's 3D output:
 *  - BODY (`state.pose_world`, 33 metric joints): each bone is aimed along its
 *    body segment in full 3D via `setFromUnitVectors`, solved parent-first.
 *  - ROOT FOLLOW (`state.pose` 2D): the whole avatar translates to the person's
 *    screen position and scales with apparent distance, so "skeleton on the
 *    right → avatar on the right" (see `rigBodyTransform`).
 *  - HANDS (`state.hands[].world`, 21 metric joints/hand): the hand bone's full
 *    orientation follows the palm (turn your palm → the avatar's palm turns),
 *    and all 30 finger bones curl. The hand stream is GPU-fast, so hands/fingers
 *    track much snappier than the ~13 fps CPU pose the arms ride.
 *
 * Left/right MIRRORS the user and is decided by IMAGE x (`state.pose` /
 * hand-landmark x), never MediaPipe's anatomical L/R label — the mirrored feed
 * would otherwise cross the limbs. Coordinate signs that depend on the
 * mirror/chirality are isolated in the `AXIS` / `HAND_AXIS` / `HAND_N_SIGN`
 * knobs so an on-device inversion is a one-character fix. Every extra behaviour
 * is behind a flag (FOLLOW_POSITION / DRIVE_HAND_ORIENT / DRIVE_FINGERS /
 * FAST_FOREARM) so any piece that misbehaves on hardware can be disabled alone.
 */

// --- feature flags -------------------------------------------------------
const FOLLOW_POSITION = true; // avatar translates + scales to the person's screen pos
const DRIVE_HAND_ORIENT = true; // hand bone follows the palm's 3D orientation
const DRIVE_FINGERS = true; // 30 finger bones curl from the hand skeleton
const FAST_FOREARM = true; // forearm tracks the fast hand stream, not slow pose

// --- smoothing time constants (s) — frame-rate-independent via damp() -----
// The body rides the ~13 fps CPU pose, so it can never beat that; but the
// client smoothing was adding a lot of the felt lag on top. These are cut low
// (snappier, a touch more stepping) since the user prioritised low delay.
const UPPER_ARM_TAU = 0.035; // was 0.06
const LOWER_ARM_TAU = 0.03; // rides the fast hand stream when FAST_FOREARM
const HAND_TAU = 0.04; // coarse wrist aim (pose fallback, no matched hand)
const HAND_ORIENT_TAU = 0.045; // palm orientation (fast hand stream)
const FINGER_TAU = 0.04; // finger curl (fast hand stream)
const SPINE_TAU = 0.04; // was 0.06
const LEG_TAU = 0.045;
const HEAD_TAU = 0.035; // was 0.05
const RELAX_TAU = 0.16; // ease a bone back to rest when its landmarks vanish
const BODY_MOVE_TAU = 0.055; // was 0.12 — root-follow was a big chunk of the "body delay"
const BODY_SCALE_TAU = 0.12; // was 0.25
// Max wrist deviation from rest (relative to the forearm) — caps the twist that
// otherwise collapses the mesh at the wrist.
const WRIST_MAX_RAD = (72 * Math.PI) / 180;

// --- gates / follow tuning ------------------------------------------------
const POSE_MIN_VIS = 0.25; // ignore pose landmarks below this visibility
const LEG_MIN_VIS = 0.4; // legs move only when actually seen
const HAND_SEEN_MS = 140; // ignore hands staler than this
const BODY_TRAVEL_FRAC = 0.45; // avatar traverses ±45% of the visible half-extent
const WSH_REF = 0.18; // nominal shoulder width (norm image) at framing distance
const SCALE_MIN = 0.86, SCALE_MAX = 1.18; // avatar zoom range with distance
const BLINK_PERIOD = 4.2; // s between blinks
const BLINK_LEN = 0.14; // s each blink lasts

// Current render-frame delta (s), refreshed at the top of each animate().
let _frameDt = 1 / 60;
/** First-order smoothing factor for this frame given a time constant `tau`. */
function damp(tau: number) {
  return 1 - Math.exp(-_frameDt / Math.max(tau, 1e-4));
}
const clamp = THREE.MathUtils.clamp;

// MediaPipe world axes (x image-right, y down, z away) → three.js (x right,
// y up, z toward viewer). Flip Y and Z. Separate knob for hands: MediaPipe's
// hand-world z sign may differ from pose-world; flip HAND_AXIS.z if the palm
// depth comes out inverted on device.
const AXIS = { x: 1, y: -1, z: -1 };
const HAND_AXIS = { x: 1, y: -1, z: -1 };
// Palm-normal chirality flips between a left and a right hand (and again with
// the mirror). Wrong sign shows the BACK of the hand where the palm should be.
// Confirm each side independently on device.
const HAND_N_SIGN: Record<"left" | "right", number> = { left: 1, right: -1 };

// MediaPipe pose landmark indices.
const NOSE = 0;
const L_SH = 11, R_SH = 12;
const L_HIP = 23, R_HIP = 24;
// Hand landmark indices used for the palm basis (wrist + finger MCP knuckles).
const H_WRIST = 0, H_INDEX_MCP = 5, H_MIDDLE_MCP = 9, H_PINKY_MCP = 17;

// A limb chain: joint landmark indices from root to tip.
interface Chain { a: number; b: number; c: number; tip: number }
const CHAIN_1: Chain = { a: 11, b: 13, c: 15, tip: 19 }; // shoulder/elbow/wrist/index
const CHAIN_2: Chain = { a: 12, b: 14, c: 16, tip: 20 };
const LEG_1 = { a: 23, b: 25, c: 27 }; // hip/knee/ankle
const LEG_2 = { a: 24, b: 26, c: 28 };

// A finger bone and the world-landmark segment it aims along.
interface FingerBone { bone: string; from: number; to: number }
function fingerBones(side: "left" | "right"): FingerBone[] {
  const s = side;
  return [
    { bone: s + "ThumbMetacarpal", from: 1, to: 2 },
    { bone: s + "ThumbProximal", from: 2, to: 3 },
    { bone: s + "ThumbDistal", from: 3, to: 4 },
    { bone: s + "IndexProximal", from: 5, to: 6 },
    { bone: s + "IndexIntermediate", from: 6, to: 7 },
    { bone: s + "IndexDistal", from: 7, to: 8 },
    { bone: s + "MiddleProximal", from: 9, to: 10 },
    { bone: s + "MiddleIntermediate", from: 10, to: 11 },
    { bone: s + "MiddleDistal", from: 11, to: 12 },
    { bone: s + "RingProximal", from: 13, to: 14 },
    { bone: s + "RingIntermediate", from: 14, to: 15 },
    { bone: s + "RingDistal", from: 15, to: 16 },
    { bone: s + "LittleProximal", from: 17, to: 18 },
    { bone: s + "LittleIntermediate", from: 18, to: 19 },
    { bone: s + "LittleDistal", from: 19, to: 20 },
  ];
}
const FINGERS_LEFT = fingerBones("left");
const FINGERS_RIGHT = fingerBones("right");

type Bones = Record<string, THREE.Object3D | null>;
interface Rest {
  restQuat: THREE.Quaternion; // bone's local rotation at rest
  childLocalPos: THREE.Vector3; // unit direction toward its child, bone-local
}
interface Rig {
  vrm: VRM;
  bones: Bones;
  rest: Record<string, Rest>;
  restHead: THREE.Quaternion;
  /** constant palm-basis→hand-bone offset, per hand (for orientation) */
  handRest: { left?: THREE.Quaternion; right?: THREE.Quaternion };
  /** camera half-extents at the avatar plane + the chest height (scale pivot) */
  frame: { wh: number; hh: number; pivotY: number };
}

// Scratch reused every frame (the rig runs at display rate — no allocation).
const _pq = new THREE.Quaternion();
const _rw = new THREE.Quaternion();
const _delta = new THREE.Quaternion();
const _world = new THREE.Quaternion();
const _local = new THREE.Quaternion();
const _qBasis = new THREE.Quaternion();
const _restDir = new THREE.Vector3();
const _target = new THREE.Vector3();
const _pos = new THREE.Vector3();
// Private scratch for the vector/basis helpers — never passed in as `out`.
const _s0 = new THREE.Vector3();
const _s1 = new THREE.Vector3();
const _f = new THREE.Vector3();
const _n = new THREE.Vector3();
const _sv = new THREE.Vector3();
const _uv = new THREE.Vector3();
const _mat = new THREE.Matrix4();
// Palm-basis input points.
const _P0 = new THREE.Vector3();
const _P5 = new THREE.Vector3();
const _P9 = new THREE.Vector3();
const _P17 = new THREE.Vector3();
// Caller-facing scratch.
const _p = new THREE.Vector3();
const _q = new THREE.Vector3();
const _dir = new THREE.Vector3();

/** Map a MediaPipe pose-world landmark into three.js world space. */
function toThree(v: Vec3, out: THREE.Vector3) {
  return out.set(v[0] * AXIS.x, v[1] * AXIS.y, v[2] * AXIS.z);
}
/** Map a MediaPipe hand-world landmark into three.js world space. */
function toThreeHand(v: Vec3, out: THREE.Vector3) {
  return out.set(v[0] * HAND_AXIS.x, v[1] * HAND_AXIS.y, v[2] * HAND_AXIS.z);
}

/** World-space direction from pose landmark i to j (into `out`). */
function segDir(W: PoseWorld, i: number, j: number, out: THREE.Vector3) {
  toThree(W[j], _s0);
  toThree(W[i], _s1);
  return out.subVectors(_s0, _s1);
}
/** World-space direction from hand landmark i to j (into `out`). */
function segDirHand(W: Vec3[], i: number, j: number, out: THREE.Vector3) {
  toThreeHand(W[j], _s0);
  toThreeHand(W[i], _s1);
  return out.subVectors(_s0, _s1);
}
/** Midpoint of pose landmarks i and j in three.js world space (into `out`). */
function midPoint(W: PoseWorld, i: number, j: number, out: THREE.Vector3) {
  toThree(W[i], _s0);
  toThree(W[j], _s1);
  return out.addVectors(_s0, _s1).multiplyScalar(0.5);
}

const vis = (pose: PoseState, i: number) => (pose[i] ? pose[i][2] : 0);

/**
 * Build a right-handed orthonormal palm frame from four hand points (wrist,
 * index-MCP, middle-MCP, pinky-MCP) into `out` (a world quaternion). forward =
 * wrist→middle-MCP (the finger axis, matching the hand bone's rest child-dir);
 * `nSign` picks which face is the palm. (s,u,f) is always proper (det +1) so
 * `setFromRotationMatrix` is valid; a wrong `nSign` only rolls it 180° about
 * the finger axis — that's the per-hand knob to confirm on device.
 */
function palmBasis(
  p0: THREE.Vector3, p5: THREE.Vector3, p9: THREE.Vector3, p17: THREE.Vector3,
  nSign: number, out: THREE.Quaternion,
): boolean {
  _f.subVectors(p9, p0);
  if (_f.lengthSq() < 1e-10) return false;
  _f.normalize();
  _s0.subVectors(p5, p0);
  _s1.subVectors(p17, p0);
  _n.crossVectors(_s0, _s1);
  if (_n.lengthSq() < 1e-10) return false;
  _n.normalize().multiplyScalar(nSign);
  _sv.crossVectors(_n, _f).normalize();
  _uv.crossVectors(_f, _sv);
  _mat.makeBasis(_sv, _uv, _f);
  out.setFromRotationMatrix(_mat);
  return true;
}

/** Palm basis from a hand's world landmarks (mapped into three.js). */
function palmBasisFromWorld(W: Vec3[], nSign: number, out: THREE.Quaternion): boolean {
  if (!W[H_WRIST] || !W[H_INDEX_MCP] || !W[H_MIDDLE_MCP] || !W[H_PINKY_MCP]) return false;
  toThreeHand(W[H_WRIST], _P0);
  toThreeHand(W[H_INDEX_MCP], _P5);
  toThreeHand(W[H_MIDDLE_MCP], _P9);
  toThreeHand(W[H_PINKY_MCP], _P17);
  return palmBasis(_P0, _P5, _P9, _P17, nSign, out);
}

/**
 * Aim bone `name` so its rest child-direction points along `dirWorld`. Solves
 * in world space then converts to local, so children follow already-rotated
 * parents. Minimal rotation from rest → preserves rest roll, no 180° flip.
 */
function aimBone(rig: Rig, name: string, dirWorld: THREE.Vector3, alpha: number) {
  const bone = rig.bones[name];
  const r = rig.rest[name];
  if (!bone || !bone.parent || !r || dirWorld.lengthSq() < 1e-9) return;
  bone.parent.getWorldQuaternion(_pq);
  _rw.copy(_pq).multiply(r.restQuat); // this bone's current rest world quat
  _restDir.copy(r.childLocalPos).applyQuaternion(_rw).normalize();
  _target.copy(dirWorld).normalize();
  _delta.setFromUnitVectors(_restDir, _target); // world rotation rest→target
  _world.copy(_delta).multiply(_rw); // desired world quat
  _local.copy(_pq).invert().multiply(_world); // back into local space
  bone.quaternion.slerp(_local, alpha);
}

/** Set bone `name` to a full WORLD orientation (via a captured palm→bone
 *  offset), converting to local through the parent. */
function orientBone(
  rig: Rig, name: string, qBasisWorld: THREE.Quaternion,
  palmToBone: THREE.Quaternion | undefined, alpha: number,
) {
  const bone = rig.bones[name];
  const r = rig.rest[name];
  if (!bone || !bone.parent || !palmToBone) return;
  bone.parent.getWorldQuaternion(_pq);
  _world.copy(qBasisWorld).multiply(palmToBone); // desired bone world quat
  _local.copy(_pq).invert().multiply(_world); // hand rotation relative to forearm
  // Clamp how far the wrist may deviate from its rest pose. An unbounded wrist
  // twist (no forearm-twist bone to absorb it) collapses the skin to a point —
  // the "candy-wrapper" that splits the wrist into two lobes with a node.
  if (r) {
    const dot = THREE.MathUtils.clamp(Math.abs(r.restQuat.dot(_local)), 0, 1);
    const ang = 2 * Math.acos(dot);
    if (ang > WRIST_MAX_RAD) {
      _qBasis.copy(_local); // target
      _local.copy(r.restQuat).slerp(_qBasis, WRIST_MAX_RAD / ang);
    }
  }
  bone.quaternion.slerp(_local, alpha);
}

/** Ease a bone back toward its captured rest rotation. */
function restBone(rig: Rig, name: string, alpha: number) {
  const b = rig.bones[name];
  const r = rig.rest[name];
  if (b && r) b.quaternion.slerp(r.restQuat, alpha);
}

/** Torso: aim the spine from hips-midpoint toward shoulders-midpoint (full-3D
 *  lean, incl. toward/away from camera). Needs both shoulders + both hips. */
function rigSpine(rig: Rig, pose: PoseState, W: PoseWorld) {
  const okSh = vis(pose, L_SH) >= POSE_MIN_VIS && vis(pose, R_SH) >= POSE_MIN_VIS;
  const okHip = vis(pose, L_HIP) >= POSE_MIN_VIS && vis(pose, R_HIP) >= POSE_MIN_VIS;
  if (!okSh || !okHip) {
    restBone(rig, "spine", damp(RELAX_TAU));
    return;
  }
  midPoint(W, L_SH, R_SH, _p);
  midPoint(W, L_HIP, R_HIP, _q);
  _dir.subVectors(_p, _q);
  aimBone(rig, "spine", _dir, damp(SPINE_TAU));
}

/** One arm: upper (shoulder→elbow, pose), lower (elbow→wrist), hand. When a
 *  hand is matched, the forearm rides the FAST hand stream and the hand bone is
 *  driven by orientation (B) instead of the coarse pose aim. */
function rigArm(
  rig: Rig, upper: string, lower: string, hand: string,
  ch: Chain, pose: PoseState, W: PoseWorld, sideHand: HandState | undefined,
) {
  // Upper arm — always pose (shoulder + elbow are pose-only landmarks).
  if (vis(pose, ch.a) >= POSE_MIN_VIS && vis(pose, ch.b) >= POSE_MIN_VIS) {
    aimBone(rig, upper, segDir(W, ch.a, ch.b, _dir), damp(UPPER_ARM_TAU));
  } else {
    restBone(rig, upper, damp(RELAX_TAU));
  }

  // Lower arm — fast (hand-rate screen plane + slow pose depth) when a hand is
  // matched, else the slow pose elbow→wrist.
  const fastWrist =
    FAST_FOREARM && sideHand?.landmarks?.[H_WRIST] && vis(pose, ch.b) >= POSE_MIN_VIS;
  if (fastWrist) {
    const e = pose[ch.b];
    const wrist2D = sideHand!.landmarks![H_WRIST];
    segDir(W, ch.b, ch.c, _p); // pose elbow→wrist (three space) for scale + depth
    const screenLen = Math.hypot(_p.x, _p.y);
    const d2x = wrist2D[0] - e[0];
    const d2y = wrist2D[1] - e[1];
    const m2 = Math.hypot(d2x, d2y);
    if (m2 > 1e-4) {
      const k = screenLen / m2; // scale the norm-image delta to the pose metric
      _dir.set(k * d2x, -k * d2y, _p.z); // image y down → three up; depth from pose
      aimBone(rig, lower, _dir, damp(LOWER_ARM_TAU));
    } else {
      aimBone(rig, lower, _p, damp(LOWER_ARM_TAU));
    }
  } else if (vis(pose, ch.b) >= POSE_MIN_VIS && vis(pose, ch.c) >= POSE_MIN_VIS) {
    aimBone(rig, lower, segDir(W, ch.b, ch.c, _dir), damp(UPPER_ARM_TAU));
  } else {
    restBone(rig, lower, damp(RELAX_TAU));
  }

  // Coarse hand aim — only when orientation (B) isn't driving this hand.
  const handDriven = !!sideHand && DRIVE_HAND_ORIENT && !!sideHand.world;
  if (!handDriven) {
    if (vis(pose, ch.c) >= POSE_MIN_VIS && vis(pose, ch.tip) >= POSE_MIN_VIS) {
      aimBone(rig, hand, segDir(W, ch.c, ch.tip, _dir), damp(HAND_TAU));
    } else {
      restBone(rig, hand, damp(RELAX_TAU));
    }
  }
}

/** One leg: hip→knee→ankle, gated harder (usually off the head-to-hips shot). */
function rigLeg(
  rig: Rig, upper: string, lower: string,
  leg: { a: number; b: number; c: number }, pose: PoseState, W: PoseWorld,
) {
  if (vis(pose, leg.a) >= LEG_MIN_VIS && vis(pose, leg.b) >= LEG_MIN_VIS) {
    aimBone(rig, upper, segDir(W, leg.a, leg.b, _dir), damp(LEG_TAU));
  } else {
    restBone(rig, upper, damp(RELAX_TAU));
  }
  if (vis(pose, leg.b) >= LEG_MIN_VIS && vis(pose, leg.c) >= LEG_MIN_VIS) {
    aimBone(rig, lower, segDir(W, leg.b, leg.c, _dir), damp(LEG_TAU));
  } else {
    restBone(rig, lower, damp(RELAX_TAU));
  }
}

interface HandBySide { left?: HandState; right?: HandState }

function rigBody(rig: Rig, pose: PoseState, W: PoseWorld, hands: HandBySide) {
  if (!pose[L_SH] || !pose[R_SH] || !pose[L_HIP] || !pose[R_HIP] || W.length < 33) {
    relaxBody(rig);
    return;
  }
  rigSpine(rig, pose, W);
  // Mirror by IMAGE x: the shoulder on the screen RIGHT (larger x) drives the
  // avatar's LEFT arm (avatar faces us). Label-agnostic → can't cross.
  const rightChain = pose[L_SH][0] >= pose[R_SH][0] ? CHAIN_1 : CHAIN_2;
  const leftChain = pose[L_SH][0] >= pose[R_SH][0] ? CHAIN_2 : CHAIN_1;
  rigArm(rig, "leftUpperArm", "leftLowerArm", "leftHand", rightChain, pose, W, hands.left);
  rigArm(rig, "rightUpperArm", "rightLowerArm", "rightHand", leftChain, pose, W, hands.right);
  const rightLeg = pose[L_HIP][0] >= pose[R_HIP][0] ? LEG_1 : LEG_2;
  const leftLeg = pose[L_HIP][0] >= pose[R_HIP][0] ? LEG_2 : LEG_1;
  rigLeg(rig, "leftUpperLeg", "leftLowerLeg", rightLeg, pose, W);
  rigLeg(rig, "rightUpperLeg", "rightLowerLeg", leftLeg, pose, W);
}

/** Hand bone follows the palm's full 3D orientation. */
function rigHandOrientation(rig: Rig, side: "left" | "right", hand: HandState, alpha: number) {
  const W = hand.world;
  if (!W || !palmBasisFromWorld(W, HAND_N_SIGN[side], _qBasis)) return;
  orientBone(rig, side + "Hand", _qBasis, rig.handRest[side], alpha);
}

/** 15 finger bones per hand curl along their own segments (parent-first). */
function rigFingers(rig: Rig, side: "left" | "right", hand: HandState, alpha: number) {
  const W = hand.world;
  if (!W) {
    relaxFingers(rig, side);
    return;
  }
  const fingers = side === "left" ? FINGERS_LEFT : FINGERS_RIGHT;
  for (const f of fingers) {
    if (W[f.from] && W[f.to]) {
      aimBone(rig, f.bone, segDirHand(W, f.from, f.to, _dir), alpha);
    } else {
      restBone(rig, f.bone, damp(RELAX_TAU));
    }
  }
}

function relaxFingers(rig: Rig, side: "left" | "right") {
  const fingers = side === "left" ? FINGERS_LEFT : FINGERS_RIGHT;
  for (const f of fingers) restBone(rig, f.bone, damp(RELAX_TAU));
}

/** Root follow: translate `vrm.scene` to the person's screen position and scale
 *  it with apparent size. Moves `vrm.scene` (one parent of the whole rig), NOT
 *  the humanoid-managed `hips`. */
function rigBodyTransform(rig: Rig, pose: PoseState | null) {
  let tx = 0, ty = 0, sTarget = 1;
  const ls = pose?.[L_SH];
  const rs = pose?.[R_SH];
  if (ls && rs && ls[2] >= POSE_MIN_VIS && rs[2] >= POSE_MIN_VIS) {
    const u = (ls[0] + rs[0]) / 2 - 0.5; // + = image right = screen right
    const v = (ls[1] + rs[1]) / 2 - 0.5; // + = image down
    const cx = rig.frame.wh * BODY_TRAVEL_FRAC;
    const cy = rig.frame.hh * BODY_TRAVEL_FRAC;
    tx = clamp(u * 2 * cx, -cx, cx);
    ty = clamp(-v * 2 * cy, -cy, cy); // image down → three up
    const wsh = Math.abs(ls[0] - rs[0]);
    sTarget = clamp(wsh / WSH_REF, SCALE_MIN, SCALE_MAX);
  }
  const s = THREE.MathUtils.lerp(rig.vrm.scene.scale.x, sTarget, damp(BODY_SCALE_TAU));
  rig.vrm.scene.scale.setScalar(s);
  // Scale about the CHEST, not the scene origin (feet): otherwise scaling up
  // grows the avatar upward and pushes the head out of frame. Adding
  // pivotY·(1−s) to y keeps the chest fixed while the avatar zooms.
  _pos.set(tx, ty + rig.frame.pivotY * (1 - s), 0);
  rig.vrm.scene.position.lerp(_pos, damp(BODY_MOVE_TAU));
}

function relaxBody(rig: Rig) {
  for (const name of Object.keys(rig.rest)) restBone(rig, name, damp(RELAX_TAU));
}

function rigHead(rig: Rig, pose: PoseState) {
  const nose = pose[NOSE];
  const ls = pose[L_SH];
  const rs = pose[R_SH];
  const head = rig.bones.head;
  if (!head || !nose || !ls || !rs || nose[2] < POSE_MIN_VIS) return;
  const midx = (ls[0] + rs[0]) / 2;
  const midy = (ls[1] + rs[1]) / 2;
  const yaw = Math.max(-0.5, Math.min(0.5, (nose[0] - midx) * 3.2));
  const pitch = Math.max(-0.3, Math.min(0.35, (nose[1] - midy + 0.16) * 1.8));
  const target = rig.restHead
    .clone()
    .multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(pitch, yaw, 0, "YXZ")));
  head.quaternion.slerp(target, damp(HEAD_TAU));
}

function rigFace(rig: Rig, mouth: number, tSec: number) {
  const em = rig.vrm.expressionManager;
  if (!em) return;
  em.setValue("aa", Math.min(Math.max(mouth, 0), 1));
  em.setValue("happy", 0.25);
  const phase = tSec % BLINK_PERIOD;
  const blink = phase < BLINK_LEN ? 1 - Math.abs(phase / BLINK_LEN - 0.5) * 2 : 0;
  em.setValue("blink", blink);
}

/** Match each detected hand to the avatar's left/right by IMAGE x (mirror rule,
 *  same as the body). The larger image-x → avatar LEFT (its left is our right).
 *  handedness label is not trusted (unreliable on the flipped feed). */
function matchHands(hands: HandState[], frameW: number): HandBySide {
  const usable = hands.filter(
    (h) => h.world && h.seen_ms < HAND_SEEN_MS && (h.landmarks?.[H_WRIST] || h.cursor),
  );
  if (usable.length === 0) return {};
  const imgX = (h: HandState) => h.landmarks?.[H_WRIST]?.[0] ?? h.cursor[0] / frameW;
  if (usable.length === 1) {
    return imgX(usable[0]) > 0.5 ? { left: usable[0] } : { right: usable[0] };
  }
  usable.sort((a, b) => imgX(a) - imgX(b));
  return { right: usable[0], left: usable[usable.length - 1] };
}

// Each driven bone → candidate child bones whose rest position defines its
// aim axis (first present wins; absent bones are skipped).
const CHILD_CANDIDATES: Record<string, VRMHumanBoneName[]> = {
  spine: ["chest", "upperChest", "neck"],
  leftUpperArm: ["leftLowerArm"],
  leftLowerArm: ["leftHand"],
  rightUpperArm: ["rightLowerArm"],
  rightLowerArm: ["rightHand"],
  leftHand: ["leftMiddleProximal", "leftIndexProximal", "leftRingProximal"],
  rightHand: ["rightMiddleProximal", "rightIndexProximal", "rightRingProximal"],
  leftUpperLeg: ["leftLowerLeg"],
  leftLowerLeg: ["leftFoot"],
  rightUpperLeg: ["rightLowerLeg"],
  rightLowerLeg: ["rightFoot"],
};
// Finger bones aim at the next bone in their chain; distals have no humanoid
// child (handled by inheriting the intermediate's axis after rest capture).
const FINGER_SUFFIXES = [
  "ThumbMetacarpal", "ThumbProximal", "ThumbDistal",
  "IndexProximal", "IndexIntermediate", "IndexDistal",
  "MiddleProximal", "MiddleIntermediate", "MiddleDistal",
  "RingProximal", "RingIntermediate", "RingDistal",
  "LittleProximal", "LittleIntermediate", "LittleDistal",
];
const DISTAL_PARENT: Record<string, string> = {
  ThumbDistal: "ThumbProximal",
  IndexDistal: "IndexIntermediate",
  MiddleDistal: "MiddleIntermediate",
  RingDistal: "RingIntermediate",
  LittleDistal: "LittleIntermediate",
};
for (const side of ["left", "right"] as const) {
  CHILD_CANDIDATES[side + "ThumbMetacarpal"] = [side + "ThumbProximal"] as VRMHumanBoneName[];
  CHILD_CANDIDATES[side + "ThumbProximal"] = [side + "ThumbDistal"] as VRMHumanBoneName[];
  for (const f of ["Index", "Middle", "Ring", "Little"]) {
    CHILD_CANDIDATES[side + f + "Proximal"] = [side + f + "Intermediate"] as VRMHumanBoneName[];
    CHILD_CANDIDATES[side + f + "Intermediate"] = [side + f + "Distal"] as VRMHumanBoneName[];
  }
}

interface Props {
  pairRef: React.RefObject<SnapshotPair | null>;
  frameW: number;
  frameH: number;
}

export function VrmAvatar({ pairRef, frameW, frameH }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current!;
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setClearColor(0x000000, 0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
    renderer.setSize(frameW, frameH, false);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(28, frameW / frameH, 0.1, 20);
    camera.position.set(0, 1.28, 1.55);
    camera.lookAt(0, 1.18, 0);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x556074, 1.6));
    const dir = new THREE.DirectionalLight(0xffffff, 1.1);
    dir.position.set(0.6, 1.4, 1.2);
    scene.add(dir);

    let rig: Rig | null = null;
    let raf = 0;
    let disposed = false;
    let lastT = performance.now();

    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    loader.load(
      "/avatar.vrm",
      (gltf) => {
        if (disposed) return;
        const vrm = gltf.userData.vrm as VRM;
        VRMUtils.removeUnnecessaryVertices(gltf.scene);
        VRMUtils.combineSkeletons(gltf.scene);
        VRMUtils.rotateVRM0(vrm); // VRM0 models -> face the camera consistently
        vrm.scene.traverse((o) => {
          o.frustumCulled = false;
        });
        scene.add(vrm.scene);
        vrm.update(0);
        vrm.scene.updateMatrixWorld(true);

        const get = (n: VRMHumanBoneName) => vrm.humanoid.getNormalizedBoneNode(n);
        const bones: Bones = {
          head: get("head"),
          neck: get("neck"),
          spine: get("spine"),
          chest: get("chest"),
          upperChest: get("upperChest"),
          leftUpperArm: get("leftUpperArm"),
          leftLowerArm: get("leftLowerArm"),
          leftHand: get("leftHand"),
          rightUpperArm: get("rightUpperArm"),
          rightLowerArm: get("rightLowerArm"),
          rightHand: get("rightHand"),
          leftUpperLeg: get("leftUpperLeg"),
          leftLowerLeg: get("leftLowerLeg"),
          rightUpperLeg: get("rightUpperLeg"),
          rightLowerLeg: get("rightLowerLeg"),
        };
        for (const side of ["left", "right"] as const) {
          for (const suf of FINGER_SUFFIXES) {
            bones[side + suf] = get((side + suf) as VRMHumanBoneName);
          }
        }

        // Capture each driven bone's rest rotation + unit child direction.
        const rest: Record<string, Rest> = {};
        for (const [bone, children] of Object.entries(CHILD_CANDIDATES)) {
          const b = bones[bone];
          if (!b) continue;
          const child = children.map(get).find((c) => c && c.position.lengthSq() > 1e-8);
          if (!child) continue;
          rest[bone] = {
            restQuat: b.quaternion.clone(),
            childLocalPos: child.position.clone().normalize(),
          };
        }
        // Distal finger bones have no humanoid child → inherit the intermediate's
        // pointing axis (fingers are ~straight at rest).
        for (const side of ["left", "right"] as const) {
          for (const [distal, parent] of Object.entries(DISTAL_PARENT)) {
            const db = bones[side + distal];
            const pr = rest[side + parent];
            if (db && pr && !rest[side + distal]) {
              rest[side + distal] = {
                restQuat: db.quaternion.clone(),
                childLocalPos: pr.childLocalPos.clone(),
              };
            }
          }
        }
        const restHead = bones.head?.quaternion.clone() ?? new THREE.Quaternion();

        // Per-hand palm→bone offset: absorbs the model's rest hand axis so the
        // runtime palm basis maps straight onto the bone.
        const handRest: Rig["handRest"] = {};
        for (const side of ["left", "right"] as const) {
          const handB = bones[side + "Hand"];
          const idx = get((side + "IndexProximal") as VRMHumanBoneName);
          const mid = get((side + "MiddleProximal") as VRMHumanBoneName);
          const lit = get((side + "LittleProximal") as VRMHumanBoneName);
          if (handB && idx && mid && lit) {
            handB.getWorldPosition(_P0);
            idx.getWorldPosition(_P5);
            mid.getWorldPosition(_P9);
            lit.getWorldPosition(_P17);
            const qBasisRest = new THREE.Quaternion();
            if (palmBasis(_P0, _P5, _P9, _P17, HAND_N_SIGN[side], qBasisRest)) {
              const qBoneRest = new THREE.Quaternion();
              handB.getWorldQuaternion(qBoneRest);
              handRest[side] = qBasisRest.invert().multiply(qBoneRest);
            }
          }
        }

        // Frame the upper body wide enough that raised arms stay on-screen, and
        // capture the visible half-extents for the root-follow mapping.
        const headPos = new THREE.Vector3();
        bones.head?.getWorldPosition(headPos);
        const hipsPos = new THREE.Vector3();
        get("hips")?.getWorldPosition(hipsPos);
        let lookY = 1.18;
        if (headPos.y > 0) {
          const span = Math.max(headPos.y - hipsPos.y, 0.4);
          lookY = (headPos.y + hipsPos.y) / 2;
          // Pull back beyond a tight head-to-knee frame (was 4.6) to leave
          // margin for the root-follow translation + distance scale.
          camera.position.set(0, headPos.y - 0.06, span * 5.6);
          camera.lookAt(0, lookY, 0);
        }
        const camDist = camera.position.distanceTo(_pos.set(0, lookY, 0));
        const hh = camDist * Math.tan(THREE.MathUtils.degToRad(14)); // fov 28 → half 14°
        const wh = hh * (frameW / frameH);

        rig = { vrm, bones, rest, restHead, handRest, frame: { wh, hh, pivotY: lookY } };
        setVrmReady(true);
      },
      undefined,
      (err: unknown) => {
        console.warn("VRM load failed", err);
        setVrmReady(false);
      },
    );

    const animate = () => {
      raf = requestAnimationFrame(animate);
      const now = performance.now();
      const dt = Math.min((now - lastT) / 1000, 0.05);
      lastT = now;
      _frameDt = dt; // feed the frame-rate-independent smoothing (damp())
      const tSec = now / 1000;

      if (rig) {
        const pair = pairRef.current;
        const state: AppState | null = pair ? interpolate(pair, now) : null;
        const vt = state?.objects.find((o): o is VtuberObject => o.type === "vtuber");
        rigFace(rig, vt?.mouth ?? 0, tSec);
        if (state?.pose) rigHead(rig, state.pose);

        const hands = state?.hands ? matchHands(state.hands, frameW) : {};
        if (state?.pose && state.pose_world) {
          rigBody(rig, state.pose, state.pose_world, hands);
        } else {
          relaxBody(rig);
        }

        // Hands ride the fast hand stream (snappier than the pose-bound arms).
        for (const side of ["left", "right"] as const) {
          const h = hands[side];
          if (h?.world) {
            if (DRIVE_HAND_ORIENT) rigHandOrientation(rig, side, h, damp(HAND_ORIENT_TAU));
            if (DRIVE_FINGERS) rigFingers(rig, side, h, damp(FINGER_TAU));
          } else if (DRIVE_FINGERS) {
            relaxFingers(rig, side);
          }
        }

        if (FOLLOW_POSITION) rigBodyTransform(rig, state?.pose ?? null);
        rig.vrm.update(dt);
      }
      renderer.render(scene, camera);
    };
    raf = requestAnimationFrame(animate);

    return () => {
      disposed = true;
      setVrmReady(false);
      cancelAnimationFrame(raf);
      if (rig) VRMUtils.deepDispose(rig.vrm.scene);
      renderer.dispose();
    };
  }, [pairRef, frameW, frameH]);

  return <canvas ref={canvasRef} className="layer" width={frameW} height={frameH} />;
}
