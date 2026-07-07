#version 300 es

// Schwarzschild thin-lens gravitational lensing + Gargantua-style
// accretion disk — WebGL2 port of src/rendering/shaders/black_hole.frag.
//
// Differences from the moderngl original:
//  * GLSL ES 3.00 (highp is REQUIRED: mediump breaks r - E^2/r at 1080p).
//  * Colors are RGB (the original was authored in BGR for cv2).
//  * Edge behaviour: out-of-frame lensed samples used to render BLACK,
//    which produced black crescents whenever the BH neared a frame edge.
//    Here the deflection fades smoothly near the border and sampling is
//    clamped, so edges warp gracefully instead of tearing to black.
//  * Photon ring hugs the shadow at 0.53*E (was 0.62*E) and is slightly
//    narrower — in this thin-lens model the critical curve IS the shadow
//    edge, and the tighter ring reads closer to the EHT/Gargantua look.
//
// See the original file for the full physics commentary.

precision highp float;

uniform sampler2D u_frame;
uniform vec2  u_bh_center;     // pixel coords of BH centre (top-left origin)
uniform float u_einstein_px;   // Einstein radius in pixels
uniform vec2  u_resolution;    // (width, height) in pixels

uniform float u_disk_inner_px;
uniform float u_disk_outer_px;
uniform float u_disk_tilt_rad;
uniform float u_disk_brightness;
uniform float u_time;
uniform float u_rotation_speed;

in  vec2 v_uv;
out vec4 f_color;

// Warm Gargantua palette (RGB): white-hot core -> gold -> deep amber.
const vec3 DISK_HOT   = vec3(1.00, 1.00, 0.95);
const vec3 DISK_WARM  = vec3(1.00, 0.82, 0.45);
const vec3 DISK_AMBER = vec3(1.00, 0.55, 0.18);

// --- Procedural turbulence for the orbiting gas -----------------------
float hash21(vec2 p) {
    p = fract(p * vec2(127.1, 311.7));
    p += dot(p, p + 34.56);
    return fract(p.x * p.y);
}

float vnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash21(i);
    float b = hash21(i + vec2(1.0, 0.0));
    float c = hash21(i + vec2(0.0, 1.0));
    float d = hash21(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float fbm(vec2 p) {
    float s = 0.0;
    float a = 0.5;
    for (int i = 0; i < 4; ++i) {
        s += a * vnoise(p);
        p = p * 2.03 + 7.0;
        a *= 0.5;
    }
    return s;
}

vec3 sample_disk(vec2 src_offset) {
    float ct = cos(u_disk_tilt_rad);
    float safe_ct = max(ct, 0.05);
    float st = sin(u_disk_tilt_rad);
    float dx = src_offset.x;
    float dy = src_offset.y / safe_ct;
    float r_disk = sqrt(dx * dx + dy * dy);

    float feather = max((u_disk_outer_px - u_disk_inner_px) * 0.12, 2.0);
    float band = smoothstep(u_disk_inner_px - feather, u_disk_inner_px + feather, r_disk)
               * (1.0 - smoothstep(u_disk_outer_px - feather, u_disk_outer_px + feather, r_disk));
    if (band <= 0.0) {
        return vec3(0.0);
    }

    float t = clamp((r_disk - u_disk_inner_px) /
                    max(u_disk_outer_px - u_disk_inner_px, 1.0), 0.0, 1.0);
    vec3 base = (t < 0.5) ? mix(DISK_HOT, DISK_WARM, t * 2.0)
                          : mix(DISK_WARM, DISK_AMBER, (t - 0.5) * 2.0);

    float lum = pow(u_disk_inner_px / r_disk, 2.5);

    // Keplerian co-rotating turbulence: clumps orbit and shear into
    // trailing spiral filaments (omega ~ r^-3/2).
    float omega = pow(u_disk_inner_px / r_disk, 1.5) * u_rotation_speed;
    float ang = omega * u_time;
    float ca = cos(ang);
    float sa = sin(ang);
    vec2 corot = vec2(ca * dx - sa * dy, sa * dx + ca * dy);

    float r_n = r_disk * 0.10;
    float phi_n = atan(corot.y, corot.x) * r_disk * 0.035;
    float clouds = fbm(vec2(phi_n, r_n));

    float filament = smoothstep(0.45, 0.95, clouds);
    float sparkle  = pow(clamp(clouds, 0.0, 1.0), 6.0);
    float modulation = 0.20 + 1.30 * filament + 1.80 * sparkle;

    // Approximate Doppler beaming + gravitational redshift.
    float v = clamp(sqrt(u_disk_inner_px / r_disk) * 0.5, 0.0, 0.95);
    float v_los = -(dx / max(r_disk, 1.0)) * st * v;
    float gamma = 1.0 / sqrt(max(1.0 - v * v, 1e-3));
    float doppler = 1.0 / max(gamma * (1.0 - v_los), 0.05);

    float redshift = sqrt(max(1.0 - 0.5 * u_einstein_px / r_disk, 0.05));

    return base * lum * pow(doppler, 3.0) * redshift
           * modulation * band * u_disk_brightness;
}

// Photon ring: hot sliver hugging the shadow edge (the critical curve of
// this thin-lens model), Doppler-brightened on the approaching side.
vec3 photon_ring(float r, vec2 d) {
    float E = u_einstein_px;
    float ring_r = 0.53 * E;
    float ring_w = max(0.04 * E, 1.2);
    float g = exp(-pow((r - ring_r) / ring_w, 2.0));

    float beam = 1.0 + 0.6 * (-d.x / max(r, 1.0));

    vec3 ring_col = vec3(1.00, 0.95, 0.75);
    return ring_col * g * beam * 1.6 * u_disk_brightness;
}

vec3 shade(vec2 pixel) {
    vec2 d = pixel - u_bh_center;
    float r = length(d);
    float E = u_einstein_px;

    float shadow = smoothstep(0.5 * E - 1.5, 0.5 * E + 1.5, r);

    float r_src = r - (E * E) / r;
    vec2 src_offset = d * (r_src / r);
    vec2 src_pixel = u_bh_center + src_offset;

    // Border fade: as this fragment approaches the frame edge, ease the
    // deflection off so lensed samples stay inside the frame — warped
    // edges instead of the original's black crescents. The disk still
    // uses the un-faded offset (it is emission, not background).
    float border = min(min(pixel.x, u_resolution.x - pixel.x),
                       min(pixel.y, u_resolution.y - pixel.y));
    float k = smoothstep(0.0, 0.10 * min(u_resolution.x, u_resolution.y), border);
    vec2 src_uv = clamp(mix(pixel, src_pixel, k) / u_resolution, 0.0, 1.0);
    vec3 background = texture(u_frame, src_uv).rgb;

    vec3 disk = sample_disk(src_offset);
    vec3 ring = photon_ring(r, d);

    vec3 col = (background + disk) * shadow + ring;
    return col;
}

void main() {
    vec2 pixel = v_uv * u_resolution;

    // 2x2 rotated-grid supersampling.
    const vec2 offs[4] = vec2[4](
        vec2(-0.25, -0.08), vec2( 0.08, -0.25),
        vec2( 0.25,  0.08), vec2(-0.08,  0.25)
    );
    vec3 acc = vec3(0.0);
    for (int i = 0; i < 4; ++i) {
        acc += shade(pixel + offs[i]);
    }
    vec3 final_color = clamp(acc * 0.25, 0.0, 1.0);
    f_color = vec4(final_color, 1.0);
}
