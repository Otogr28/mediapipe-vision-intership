import type {
  AppState,
  OrbitalsObject,
  SlingshotObject,
  SphereObject,
  Vec2,
  VtuberObject,
} from "../state/types";

/**
 * Canvas renderers for the physics scene objects (sphere, slingshot,
 * orbitals) and the vtuber puppet. Pure rendering of the backend simulation
 * state, in frame pixels. The black hole is NOT here — it's the WebGL layer
 * (gl/LensedVideo).
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
// Orbital body id -> recent positions; a separate namespace from the
// slingshot's projectile ids (never on screen at the same time, but kept
// distinct so a leftover id can't cross-contaminate).
const orbTrails = new Map<number, Vec2[]>();
const ORB_TRAIL_LEN = 64; // ORB_TRAIL_LEN
let trailSeq = -1;

/** Push one point per live id, capped, and drop ids that vanished. */
function accumulate(
  store: Map<number, Vec2[]>,
  points: { id: number; x: number; y: number }[],
  cap: number,
) {
  const liveIds = new Set<number>();
  for (const p of points) {
    liveIds.add(p.id);
    let trail = store.get(p.id);
    if (!trail) {
      trail = [];
      store.set(p.id, trail);
    }
    trail.push([p.x, p.y]);
    if (trail.length > cap) trail.shift();
  }
  for (const id of store.keys()) {
    if (!liveIds.has(id)) store.delete(id);
  }
}

