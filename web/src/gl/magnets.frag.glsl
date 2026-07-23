#version 300 es

// Iron-filings picture of the bar magnets' field, evaluated ANALYTICALLY:
// one compass needle per grid cell, aligned with the local B, opacity from
// tanh(|B| / u_b_ref). White tail, red tip pointing along the field, the
// same needle a real compass grid (or PhET's) would show.
//
// The field is exact 2D magnetostatics for uniformly magnetized bars: each
// bar contributes its two pole faces as "magnetic surface charge" segments
// (closed form, atan + log — the same integral as a charged rod in 2D
// electrostatics), plus the bound-magnetization term +M inside the bar
// (B = H + M with mu0 = 1) so div B = 0 and lines close S->N through the
// bar. The +M window is smoothed over u_edge_smooth px, matching
// Magnets.field_at in ui/interactables.py — keep the two in sync (the
// MAG_* block in src/config.py is the single source for the constants).
//
// Like the charges shader this is stateless: no ping-pong, no timestep,
// just a fresh closed-form evaluation of wherever the user dragged the
// bars. MAX_MAGNETS mirrors config.MAG_MAX — keep in sync.
//
// The needle length is under the cell size, so each needle lives entirely
// inside its own cell and one field evaluation per pixel (at the pixel's
// cell centre) is enough — no neighbour sampling.

precision highp float;

uniform vec2  u_resolution;    // frame pixels
uniform int   u_count;
uniform vec3  u_magnets[4];    // per bar: x_px, y_px, m (sign = orientation)
uniform float u_half_len;      // bar half-length a (px)
uniform float u_half_h;        // bar half-height b (px)
uniform float u_edge_smooth;   // +M window smoothing (px)
uniform float u_b_ref;         // |B| of a fully opaque needle
uniform float u_spacing;       // needle grid cell (px)
uniform float u_needle_len;    // needle length (px)

in  vec2 v_uv;
out vec4 f_color;

const float PI = 3.14159265358979;
const vec3 TIP  = vec3(0.96, 0.35, 0.35);   // red toward B (the "north" end)
const vec3 TAIL = vec3(0.92, 0.92, 0.92);

// H of one pole face: a uniformly "charged" vertical segment at x = xs,
// y in [y1, y2], density lam. The atan2 identity
// atan(t2/X) - atan(t1/X) == atan(X*(t2-t1), X*X + t1*t2) is branch-safe
// everywhere, including inside the bar.
vec2 segH(vec2 p, float xs, float y1, float y2, float lam) {
    float X = p.x - xs;
    float t1 = y1 - p.y;
    float t2 = y2 - p.y;
    float hx = lam / (2.0 * PI) * atan(X * (t2 - t1), X * X + t1 * t2);
    float hy = lam / (4.0 * PI)
             * log((X * X + t1 * t1 + 1e-6) / (X * X + t2 * t2 + 1e-6));
    return vec2(hx, hy);
}

vec2 fieldAt(vec2 p) {
    vec2 B = vec2(0.0);
    for (int i = 0; i < 4; i++) {
        if (i >= u_count) break;
        vec3 mg = u_magnets[i];
        B += segH(p, mg.x + u_half_len, mg.y - u_half_h, mg.y + u_half_h,  mg.z);
        B += segH(p, mg.x - u_half_len, mg.y - u_half_h, mg.y + u_half_h, -mg.z);
        // Bound magnetization inside the bar, edge-smoothed (matches the
        // Python _smooth01 window).
        float wx = smoothstep(0.0, 1.0,
                              (u_half_len - abs(p.x - mg.x)) / u_edge_smooth + 0.5);
        float wy = smoothstep(0.0, 1.0,
                              (u_half_h - abs(p.y - mg.y)) / u_edge_smooth + 0.5);
        B.x += mg.z * wx * wy;
    }
    return B;
}

void main() {
    vec2 p = v_uv * u_resolution;

    vec2 cell = floor(p / u_spacing);
    vec2 center = (cell + 0.5) * u_spacing;

    vec2 B = fieldAt(center);
    float m = length(B);
    float strength = tanh(m / u_b_ref);
    if (m < 1e-9 || strength < 0.04) {
        f_color = vec4(0.0);
        return;
    }
    vec2 dir = B / m;

    // Distance from this pixel to the needle segment through the cell
    // centre. Weak field: shorter needle, so the far grid thins out.
    float halfLen = 0.5 * u_needle_len * (0.55 + 0.45 * strength);
    vec2 d = p - center;
    float along = dot(d, dir);
    vec2 nearest = center + dir * clamp(along, -halfLen, halfLen);
    float dist = length(p - nearest);

    float aa = max(fwidth(dist) * 1.2, 0.75);
    float body = 1.0 - smoothstep(1.3 - aa * 0.5, 1.3 + aa, dist);

    // Red half toward B, white half behind, split softly at the centre.
    float tip = smoothstep(-1.5, 1.5, along);
    vec3 col = mix(TAIL, TIP, tip);

    float a = strength * body * 0.9;
    f_color = vec4(col * a, a);   // premultiplied over the camera
}
