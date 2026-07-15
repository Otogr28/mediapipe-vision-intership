#version 300 es

// One finite-difference step of the damped 2D wave equation, run in a
// ping-pong RG16F texture at SIM resolution (one texel = one grid cell):
//
//   u_next = (2 - d) * u - (1 - d) * u_prev + s^2 * lap(u)
//
// .r holds u(t), .g holds u(t - dt); the output writes (u_next, u) so a
// single texture carries both time levels. Point sources are blended in
// as Dirichlet oscillators (the texel is pulled toward A*sin(2*pi*f*age)
// by a small Gaussian weight), matching the numpy fallback in
// src/ui/interactables.py (Waves._step_field) — keep the two in sync.
//
// Boundaries: sampling is clamped to the edge texel (Neumann, du/dn = 0),
// so the frame edges REFLECT like the walls of a real ripple tank.
//
// ORIENTATION (subtle — this was a bug): the texel index comes from
// gl_FragCoord, i.e. THE TEXEL THIS FRAGMENT WRITES, so the read and the write
// are the same cell. Deriving it from the shared vertex shader's v_uv instead
// mixes conventions — v_uv is top-left origin while gl_FragCoord.y is
// bottom-origin — so every step read row 0 and wrote row simH-1, flipping the
// field and injecting each source at its mirrored row (one source rendered as
// two, mirrored vertically). Consequently gl_FragCoord.y (and therefore
// u_sources' y) is BOTTOM-origin: the JS side converts source y out of frame
// coords, and the display pass flips v back. Keep all three in agreement.
//
// MAX_SOURCES mirrors config.WAVE_MAX_SOURCES — keep in sync.

precision highp float;

uniform sampler2D u_field;
uniform vec2  u_sim;         // sim grid size (texels)
uniform float u_s2;          // (c * dt / dx)^2, Courant number squared
uniform float u_delta;       // velocity damping this step (0..1)
uniform float u_time;        // sim clock AFTER this step (s)
uniform int   u_count;       // live sources
uniform vec4  u_sources[6];  // per source: x_cell, y_cell (BOTTOM-origin, see
                             // the orientation note), freq_hz, born_s
uniform float u_amp;         // source amplitude (field units)
uniform float u_ramp;        // onset ramp length (s)

// NOTE: deliberately does NOT read the vertex shader's v_uv — see the
// orientation note above. The texel index comes from gl_FragCoord.
out vec2 f_field;

const float SIGMA2 = 2.25;   // Gaussian source footprint, sigma = 1.5 cells

float at(ivec2 p, ivec2 hi) {
    return texelFetch(u_field, clamp(p, ivec2(0), hi), 0).r;
}

void main() {
    // The texel this fragment writes — read the same one (see the note above).
    ivec2 hi = ivec2(u_sim) - 1;
    ivec2 p = clamp(ivec2(gl_FragCoord.xy), ivec2(0), hi);

    vec2 uv2 = texelFetch(u_field, p, 0).rg;   // (u, u_prev)
    float u = uv2.r;

    // 9-point isotropic Laplacian (the 5-point stencil turns circular
    // ripples square after a few wavelengths).
    float lap = (4.0 * (at(p + ivec2(1, 0), hi) + at(p - ivec2(1, 0), hi)
                        + at(p + ivec2(0, 1), hi) + at(p - ivec2(0, 1), hi))
                 + at(p + ivec2(1, 1), hi) + at(p + ivec2(1, -1), hi)
                 + at(p - ivec2(1, 1), hi) + at(p - ivec2(1, -1), hi)
                 - 20.0 * u) / 6.0;

    float next = (2.0 - u_delta) * u - (1.0 - u_delta) * uv2.g + u_s2 * lap;

    // Oscillating point sources (Dirichlet blend).
    vec2 cell = vec2(p) + 0.5;
    for (int i = 0; i < 6; i++) {
        if (i >= u_count) break;
        vec4 s = u_sources[i];
        float age = u_time - s.w;
        if (age < 0.0) continue;
        vec2 d = cell - s.xy;
        float w = exp(-dot(d, d) / (2.0 * SIGMA2));
        float target = u_amp * min(age / u_ramp, 1.0)
                       * sin(6.2831853 * s.z * age);
        next = mix(next, target, w);
    }

    f_field = vec2(next, u);
}
