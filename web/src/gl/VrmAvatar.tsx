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
import type { AppState, PoseState, VtuberObject } from "../state/types";
import type { SnapshotPair } from "../state/useAppState";
import { setVrmReady } from "./vrmState";

/**
 * Open-source VRM vtuber avatar (CC0 model "Sendagaya Shino" from
 * madjin/vrm-samples, at /avatar.vrm), rendered with three.js +
 * @pixiv/three-vrm as a WebGL layer. Mounted only while a vtuber object is
 * present (see App.tsx). Until the model is live, overlay/scene.ts shows a
 * loading spinner (no placeholder puppet).
 *
 * Rigging is a SCREEN-PLANE mapping from the app's own pose landmarks (no
 * Kalidokit, no z, no state-contract change). Each arm bone is rotated about
 * the camera-forward (Z) axis to the image angle of its segment
 * (shoulder→elbow, elbow→wrist) — a single-axis rotation, so there is no
 * twisting or 180° flip. The left/right mapping MIRRORS the user (you raise a
 * hand, the avatar raises the hand on the same side of the screen), which is
 * why the person's right-side landmarks drive the avatar's *left* arm (the
 * avatar faces you). The mouth opens with the pinch; the head follows the
 * nose. Body pose only exists while HALL_POSE is on — the backend turns it on
 * automatically when Vtuber is selected (ui.wants_pose()).
 */

// --- rig tuning knobs ----------------------------------------------------
const ARM_DAMP = 0.4; // slerp toward the target arm pose each frame
const HEAD_DAMP = 0.3;
const POSE_MIN_VIS = 0.25; // ignore landmarks below this visibility
const BLINK_PERIOD = 4.2; // s between blinks
const BLINK_LEN = 0.14; // s each blink lasts

const ZAXIS = new THREE.Vector3(0, 0, 1);

// MediaPipe pose indices.
const NOSE = 0;
const L_SH = 11, R_SH = 12;

type Bones = Record<string, THREE.Object3D | null>;
interface ArmRest {
  restQuat: THREE.Quaternion; // bone's local rotation at rest
  childLocalPos: THREE.Vector3; // direction toward the child, in bone-local space
}

interface Rig {
  vrm: VRM;
  bones: Bones;
  arm: Record<string, ArmRest>;
  restHead: THREE.Quaternion;
  restSpine: THREE.Quaternion;
}

function wrap(a: number) {
  while (a > Math.PI) a -= 2 * Math.PI;
  while (a < -Math.PI) a += 2 * Math.PI;
  return a;
}

/** Point an arm bone so its segment sits at `targetWorldAngle` in the screen
 *  (world XY) plane. Rotates about the TRUE world-Z axis (expressed in the
 *  bone's parent frame) so the model's own orientation — including the 180°
 *  flip three-vrm applies to VRM0 models, and any torso lean — can't invert
 *  the direction. Recomputes the rest angle from the CURRENT parent each frame
 *  so the forearm follows the (already-rotated) upper arm correctly. */
function aimArm(rig: Rig, name: string, targetWorldAngle: number, damp: number) {
  const bone = rig.bones[name];
  const r = rig.arm[name];
  if (!bone || !bone.parent || !r) return;
  const pq = new THREE.Quaternion();
  bone.parent.getWorldQuaternion(pq);
  const restWorldDir = r.childLocalPos
    .clone()
    .applyQuaternion(pq.clone().multiply(r.restQuat));
  const restWorldAngle = Math.atan2(restWorldDir.y, restWorldDir.x);
  const delta = wrap(targetWorldAngle - restWorldAngle);
  const axis = ZAXIS.clone().applyQuaternion(pq.clone().invert()).normalize();
  const q = new THREE.Quaternion().setFromAxisAngle(axis, delta).multiply(r.restQuat);
  bone.quaternion.slerp(q, damp);
}

