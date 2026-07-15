import { useEffect, useRef } from "react";
import { interpolate } from "../state/interp";
import type { SnapshotPair } from "../state/useAppState";
import { drawCursors } from "./cursor";
import { drawBackdrop, drawScene, updateTrails } from "./scene";
import { drawSkeleton } from "./skeleton";

interface Props {
  pairRef: React.RefObject<SnapshotPair | null>;
  frameW: number;
  frameH: number;
}

/**
 * The Canvas2D overlay: skeleton, scene objects and pinch cursors, drawn
 * every display frame in FRAME-PIXEL coordinates (the canvas buffer is the
 * camera frame size; CSS scales it with the stage, so no transform math
 * exists anywhere in the draw code).
 *
 * Runs its own rAF loop reading `pairRef` — React never re-renders this.
 */
export function OverlayCanvas({ pairRef, frameW, frameH }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext("2d")!;
    let raf = 0;
    let lastSeq = -1;
    // hand_id -> flash start time; trail buffers live in scene.ts.
    const flashes = new Map<string, number>();

    const draw = () => {
      raf = requestAnimationFrame(draw);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const pair = pairRef.current;
      if (!pair) return;
      const now = performance.now();

      // One-frame edge events are consumed once per backend snapshot,
      // not once per rAF (the same snapshot is drawn several times).
      if (pair.curr.seq !== lastSeq) {
        lastSeq = pair.curr.seq;
        for (const h of pair.curr.hands) {
          if (h.pinching) flashes.set(h.id, now);
        }
        // Trails accumulate the EXACT backend positions, one per snapshot.
        updateTrails(pair.curr);
      }

      const state = interpolate(pair, now);
      // The backdrop dims the camera image only: it goes down first, so the
      // skeleton, scene and cursors all sit on top of it at full strength.
      // Nothing here can reach the frame inference sees — the backend streams
      // raw frames and does no drawing in web mode.
      drawBackdrop(ctx, state);
      drawSkeleton(ctx, state, frameW, frameH);
      drawScene(ctx, state, now);
      drawCursors(ctx, state.hands, flashes, now, frameW, frameH);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [pairRef, frameW, frameH]);

  return (
    <canvas
      ref={canvasRef}
      className="layer"
      width={frameW}
      height={frameH}
    />
  );
}
