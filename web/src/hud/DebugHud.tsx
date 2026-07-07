import type { AppState } from "../state/types";

const BAR_MAX_RATIO = 1.5; // matches ui/debug_hud.py full scale

/**
 * Pinch-pipeline debug panel — web port of src/ui/debug_hud.py.
 * Toggled client-side with the `d` key; the numbers ride the state
 * payload whenever the backend runs with HALL_DEBUG=1.
 */
export function DebugHud({ state, frameH }: { state: AppState; frameH: number }) {
  const d = state.debug;
  const close = d?.close_ratio ?? 0.45;
  const release = d?.release_ratio ?? 0.9;

  return (
    <div className="panel debug-hud data" style={{ left: 16, top: frameH - 16, transform: "translateY(-100%)" }}>
      {d ? (
        <>
          <div>
            render {d.render_fps.toFixed(0)} fps · hand det{" "}
            {d.hand_fps.toFixed(0)} fps · age {d.age_ms.toFixed(0)} ms
          </div>
          <div className="dim">
            backend {d.backend} · close &lt; {close} · release &gt; {release}
          </div>
        </>
      ) : (
        <div className="dim">backend debug off — set HALL_DEBUG=1</div>
      )}
      {state.hands.map((h) => {
        const ratio = h.ratio;
        const fill =
          ratio !== null ? Math.min(ratio / BAR_MAX_RATIO, 1) * 100 : 0;
        return (
          <div key={h.id} className="dbg-hand">
            <div>
              {h.id}: {h.state} · ratio {ratio !== null ? ratio.toFixed(2) : "--"}{" "}
              · prog {h.progress.toFixed(2)}
            </div>
            <div className="dbg-bar">
              <div
                className="dbg-fill"
                style={{
                  width: `${fill}%`,
                  background: h.held ? "var(--go)" : "var(--trace)",
                }}
              />
              <div
                className="dbg-tick"
                style={{ left: `${(close / BAR_MAX_RATIO) * 100}%` }}
              />
              <div
                className="dbg-tick"
                style={{ left: `${(release / BAR_MAX_RATIO) * 100}%` }}
              />
            </div>
            <div className="dim">
              cursor ({h.cursor[0].toFixed(0)}, {h.cursor[1].toFixed(0)}) ·
              seen {h.seen_ms.toFixed(0)} ms ago
            </div>
          </div>
        );
      })}
    </div>
  );
}
