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
import type { AppState, PoseState, PoseWorld, VtuberObject } from "../state/types";
import type { SnapshotPair } from "../state/useAppState";
import { setVrmReady } from "./vrmState";

/**
 * Open-source VRM vtuber avatar (CC0 model "Sendagaya Shino" from
 * madjin/vrm-samples, at /avatar.vrm), rendered with three.js +
 * @pixiv/three-vrm as a WebGL layer. Mounted only while a vtuber object is
 * present (see App.tsx). Until the model is live, overlay/scene.ts shows a
 * loading spinner (no placeholder puppet).
 *
 * Rigging is a FULL-3D bone mapping driven by MediaPipe's metric world
 * skeleton (`state.pose_world`, meters, origin at hips). For each humanoid
 * bone we take the direction of its body segment (shoulder→elbow, elbow→wrist,
 * hip→knee, …) in 3D and rotate the bone so its REST child-direction aligns
 * with that target (`setFromUnitVectors`) — a minimal-rotation solve, not a
 * single-axis swing, so the avatar reaches toward the camera, twists, and
 * bends every joint instead of just leaning in the screen plane. Bones are
 * solved parent-first (spine → upper arm → lower arm → hand) so each child
 * follows its already-rotated parent.
 *
 * Left/right MIRRORS the user (raise a hand, the avatar raises the hand on the
 * same side of the screen). We decide the mapping by the shoulders' IMAGE x
 * (`state.pose`), not MediaPipe's anatomical L/R label, so the mirrored feed
 * never crosses the arms. The 2D `pose` still drives the head; the mouth opens
 * with the pinch. Body pose only exists while HALL_POSE is on — the backend
 * turns it on automatically when Vtuber is selected (ui.wants_pose()).
 */

// --- rig tuning knobs ----------------------------------------------------
const ARM_DAMP = 0.45; // slerp toward the target each frame (higher = snappier)
const HAND_DAMP = 0.35;
const SPINE_DAMP = 0.18;
const LEG_DAMP = 0.3;
const HEAD_DAMP = 0.3;
const RELAX_DAMP = 0.1; // ease a bone back to rest when its landmarks vanish
const POSE_MIN_VIS = 0.25; // ignore landmarks below this visibility
const LEG_MIN_VIS = 0.55; // legs are usually out of frame — demand more before moving
const BLINK_PERIOD = 4.2; // s between blinks
const BLINK_LEN = 0.14; // s each blink lasts

// MediaPipe world axes (x image-right, y down, z away from camera) → three.js
// (x right, y up, z toward viewer). Flip Y and Z. Sign knobs kept explicit so
// a mirror/depth inversion is a one-character change.
const AXIS = { x: 1, y: -1, z: -1 };

// MediaPipe pose landmark indices.
const NOSE = 0;
const L_SH = 11, R_SH = 12;
const L_HIP = 23, R_HIP = 24;

// A limb chain: joint landmark indices from root to tip.
interface Chain { a: number; b: number; c: number; tip: number }
const CHAIN_1: Chain = { a: 11, b: 13, c: 15, tip: 19 }; // shoulder/elbow/wrist/index
const CHAIN_2: Chain = { a: 12, b: 14, c: 16, tip: 20 };
const LEG_1 = { a: 23, b: 25, c: 27 }; // hip/knee/ankle
const LEG_2 = { a: 24, b: 26, c: 28 };

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
}

// Scratch objects reused every frame (rig runs at display rate — no per-frame
// allocation).
const _pq = new THREE.Quaternion();
const _rw = new THREE.Quaternion();
const _delta = new THREE.Quaternion();
const _world = new THREE.Quaternion();
const _local = new THREE.Quaternion();
const _restDir = new THREE.Vector3();
const _target = new THREE.Vector3();
// Private scratch for the vector helpers below — never passed in as `out`, so
// a caller can hold two helper results live at once without aliasing.
const _s0 = new THREE.Vector3();
const _s1 = new THREE.Vector3();
// Caller-facing scratch.
const _p = new THREE.Vector3();
const _q = new THREE.Vector3();
const _dir = new THREE.Vector3();

/** Map a MediaPipe world landmark [x,y,z] into three.js world space. */
function toThree(v: [number, number, number], out: THREE.Vector3) {
  return out.set(v[0] * AXIS.x, v[1] * AXIS.y, v[2] * AXIS.z);
}

