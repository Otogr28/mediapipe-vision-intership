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
 * present (see App.tsx), so three.js never runs otherwise. Until the model is
 * live, overlay/scene.ts shows a loading spinner (no placeholder puppet).
 *
 * Rigging is a small, hand-written IMAGE-PLANE mapping from the app's own
 * landmarks (no Kalidokit, no z needed): each arm bone is aimed from its joint
 * toward the next (shoulder→elbow, elbow→wrist) using the pose landmarks, the
 * mouth opens with the pinch (the `mouth` field), plus an idle sway and blink
 * so the character is alive even before anyone moves. Body pose only exists
 * while HALL_POSE is on — the backend turns it on automatically when Vtuber is
 * selected (ui.wants_pose()); with no pose the avatar just idles + lip-syncs.
 *
 * `isVrmReady()` lets the Canvas fallback (overlay/scene.ts) hide its mascot
 * once the model is live; it flips back to false on unmount / load failure.
 */

// --- rig tuning knobs (adjust these, not the math) ----------------------
const ARM_DAMP = 0.35; // slerp toward the target arm pose each frame
const MIRROR_X = -1; // camera feed is mirrored; flips image-x into avatar-x
const ARM_FWD_Z = 0.15; // small forward lean so arms read as 3D, not flat
const POSE_MIN_VIS = 0.3; // ignore arm landmarks below this visibility
const BLINK_PERIOD = 4.2; // s between blinks
const BLINK_LEN = 0.14; // s each blink lasts

// MediaPipe pose indices.
const L_SH = 11, R_SH = 12, L_EL = 13, R_EL = 14, L_WR = 15, R_WR = 16;

type Bones = Record<string, THREE.Object3D | null>;

interface Rig {
  vrm: VRM;
  bones: Bones;
  restDir: Record<string, THREE.Vector3>; // child-bone rest direction, local
}

function poseVec(pose: PoseState, i: number): [number, number, number] {
  const p = pose[i];
  return [p[0], p[1], p[2]];
}

// Aim `bone` so its rest-forward (toward its child) points along a world-space
// target direction, expressed here as image-plane (dx, dy) with dy pointing
// down. Result is slerped in for smoothness.
function aimBone(
  bone: THREE.Object3D | null,
  restDirLocal: THREE.Vector3 | undefined,
  dxImg: number,
  dyImg: number,
  damp: number,
) {
  if (!bone || !restDirLocal || !bone.parent) return;
  const targetWorld = new THREE.Vector3(
    MIRROR_X * dxImg,
    -dyImg,
    ARM_FWD_Z,
  ).normalize();
  const pq = new THREE.Quaternion();
  bone.parent.getWorldQuaternion(pq).invert();
  const targetLocal = targetWorld.applyQuaternion(pq).normalize();
  const q = new THREE.Quaternion().setFromUnitVectors(restDirLocal, targetLocal);
  bone.quaternion.slerp(q, damp);
}

function rigArms(rig: Rig, pose: PoseState) {
  const arms: [string, string, number, number, number][] = [
    ["rightUpperArm", "rightLowerArm", R_SH, R_EL, R_WR],
    ["leftUpperArm", "leftLowerArm", L_SH, L_EL, L_WR],
  ];
  for (const [upper, lower, si, ei, wi] of arms) {
    const s = poseVec(pose, si);
    const e = poseVec(pose, ei);
    const w = poseVec(pose, wi);
    if (s[2] < POSE_MIN_VIS || e[2] < POSE_MIN_VIS) continue;
    aimBone(rig.bones[upper], rig.restDir[upper], e[0] - s[0], e[1] - s[1], ARM_DAMP);
    if (w[2] >= POSE_MIN_VIS) {
      aimBone(rig.bones[lower], rig.restDir[lower], w[0] - e[0], w[1] - e[1], ARM_DAMP);
    }
  }
}

