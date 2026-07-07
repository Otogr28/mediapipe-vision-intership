import { useEffect } from "react";
import { PinchHand } from "./PinchHand";

const DURATION_MS = 4600;

/**
 * Startup splash. Frontend-local by design: it plays when the PAGE loads
 * (the backend's 3 s boot-clock intro would already be over by the time a
 * kiosk browser connects). Dark glass over the live video, the animated
 * pinch demo, and a progress bar; unmounts itself via onDone.
 */
export function Intro({ onDone }: { onDone: () => void }) {
  useEffect(() => {
    const t = window.setTimeout(onDone, DURATION_MS);
    return () => window.clearTimeout(t);
  }, [onDone]);

  return (
    <div className="intro">
      <div className="intro-title label">HalLMediaPipe</div>
      <div className="intro-sub">Gesture-controlled vision</div>
      <PinchHand size={140} />
      <div className="intro-hint label">Close your hand to interact</div>
      <div className="intro-bar">
        <div className="intro-bar-fill" />
      </div>
    </div>
  );
}