export function updateTrails(state: AppState) {
  if (state.seq === trailSeq) return;
  trailSeq = state.seq;

  const sling = state.objects.find(
    (o): o is SlingshotObject => o.type === "slingshot",
  );
  if (sling) accumulate(trails, sling.projectiles, TRAIL_LEN);
  else if (trails.size) trails.clear();

  const orb = state.objects.find(
    (o): o is OrbitalsObject => o.type === "orbitals",
  );
  if (orb) accumulate(orbTrails, orb.bodies, ORB_TRAIL_LEN);
  else if (orbTrails.size) orbTrails.clear();
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

// ---- orbitals -----------------------------------------------------------

type RGB = [number, number, number];
const mixc = (c: number, target: number, t: number) =>
  Math.round(c + (target - c) * t);
const rgbStr = ([r, g, b]: RGB, a = 1) => `rgba(${r},${g},${b},${a})`;
const lighten = ([r, g, b]: RGB, t: number) =>
  `rgb(${mixc(r, 255, t)},${mixc(g, 255, t)},${mixc(b, 255, t)})`;
const darken = ([r, g, b]: RGB, t: number) =>
  `rgb(${mixc(r, 0, t)},${mixc(g, 0, t)},${mixc(b, 0, t)})`;

function drawOrbBody(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  r: number,
  rgb: RGB,
  collapsed: boolean,
  ghost = false,
) {
  if (collapsed) {
    // Accretion glow, then a black event-horizon disk with a bright ring.
    const ring = ctx.createRadialGradient(x, y, r * 0.5, x, y, r * 2.4);
    ring.addColorStop(0, "rgba(190,150,255,0)");
    ring.addColorStop(0.55, "rgba(150,90,230,0.5)");
    ring.addColorStop(1, "rgba(150,90,230,0)");
    ctx.fillStyle = ring;
    ctx.beginPath();
    ctx.arc(x, y, r * 2.4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#05040a";
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "rgba(205,170,255,0.9)";
    ctx.lineWidth = 2.5;
    ctx.stroke();
    return;
  }
  // Soft glow halo.
  const glow = ctx.createRadialGradient(x, y, r * 0.2, x, y, r * 2.4);
  glow.addColorStop(0, rgbStr(rgb, ghost ? 0.28 : 0.55));
  glow.addColorStop(0.4, rgbStr(rgb, ghost ? 0.1 : 0.22));
  glow.addColorStop(1, rgbStr(rgb, 0));
  ctx.fillStyle = glow;
  ctx.beginPath();
  ctx.arc(x, y, r * 2.4, 0, Math.PI * 2);
  ctx.fill();
  if (ghost) {
    ctx.strokeStyle = rgbStr(rgb, 0.85);
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.stroke();
    return;
  }
  // Lit sphere: bright offset core -> body colour -> dark rim.
  const g = ctx.createRadialGradient(
    x - r * 0.35, y - r * 0.35, r * 0.1,
    x, y, r,
  );
  g.addColorStop(0, lighten(rgb, 0.6));
  g.addColorStop(0.5, rgbStr(rgb, 1));
  g.addColorStop(1, darken(rgb, 0.45));
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fill();
}

function drawOrbitals(ctx: CanvasRenderingContext2D, o: OrbitalsObject) {
  // Fading trails toward each body's colour.
  for (const b of o.bodies) {
    const trail = orbTrails.get(b.id);
    if (!trail || trail.length < 2) continue;
    const n = trail.length;
    for (let i = 0; i < n; i++) {
      const t = (i + 1) / n;
      ctx.fillStyle = rgbStr(b.rgb, 0.5 * t);
      ctx.beginPath();
      ctx.arc(trail[i][0], trail[i][1], Math.max(1, b.r * 0.32 * t), 0, Math.PI * 2);
      ctx.fill();
    }
  }
  for (const b of o.bodies) {
    drawOrbBody(ctx, b.x, b.y, b.r, b.rgb, b.collapsed);
  }

  if (o.aiming && o.spawn) {
    const [sx, sy] = o.spawn;
    const rgb = o.kind_rgb;
    if (o.pull) {
      const [px, py] = o.pull;
      // Sling band from the spawn point to the pulled cursor.
      ctx.strokeStyle = "rgba(8,10,15,0.8)";
      ctx.lineWidth = 5;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(px, py);
      ctx.stroke();
      ctx.strokeStyle = "rgba(220,220,220,0.9)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(px, py);
      ctx.stroke();
    }
    // Dotted predicted orbit.
    ctx.fillStyle = rgbStr(rgb, 0.95);
    for (const [ax, ay] of o.arc) {
      ctx.beginPath();
      ctx.arc(ax, ay, 2.4, 0, Math.PI * 2);
      ctx.fill();
    }
    // Ghost of the body to launch + launch-velocity arrow (opposite pull).
    drawOrbBody(ctx, sx, sy, o.kind_r, rgb, false, true);
    if (o.pull) {
      const [px, py] = o.pull;
      const dx = sx - px;
      const dy = sy - py;
      const mag = Math.hypot(dx, dy);
      if (mag > 2) {
        const len = Math.min(mag, 150);
        const ex = sx + (dx / mag) * len;
        const ey = sy + (dy / mag) * len;
        drawArrow(ctx, sx, sy, ex, ey, rgbStr(rgb, 0.95));
      }
    }
    if (o.readout) {
      const label = `${o.readout.kind}  v₀ ${o.readout.v0.toFixed(0)} px/s`;
      ctx.font = "600 15px 'IBM Plex Mono', monospace";
      ctx.textAlign = "left";
      ctx.textBaseline = "bottom";
      const tw = ctx.measureText(label).width;
      ctx.fillStyle = "rgba(8,10,15,0.7)";
      ctx.fillRect(sx + 14, sy - 34, tw + 14, 24);
      ctx.fillStyle = rgbStr(rgb, 1);
      ctx.fillText(label, sx + 21, sy - 14);
    }
  }
}

function drawArrow(
  ctx: CanvasRenderingContext2D,
  sx: number,
  sy: number,
  ex: number,
  ey: number,
  color: string,
) {
  const ux = ex - sx;
  const uy = ey - sy;
  const mag = Math.hypot(ux, uy) || 1;
  const nx = ux / mag;
  const ny = uy / mag;
  const head = 12;
  const hx = ex - nx * head;
  const hy = ey - ny * head;
  const wx = -ny * head * 0.55;
  const wy = nx * head * 0.55;
  ctx.strokeStyle = color;
  ctx.lineWidth = 3;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(sx, sy);
  ctx.lineTo(hx, hy);
  ctx.stroke();
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(ex, ey);
  ctx.lineTo(hx + wx, hy + wy);
  ctx.lineTo(hx - wx, hy - wy);
  ctx.closePath();
  ctx.fill();
}

// ---- vtuber puppet ------------------------------------------------------

const POSE_LSHOULDER = 11;
const POSE_RSHOULDER = 12;
const POSE_LELBOW = 13;
const POSE_RELBOW = 14;
const POSE_LWRIST = 15;
const POSE_RWRIST = 16;

const PUP_BODY: RGB = [244, 233, 208];
const PUP_OUTLINE = "#3a2a5e";
const PUP_ACCENT = "#8b6cff";
const PUP_STAR = "#ffd76a";
const PUP_EYE = "#241a33";

/** A hand's on-screen anchor (wrist if landmarks are live, else the pinch
 *  cursor) plus its pinch progress — enough to puppet a paw. */
function handAnchors(state: AppState, w: number, h: number) {
  const out: { x: number; y: number; progress: number }[] = [];
  for (const hand of state.hands) {
    if (hand.seen_ms > 250) continue;
    if (hand.landmarks && hand.landmarks[0]) {
      out.push({
        x: hand.landmarks[0][0] * w,
        y: hand.landmarks[0][1] * h,
        progress: hand.progress,
      });
    } else {
      out.push({ x: hand.cursor[0], y: hand.cursor[1], progress: hand.progress });
    }
  }
  return out;
}

function drawPuppet(
  ctx: CanvasRenderingContext2D,
  v: VtuberObject,
  state: AppState,
) {
  const w = state.frame.w;
  const h = state.frame.h;

  // Dim the camera so the character reads as the subject, not an overlay.
  const bg = ctx.createRadialGradient(
    w / 2, h * 0.42, h * 0.2, w / 2, h / 2, Math.max(w, h) * 0.75,
  );
  bg.addColorStop(0, "rgba(14,10,26,0.72)");
  bg.addColorStop(1, "rgba(4,3,10,0.92)");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);

  const hands = handAnchors(state, w, h);
  const bob = Math.sin((v.t * 2 * Math.PI) / 3.2) * 12;

  // Head anchored above the hands' midpoint (or centre when no hand yet).
  let hx = w / 2;
  let hy = h * 0.5;
  if (hands.length) {
    hx = hands.reduce((s, p) => s + p.x, 0) / hands.length;
    hy = hands.reduce((s, p) => s + p.y, 0) / hands.length;
  }
  const R = Math.min(w, h) * 0.11; // head radius, frame-scaled
  const headX = Math.max(R + 20, Math.min(w - R - 20, hx));
  const headY = Math.max(R + 60, hy - R * 2.4) + bob;
  const bodyX = headX;
  const bodyY = headY + R * 1.7;

  const pose = state.pose;
  const poseGood = (i: number) => pose && pose[i] && pose[i][2] > 0.35;

  // ---- arms: shoulder->elbow->wrist when pose is on, else a soft curve ---
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  const armSides: [number, number, number][] = [
    [POSE_LSHOULDER, POSE_LELBOW, POSE_LWRIST],
    [POSE_RSHOULDER, POSE_RELBOW, POSE_RWRIST],
  ];
  const drawnPaws: { x: number; y: number; progress: number }[] = [];
  if (pose && armSides.every(([s]) => poseGood(s))) {
    for (const [s, e, wr] of armSides) {
      const sp: Vec2 = [pose![s][0] * w, pose![s][1] * h];
      const ep: Vec2 = poseGood(e) ? [pose![e][0] * w, pose![e][1] * h] : sp;
      const wp: Vec2 = poseGood(wr) ? [pose![wr][0] * w, pose![wr][1] * h] : ep;
      ctx.strokeStyle = PUP_OUTLINE;
      ctx.lineWidth = R * 0.5;
      ctx.beginPath();
      ctx.moveTo(bodyX, bodyY);
      ctx.lineTo(sp[0], sp[1]);
      ctx.quadraticCurveTo(ep[0], ep[1], wp[0], wp[1]);
      ctx.stroke();
      ctx.strokeStyle = rgbStr(PUP_BODY);
      ctx.lineWidth = R * 0.34;
      ctx.beginPath();
      ctx.moveTo(bodyX, bodyY);
      ctx.lineTo(sp[0], sp[1]);
      ctx.quadraticCurveTo(ep[0], ep[1], wp[0], wp[1]);
      ctx.stroke();
      const near = hands.reduce<{ d: number; p: (typeof hands)[number] } | null>(
        (best, p) => {
          const d = Math.hypot(p.x - wp[0], p.y - wp[1]);
          return !best || d < best.d ? { d, p } : best;
        },
        null,
      );
      drawnPaws.push({ x: wp[0], y: wp[1], progress: near?.p.progress ?? 0 });
    }
  } else {
    for (const p of hands) {
      const midx = (bodyX + p.x) / 2 + (p.x < bodyX ? -R * 0.4 : R * 0.4);
      const midy = Math.max(bodyY, p.y) + R * 0.5;
      ctx.strokeStyle = PUP_OUTLINE;
      ctx.lineWidth = R * 0.5;
      ctx.beginPath();
      ctx.moveTo(bodyX, bodyY);
      ctx.quadraticCurveTo(midx, midy, p.x, p.y);
      ctx.stroke();
      ctx.strokeStyle = rgbStr(PUP_BODY);
      ctx.lineWidth = R * 0.34;
      ctx.beginPath();
      ctx.moveTo(bodyX, bodyY);
      ctx.quadraticCurveTo(midx, midy, p.x, p.y);
      ctx.stroke();
      drawnPaws.push(p);
    }
  }

  // ---- torso ----
  ctx.fillStyle = PUP_OUTLINE;
  ctx.beginPath();
  ctx.ellipse(bodyX, bodyY + R * 0.2, R * 0.82, R * 1.0, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = rgbStr(PUP_BODY);
  ctx.beginPath();
  ctx.ellipse(bodyX, bodyY + R * 0.2, R * 0.7, R * 0.86, 0, 0, Math.PI * 2);
  ctx.fill();
  // Little chest star.
  drawStar(ctx, bodyX, bodyY + R * 0.15, R * 0.24, PUP_ACCENT);

  // ---- antenna + star ----
  ctx.strokeStyle = PUP_OUTLINE;
  ctx.lineWidth = R * 0.09;
  ctx.beginPath();
  ctx.moveTo(headX, headY - R * 0.9);
  ctx.quadraticCurveTo(headX + R * 0.2, headY - R * 1.35, headX, headY - R * 1.6);
  ctx.stroke();
  drawStar(ctx, headX, headY - R * 1.7, R * 0.3, PUP_STAR, true);

  // ---- head ----
  const hg = ctx.createRadialGradient(
    headX - R * 0.3, headY - R * 0.3, R * 0.1, headX, headY, R,
  );
  hg.addColorStop(0, "#fff6e4");
  hg.addColorStop(1, rgbStr(PUP_BODY));
  ctx.fillStyle = PUP_OUTLINE;
  ctx.beginPath();
  ctx.arc(headX, headY, R + R * 0.06, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = hg;
  ctx.beginPath();
  ctx.arc(headX, headY, R, 0, Math.PI * 2);
  ctx.fill();

  // ---- eyes (track the hands) + blink ----
  const gazeTarget = hands.length
    ? {
        x: hands.reduce((s, p) => s + p.x, 0) / hands.length,
        y: hands.reduce((s, p) => s + p.y, 0) / hands.length,
      }
    : { x: headX, y: headY + R };
  let gx = gazeTarget.x - headX;
  let gy = gazeTarget.y - headY;
  const gmag = Math.hypot(gx, gy) || 1;
  gx = (gx / gmag) * R * 0.16;
  gy = (gy / gmag) * R * 0.16;
  const blink = v.t % 4 > 3.82 ? 0.12 : 1; // quick blink every ~4 s
  const eyeR = R * 0.2;
  for (const ex of [-R * 0.4, R * 0.4]) {
    const cxx = headX + ex;
    const cyy = headY - R * 0.08;
    ctx.fillStyle = "#fff";
    ctx.beginPath();
    ctx.ellipse(cxx, cyy, eyeR, eyeR * blink, 0, 0, Math.PI * 2);
    ctx.fill();
    if (blink > 0.5) {
      ctx.fillStyle = PUP_EYE;
      ctx.beginPath();
      ctx.arc(cxx + gx, cyy + gy, eyeR * 0.62, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "rgba(255,255,255,0.9)";
      ctx.beginPath();
      ctx.arc(cxx + gx - eyeR * 0.2, cyy + gy - eyeR * 0.2, eyeR * 0.2, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  // Cheeks.
  ctx.fillStyle = "rgba(255,140,150,0.4)";
  for (const ex of [-R * 0.55, R * 0.55]) {
    ctx.beginPath();
    ctx.ellipse(headX + ex, headY + R * 0.34, R * 0.16, R * 0.1, 0, 0, Math.PI * 2);
    ctx.fill();
  }
  // Mouth — opens with the pinch (mouth ∈ [0,1]).
  const mo = R * (0.05 + 0.34 * v.mouth);
  ctx.fillStyle = "#7a3550";
  ctx.beginPath();
  ctx.ellipse(headX, headY + R * 0.44, R * 0.24, mo, 0, 0, Math.PI * 2);
  ctx.fill();

  // ---- paws at the hands (curl inward as the pinch closes) ----
  for (const p of drawnPaws) {
    const pr = R * (0.42 - 0.08 * p.progress);
    ctx.fillStyle = PUP_OUTLINE;
    ctx.beginPath();
    ctx.arc(p.x, p.y, pr + R * 0.05, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = rgbStr(PUP_BODY);
    ctx.beginPath();
    ctx.arc(p.x, p.y, pr, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "rgba(255,140,150,0.35)";
    ctx.beginPath();
    ctx.arc(p.x, p.y, pr * 0.5, 0, Math.PI * 2);
    ctx.fill();
  }
}

function drawStar(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  r: number,
  color: string,
  glow = false,
) {
  if (glow) {
    const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r * 2.6);
    g.addColorStop(0, "rgba(255,215,106,0.6)");
    g.addColorStop(1, "rgba(255,215,106,0)");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(cx, cy, r * 2.6, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.fillStyle = color;
  ctx.beginPath();
  for (let i = 0; i < 10; i++) {
    const ang = (Math.PI / 5) * i - Math.PI / 2;
    const rad = i % 2 === 0 ? r : r * 0.45;
    const x = cx + Math.cos(ang) * rad;
    const y = cy + Math.sin(ang) * rad;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.closePath();
  ctx.fill();
}

// ---- dispatch -----------------------------------------------------------

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
      case "orbitals":
        drawOrbitals(ctx, obj);
        break;
      case "vtuber":
        drawPuppet(ctx, obj, state);
        break;
      default:
        break; // sixseven + black_hole render in other layers
    }
  }
}
