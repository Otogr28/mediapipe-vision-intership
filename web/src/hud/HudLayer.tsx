import { useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

interface Props {
  frameW: number;
  frameH: number;
  children: ReactNode;
}

/**
 * A DOM layer that lives in FRAME-PIXEL coordinates, like the canvases:
 * it is laid out at the camera frame's size and scaled onto the stage with
 * a transform. Children position with plain `left/top/width/height` in
 * frame pixels — identical numbers to the backend rects — and every font
 * and padding scales with the stage automatically.
 */
export function HudLayer({ frameW, frameH, children }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el?.parentElement) return;
    const stage = el.parentElement;
    const observer = new ResizeObserver(() => {
      setScale(stage.clientWidth / frameW);
    });
    observer.observe(stage);
    return () => observer.disconnect();
  }, [frameW]);

  return (
    <div
      ref={ref}
      className="hud-layer"
      style={{
        width: frameW,
        height: frameH,
        transform: `scale(${scale})`,
      }}
    >
      {children}
    </div>
  );
}
