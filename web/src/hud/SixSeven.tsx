import type { SixSevenObject } from "../state/types";

/** m:ss, matching `SixSevenCounter._clock` in the cv2 fallback. */
function clock(seconds: number): string {
  const total = Math.ceil(Math.max(0, seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** The line above the clock. Same words as the cv2 fallback. */
function status(obj: SixSevenObject): string {
  if (obj.phase === "ready") return "Raise an arm to start";
  if (obj.phase === "running") return "6 7";
  return obj.rank === null ? "Time" : `New #${obj.rank + 1}`;
}

/**
 * Top-centre card for the 6-7 counter: round clock, live count, and the
 * persistent high-score table underneath.
 *
 * The board is hidden until somebody has scored, so a freshly-flashed
 * device shows a counter rather than five empty rows. Python owns every
 * number here (clock, count, ranking, which row is yours); this only draws
 * them, like every other scene.
 */
export function SixSeven({ obj, frameW }: { obj: SixSevenObject; frameW: number }) {
  const flash = obj.flash; // 1.0 right after a count, decaying to 0
  // Amber in the last five seconds: the app's "act now" colour, the same
  // one a closing pinch uses.
  const late = obj.phase === "running" && obj.remaining <= 5;
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
      <div className="label six-label">{status(obj)}</div>
      <div className={`data six-clock${late ? " six-clock-late" : ""}`}>
        {clock(obj.remaining)}
      </div>
      <div
        className="data six-count"
        style={{ transform: `scale(${1 + 0.18 * flash})` }}
      >
        {obj.count}
      </div>
      {obj.board.length > 0 && (
        <div className="six-board">
          <div className="label six-board-head">Best</div>
          {obj.board.map((score, i) => (
            <div
              key={i}
              className={`data six-row${obj.rank === i ? " six-row-mine" : ""}`}
            >
              <span className="six-rank">{i + 1}.</span>
              <span className="six-score">{score}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
