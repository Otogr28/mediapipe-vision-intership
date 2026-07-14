import type { SnapshotPair } from "./useAppState";
import type { AppState, SceneObject, Vec2 } from "./types";

/**
 * Render-time interpolation between the two latest state snapshots.
 *
 * The backend publishes at ~30 Hz while the canvas draws at display rate;
 * lerping POSITIONS between consecutive snapshots removes the 30 Hz
 * stepping. Only positions are touched — the backend already One-Euro
 * filters the cursor, so no extra smoothing is layered on top, and flags/
 * counters snap to the newest value.
 */

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const lerpVec = (a: Vec2, b: Vec2, t: number): Vec2 => [
  lerp(a[0], b[0], t),
  lerp(a[1], b[1], t),
];

/**
 * Interpolation factor for `now` (performance.now() ms). Allows a little
 * extrapolation (t <= 1.25) so motion doesn't hitch when an event arrives
 * late, but never runs further ahead than that.
 */
export function interpT(pair: SnapshotPair, now: number): number {
  const span = pair.currAt - pair.prevAt;
  if (!pair.prev || span <= 0) return 1;
  return Math.min((now - pair.prevAt) / span, 1.25);
}

/**
 * The current snapshot with positions lerped from the previous one.
 * Entities are matched by stable identity (hand id, object id/type);
 * unmatched entities render at their newest position.
 */
export function interpolate(pair: SnapshotPair, now: number): AppState {
  const { prev, curr } = pair;
  if (!prev) return curr;
  const t = interpT(pair, now);
  if (t >= 1 && pair.currAt === pair.prevAt) return curr;

  const prevHands = new Map(prev.hands.map((h) => [h.id, h]));
  const hands = curr.hands.map((h) => {
    const p = prevHands.get(h.id);
    if (!p) return h;
    return {
      ...h,
      cursor: lerpVec(p.cursor, h.cursor, t),
      landmarks:
        h.landmarks && p.landmarks && p.landmarks.length === h.landmarks.length
          ? h.landmarks.map((lm, i) => lerpVec(p.landmarks![i], lm, t))
          : h.landmarks,
    };
  });

  const pose =
    curr.pose && prev.pose && prev.pose.length === curr.pose.length
      ? curr.pose.map((lm, i) => {
          const p = prev.pose![i];
          return [lerp(p[0], lm[0], t), lerp(p[1], lm[1], t), lm[2]] as [
            number,
            number,
            number,
          ];
        })
      : curr.pose;

  const objects = curr.objects.map((o): SceneObject => {
    const po = prev.objects.find(
      (q) =>
        q.type === o.type &&
        ("id" in q && "id" in o ? q.id === (o as { id: number }).id : true),
    );
    if (!po) return o;
    switch (o.type) {
      case "sphere":
        if (po.type !== "sphere") return o;
        return { ...o, x: lerp(po.x, o.x, t), y: lerp(po.y, o.y, t) };
      case "black_hole":
        if (po.type !== "black_hole") return o;
        return { ...o, x: lerp(po.x, o.x, t), y: lerp(po.y, o.y, t) };
      case "slingshot": {
        if (po.type !== "slingshot") return o;
        const prevProj = new Map(po.projectiles.map((p) => [p.id, p]));
        return {
          ...o,
          pull:
            o.pull && po.pull ? lerpVec(po.pull, o.pull, t) : o.pull,
          projectiles: o.projectiles.map((p) => {
            const pp = prevProj.get(p.id);
            if (!pp) return p;
            return { ...p, x: lerp(pp.x, p.x, t), y: lerp(pp.y, p.y, t) };
          }),
        };
      }
      case "orbitals": {
        if (po.type !== "orbitals") return o;
        const prevBodies = new Map(po.bodies.map((b) => [b.id, b]));
        return {
          ...o,
          pull: o.pull && po.pull ? lerpVec(po.pull, o.pull, t) : o.pull,
          bodies: o.bodies.map((b) => {
            const pb = prevBodies.get(b.id);
            if (!pb) return b;
            return { ...b, x: lerp(pb.x, b.x, t), y: lerp(pb.y, b.y, t) };
          }),
        };
      }
      case "waves": {
        if (po.type !== "waves") return o;
        const prevSrc = new Map(po.sources.map((s) => [s.id, s]));
        return {
          ...o,
          sources: o.sources.map((s) => {
            const ps = prevSrc.get(s.id);
            if (!ps) return s;
            return { ...s, x: lerp(ps.x, s.x, t), y: lerp(ps.y, s.y, t) };
          }),
        };
      }
      default:
        return o;
    }
  });

  return { ...curr, hands, pose, objects };
}
