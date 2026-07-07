import type { HandState } from "../state/types";

/**
 * Per-hand pinch cursor — the web port of `src/ui/cursor.py`.
 *
 * Same affordance, redrawn in the design system: a ring whose arc fills
 * clockwise from 12 o'clock with the pinch progress (amber while closing,
 * green while held), a centre dot, and an expanding flash confirming each
 * registered click. The onboarding hand demo shows this exact ring, so
 * users recognize it on their own hand.
 */

const RING_R = 16;
const DOT_R = 4;
const STALE_MS = 200; // matches cursor.py STALE_S
const FLASH_MS = 260;
const FLASH_GROW = 22;

const UNDER = "rgba(8,10,15,0.75)";
const IDLE = "rgba(237,241,247,0.65)";
const AMBER = "#ffb84d";
const GREEN = "#63e6a4";
const FLASH = "#ffffff";

export function drawCursors(
  ctx: CanvasRenderingContext2D,
  hands: HandState[],
  flashes: Map<string, number>,
  now: number,
  frameW: number,
  frameH: number,
) {
  const live = new Set<string>();
  for (const hand of hands) {
    if (hand.seen_ms > STALE_MS) continue; // grace-window ghost
    live.add(hand.id);

    const [x, y] = hand.cursor;
    if (x < 0 || y < 0 || x >= frameW || y >= frameH) continue;

    const color =
      hand.held ? GREEN : hand.progress > 0 ? AMBER : IDLE;

    // Base ring: dark under-stroke for readability on any video content.
    ctx.lineCap = "round";
    ctx.strokeStyle = UNDER;
    ctx.lineWidth = 4.5;
    ctx.beginPath();
    ctx.arc(x, y, RING_R, 0, Math.PI * 2);
    ctx.stroke();
    ctx.strokeStyle = IDLE;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(x, y, RING_R, 0, Math.PI * 2);
    ctx.stroke();

    // Progress arc from 12 o'clock.
    if (hand.progress > 0) {
      const start = -Math.PI / 2;
      const end = start + Math.PI * 2 * hand.progress;
      ctx.strokeStyle = UNDER;
      ctx.lineWidth = 5.5;
      ctx.beginPath();
      ctx.arc(x, y, RING_R, start, end);
      ctx.stroke();
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(x, y, RING_R, start, end);
      ctx.stroke();
    }

    // Centre dot, larger while held.
    const r = DOT_R + (hand.held ? 2 : 0);
    ctx.fillStyle = UNDER;
    ctx.beginPath();
    ctx.arc(x, y, r + 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();

    // Click flash: expanding, thinning, fading ring.
    const started = flashes.get(hand.id);
    if (started !== undefined) {
      const p = (now - started) / FLASH_MS;
      if (p >= 1) {
        flashes.delete(hand.id);
      } else {
        ctx.strokeStyle = FLASH;
        ctx.globalAlpha = 1 - p;
        ctx.lineWidth = 3 * (1 - p) + 0.5;
        ctx.beginPath();
        ctx.arc(x, y, RING_R + p * FLASH_GROW, 0, Math.PI * 2);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
    }
  }

  // Drop flash timers of hands that left the frame.
  for (const id of flashes.keys()) {
    if (!live.has(id)) flashes.delete(id);
  }
}
