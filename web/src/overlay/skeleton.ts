import type { AppState } from "../state/types";

/**
 * Pose + hand skeleton, drawn in frame pixels.
 *
 * Visual language: thin cool-blue traces (passive detector output), joints
 * as small bright nodes. Hands warm from trace-blue toward amber as the
 * pinch closes, so the skeleton itself telegraphs the gesture state.
 */

const POSE_CONNECTIONS: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 7], [0, 4], [4, 5], [5, 6], [6, 8], [9, 10],
  [11, 12], [11, 13], [13, 15], [15, 17], [15, 19], [15, 21], [17, 19],
  [12, 14], [14, 16], [16, 18], [16, 20], [16, 22], [18, 20],
  [11, 23], [12, 24], [23, 24], [23, 25], [24, 26], [25, 27], [26, 28],
  [27, 29], [28, 30], [29, 31], [30, 32], [27, 31], [28, 32],
];

const HAND_CONNECTIONS: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20],
  [0, 17],
];

const FINGERTIPS = [4, 8, 12, 16, 20];

const MIN_VIS = 0.35;

/** Blend the trace blue toward amber by t (pinch progress). */
function handStroke(t: number, alpha: number): string {
  const r = Math.round(127 + (255 - 127) * t);
  const g = Math.round(180 + (184 - 180) * t);
  const b = Math.round(255 + (77 - 255) * t);
  return `rgba(${r},${g},${b},${alpha})`;
}

export function drawSkeleton(
  ctx: CanvasRenderingContext2D,
  state: AppState,
  w: number,
  h: number,
) {
  // In vtuber mode the puppet replaces the raw skeleton — drawing both would
  // clutter the character with its own tracking lines.
  if (state.objects.some((o) => o.type === "vtuber")) return;

  ctx.lineCap = "round";
  ctx.lineJoin = "round";

  if (state.pose) {
    const pts = state.pose.map(
      ([x, y, vis]) => [x * w, y * h, vis] as [number, number, number],
    );
    ctx.lineWidth = 2.5;
    for (const [a, b] of POSE_CONNECTIONS) {
      const pa = pts[a];
      const pb = pts[b];
      if (!pa || !pb || pa[2] < MIN_VIS || pb[2] < MIN_VIS) continue;
      const alpha = 0.55 * Math.min(pa[2], pb[2]);
      ctx.strokeStyle = `rgba(127,180,255,${alpha})`;
      ctx.beginPath();
      ctx.moveTo(pa[0], pa[1]);
      ctx.lineTo(pb[0], pb[1]);
      ctx.stroke();
    }
    for (const [x, y, vis] of pts) {
      if (vis < MIN_VIS) continue;
      ctx.fillStyle = `rgba(213,228,255,${0.8 * vis})`;
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  for (const hand of state.hands) {
    if (!hand.landmarks) continue;
    const pts = hand.landmarks.map(([x, y]) => [x * w, y * h]);
    const warm = hand.progress;
    ctx.lineWidth = 2.5;
    ctx.strokeStyle = handStroke(warm, 0.75);
    ctx.beginPath();
    for (const [a, b] of HAND_CONNECTIONS) {
      ctx.moveTo(pts[a][0], pts[a][1]);
      ctx.lineTo(pts[b][0], pts[b][1]);
    }
    ctx.stroke();
    ctx.fillStyle = handStroke(warm, 0.95);
    for (const tip of FINGERTIPS) {
      ctx.beginPath();
      ctx.arc(pts[tip][0], pts[tip][1], 3.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}
