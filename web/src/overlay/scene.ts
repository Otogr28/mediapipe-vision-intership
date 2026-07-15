import { isVrmReady } from "../gl/vrmState";
import { isSkeletonView } from "./debugView";
import type {
  AppState,
  ChargesObject,
  OrbitalsObject,
  SlingshotObject,
  SpacetimeObject,
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
// Spacetime orbiter id -> recent PLANE positions (the sheet depth is derived,
// so storing (x, y) is enough to re-project a whole trail each frame).
const stTrails = new Map<number, Vec2[]>();
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

  // Spacetime orbiters: the trail is the whole point here — a precessing
  // ellipse only reads as precessing if you can see where it has been.
  const st = state.objects.find(
    (o): o is SpacetimeObject => o.type === "spacetime",
  );
  if (st) accumulate(stTrails, st.orbiters, st.trail_len);
  else if (stTrails.size) stTrails.clear();
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

// Flowing arrowheads. They ride the SAME traced polylines (the geometry is
// untouched) and just march along them, so they show which way the field
// points: out of + charges, into - ones.
//
// Arc length is exactly `index * LINE_STEP_PX` because the tracer steps a
// fixed distance, so an arrow's vertex index is an O(1) divide — no search.
const ARROW_SPACING_PX = 46; // arc length between arrows on one line
const ARROW_SPEED_PX_S = 34; // how fast they crawl along it
const ARROW_LEN_PX = 9;
/**
 * |E| that maps to a full-strength arrow. Arrow size/alpha come from the
 * LOCAL |E|, which is what makes cancellation visible for free: at a null
 * point between like charges |E| is exactly 0, so the arrows there shrink to
 * nothing on their own — no special case. Far field (weak) fades too, which
 * keeps the picture clean. ~3 puts a unit charge's arrows at full strength
 * about 150 px out.
 */
const ARROW_E_REF = 3.0;

/** One traced field line: the polyline plus |E| sampled at each vertex. */
interface FieldLine {
  pts: Vec2[];
  /** |E| at each vertex, parallel to `pts` — drives arrow size/alpha. */
  e: number[];
}

interface FieldLines {
  lines: FieldLine[];
  /**
   * +1 when the polylines were traced ALONG E (seeded on + charges, the
   * normal case), -1 when traced against it (negatives-only fallback). The
   * arrows point this way, so they always fly along the real field.
   */
  dir: number;
}

function fieldLines(o: ChargesObject, w: number, h: number): FieldLines {
  const lines: FieldLine[] = [];
  if (!o.charges.length) return { lines, dir: 1 };
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
      const e: number[] = [];
      for (let s = 0; s < LINE_MAX_STEPS; s++) {
        const [ex, ey] = fieldAt(o, x, y);
        const m = Math.hypot(ex, ey);
        e.push(m); // |E| at THIS vertex — free, we already computed it
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
      // `e` lags `pts` by the final vertex (the loop breaks before sampling
      // it); repeat the last value so the two stay index-aligned.
      while (e.length < pts.length) e.push(e[e.length - 1] ?? 0);
      if (pts.length > 1) lines.push({ pts, e });
    }
  }
  return { lines, dir };
}

/**
 * Draw the arrowheads riding one line at the current phase. Arc length is
 * `index * LINE_STEP_PX`, so the vertex under an arrow is a divide, not a
 * search — this stays cheap even with a couple of hundred lines.
 */
