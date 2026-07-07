import type {
  AppState,
  SlingshotObject,
  SphereObject,
  Vec2,
} from "../state/types";

/**
 * Canvas renderers for the physics scene objects (sphere, slingshot).
 * Pure rendering of the backend simulation state, in frame pixels.
 * The black hole is NOT here — it's the WebGL layer (gl/LensedVideo).
 */

// ---- palette (RGB ports of the BGR constants in ui/interactables.py) ----

const BALL = "#ff9a2e"; // BGR (0,120,255)
const BALL_HI = "#ffd9a1";
const BALL_RIM = "rgba(120,60,10,0.9)";
const BALL_GRABBED = "#3fdc82"; // BGR (0,220,100)
const BALL_GRABBED_HI = "#b8ffd9";
const BAND = "#ffc83c"; // BGR (60,200,255)
const ARC_DOT = "#ffee55"; // BGR (0,255,255)
const ANCHOR = "#b4b4b4";
const UNDER = "rgba(8,10,15,0.8)";

const COL_WEIGHT = "#ffb400"; // BGR (0,180,255)
const COL_DRAG = "#00c8ff"; // BGR (255,200,0)
const COL_NORMAL = "#00eb00"; // BGR (0,235,0)
const COL_NET = "#f0f0f0";

// Mirrors of the force-overlay constants in ui/interactables.py.
const FORCE_PX_PER_N = 6.0;
const FORCE_MAX_PX = 130;
const MIN_FORCE_DRAW_N = 0.25;
const ARROW_HEAD_PX = 9;

const TRAIL_LEN = 40; // SLING_TRAIL_LEN

// ---- client-side trail accumulation ------------------------------------

// projectile id -> recent positions (frame px). The backend streams one
// position per snapshot; appending per NEW snapshot reconstructs the trail
// the cv2 version kept server-side.
const trails = new Map<number, Vec2[]>();
let trailSeq = -1;

export function updateTrails(state: AppState) {
  if (state.seq === trailSeq) return;
  trailSeq = state.seq;
  const sling = state.objects.find(
    (o): o is SlingshotObject => o.type === "slingshot",
  );
  if (!sling) {
    if (trails.size) trails.clear();
    return;
  }
  const liveIds = new Set<number>();
  for (const p of sling.projectiles) {
    liveIds.add(p.id);
    let trail = trails.get(p.id);
    if (!trail) {
      trail = [];
      trails.set(p.id, trail);
    }
    trail.push([p.x, p.y]);
    if (trail.length > TRAIL_LEN) trail.shift();
  }
  for (const id of trails.keys()) {
    if (!liveIds.has(id)) trails.delete(id);
  }
}

// ---- drawing helpers ----------------------------------------------------

function drawBall(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  r: number,
  grabbed: boolean,
) {
  const base = grabbed ? BALL_GRABBED : BALL;
  const hi = grabbed ? BALL_GRABBED_HI : BALL_HI;
  const g = ctx.createRadialGradient(
    x - r * 0.35, y - r * 0.35, r * 0.15,
    x, y, r,
  );
  g.addColorStop(0, hi);
  g.addColorStop(0.45, base);
  g.addColorStop(1, grabbed ? "rgba(10,90,45,0.95)" : BALL_RIM);
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fill();
  if (grabbed) {
    ctx.strokeStyle = BALL_GRABBED;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(x, y, r + 8, 0, Math.PI * 2);
    ctx.stroke();
  }
}

function drawForceArrow(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  ballR: number,
  fx: number,
  fy: number,
  color: string,
  tag: string,
  dashed = false,
) {
  const mag = Math.hypot(fx, fy);
  if (mag < MIN_FORCE_DRAW_N) return;
  let length = Math.min(mag * FORCE_PX_PER_N, FORCE_MAX_PX);
  length = Math.max(length, ARROW_HEAD_PX + 4);
  const ux = fx / mag;
  const uy = fy / mag;
  const sx = cx + ux * (ballR + 3);
  const sy = cy + uy * (ballR + 3);
  const ex = sx + ux * length;
  const ey = sy + uy * length;
  const hx = ex - ux * ARROW_HEAD_PX;
  const hy = ey - uy * ARROW_HEAD_PX;
  const wx = -uy * ARROW_HEAD_PX * 0.55;
  const wy = ux * ARROW_HEAD_PX * 0.55;

  ctx.lineCap = "round";
  const strokeShaft = (style: string, width: number) => {
    ctx.strokeStyle = style;
    ctx.lineWidth = width;
    ctx.setLineDash(dashed ? [5, 4] : []);
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(hx, hy);
    ctx.stroke();
    ctx.setLineDash([]);
  };
  const fillHead = (style: string, outline: number) => {
    ctx.beginPath();
    ctx.moveTo(ex, ey);
    ctx.lineTo(hx + wx, hy + wy);
    ctx.lineTo(hx - wx, hy - wy);
    ctx.closePath();
    if (outline > 0) {
      ctx.strokeStyle = style;
      ctx.lineWidth = outline;
      ctx.stroke();
    } else {
      ctx.fillStyle = style;
      ctx.fill();
    }
  };

  // Dark under-stroke keeps the colours readable on any video content.
  strokeShaft(UNDER, 5);
  fillHead(UNDER, 3);
  strokeShaft(color, 2);
  fillHead(color, 0);

  // Tag letter just past the tip (net sits further out — in free fall
  // net coincides with W and the tags would stack).
  const off = dashed ? 26 : 10;
  const tx = ex + ux * off;
  const ty = ey + uy * off;
  ctx.font = "600 15px 'IBM Plex Mono', monospace";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.lineWidth = 3;
  ctx.strokeStyle = UNDER;
  ctx.strokeText(tag, tx, ty);
  ctx.fillStyle = color;
  ctx.fillText(tag, tx, ty);
}

