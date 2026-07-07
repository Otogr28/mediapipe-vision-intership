import { useEffect, useRef, useState } from "react";
import type { AppState } from "./types";

/**
 * A pair of consecutive state snapshots plus their arrival clocks — the
 * input to render-time interpolation (see interp.ts). `prev` is null until
 * two events have arrived.
 */
export interface SnapshotPair {
  prev: AppState | null;
  prevAt: number;
  curr: AppState;
  currAt: number;
}

export interface AppStateHook {
  /** Latest snapshot, for React-rendered (DOM) parts. */
  state: AppState | null;
  /** True while the SSE stream is open and events are flowing. */
  connected: boolean;
  /**
   * Live ref to the snapshot pair for canvas rAF loops — reading it never
   * re-renders React. Mutated on every SSE event (~30 Hz).
   */
  pairRef: React.RefObject<SnapshotPair | null>;
}

/** How long without events before the stream counts as stalled (ms). */
const STALL_MS = 2000;

/**
 * Subscribes to the backend's `/state` SSE stream.
 *
 * Two consumers with different needs share it:
 * - React DOM (buttons, HUD): re-rendered per event via useState. The tree
 *   is small and mostly memoizable; 30 Hz is fine.
 * - Canvas layers: read `pairRef` inside their own rAF loop and interpolate
 *   between the two latest snapshots for display-rate smoothness.
 *
 * EventSource auto-reconnects; `connected` additionally drops on a stall
 * (no events for STALL_MS) so the UI can show a banner while the backend
 * is down but the socket hasn't errored yet.
 */
export function useAppState(): AppStateHook {
  const [state, setState] = useState<AppState | null>(null);
  const [connected, setConnected] = useState(false);
  const pairRef = useRef<SnapshotPair | null>(null);

  useEffect(() => {
    const source = new EventSource("/state");
    let stallTimer: number | undefined;

    const bumpStall = () => {
      window.clearTimeout(stallTimer);
      stallTimer = window.setTimeout(() => setConnected(false), STALL_MS);
    };

    source.onmessage = (ev) => {
      const snapshot = JSON.parse(ev.data) as AppState;
      const now = performance.now();
      const last = pairRef.current;
      pairRef.current = {
        prev: last?.curr ?? null,
        prevAt: last?.currAt ?? now,
        curr: snapshot,
        currAt: now,
      };
      setState(snapshot);
      setConnected(true);
      bumpStall();
    };
    source.onerror = () => setConnected(false);

    return () => {
      window.clearTimeout(stallTimer);
      source.close();
    };
  }, []);

  return { state, connected, pairRef };
}