function drawFlowArrows(
  ctx: CanvasRenderingContext2D,
  line: FieldLine,
  dir: number,
  phase: number,
) {
  const { pts, e } = line;
  const len = (pts.length - 1) * LINE_STEP_PX;
  for (let s = phase; s < len; s += ARROW_SPACING_PX) {
    const idx = s / LINE_STEP_PX;
    const i = Math.floor(idx);
    if (i < 0 || i + 1 >= pts.length) continue;
    const f = idx - i;
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[i + 1];
    const px = x0 + (x1 - x0) * f;
    const py = y0 + (y1 - y0) * f;
    // Tangent, flipped to the true field direction for negative-seeded lines.
    let tx = (x1 - x0) * dir;
    let ty = (y1 - y0) * dir;
    const tm = Math.hypot(tx, ty);
    if (tm < 1e-6) continue;
    tx /= tm;
    ty /= tm;
    // Strength from the LOCAL |E|: arrows vanish where the field cancels.
    const strength = Math.tanh((e[i] ?? 0) / ARROW_E_REF);
    if (strength < 0.04) continue;
    const L = ARROW_LEN_PX * (0.45 + 0.55 * strength);
    const W = L * 0.52;
    const nx = -ty;
    const ny = tx;
    ctx.globalAlpha = strength;
    ctx.beginPath();
    ctx.moveTo(px + tx * L * 0.5, py + ty * L * 0.5); // tip
    ctx.lineTo(px - tx * L * 0.5 + nx * W * 0.5, py - ty * L * 0.5 + ny * W * 0.5);
    ctx.lineTo(px - tx * L * 0.5 - nx * W * 0.5, py - ty * L * 0.5 - ny * W * 0.5);
    ctx.closePath();
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

// Tracing is O(lines x steps x charges) — up to ~1M ops/frame with eight 2q
// charges, which the Jetson would feel at 60 fps. But the lines only change
// when a charge MOVES, and the common case is a static scene the user is
// looking at, so memoise on a signature of the charge list: dragging retraces,
// standing still is free.
let linesCache: FieldLines = { lines: [], dir: 1 };
let linesKey = "";

function cachedFieldLines(o: ChargesObject, w: number, h: number): FieldLines {
  const key = o.charges
    .map((c) => `${c.id}:${c.x.toFixed(1)}:${c.y.toFixed(1)}:${c.q}`)
    .join("|");
  if (key !== linesKey) {
    linesKey = key;
    linesCache = fieldLines(o, w, h);
  }
  return linesCache;
}

function drawCharges(
  ctx: CanvasRenderingContext2D,
  o: ChargesObject,
  now: number,
) {
  const w = ctx.canvas.width;
  const h = ctx.canvas.height;
  const { lines, dir } = cachedFieldLines(o, w, h);

  // The arrows march on a frontend-local clock: the flow is pure decoration
  // (the physics is static), so the backend has nothing to say about it.
  const phase = ((now / 1000) * ARROW_SPEED_PX_S) % ARROW_SPACING_PX;

  ctx.strokeStyle = "rgba(255,255,255,0.42)";
  ctx.lineWidth = 1.25;
  for (const { pts } of lines) {
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.stroke();
  }

  ctx.fillStyle = "rgba(255,255,255,0.95)";
  for (const line of lines) drawFlowArrows(ctx, line, dir, phase);

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

// ---- spacetime (relativistic gravity) -----------------------------------

/**
 * Ports of `_flamm_depth` and `Spacetime._project` in ui/interactables.py —
 * KEEP IN SYNC. The backend sends the masses, the camera and the constants;
 * the sheet itself is re-derived here so it costs nothing in the payload.
 */
function flammDepth(r: number, rs: number, reach: number, gain: number) {
  if (rs <= 0 || r >= reach || rs >= reach) return 0;
  const rr = Math.max(r, rs); // inside the horizon the embedding ends
  const edge = 2 * Math.sqrt(rs * (reach - rs));
  const here = 2 * Math.sqrt(rs * (rr - rs));
  return -gain * (edge - here);
}

function sheetDepth(o: SpacetimeObject, x: number, y: number) {
  let z = 0;
  for (const m of o.masses) {
    z += flammDepth(Math.hypot(x - m.x, y - m.y), m.rs, o.reach, o.depth_gain);
  }
  // Soft depth ceiling — mirrors Spacetime._depth. The embedding is vertical
  // at the throat, so an unclamped funnel projects to a tangle; tanh leaves a
  // shallow well untouched and saturates the deep ones smoothly.
  return -o.max_depth * Math.tanh(-z / o.max_depth);
}

/**
 * Areal radius -> Schwarzschild ISOTROPIC radius. Port of
 * `_isotropic_radius` in ui/interactables.py — KEEP IN SYNC.
 *
 * Inverts r = rbar*(1 + rs/(4*rbar))², landing the horizon at rbar = rs/4.
 * Drawing the lattice at rbar is what compresses space toward a mass in the
 * 3D view — it comes from the metric, not from taste.
 */
function isotropicRadius(r: number, rs: number) {
  if (rs <= 0) return r;
  const half = rs * 0.5;
  const b = r - half;
  const disc = b * b - half * half;
  if (disc <= 0) return rs * 0.25;
  return (b + Math.sqrt(disc)) * 0.5;
}

/**
 * Lense–Thirring frame dragging — port of `Spacetime._drag_frame`.
 * A spinning mass winds space around itself at ω = 2GJ/(c²r³); the 1/r³
 * falloff makes it a tight local swirl, invisible around a star and violent
 * around a fast hole. Display only.
 */
function dragFrame(o: SpacetimeObject, x: number, y: number): [number, number] {
  for (const m of o.masses) {
    if (m.spin <= 0) continue;
    const dx = x - m.x;
    const dy = y - m.y;
    const r = Math.hypot(dx, dy);
    if (r < 1e-6 || r >= o.reach) continue;
    const rEff = Math.max(r, m.r_horizon);
    const j = m.spin * (m.rs * 0.5); // J/(Mc) = a* * M
    let twist = (2 * o.g * m.m * j) / (o.c * o.c * rEff * rEff * rEff);
    twist = Math.max(-o.lt_max, Math.min(o.lt_max, twist * o.lt_gain));
    twist *= (1 - r / o.reach) ** 2;
    if (Math.abs(twist) < 1e-5) continue;
    const c = Math.cos(twist);
    const s = Math.sin(twist);
    x = m.x + dx * c - dy * s;
    y = m.y + dx * s + dy * c;
  }
  return [x, y];
}

/**
 * 3D-view radial map — port of `Spacetime._lattice_offset`. Pulls a lattice
 * point toward each mass in full 3D by the isotropic relation, so the layers
 * above and below a mass bend toward it too.
 */
function latticeOffset(
  o: SpacetimeObject,
  x: number,
  y: number,
  z: number,
): [number, number, number] {
  for (const m of o.masses) {
    const dx = x - m.x;
    const dy = y - m.y;
    const dz = z;
    const r = Math.sqrt(dx * dx + dy * dy + dz * dz);
    if (r < 1e-6 || r >= o.reach) continue;
    const rbar = isotropicRadius(Math.max(r, m.r_horizon), m.rs);
    let delta = (r - rbar) * o.lattice_gain;
    delta *= (1 - r / o.reach) ** 2;
    // never pull a point through the centre
    delta = Math.min(delta, r - m.r_horizon * 0.5);
    const k = (r - delta) / r;
    x = m.x + dx * k;
    y = m.y + dy * k;
    z = dz * k;
  }
  return [x, y, z];
}

/** World (plane px, depth) -> [screenX, screenY, cameraDepth]. */
function project(
  o: SpacetimeObject,
  x: number,
  y: number,
  z: number,
  fw: number,
  fh: number,
): [number, number, number] {
  const cx = fw * 0.5;
  const cy = fh * 0.5;
  const px = x - cx;
  const py = y - cy;
  const cyaw = Math.cos(o.yaw);
  const syaw = Math.sin(o.yaw);
  const x1 = px * cyaw - py * syaw;
  const y1 = px * syaw + py * cyaw;
  const cp = Math.cos(o.pitch);
  const sp = Math.sin(o.pitch);
  const y2 = y1 * sp - z * cp;
  const d = y1 * cp + z * sp;
  const f = o.focal / Math.max(o.focal + d, 1);
  return [cx + x1 * f * o.zoom, cy + y2 * f * o.zoom, d];
}

/** Perspective scale at a camera depth — sizes markers with the grid. */
function depthScale(o: SpacetimeObject, d: number) {
  return (o.focal / Math.max(o.focal + d, 1)) * o.zoom;
}

/**
 * The backdrop dim. Drawn on the OVERLAY canvas, which sits above the camera
 * <img> — so it darkens the video only, and the skeleton/grid/HUD stack on top
 * at full strength. The frame the backend hands to inference is never touched
 * (in web mode the backend does not draw at all).
 */
export function drawBackdrop(ctx: CanvasRenderingContext2D, state: AppState) {
  const o = state.objects.find(
    (s): s is SpacetimeObject => s.type === "spacetime",
  );
  if (!o) return;
  const [r, g, b] = o.dim_rgb;
  ctx.fillStyle = `rgba(${r},${g},${b},${o.dim})`;
  ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
}

function drawSpacetime(
  ctx: CanvasRenderingContext2D,
  o: SpacetimeObject,
  fw: number,
  fh: number,
) {
  const cx = fw * 0.5;
  const cy = fh * 0.5;

  // One stroke per gridline (not per segment): ~40 draw calls a frame instead
  // of ~3000, which is what keeps this affordable on the Jetson kiosk. The
  // well reads from the GEOMETRY (the sag) plus the mass markers; the fog only
  // has to sell near-vs-far, so a per-line mean depth is enough.
  const strokeLine = (pts: [number, number, number][], alpha = 1) => {
    if (pts.length < 2) return;
    let meanD = 0;
    for (const p of pts) meanD += p[2];
    meanD /= pts.length;
    // Fog: +/- one frame-width of depth maps to the alpha range.
    const t = Math.max(0, Math.min(1, 0.5 - meanD / (fw * 1.6)));
    ctx.strokeStyle = `rgba(${120 + 80 * t},${170 + 60 * t},255,${(0.16 + 0.42 * t) * alpha})`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.stroke();
  };

  if (o.view_3d) {
    // --- 3D: a VOLUME of space, compressed radially toward each mass. No
    // fake extra dimension and no "downhill" — the grid is simply denser where
    // distances are stretched, which is what curvature actually does.
    const [lc, lr, layers, ls, lext, ldepth] = o.lattice;
    const hw = fw * lext * 0.5;
    const hh = fh * lext * 0.5;
    const lx0 = cx - hw;
    const lx1 = cx + hw;
    const ly0 = cy - hh;
    const ly1 = cy + hh;
    const zs: number[] = [];
    for (let k = 0; k < layers; k++) {
      zs.push(layers > 1 ? ldepth * (k / (layers - 1) - 0.5) : 0);
    }
    const pt = (x: number, y: number, z: number): [number, number, number] => {
      const [tx, ty] = dragFrame(o, x, y);
      const [wx, wy, wz] = latticeOffset(o, tx, ty, z);
      return project(o, wx, wy, wz, fw, fh);
    };
    for (const z of zs) {
      // The equatorial layer is where the orbits live — brighten it so the
      // stack reads as a volume with a distinguished plane, not a mush.
      const a = Math.abs(z) < 1e-6 ? 1.35 : 0.62;
      for (let i = 0; i <= lc; i++) {
        const x = lx0 + ((lx1 - lx0) * i) / lc;
        const pts: [number, number, number][] = [];
        for (let j = 0; j <= ls; j++) {
          pts.push(pt(x, ly0 + ((ly1 - ly0) * j) / ls, z));
        }
        strokeLine(pts, a);
      }
      for (let j = 0; j <= lr; j++) {
        const y = ly0 + ((ly1 - ly0) * j) / lr;
        const pts: [number, number, number][] = [];
        for (let i = 0; i <= ls; i++) {
          pts.push(pt(lx0 + ((lx1 - lx0) * i) / ls, y, z));
        }
        strokeLine(pts, a);
      }
    }
    if (o.lattice_verticals && layers > 1) {
      const zn = 10;
      const vs = Math.max(1, o.vert_stride);
      for (let i = 0; i <= lc; i += vs) {
        for (let j = 0; j <= lr; j += vs) {
          const x = lx0 + ((lx1 - lx0) * i) / lc;
          const y = ly0 + ((ly1 - ly0) * j) / lr;
          const pts: [number, number, number][] = [];
          for (let k = 0; k <= zn; k++) {
            pts.push(pt(x, y, zs[0] + ((zs[zs.length - 1] - zs[0]) * k) / zn));
          }
          strokeLine(pts, 0.3);
        }
      }
    }
  } else {
    // --- 2D: the classic embedding sheet (one slice, bent into a dimension
    // that is not really there).
    const [cols, rows, samples, extent] = o.grid;
    const hw = fw * extent * 0.5;
    const hh = fh * extent * 0.5;
    const x0 = cx - hw;
    const x1 = cx + hw;
    const y0 = cy - hh;
    const y1 = cy + hh;
    const pt = (x: number, y: number): [number, number, number] => {
      const [tx, ty] = dragFrame(o, x, y);
      return project(o, tx, ty, sheetDepth(o, tx, ty), fw, fh);
    };
    for (let i = 0; i <= cols; i++) {
      const x = x0 + ((x1 - x0) * i) / cols;
      const pts: [number, number, number][] = [];
      for (let j = 0; j <= samples; j++) {
        pts.push(pt(x, y0 + ((y1 - y0) * j) / samples));
      }
      strokeLine(pts);
    }
    for (let j = 0; j <= rows; j++) {
      const y = y0 + ((y1 - y0) * j) / rows;
      const pts: [number, number, number][] = [];
      for (let i = 0; i <= samples; i++) {
        pts.push(pt(x0 + ((x1 - x0) * i) / samples, y));
      }
      strokeLine(pts);
    }
  }

  // Orbiters live in the equatorial plane; in 3D that IS z = 0, in 2D it is
  // the sheet's own surface.
  const depthAt = (x: number, y: number) => (o.view_3d ? 0 : sheetDepth(o, x, y));

  // Orbiter trails — the precession evidence.
  const [tr, tg, tb] = o.orbiter_rgb;
  for (const orb of o.orbiters) {
    const trail = stTrails.get(orb.id);
    if (!trail || trail.length < 2) continue;
    ctx.strokeStyle = `rgba(${tr},${tg},${tb},0.5)`;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < trail.length; i++) {
      const [wx, wy] = trail[i];
      const [sx, sy] = project(o, wx, wy, depthAt(wx, wy), fw, fh);
      if (i === 0) ctx.moveTo(sx, sy);
      else ctx.lineTo(sx, sy);
    }
    ctx.stroke();
  }

  // Markers, far to near, so a body behind a well is occluded by the one in
  // front rather than punching through it.
  type Marker = { d: number; draw: () => void };
  const markers: Marker[] = [];

  for (const orb of o.orbiters) {
    const [sx, sy, d] = project(o, orb.x, orb.y, depthAt(orb.x, orb.y), fw, fh);
    const rad = Math.max(2.5, 5 * depthScale(o, d));
    markers.push({
      d,
      draw: () => {
        ctx.fillStyle = `rgb(${tr},${tg},${tb})`;
        ctx.beginPath();
        ctx.arc(sx, sy, rad, 0, Math.PI * 2);
        ctx.fill();
      },
    });
  }

  for (const m of o.masses) {
    const [sx, sy, d] = project(o, m.x, m.y, depthAt(m.x, m.y), fw, fh);
    const sc = depthScale(o, d);
    // A compact body IS its horizon, so it is drawn at r_horizon — which
    // SHRINKS as it spins. A star only gets a marker, floored so it stays
    // visible when the camera pulls back.
    const rad = m.compact
      ? Math.max(4, m.r_horizon * sc)
      : Math.max(7, m.r_horizon * sc * 0.9);
    const ergo = m.r_ergo * sc;
    const [r, g, b] = m.rgb;
    markers.push({
      d,
      draw: () => {
        if (!m.compact) {
          const glow = ctx.createRadialGradient(sx, sy, 0, sx, sy, rad * 3);
          glow.addColorStop(0, `rgba(${r},${g},${b},0.5)`);
          glow.addColorStop(1, `rgba(${r},${g},${b},0)`);
          ctx.fillStyle = glow;
          ctx.beginPath();
          ctx.arc(sx, sy, rad * 3, 0, Math.PI * 2);
          ctx.fill();
        }
        // Ergosphere. It sits at rs regardless of spin while the horizon
        // shrinks under it, so this ring only separates from the body when it
        // spins — the gap IS the spin, and at a* = 0 it closes by itself.
        if (m.spin > 0 && ergo > rad + 1.5) {
          ctx.strokeStyle = `rgba(150,190,255,${0.16 + 0.3 * m.spin})`;
          ctx.lineWidth = 1;
          ctx.setLineDash([3, 4]);
          ctx.beginPath();
          ctx.arc(sx, sy, ergo, 0, Math.PI * 2);
          ctx.stroke();
          ctx.setLineDash([]);
        }
        ctx.fillStyle = `rgb(${r},${g},${b})`;
        ctx.beginPath();
        ctx.arc(sx, sy, rad, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = m.grabbed
          ? "#3fdc82"
          : m.compact
            ? "rgba(190,200,255,0.85)"
            : "rgba(255,255,255,0.6)";
        ctx.lineWidth = m.grabbed ? 2.5 : 1;
        ctx.stroke();
        // Spin marker: two spokes, so rotation is legible on a plain disk
        // (one spoke on a symmetric disk reads ambiguously at speed).
        if (m.spin > 0) {
          ctx.strokeStyle = m.compact
            ? "rgba(200,215,255,0.9)"
            : "rgba(90,60,20,0.9)";
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          for (const k of [0, Math.PI]) {
            ctx.moveTo(sx, sy);
            ctx.lineTo(
              sx + Math.cos(m.phase + k) * rad * 0.85,
              sy + Math.sin(m.phase + k) * rad * 0.85,
            );
          }
          ctx.stroke();
        }
        if (m.flash > 0) {
          ctx.strokeStyle = `rgba(255,255,255,${m.flash})`;
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(sx, sy, rad + 30 * (1 - m.flash), 0, Math.PI * 2);
          ctx.stroke();
        }
      },
    });
  }

  markers.sort((a, b) => b.d - a.d);
  for (const mk of markers) mk.draw();

  // Ghost: where a release would drop the next object.
  if (o.ghost) {
    const [sx, sy] = project(
      o,
      o.ghost.x,
      o.ghost.y,
      depthAt(o.ghost.x, o.ghost.y),
      fw,
      fh,
    );
    ctx.strokeStyle = "rgba(230,230,240,0.8)";
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.arc(sx, sy, 11, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Rotate affordance: while both hands drive the camera, say so.
  if (o.rotating) {
    ctx.fillStyle = "rgba(140,235,255,0.9)";
    ctx.font = "600 22px ui-sans-serif, system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText("3D rotate", cx, 16);
  }
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
        drawCharges(ctx, obj, _now);
        break;
      case "spacetime":
        drawSpacetime(ctx, obj, state.frame.w, state.frame.h);
        break;
      case "vtuber":
        drawPuppet(ctx, state, _now);
        break;
      default:
        break; // sixseven + black_hole render in other layers
    }
  }
}
