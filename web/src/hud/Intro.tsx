import { useEffect } from "react";
import { GestureDemo } from "./GestureDemo";

const DURATION_MS = 4600;

/**
 * Startup splash. Frontend-local by design: it plays when the PAGE loads
 * (the backend's 3 s boot-clock intro would already be over by the time a
 * kiosk browser connects). Dark glass over the live video, the animated
 * gesture demo, and a progress bar; unmounts itself via onDone.
 *
 * Only reached when attract mode is OFF. With it on, the greeting is the
 * same idea done better — once per visitor instead of once per page load,
 * which on a kiosk means once per boot, seen by nobody.
 */
export function Intro({
  onDone,
  gesture,
  hint,
}: {
  onDone: () => void;
  gesture?: "pinch" | "fist";
  hint?: string;
}) {
  useEffect(() => {
    const t = window.setTimeout(onDone, DURATION_MS);
    return () => window.clearTimeout(t);
  }, [onDone]);

  return (
    <div className="intro">
      <div className="intro-title label">HalLMediaPipe</div>
      <div className="intro-sub">Gesture-controlled vision</div>
      <GestureDemo gesture={gesture} size={140} />
      <div className="intro-hint label">
        {hint ?? "Close your hand to interact"}
      </div>
      <div className="intro-bar">
        <div className="intro-bar-fill" />
      </div>
    </div>
  );
}