// ---- object renderers ---------------------------------------------------

function drawSphere(ctx: CanvasRenderingContext2D, s: SphereObject) {
  drawBall(ctx, s.x, s.y, s.r, s.grabbed);
}

function drawSlingshot(ctx: CanvasRenderingContext2D, s: SlingshotObject) {
  const [ax, ay] = s.anchor;

  if (s.aiming && s.pull) {
    const [px, py] = s.pull;
    // Rubber band from the two forks to the pulled ball.
    ctx.strokeStyle = UNDER;
    ctx.lineWidth = 5;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(ax - 16, ay - 10);
    ctx.lineTo(px, py);
    ctx.moveTo(ax + 16, ay - 10);
    ctx.lineTo(px, py);
    ctx.stroke();
    ctx.strokeStyle = BAND;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(ax - 16, ay - 10);
    ctx.lineTo(px, py);
    ctx.moveTo(ax + 16, ay - 10);
    ctx.lineTo(px, py);
    ctx.stroke();

    // Dotted predicted arc.
    ctx.fillStyle = ARC_DOT;
    for (const [tx, ty] of s.arc) {
      ctx.beginPath();
      ctx.arc(tx, ty, 3, 0, Math.PI * 2);
      ctx.fill();
    }

    drawBall(ctx, px, py, s.ball_r, false);
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(px, py, s.ball_r, 0, Math.PI * 2);
    ctx.stroke();
  } else {
    // Idle ball resting above the anchor.
    drawBall(ctx, ax, ay - s.ball_r, s.ball_r, false);
  }

  // Anchor post above the ball so it reads as the fixed point.
  ctx.fillStyle = ANCHOR;
  ctx.beginPath();
  ctx.arc(ax, ay, 6, 0, Math.PI * 2);
  ctx.fill();

  // Flying projectiles: trail, ball, force vectors.
  for (const p of s.projectiles) {
    const trail = trails.get(p.id);
    if (trail && trail.length > 1) {
      const n = trail.length;
      for (let i = 0; i < n; i++) {
        const t = (i + 1) / n;
        ctx.fillStyle = `rgba(255,160,60,${0.45 * t})`;
        ctx.beginPath();
        ctx.arc(trail[i][0], trail[i][1], Math.max(1, s.ball_r * 0.3 * t), 0, Math.PI * 2);
        ctx.fill();
      }
    }
    drawBall(ctx, p.x, p.y, s.ball_r, false);

    const net: Vec2 = [
      p.f_w[0] + p.f_d[0] + p.f_c[0],
      p.f_w[1] + p.f_d[1] + p.f_c[1],
    ];
    drawForceArrow(ctx, p.x, p.y, s.ball_r, p.f_w[0], p.f_w[1], COL_WEIGHT, "W");
    drawForceArrow(ctx, p.x, p.y, s.ball_r, p.f_d[0], p.f_d[1], COL_DRAG, "D");
    drawForceArrow(ctx, p.x, p.y, s.ball_r, p.f_c[0], p.f_c[1], COL_NORMAL, "N");
    drawForceArrow(ctx, p.x, p.y, s.ball_r, net[0], net[1], COL_NET, "net", true);
  }
}

export function drawScene(
  ctx: CanvasRenderingContext2D,
  state: AppState,
  _now: number,
) {
  for (const obj of state.objects) {
    switch (obj.type) {
      case "sphere":
        drawSphere(ctx, obj);
        break;
      case "slingshot":
        drawSlingshot(ctx, obj);
        break;
      default:
        break; // sixseven + black_hole render in other layers
    }
  }
}
