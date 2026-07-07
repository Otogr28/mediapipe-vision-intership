import type { SixSevenObject } from "../state/types";

/** Top-centre counter card for the 6-7 arm-pump counter. */
export function SixSeven({ obj, frameW }: { obj: SixSevenObject; frameW: number }) {
  const flash = obj.flash; // 1.0 right after a count, decaying to 0
  return (
    <div
      className="panel brackets sixseven"
      style={{
        left: frameW / 2,
        top: 14,
        transform: "translateX(-50%)",
        borderColor: flash > 0 ? `rgba(99,230,164,${0.35 + 0.65 * flash})` : undefined,
      }}
    >
      <div className="label six-label">6 7 count</div>
      <div
        className="data six-count"
        style={{ transform: `scale(${1 + 0.18 * flash})` }}
      >
        {obj.count}
      </div>
    </div>
  );
}
