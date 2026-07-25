import { GestureDemo } from "./GestureDemo";

/**
 * Bottom-right onboarding reminder. Mounted while the backend says the
 * hint is due (`session.hint.visible` — person detected, hasn't
 * interacted, not expired); the visibility LOGIC stays in Python
 * (ui/hints.py), only the presentation lives here.
 *
 * The demo hand and its wording both come from the backend, so the panel
 * always shows the gesture the detector is actually watching for.
 */
export function HintPanel({
  frameW,
  frameH,
  gesture,
  text,
}: {
  frameW: number;
  frameH: number;
  gesture?: "pinch" | "fist";
  text?: string;
}) {
  return (
    <div
      className="panel brackets hint-panel"
      style={{ left: frameW - 320, top: frameH - 296 }}
    >
      <GestureDemo gesture={gesture} size={96} />
      <div className="hint-text">{text ?? "Close your hand to interact"}</div>
    </div>
  );
}
