#version 300 es

// Electrostatic potential + equipotential contours, evaluated ANALYTICALLY
// per pixel:  V = k * sum(q_i / r_i),  with r softened so a charge's own
// core doesn't blow up to a saturated disk.
//
// Unlike the Waves field this is stateless — no ping-pong texture, no time
// integration, no CFL limit — so it is a single cheap pass and cannot drift
// or diverge. The charges are static (see config.py's CHG_* note), so every
// frame is a fresh closed-form evaluation of wherever the user dragged them.
//
// Output is premultiplied alpha over the camera: warm red where V > 0, cool
// blue where V < 0, transparent near V = 0, plus a bright band wherever V
// crosses a multiple of u_equipot_step — those bands ARE the equipotentials
// (surfaces of constant V, always perpendicular to the field lines the
// Canvas2D layer draws on top).
//
// MAX_CHARGES mirrors config.CHG_MAX — keep in sync.
//
// NOTE: v_uv here is the shared vertex shader's TOP-LEFT origin uv, which is
// exactly what we want — `v_uv * u_resolution` reproduces the backend's
// frame pixel coords, so charge positions need no conversion. (There is no
// framebuffer round-trip in this pass, so the bottom-origin gl_FragCoord
// trap that bit the Waves step shader doesn't apply here.)

precision highp float;

uniform vec2  u_resolution;   // frame pixels
uniform int   u_count;
uniform vec3  u_charges[8];   // per charge: x_px, y_px, q
uniform float u_k;            // Coulomb constant (screen units)
uniform float u_soften;       // core softening radius (px)
uniform float u_equipot_step; // volts between equipotential bands

in  vec2 v_uv;
out vec4 f_color;

const vec3  POS   = vec3(0.96, 0.35, 0.35);   // warm red  (+V)
const vec3  NEG   = vec3(0.31, 0.59, 0.96);   // cool blue (-V)
const float GAIN  = 3.0;      // V units per tanh unit = equipot_step * GAIN

void main() {
    vec2 p = v_uv * u_resolution;

    float v = 0.0;
    float s2 = u_soften * u_soften;
    for (int i = 0; i < 8; i++) {
        if (i >= u_count) break;
        vec3 c = u_charges[i];
        float r = sqrt(dot(p - c.xy, p - c.xy) + s2);
        v += u_k * c.z / r;
    }

    // Diverging tint. tanh so a lone charge reads without its core blowing
    // out and eight charges still land in range (same argument as the Waves
    // tone curve).
    float t = tanh(v / (u_equipot_step * GAIN));
    vec3 col = t > 0.0 ? POS : NEG;
    float a = clamp(abs(t) * 0.9, 0.0, 0.72);

    // Equipotential bands: how close V sits to a contour level, measured in
    // level units, made resolution-independent with a screen-space
    // derivative so the bands stay ~1px wide instead of pooling where the
    // field is flat.
    float lv = v / u_equipot_step;
    float d = abs(fract(lv + 0.5) - 0.5);
    float aa = max(fwidth(lv), 1e-5);
    float band = 1.0 - smoothstep(0.0, aa * 1.2, d);
    col = mix(col, vec3(1.0), band * 0.75);
    a = max(a, band * 0.55);

    f_color = vec4(col * a, a);
}