function rigOneArm(
  rig: Rig,
  upper: string,
  lower: string,
  idx: [number, number, number], // shoulder, elbow, wrist landmark indices
  pose: PoseState,
) {
  const s = pose[idx[0]];
  const e = pose[idx[1]];
  const w = pose[idx[2]];
  if (!s || !e || s[2] < POSE_MIN_VIS || e[2] < POSE_MIN_VIS) return;
  // image y grows downward -> negate for world up.
  aimArm(rig, upper, Math.atan2(-(e[1] - s[1]), e[0] - s[0]), ARM_DAMP);
  if (w && w[2] >= POSE_MIN_VIS) {
    aimArm(rig, lower, Math.atan2(-(w[1] - e[1]), w[0] - e[0]), ARM_DAMP);
  }
}

function rigArms(rig: Rig, pose: PoseState) {
  const a = pose[11];
  const b = pose[12];
  if (!a || !b) return;
  // MIRROR by IMAGE POSITION, not anatomical label: the shoulder landmark with
  // the larger image-x is on the screen RIGHT and must drive the avatar's LEFT
  // arm (which is on the screen right, since the avatar faces us). Using the
  // actual x keeps the mirror correct no matter how MediaPipe labels L/R on
  // the flipped feed — and stops the arms from crossing.
  const set11: [number, number, number] = [11, 13, 15];
  const set12: [number, number, number] = [12, 14, 16];
  const rightSide = a[0] >= b[0] ? set11 : set12; // landmarks on the image right
  const leftSide = a[0] >= b[0] ? set12 : set11; // landmarks on the image left
  rigOneArm(rig, "leftUpperArm", "leftLowerArm", rightSide, pose);
  rigOneArm(rig, "rightUpperArm", "rightLowerArm", leftSide, pose);
}

function relaxArms(rig: Rig) {
  // Ease arms back toward the model's REST pose (not identity) when pose is off.
  for (const name of ["leftUpperArm", "leftLowerArm", "rightUpperArm", "rightLowerArm"]) {
    const b = rig.bones[name];
    const r = rig.arm[name];
    if (b && r) b.quaternion.slerp(r.restQuat, 0.08);
  }
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

function rigSpine(rig: Rig, pose: PoseState) {
  const ls = pose[L_SH];
  const rs = pose[R_SH];
  const spine = rig.bones.spine;
  if (!spine || !ls || !rs || ls[2] < POSE_MIN_VIS || rs[2] < POSE_MIN_VIS) return;
  const midx = (ls[0] + rs[0]) / 2 - 0.5; // shoulder centre vs frame centre
  const lean = Math.max(-0.22, Math.min(0.22, midx * 1.4));
  const target = rig.restSpine
    .clone()
    .multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0, lean)));
  spine.quaternion.slerp(target, 0.12);
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
          rightUpperArm: get("rightUpperArm"),
          rightLowerArm: get("rightLowerArm"),
        };

        // Capture each arm bone's REST rotation + its rest screen angle (the
        // rig rotates relative to these, so it works for any rest pose).
        const arm: Record<string, ArmRest> = {};
        const childOf: Record<string, VRMHumanBoneName> = {
          leftUpperArm: "leftLowerArm",
          leftLowerArm: "leftHand",
          rightUpperArm: "rightLowerArm",
          rightLowerArm: "rightHand",
        };
        for (const [bone, child] of Object.entries(childOf)) {
          const b = bones[bone];
          const c = get(child);
          if (b && c) {
            arm[bone] = {
              restQuat: b.quaternion.clone(),
              childLocalPos: c.position.clone().normalize(),
            };
          }
        }
        const restHead = bones.head?.quaternion.clone() ?? new THREE.Quaternion();
        const restSpine = bones.spine?.quaternion.clone() ?? new THREE.Quaternion();

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

        rig = { vrm, bones, arm, restHead, restSpine };
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
        if (state?.pose) {
          rigArms(rig, state.pose);
          rigSpine(rig, state.pose);
          rigHead(rig, state.pose);
        } else {
          relaxArms(rig);
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