function rigSpine(rig: Rig, pose: PoseState) {
  // Lean the torso toward where the shoulders sit — extra whole-body response
  // so the avatar visibly follows the person, not just the arms.
  const ls = pose[L_SH];
  const rs = pose[R_SH];
  const spine = rig.bones.spine;
  if (!spine || !ls || !rs || ls[2] < POSE_MIN_VIS || rs[2] < POSE_MIN_VIS)
    return;
  const midx = (ls[0] + rs[0]) / 2 - 0.5; // shoulder centre vs frame centre
  const target = Math.max(-0.32, Math.min(0.32, MIRROR_X * midx * 1.6));
  spine.rotation.z += (target - spine.rotation.z) * 0.15;
}

function relaxArms(rig: Rig) {
  // Ease arms back toward the model's rest pose when pose is unavailable.
  for (const name of ["leftUpperArm", "leftLowerArm", "rightUpperArm", "rightLowerArm"]) {
    const b = rig.bones[name];
    if (b) b.quaternion.slerp(new THREE.Quaternion(), 0.08);
  }
}

function rigFace(rig: Rig, mouth: number, tSec: number) {
  const em = rig.vrm.expressionManager;
  if (!em) return;
  em.setValue("aa", Math.min(Math.max(mouth, 0), 1));
  em.setValue("happy", 0.25); // a gentle resting smile
  const phase = tSec % BLINK_PERIOD;
  const blink = phase < BLINK_LEN ? 1 - Math.abs(phase / BLINK_LEN - 0.5) * 2 : 0;
  em.setValue("blink", blink);
}

function rigIdle(rig: Rig, tSec: number) {
  // Subtle breathing sway on the upper body + a slow head drift, so the
  // avatar never looks frozen.
  const chest = rig.bones.upperChest ?? rig.bones.chest;
  if (chest) chest.rotation.z = Math.sin(tSec * 1.1) * 0.02;
  const head = rig.bones.head;
  if (head) {
    head.rotation.y = Math.sin(tSec * 0.5) * 0.08;
    head.rotation.x = Math.sin(tSec * 0.7) * 0.04;
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
    const renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: true,
    });
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
        VRMUtils.rotateVRM0(vrm); // VRM0 models face +Z; make them face the camera
        vrm.scene.traverse((o) => {
          o.frustumCulled = false;
        });
        scene.add(vrm.scene);

        const get = (n: VRMHumanBoneName) =>
          vrm.humanoid.getNormalizedBoneNode(n);
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
        const restDir: Record<string, THREE.Vector3> = {};
        const childOf: Record<string, string> = {
          leftUpperArm: "leftLowerArm",
          leftLowerArm: "leftHand",
          rightUpperArm: "rightLowerArm",
          rightLowerArm: "rightHand",
        };
        for (const [bone, child] of Object.entries(childOf)) {
          const cn = vrm.humanoid.getNormalizedBoneNode(
            child as VRMHumanBoneName,
          );
          if (bones[bone] && cn) {
            restDir[bone] = cn.position.clone().normalize();
          }
        }

        // Frame the upper body from the model's actual proportions.
        const headPos = new THREE.Vector3();
        bones.head?.getWorldPosition(headPos);
        const hips = get("hips");
        const hipsPos = new THREE.Vector3();
        hips?.getWorldPosition(hipsPos);
        if (headPos.y > 0) {
          // Frame wide enough that RAISED arms stay on-screen (a tight
          // head-to-navel crop made arm motion invisible — it left frame).
          const span = Math.max(headPos.y - hipsPos.y, 0.4);
          const chestY = (headPos.y + hipsPos.y) / 2;
          camera.position.set(0, headPos.y - 0.12, span * 4.5);
          camera.lookAt(0, chestY, 0);
        }

        rig = { vrm, bones, restDir };
        setVrmReady(true);
      },
      undefined,
      (err: unknown) => {
        console.warn("VRM load failed; keeping canvas puppet", err);
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
        const vt = state?.objects.find(
          (o): o is VtuberObject => o.type === "vtuber",
        );
        const mouth = vt?.mouth ?? 0;
        rigFace(rig, mouth, tSec);
        rigIdle(rig, tSec);
        if (state?.pose) {
          rigArms(rig, state.pose);
          rigSpine(rig, state.pose);
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
