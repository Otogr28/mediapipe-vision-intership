import { isVrmReady } from "../gl/vrmState";
import { isSkeletonView } from "./debugView";
import type {
  AppState,
  ChargesObject,
  OrbitalsObject,
  SlingshotObject,
  SphereObject,
  Vec2,
  WavesObject,
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
  ghost = false,
) {
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
    drawOrbBody(ctx, b.x, b.y, b.r, b.rgb);
    // Impact / merge flash: a bright ring that expands and fades out.
    if (b.flash > 0.001) {
      const fr = b.r + (1 - b.flash) * b.r * 3.2;
      ctx.strokeStyle = `rgba(255,255,255,${b.flash})`;
      ctx.lineWidth = 1 + b.flash * 2.5;
      ctx.beginPath();
      ctx.arc(b.x, b.y, fr, 0, Math.PI * 2);
      ctx.stroke();
    }
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
    drawOrbBody(ctx, sx, sy, o.kind_r, rgb, true);
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
      const label = `${o.readout.kind}  m ${o.readout.mass}  v₀ ${o.readout.v0.toFixed(0)} px/s`;
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

// ---- waves (source markers only — the field renders in gl/WavesLayer) ---

function drawWaves(
  ctx: CanvasRenderingContext2D,
  o: WavesObject,
  now: number,
) {
  for (const s of o.sources) {
    const hot = s.grabbed;
    const col = hot ? "rgba(255,255,255,0.95)" : "rgba(210,232,255,0.8)";
    // A ring that breathes at the source's own frequency, so the marker
    // itself telegraphs low vs high before the ripples read.
    const phase = Math.sin(2 * Math.PI * s.freq * (now / 1000));
    const r = 11 + 2.5 * phase;
    ctx.strokeStyle = col;
    ctx.lineWidth = hot ? 3 : 1.5;
    ctx.beginPath();
    ctx.arc(s.x, s.y, r, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = col;
    ctx.beginPath();
    ctx.arc(s.x, s.y, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.font = "500 15px 'IBM Plex Sans', system-ui, sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "bottom";
    ctx.fillText(`${s.freq} Hz`, s.x + 16, s.y - 10);
  }
}

// ---- charges (field lines + markers; the tint/equipotentials are the
// ---- WebGL layer, gl/ChargesLayer) -------------------------------------
//
// The field lines are DERIVED from the charge list here rather than streamed
// — same deal as the client-side Orbitals trails: the backend sends 8 charges
// (~50 bytes) and the browser reconstructs hundreds of polyline points from
// them. Streaming the lines themselves would blow the ~5 KB state budget.
// Ported from Charges.field_at / Charges._field_lines in ui/interactables.py.

function fieldAt(
  o: ChargesObject,
  x: number,
  y: number,
): [number, number] {
  let ex = 0;
  let ey = 0;
  const s2 = o.soften * o.soften;
  for (const c of o.charges) {
    const dx = x - c.x;
    const dy = y - c.y;
    const r2 = dx * dx + dy * dy + s2;
    const inv = (o.k * c.q) / (r2 * Math.sqrt(r2));
    ex += inv * dx;
    ey += inv * dy;
  }
  return [ex, ey];
}

const LINE_STEP_PX = 6;
const LINE_MAX_STEPS = 320;

function fieldLines(o: ChargesObject, w: number, h: number): Vec2[][] {
  const lines: Vec2[][] = [];
  if (!o.charges.length) return lines;
  const hasNeg = o.charges.some((c) => c.q < 0);
  // Lines run + -> -, so seed on the positives. With no positive charge in
  // the scene, seed the negatives and walk backwards along E instead of
  // rendering nothing.
  let seeds = o.charges.filter((c) => c.q > 0);
  let dir = 1;
  if (!seeds.length) {
    seeds = o.charges.filter((c) => c.q < 0);
    dir = -1;
  }
  for (const c of seeds) {
    // Line COUNT scales with |q| — the textbook convention that line density
    // encodes charge magnitude, so a 2q charge visibly sprouts twice as many.
    const n = Math.max(3, Math.round(o.lines_per_q * Math.abs(c.q)));
    for (let i = 0; i < n; i++) {
      const a = (2 * Math.PI * i) / n;
      let x = c.x + Math.cos(a) * o.soften;
      let y = c.y + Math.sin(a) * o.soften;
      const pts: Vec2[] = [[x, y]];
      for (let s = 0; s < LINE_MAX_STEPS; s++) {
        const [ex, ey] = fieldAt(o, x, y);
        const m = Math.hypot(ex, ey);
        if (m < 1e-9) break;
        // RK2 (midpoint) on the unit field direction.
        const mx = x + (dir * (ex / m) * LINE_STEP_PX) / 2;
        const my = y + (dir * (ey / m) * LINE_STEP_PX) / 2;
        const [ex2, ey2] = fieldAt(o, mx, my);
        const m2 = Math.hypot(ex2, ey2);
        if (m2 < 1e-9) break;
        x += dir * (ex2 / m2) * LINE_STEP_PX;
        y += dir * (ey2 / m2) * LINE_STEP_PX;
        pts.push([x, y]);
        if (x < 0 || x >= w || y < 0 || y >= h) break;
        // Terminate on a negative charge (field lines end on them).
        if (
          hasNeg &&
          o.charges.some(
            (c2) => c2.q < 0 && Math.hypot(x - c2.x, y - c2.y) < o.soften * 1.2,
          )
        ) {
          break;
        }
      }
      if (pts.length > 1) lines.push(pts);
    }
  }
  return lines;
}

// Tracing is O(lines x steps x charges) — up to ~1M ops/frame with eight 2q
// charges, which the Jetson would feel at 60 fps. But the lines only change
// when a charge MOVES, and the common case is a static scene the user is
// looking at, so memoise on a signature of the charge list: dragging retraces,
// standing still is free.
let linesCache: Vec2[][] = [];
let linesKey = "";

function cachedFieldLines(o: ChargesObject, w: number, h: number): Vec2[][] {
  const key = o.charges
    .map((c) => `${c.id}:${c.x.toFixed(1)}:${c.y.toFixed(1)}:${c.q}`)
    .join("|");
  if (key !== linesKey) {
    linesKey = key;
    linesCache = fieldLines(o, w, h);
  }
  return linesCache;
}

function drawCharges(ctx: CanvasRenderingContext2D, o: ChargesObject) {
  const w = ctx.canvas.width;
  const h = ctx.canvas.height;

  ctx.strokeStyle = "rgba(255,255,255,0.62)";
  ctx.lineWidth = 1.25;
  for (const pts of cachedFieldLines(o, w, h)) {
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.stroke();
  }

  for (const c of o.charges) {
    const r = 13 + 5 * (Math.abs(c.q) - 1);
    ctx.fillStyle = c.q > 0 ? "#f45a5a" : "#509bf5";
    ctx.beginPath();
    ctx.arc(c.x, c.y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "rgba(255,255,255,0.95)";
    ctx.lineWidth = c.grabbed ? 3 : 1.5;
    ctx.stroke();
    // +/- glyph.
    ctx.lineWidth = 2.5;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(c.x - r / 2, c.y);
    ctx.lineTo(c.x + r / 2, c.y);
    if (c.q > 0) {
      ctx.moveTo(c.x, c.y - r / 2);
      ctx.lineTo(c.x, c.y + r / 2);
    }
    ctx.stroke();
  }
}

// ---- vtuber avatar (loading state) ------------------------------------
// The real avatar is the WebGL VRM (gl/VrmAvatar). Here we only dim the
// camera and, until the model is live, show a clean loading spinner — NO
// placeholder puppet (that stand-in was the "beta model" people saw first).

function drawPuppet(
  ctx: CanvasRenderingContext2D,
  state: AppState,
  now: number,
) {
  // Skeleton view hides the avatar and draws the raw inference on the body —
  // so skip the dimming + spinner entirely and let the clear video show.
  if (isSkeletonView()) return;
  const w = state.frame.w;
  const h = state.frame.h;
  const bg = ctx.createRadialGradient(
    w / 2, h * 0.42, h * 0.2, w / 2, h / 2, Math.max(w, h) * 0.75,
  );
  bg.addColorStop(0, "rgba(14,10,26,0.72)");
  bg.addColorStop(1, "rgba(4,3,10,0.92)");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);

  if (isVrmReady()) return; // the VRM layer draws the character on top

  const cx = w / 2;
  const cy = h / 2;
  const r = Math.min(w, h) * 0.05;
  const a = (now / 1000) * 2.2;
  ctx.strokeStyle = "rgba(127,180,255,0.85)";
  ctx.lineWidth = 4;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.arc(cx, cy, r, a, a + Math.PI * 1.4);
  ctx.stroke();
  ctx.fillStyle = "rgba(237,241,247,0.7)";
  ctx.font = "500 22px 'IBM Plex Sans', system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("summoning avatar\u2026", cx, cy + r + 34);
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
      case "waves":
        drawWaves(ctx, obj, _now);
        break;
      case "charges":
        drawCharges(ctx, obj);
        break;
      case "vtuber":
        drawPuppet(ctx, state, _now);
        break;
      default:
        break; // sixseven + black_hole render in other layers
    }
  }
}
