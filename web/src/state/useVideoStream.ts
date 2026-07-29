import { useCallback, useEffect, useRef, useState } from "react";
import type { SnapshotPair } from "./useAppState";

/**
 * Keeps the live MJPEG <img> connected.
 *
 * The camera layer is a single long-lived `multipart/x-mixed-replace` request.
 * An <img> gives no per-frame event and, unlike EventSource, does NOT reopen
 * itself: a connection that dies or freezes mid-visit leaves a blank camera
 * layer until something remounts the element. On the exhibit that something
 * was the attract cycle, which is why the operator's symptom was "the camera
 * stops showing until it goes through idle" — minutes of blank picture while
 * the backend was measurably healthy (/state climbing, /snapshot.jpg fresh, a
 * new client pulling ~29 fps off the same route).
 *
 * So the liveness test is the picture itself: sample it into a tiny canvas and
 * watch whether it changes. Two other signals fill the gaps a pixel compare
 * cannot see — `onError` for a refused or reset connection, and a first-frame
 * deadline for one that opens and never decodes anything.
 */

/** How often the picture is checked for movement (ms). */
const SAMPLE_MS = 500;
/** Consecutive identical samples before the stream counts as frozen. */
const STALL_SAMPLES = 6;
/** A connection that decodes no frame within this long is stalled too (ms). */
const FIRST_FRAME_MS = 6000;
/**
 * Sample size. Small enough that drawImage + getImageData at 2 Hz is free,
 * big enough that anybody moving in frame changes at least one byte. Averaging
 * ~20x20 source pixels per sample pixel does suppress sensor noise, so a
 * genuinely motionless scene can read as frozen — that false positive is what
 * the backoff below is for.
 */
const SAMPLE_W = 64;
const SAMPLE_H = 36;
/** First retry delay, doubling per consecutive failure, capped (ms). */
const RETRY_MS = 3000;
const RETRY_MAX_MS = 30000;

export interface VideoStream {
  /** Ref for the <img> — also what LensedVideo samples as its GL texture. */
  ref: React.RefObject<HTMLImageElement | null>;
  /** React key: changing it is what tears the dead connection down. */
  key: number;
  /** Cache-busted after the first attempt, so a retry is a fresh request. */
  src: string;
  onError: () => void;
}

function sameBytes(a: Uint8ClampedArray, b: Uint8ClampedArray) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

/**
 * @param active  Whether the <img> is mounted (false during attract, where the
 *                element is deliberately dropped so nothing is decoded).
 * @param pairRef The state stream, used only to tell a stalled VIDEO apart from
 *                a stopped BACKEND.
 */
export function useVideoStream(
  active: boolean,
  pairRef: React.RefObject<SnapshotPair | null>,
): VideoStream {
  const ref = useRef<HTMLImageElement>(null);
  const [attempt, setAttempt] = useState(0);
  // Backoff has to outlive the remount a reconnect causes, so it sits in refs
  // rather than inside the effect (which restarts on every attempt).
  const nextRetryAt = useRef(0);
  const backoff = useRef(RETRY_MS);

  const reconnect = useCallback((why: string) => {
    const now = performance.now();
    if (now < nextRetryAt.current) return;
    nextRetryAt.current = now + backoff.current;
    backoff.current = Math.min(backoff.current * 2, RETRY_MAX_MS);
    // Said out loud: a reconnect means something upstream is wrong, and this
    // line is the only trace of it (web/scripts/shot.mjs collects warnings).
    console.warn(`camera stream ${why} — reopening /stream.mjpg`);
    setAttempt((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!active) return;

    const canvas = document.createElement("canvas");
    canvas.width = SAMPLE_W;
    canvas.height = SAMPLE_H;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return;

    const startedAt = performance.now();
    let last: Uint8ClampedArray | null = null;
    let identical = 0;
    let lastAt = -1;

    const check = () => {
      const img = ref.current;
      if (!img) return;

      // Only judge the <img> while the BACKEND is publishing. `currAt` is
      // stamped by useAppState on every SSE event, so it says "the render loop
      // came round" without depending on a payload field — and the loop
      // publishes the JPEG in the same iteration it publishes the state. With
      // the backend down, reopening the stream buys nothing and App's
      // "Reconnecting to camera backend" banner is already the true thing.
      const at = pairRef.current?.currAt ?? -1;
      const publishing = at !== lastAt;
      lastAt = at;
      if (!publishing) {
        identical = 0;
        return;
      }

      if (img.naturalWidth === 0) {
        // Nothing decoded on this connection yet: there is no picture to
        // compare, so the sampler below would wait forever.
        if (performance.now() - startedAt > FIRST_FRAME_MS) {
          reconnect("delivered no frame");
        }
        return;
      }

      ctx.drawImage(img, 0, 0, SAMPLE_W, SAMPLE_H);
      const px = ctx.getImageData(0, 0, SAMPLE_W, SAMPLE_H).data;
      if (last && sameBytes(last, px)) {
        identical += 1;
        if (identical >= STALL_SAMPLES) reconnect("frozen");
      } else {
        identical = 0;
        // The picture moved, so this connection works: drop the backoff a
        // previous failure built up, and let the next stall retry fast.
        backoff.current = RETRY_MS;
      }
      last = px;
    };

    const timer = window.setInterval(check, SAMPLE_MS);
    return () => window.clearInterval(timer);
  }, [active, attempt, pairRef, reconnect]);

  return {
    ref,
    key: attempt,
    src: attempt === 0 ? "/stream.mjpg" : `/stream.mjpg?r=${attempt}`,
    onError: () => reconnect("errored"),
  };
}
