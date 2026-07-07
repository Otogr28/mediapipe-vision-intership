import { PinchHand } from "./PinchHand";

/**
 * Bottom-right onboarding reminder. Mounted while the backend says the
 * hint is due (`session.hint.visible` — person detected, hasn't
 * interacted, not expired); the visibility LOGIC stays in Python
 * (ui/hints.py), only the presentation lives here.
 */
export function HintPanel({ frameW, frameH }: { frameW: number; frameH: number }) {
  return (
    <div
      className="panel brackets hint-panel"
      style={{ left: frameW - 320, top: frameH - 296 }}
    >
      <PinchHand size={96} />
      <div className="hint-text">Close your hand to interact</div>
    </div>
  );
}
