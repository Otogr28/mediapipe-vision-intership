import type { SlingshotObject } from "../state/types";

/**
 * DOM panels of the slingshot experiment: the aim readout (SI numbers for
 * the pending shot) and the force-legend / constants card. The geometry —
 * band, arc, balls, arrows — is canvas (overlay/scene.ts).
 */

// Mirrors of the SI constants in ui/interactables.py, display-only.
const G = 9.81;
const MASS = 1.0;
const RADIUS_M = 0.22;
const DRAG_CD = 0.47;
const AIR_RHO = 1.225;
const BAND_K = 44.2;
const BAND_EFF = 0.75;
const FRICTION_MU = 0.5;
const PHYS_HZ = 120;
const DRAG_K = 0.5 * AIR_RHO * DRAG_CD * Math.PI * RADIUS_M * RADIUS_M;
const V_TERMINAL = Math.sqrt((MASS * G) / DRAG_K);

export function AimReadout({ obj }: { obj: SlingshotObject }) {
  if (!obj.readout || !obj.pull) return null;
  const r = obj.readout;
  const [ax, ay] = obj.anchor;
  return (
    <div
      className="panel aim-readout data"
      style={{ left: ax, top: ay - obj.ball_r - 24, transform: "translate(-50%, -100%)" }}
    >
      <div>
        <span className="dim">angle</span> {r.angle > 0 ? "+" : ""}
        {r.angle.toFixed(0)}° <span className="dim">v₀</span> {r.v0.toFixed(1)} m/s
      </div>
      <div>
        <span className="dim">draw</span> {r.draw_n.toFixed(0)} N{" "}
        <span className="dim">E</span> {r.e_j.toFixed(0)} J{" "}
        <span className="dim">→ KE</span> {r.ke_j.toFixed(0)} J
      </div>
    </div>
  );
}

const LEGEND_ROWS: { color: string; text: string }[] = [
  { color: "#ffb400", text: "W weight m·g" },
  { color: "#00c8ff", text: "D air drag ½ρ·Cd·A·v²" },
  { color: "#00eb00", text: "N contact normal + friction" },
  { color: "#f0f0f0", text: "net sum of forces (dashed)" },
];

export function SlingshotLegend() {
  return (
    <div className="panel brackets sling-legend">
      <div className="label legend-title">Forces</div>
      {LEGEND_ROWS.map((row) => (
        <div key={row.text} className="legend-row">
          <span className="swatch" style={{ background: row.color }} />
          <span>{row.text}</span>
        </div>
      ))}
      <div className="legend-footer data">
        <div>g {G} m/s² · m {MASS.toFixed(1)} kg · r {RADIUS_M} m</div>
        <div>Cd {DRAG_CD} · ρ {AIR_RHO} kg/m³ · vt {V_TERMINAL.toFixed(0)} m/s</div>
        <div>band k {BAND_K} N/m · eff {(BAND_EFF * 100).toFixed(0)}% · μ {FRICTION_MU}</div>
        <div>RK4 @ {PHYS_HZ} Hz fixed step</div>
      </div>
    </div>
  );
}
