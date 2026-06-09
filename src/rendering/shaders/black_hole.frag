#version 330

// Schwarzschild thin-lens gravitational lensing + Gargantua-style
// accretion disk.
//
// Lensing. For each output pixel at screen-space distance r from the BH
// centre the Schwarzschild deflection alpha = 4GM/(c^2 b) reduces in
// pixel units to a radial pull:
//
//     r_src = r - E^2 / r        (E = Einstein radius in pixels)
//
// `r_src` is allowed to be NEGATIVE — that branch represents the inner
// image of a source on the *opposite* side of the BH, which is what
// produces the "ring around the shadow" appearance: light from the
// back of the accretion disk wraps over the top of the BH and lands
// inside the Einstein radius. Without this branch the BH looks like a
// flat disc with no halo. The shadow itself (r < 0.5 * E) is still
// drawn black, so we lose the captured photons, not the inner image.
//
// Accretion disk. Modelled as a thin annulus in a plane tilted around
// the x-axis by `u_disk_tilt_rad`. For each fragment we take the
// lensed source offset (which already encodes the gravitational pull)
// and un-project it back into the disk plane: dividing the y component
// by cos(tilt) recovers disk-plane radius. If that radius falls inside
// [inner, outer] the disk emits — combining a radial temperature
// gradient, Doppler beaming from orbital motion, and gravitational
// redshift escaping the BH potential well. Composite is additive
// (emission, not occlusion) over the lensed background.
//
// Quality. The whole shade is supersampled on a 2x2 rotated grid and
// every hard boundary (shadow edge, disk inner/outer rim, photon ring)
// is feathered with smoothstep, so the silhouette reads smooth instead
// of pixelated. A bright thin photon ring hugging the shadow gives the
// iconic Gargantua "ring of fire".

uniform sampler2D u_frame;
uniform vec2  u_bh_center;     // pixel coords of BH centre on screen
uniform float u_einstein_px;   // Einstein radius in pixels
uniform vec2  u_resolution;    // (width, height) of the frame in pixels

uniform float u_disk_inner_px;     // disk inner edge in disk-frame px
uniform float u_disk_outer_px;     // disk outer edge in disk-frame px
uniform float u_disk_tilt_rad;     // 0 = face-on, pi/2 = edge-on
uniform float u_disk_brightness;   // overall multiplier; 0 disables visually
uniform float u_time;              // elapsed seconds since BH spawn — drives disk rotation
uniform float u_rotation_speed;    // angular speed at inner edge (rad/s); outer rings rotate slower (Keplerian)

in  vec2 v_uv;
out vec4 f_color;

// Warm Gargantua palette, expressed in BGR because the texture is
// uploaded as BGR and the output goes straight to cv2.imshow. The disk
// stays in the white -> gold -> amber range; it never falls to dull red,
// which is what made the old gradient read as "cheap".
const vec3 DISK_HOT  = vec3(0.95, 1.00, 1.00);  // near-white, overexposed core
const vec3 DISK_WARM = vec3(0.45, 0.82, 1.00);  // golden
const vec3 DISK_AMBER= vec3(0.18, 0.55, 1.00);  // deep amber (still bright)

// --- Procedural turbulence for the orbiting gas -----------------------
// A small value-noise + fBm stack. We sample it in a *co-rotating* disk
// frame (see sample_disk) so the clumps it produces actually orbit the
// BH instead of sitting still like a decal. Because each radius rotates
// at its own Keplerian rate, a uniform noise field gets sheared into
// trailing spiral filaments over time — the look of real accretion gas.
float hash21(vec2 p) {
    p = fract(p * vec2(127.1, 311.7));
    p += dot(p, p + 34.56);
    return fract(p.x * p.y);
}

float vnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);           // smooth Hermite interp
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

    // Un-project the tilt: the disk's vertical extent on screen is
    // compressed by cos(tilt), so dividing y by cos(tilt) recovers the
    // disk-plane radius. `safe_ct` keeps the math well-defined when the
    // disk approaches edge-on.
    float safe_ct = max(ct, 0.05);
    float st = sin(u_disk_tilt_rad);
    float dx = src_offset.x;
    float dy = src_offset.y / safe_ct;
    float r_disk = sqrt(dx * dx + dy * dy);

    // Feathered radial band. Instead of a hard [inner, outer] cutoff we
    // ramp emission up across `feather` pixels at each rim, so the disk
    // edges are anti-aliased rather than jagged. `feather` scales with
    // the disk width so it stays proportionate at any zoom.
    float feather = max((u_disk_outer_px - u_disk_inner_px) * 0.12, 2.0);
    float band = smoothstep(u_disk_inner_px - feather, u_disk_inner_px + feather, r_disk)
               * (1.0 - smoothstep(u_disk_outer_px - feather, u_disk_outer_px + feather, r_disk));
    if (band <= 0.0) {
        return vec3(0.0);
    }

    // Radial temperature: white-hot inside fading to gold then amber.
    float t = clamp((r_disk - u_disk_inner_px) /
                    max(u_disk_outer_px - u_disk_inner_px, 1.0), 0.0, 1.0);
    vec3 base = (t < 0.5) ? mix(DISK_HOT, DISK_WARM, t * 2.0)
                          : mix(DISK_WARM, DISK_AMBER, (t - 0.5) * 2.0);

    // Luminosity falloff with radius — emission roughly drops as 1/r^2.5.
    // Gentler than the old 1/r^3 so the disk body stays luminous and
    // smooth rather than collapsing to a thin bright rim.
    float lum = pow(u_disk_inner_px / r_disk, 2.5);

    // Orbiting gas, made of moving turbulent clumps instead of a static
    // texture. Keplerian motion gives omega(r) ~ r^(-3/2): inner orbits
    // sweep much faster than outer ones. We rotate this fragment's
    // disk-plane position *backwards* by the angle the gas at this radius
    // has travelled, then sample a static noise field in that co-rotating
    // frame. Net effect: each clump rides its orbit, and the radial
    // spread of omega shears the field into spiral filaments over time —
    // the disk visibly churns and trails like real accreting matter.
    float omega = pow(u_disk_inner_px / r_disk, 1.5) * u_rotation_speed;
    float ang = omega * u_time;
    float ca = cos(ang);
    float sa = sin(ang);
    vec2 corot = vec2(ca * dx - sa * dy, sa * dx + ca * dy);

    // Anisotropic sampling: stretch tangentially (and compress radially)
    // so clumps read as orbit-aligned filaments rather than round blobs.
    float r_n = r_disk * 0.10;                       // radial detail
    float phi_n = atan(corot.y, corot.x) * r_disk * 0.035;  // along-orbit detail
    float clouds = fbm(vec2(phi_n, r_n));

    // Sharp bright cores ride on top of the soft cloud layer so the eye
    // picks out discrete particles streaming around the hole.
    float filament = smoothstep(0.45, 0.95, clouds);
    float sparkle  = pow(clamp(clouds, 0.0, 1.0), 6.0);
    float modulation = 0.20 + 1.30 * filament + 1.80 * sparkle;

    // Doppler beaming. Disk material orbits counter-clockwise (viewed
    // from +z); orbital speed ~ sqrt(R_in / r) capped sub-light. The
    // line-of-sight component depends on tilt: a vector tangent to the
    // disk at azimuth phi has world-frame z component = cos(phi) * sin(tilt).
    // Approaching side (negative LOS velocity in our convention) is
    // brighter — this is the asymmetric left/right brightness that makes
    // Gargantua look like it's actually spinning.
    float v = clamp(sqrt(u_disk_inner_px / r_disk) * 0.5, 0.0, 0.95);
    float v_los = -(dx / max(r_disk, 1.0)) * st * v;
    float gamma = 1.0 / sqrt(max(1.0 - v * v, 1e-3));
    float doppler = 1.0 / max(gamma * (1.0 - v_los), 0.05);

    // Gravitational redshift: photons lose energy escaping the BH well.
    // Using E as the gravitational scale (a proxy for the Schwarzschild
    // radius in our screen-space units).
    float redshift = sqrt(max(1.0 - 0.5 * u_einstein_px / r_disk, 0.05));

    return base * lum * pow(doppler, 3.0) * redshift
           * modulation * band * u_disk_brightness;
}

// Bright thin photon ring hugging the shadow — light that orbited the BH
// one or more times before escaping toward us. This is the signature
// Gargantua "ring of fire". It is a warm gaussian sliver just outside the
// shadow radius, modulated by the same Doppler asymmetry as the disk so
// the ring is brighter on the approaching (left) side.
vec3 photon_ring(float r, vec2 d) {
    float E = u_einstein_px;
    float ring_r = 0.62 * E;            // sits just outside the 0.5*E shadow
    float ring_w = max(0.05 * E, 1.5);  // sliver thickness
    float g = exp(-pow((r - ring_r) / ring_w, 2.0));

    // Doppler-style left/right asymmetry: brighter where material moves
    // toward the viewer.
    float beam = 1.0 + 0.6 * (-d.x / max(r, 1.0));

    vec3 ring_col = vec3(0.75, 0.95, 1.00);  // hot gold-white (BGR)
    return ring_col * g * beam * 1.6 * u_disk_brightness;
}

// Full shade for one sub-sample at the given screen-space pixel.
vec3 shade(vec2 pixel) {
    vec2 d = pixel - u_bh_center;
    float r = length(d);
    float E = u_einstein_px;

    // Feathered event-horizon shadow. `shadow` is 0 inside the horizon
    // and ramps to 1 over a couple of pixels, so the silhouette edge is
    // anti-aliased instead of a hard staircase.
    float shadow = smoothstep(0.5 * E - 1.5, 0.5 * E + 1.5, r);

    // Schwarzschild thin-lens deflection. r_src may be negative for
    // r < E — this is the inner image (opposite side of the BH) and is
    // responsible for the ring-of-light effect inside the lensing halo.
    float r_src = r - (E * E) / r;
    vec2 src_offset = d * (r_src / r);
    vec2 src_pixel = u_bh_center + src_offset;
    vec2 src_uv = src_pixel / u_resolution;

    vec3 background;
    if (src_uv.x < 0.0 || src_uv.x > 1.0 ||
        src_uv.y < 0.0 || src_uv.y > 1.0) {
        background = vec3(0.0);
    } else {
        background = texture(u_frame, src_uv).rgb;
    }

    vec3 disk = sample_disk(src_offset);
    vec3 ring = photon_ring(r, d);

    // Background and lensed disk image are swallowed by the shadow; the
    // photon ring lives just outside it and is added on top.
    vec3 col = (background + disk) * shadow + ring;
    return col;
}

void main() {
    vec2 pixel = v_uv * u_resolution;

    // 2x2 rotated-grid supersampling. Four jittered sub-samples averaged
    // per fragment knock out the aliasing on the shadow rim, the photon
    // ring and the disk edges — the single biggest "looks low quality"
    // culprit in the old single-tap version.
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