/** World-space direction from landmark i to landmark j (into `out`). */
function segDir(W: PoseWorld, i: number, j: number, out: THREE.Vector3) {
  toThree(W[j], _s0);
  toThree(W[i], _s1);
  return out.subVectors(_s0, _s1);
}

/** Midpoint of landmarks i and j in three.js world space (into `out`). */
function midPoint(W: PoseWorld, i: number, j: number, out: THREE.Vector3) {
  toThree(W[i], _s0);
  toThree(W[j], _s1);
  return out.addVectors(_s0, _s1).multiplyScalar(0.5);
}

const vis = (pose: PoseState, i: number) => (pose[i] ? pose[i][2] : 0);

/**
 * Orient bone `name` so its segment points along `dirWorld` (a direction in
 * three.js world space). Works entirely in world space then converts back to
 * the bone's local frame, so it's immune to the parent chain's current pose —
 * as long as parents are solved first, children follow. The delta is measured
 * from the bone's REST world direction, preserving the model's rest roll (no
 * arbitrary twist), and it's the minimal rotation (`setFromUnitVectors`), so
 * there's no 180° flip.
 */
function aimBone(rig: Rig, name: string, dirWorld: THREE.Vector3, damp: number) {
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
  bone.quaternion.slerp(_local, damp);
}

/** Ease a bone back toward its captured rest rotation. */
function restBone(rig: Rig, name: string, damp: number) {
  const b = rig.bones[name];
  const r = rig.rest[name];
  if (b && r) b.quaternion.slerp(r.restQuat, damp);
}

/** Torso: aim the spine from the hips-midpoint toward the shoulders-midpoint
 *  — a full-3D lean (side, and toward/away from camera) rather than a flat
 *  screen-plane tilt. Needs both shoulders and both hips in view. */
function rigSpine(rig: Rig, pose: PoseState, W: PoseWorld) {
  const okSh = vis(pose, L_SH) >= POSE_MIN_VIS && vis(pose, R_SH) >= POSE_MIN_VIS;
  const okHip = vis(pose, L_HIP) >= POSE_MIN_VIS && vis(pose, R_HIP) >= POSE_MIN_VIS;
  if (!okSh || !okHip) {
    restBone(rig, "spine", RELAX_DAMP);
    return;
  }
  midPoint(W, L_SH, R_SH, _p);
  midPoint(W, L_HIP, R_HIP, _q);
  _dir.subVectors(_p, _q);
  aimBone(rig, "spine", _dir, SPINE_DAMP);
}

/** One arm: upper (shoulder→elbow), lower (elbow→wrist), hand (wrist→index).
 *  Each segment relaxes individually when its landmarks drop below threshold. */
function rigArm(
  rig: Rig,
  upper: string,
  lower: string,
  hand: string,
  ch: Chain,
  pose: PoseState,
  W: PoseWorld,
) {
  if (vis(pose, ch.a) >= POSE_MIN_VIS && vis(pose, ch.b) >= POSE_MIN_VIS) {
    aimBone(rig, upper, segDir(W, ch.a, ch.b, _dir), ARM_DAMP);
  } else {
    restBone(rig, upper, RELAX_DAMP);
  }
  if (vis(pose, ch.b) >= POSE_MIN_VIS && vis(pose, ch.c) >= POSE_MIN_VIS) {
    aimBone(rig, lower, segDir(W, ch.b, ch.c, _dir), ARM_DAMP);
  } else {
    restBone(rig, lower, RELAX_DAMP);
  }
  // Wrist bend follows the pose's index knuckle — coarse (fingers come from the
  // hand detector, not pose), but enough to stop a stiff, frozen hand.
  if (vis(pose, ch.c) >= POSE_MIN_VIS && vis(pose, ch.tip) >= POSE_MIN_VIS) {
    aimBone(rig, hand, segDir(W, ch.c, ch.tip, _dir), HAND_DAMP);
  } else {
    restBone(rig, hand, RELAX_DAMP);
  }
}

/** One leg: hip→knee→ankle. Gated harder than arms since the avatar is framed
 *  head-to-hips and the legs are usually off-screen / poorly seen. */
function rigLeg(
  rig: Rig,
  upper: string,
  lower: string,
  leg: { a: number; b: number; c: number },
  pose: PoseState,
  W: PoseWorld,
) {
  if (vis(pose, leg.a) >= LEG_MIN_VIS && vis(pose, leg.b) >= LEG_MIN_VIS) {
    aimBone(rig, upper, segDir(W, leg.a, leg.b, _dir), LEG_DAMP);
  } else {
    restBone(rig, upper, RELAX_DAMP);
  }
  if (vis(pose, leg.b) >= LEG_MIN_VIS && vis(pose, leg.c) >= LEG_MIN_VIS) {
    aimBone(rig, lower, segDir(W, leg.b, leg.c, _dir), LEG_DAMP);
  } else {
    restBone(rig, lower, RELAX_DAMP);
  }
}

