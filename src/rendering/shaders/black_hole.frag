#version 330

// Schwarzschild thin-lens gravitational lensing + accretion disk.
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

vec3 sample_disk(vec2 src_offset) {
    float ct = cos(u_disk_tilt_rad);
    float st = sin(u_disk_tilt_rad);

    // Un-project the tilt: the disk's vertical extent on screen is
    // compressed by cos(tilt), so dividing y by cos(tilt) recovers the
    // disk-plane radius. `safe_ct` keeps the math well-defined when the
    // disk approaches edge-on.
    float safe_ct = max(ct, 0.05);
    float dx = src_offset.x;
    float dy = src_offset.y / safe_ct;
    float r_disk = sqrt(dx * dx + dy * dy);

    if (r_disk < u_disk_inner_px || r_disk > u_disk_outer_px) {
        return vec3(0.0);
    }

    // Radial temperature: hot bluish-white inside, cool red outside.
    // Colors are in BGR because the texture is uploaded as BGR and the
    // output goes straight to cv2.imshow.
    float t = clamp((r_disk - u_disk_inner_px) /
                    max(u_disk_outer_px - u_disk_inner_px, 1.0), 0.0, 1.0);
    vec3 hot  = vec3(0.85, 1.0,  1.0 );  // pale yellow-white
    vec3 mid  = vec3(0.25, 0.75, 1.0 );  // bright orange
    vec3 cool = vec3(0.05, 0.30, 0.80);  // deep red
    vec3 base = (t < 0.5) ? mix(hot, mid, t * 2.0)
                          : mix(mid, cool, (t - 0.5) * 2.0);

    // Luminosity falloff with radius — emission roughly drops as 1/r^3.
    float lum = pow(u_disk_inner_px / r_disk, 3.0);

    // Differential rotation. The disk's azimuth at this radius is the
    // un-projected angle of the lensed source offset. Keplerian motion
    // gives omega(r) ~ r^(-3/2) — inner rings spin much faster than
    // outer ones, so streaks at different radii shear over time. The
    // multi-harmonic sine pattern below is a cheap procedural noise
    // that reads as "clumpy gas" without needing a 2D noise lookup.
    float phi = atan(dy, dx);
    float omega = pow(u_disk_inner_px / r_disk, 1.5) * u_rotation_speed;
    float phi_t = phi - omega * u_time;
    float texture_mod =
          0.25 * sin(phi_t * 5.0)
        + 0.15 * sin(phi_t * 11.0 + r_disk * 0.04)
        + 0.10 * sin(phi_t * 17.0 - r_disk * 0.02);
    float modulation = max(1.0 + texture_mod, 0.35);

    // Doppler beaming. Disk material orbits counter-clockwise (viewed
    // from +z); orbital speed ~ sqrt(R_in / r) capped sub-light. The
    // line-of-sight component depends on tilt: a vector tangent to the
    // disk at azimuth phi has world-frame z component = cos(phi) * sin(tilt).
    // Approaching side (negative LOS velocity in our convention) is
    // brighter.
    float v = clamp(sqrt(u_disk_inner_px / r_disk) * 0.5, 0.0, 0.95);
    float v_los = -(dx / max(r_disk, 1.0)) * st * v;
    float gamma = 1.0 / sqrt(max(1.0 - v * v, 1e-3));
    float doppler = 1.0 / max(gamma * (1.0 - v_los), 0.05);

    // Gravitational redshift: photons lose energy escaping the BH well.
    // Using E as the gravitational scale (a proxy for the Schwarzschild
    // radius in our screen-space units).
    float redshift = sqrt(max(1.0 - 0.5 * u_einstein_px / r_disk, 0.05));

    return base * lum * pow(doppler, 3.0) * redshift
           * modulation * u_disk_brightness;
}

void main() {
    vec2 pixel = v_uv * u_resolution;
    vec2 d = pixel - u_bh_center;
    float r = length(d);
    float E = u_einstein_px;

    // Event horizon / photon sphere shadow.
    if (r < 0.5 * E) {
        f_color = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }

    // Schwarzschild thin-lens deflection. r_src may be negative for
    // r < E — this is the inner image (opposite side of the BH) and
    // is responsible for the ring-of-light effect inside the lensing
    // halo. We DON'T short-circuit on negative r_src any more.
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
    vec3 final_color = clamp(background + disk, 0.0, 1.0);
    f_color = vec4(final_color, 1.0);
}
