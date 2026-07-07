import { memo } from "react";
import type { ButtonState, SpeedPill } from "../state/types";

/**
 * Gesture buttons — pure displays of the backend's hit-testing (the rects
 * and hovered/pressed flags come straight from `ui/button.py`). No DOM
 * pointer events: the pinch cursor is the only pointer in this app.
 */

const Button = memo(function Button({ btn }: { btn: ButtonState }) {
  const [x, y, w, h] = btn.rect;
  const cls =
    "gbtn brackets" +
    (btn.pressed ? " pressed" : btn.hovered ? " hovered" : "");
  return (
    <div
      className={cls}
      data-btn-id={btn.id}
      style={{ left: x, top: y, width: w, height: h }}
    >
      <span>{btn.label}</span>
    </div>
  );
});

export function Buttons({
  buttons,
  speed,
}: {
  buttons: ButtonState[];
  speed: SpeedPill | null;
}) {
  return (
    <>
      {buttons.map((b) => (
        <Button key={b.id} btn={b} />
      ))}
      {speed && (
        <div
          className="speed-pill data"
          style={{
            left: speed.rect[0],
            top: speed.rect[1],
            width: speed.rect[2],
            height: speed.rect[3],
          }}
        >
          {speed.text}
        </div>
      )}
    </>
  );
}