function rigBody(rig: Rig, pose: PoseState, W: PoseWorld) {
  // Both feeds always carry 33 joints; bail defensively if a frame is short.
  if (!pose[L_SH] || !pose[R_SH] || !pose[L_HIP] || !pose[R_HIP] || W.length < 33) {
    relaxBody(rig);
    return;
  }
  rigSpine(rig, pose, W);
  // Mirror by IMAGE x: the shoulder on the screen RIGHT (larger x) drives the
  // avatar's LEFT arm (the avatar faces us, so its left is on our right). This
  // is label-agnostic, so the mirrored feed can't cross the arms.
  const rightChain = pose[L_SH][0] >= pose[R_SH][0] ? CHAIN_1 : CHAIN_2;
  const leftChain = pose[L_SH][0] >= pose[R_SH][0] ? CHAIN_2 : CHAIN_1;
  rigArm(rig, "leftUpperArm", "leftLowerArm", "leftHand", rightChain, pose, W);
  rigArm(rig, "rightUpperArm", "rightLowerArm", "rightHand", leftChain, pose, W);
  // Legs, same mirror-by-x rule.
  const rightLeg = pose[L_HIP][0] >= pose[R_HIP][0] ? LEG_1 : LEG_2;
  const leftLeg = pose[L_HIP][0] >= pose[R_HIP][0] ? LEG_2 : LEG_1;
  rigLeg(rig, "leftUpperLeg", "leftLowerLeg", rightLeg, pose, W);
  rigLeg(rig, "rightUpperLeg", "rightLowerLeg", leftLeg, pose, W);
}

function relaxBody(rig: Rig) {
  for (const name of Object.keys(rig.rest)) restBone(rig, name, 0.08);
}

function rigHead(rig: Rig, pose: PoseState) {
  const nose = pose[NOSE];
  const ls = pose[L_SH];
  const rs = pose[R_SH];
  const head = rig.bones.head;
  if (!head || !nose || !ls || !rs || nose[2] < POSE_MIN_VIS) return;
  const midx = (ls[0] + rs[0]) / 2;
  const midy = (ls[1] + rs[1]) / 2;
  // nose right of centre -> look screen-right (mirror). image y down.
  const yaw = Math.max(-0.5, Math.min(0.5, (nose[0] - midx) * 3.2));
  const pitch = Math.max(-0.3, Math.min(0.35, (nose[1] - midy + 0.16) * 1.8));
  const target = rig.restHead
    .clone()
    .multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(pitch, yaw, 0, "YXZ")));
  head.quaternion.slerp(target, HEAD_DAMP);
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

// Each driven bone and the candidate child bones whose rest position defines
// its "point-at" axis (first present wins — finger/leg bones may be absent).
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

        // Capture each driven bone's REST rotation + the unit direction toward
        // its child at rest. The rig rotates relative to these, so it works for
        // any model's rest pose. A bone whose child is missing stays undriven.
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
        const restHead = bones.head?.quaternion.clone() ?? new THREE.Quaternion();

        // Frame the upper body wide enough that raised arms stay on-screen.
        const headPos = new THREE.Vector3();
        bones.head?.getWorldPosition(headPos);
        const hipsPos = new THREE.Vector3();
        get("hips")?.getWorldPosition(hipsPos);
        if (headPos.y > 0) {
          const span = Math.max(headPos.y - hipsPos.y, 0.4);
          const chestY = (headPos.y + hipsPos.y) / 2;
          camera.position.set(0, headPos.y - 0.12, span * 4.6);
          camera.lookAt(0, chestY, 0);
        }

        rig = { vrm, bones, rest, restHead };
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
      const tSec = now / 1000;

      if (rig) {
        const pair = pairRef.current;
        const state: AppState | null = pair ? interpolate(pair, now) : null;
        const vt = state?.objects.find((o): o is VtuberObject => o.type === "vtuber");
        rigFace(rig, vt?.mouth ?? 0, tSec);
        if (state?.pose) rigHead(rig, state.pose);
        if (state?.pose && state.pose_world) {
          rigBody(rig, state.pose, state.pose_world);
        } else {
          relaxBody(rig);
        }
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
