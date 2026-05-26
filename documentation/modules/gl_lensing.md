---
title: gl_lensing.py
tags: [module, rendering, gpu, moderngl, shader, black-hole]
---

# `gl_lensing.py` — GPU Lensing Renderer

**Location:** `src/rendering/gl_lensing.py`
**Shaders:** `src/rendering/shaders/{fullscreen.vert, black_hole.frag}`

ModernGL-backed offscreen renderer that applies physically motivated screen-space effects to a camera frame. Currently provides Schwarzschild thin-lens gravitational lensing plus an accretion disk (temperature, Doppler beaming, gravitational redshift) for a single black hole, used by the `BlackHole` interactable from [[interactables]].

The renderer is intentionally generic: it owns a standalone GL context, a fullscreen quad, and a single shader program. Future GPU passes (additional post-processing) can attach more programs to the same context.

---

## Why GPU

The project deploys on an NVIDIA Jetson. Per-pixel gravitational deflection sampled at camera resolution (~300k fragments at 640x480, more at higher captures) is comfortably real-time on the Jetson GPU but would stall the camera loop if done in NumPy. The GPU also keeps the door open for an accretion disk pass without a CPU bottleneck.

The frame travels CPU → GPU (`texture.write`) → fragment shader → FBO → CPU (`fbo.read_into`) per frame. The roundtrip is small at standard camera resolutions; if it ever becomes the bottleneck, the next step is CUDA-GL interop or persistent-mapped buffers (out of scope today).

---

## Physics — Schwarzschild Thin-Lens

For each output pixel at screen-space distance `r` from the BH centre, the shader maps it back to a source pixel via the Schwarzschild deflection angle `α = 4GM/(c²b)` rewritten in pixel units. With `E` the Einstein radius in pixels:

```
r_src = r - E² / r
```

`r_src` is allowed to be **negative**. The negative branch is the *inner image* — the second solution of the thin-lens equation `β = θ − θ_E²/θ`, which physically represents light from a source on the opposite side of the BH that wrapped around the lens. This is the branch responsible for the bright ring just outside the event-horizon shadow: light from the back of the accretion disk gets bent over the top of the BH and lands inside the Einstein radius. Without this branch the BH would look like a flat featureless disc.

| Region | Condition | Output |
|---|---|---|
| Event-horizon shadow | `r < 0.5 · E` | Pure black |
| Off-frame background sample | `src_uv` outside `[0, 1]²` | Background = 0 (disk still composited if hit) |
| Outer image | `r > E` | Background + disk sampled at `bh_center + (r_src/r) · d` (same side as the screen pixel) |
| Inner image | `0.5·E < r < E` | Background + disk sampled at the *opposite* side via `(r_src/r) < 0` |

The Einstein-radius parameterisation is convenient: doubling `E` doubles the visual "weight" of the BH without changing any other knob. The relationship to physical mass `M` is `E² ∝ M`, so a tunable `M` slider would feed `E = sqrt(k · M)` for some scene-dependent `k`.

## Physics — Accretion Disk

The disk is a thin annulus in a plane tilted around the x-axis by `u_disk_tilt_rad`. For each fragment the shader takes the lensed `src_offset` (which already contains the gravitational deflection) and un-projects the tilt by dividing the y component by `cos(tilt)` to recover disk-plane radius `r_disk`. The disk emits when `r_disk ∈ [inner, outer]`.

Four physical effects shape the emission:

1. **Radial temperature gradient** — colour interpolates from a hot inner band (pale yellow-white) through orange (mid-disk) to a cool deep red at the outer edge. Luminosity follows `(R_in / r_disk)³`, a steeper-than-Newtonian falloff that emphasises the inner ring.
2. **Doppler beaming** — disk material orbits counter-clockwise viewed from `+z` with speed `v ≈ √(R_in / r_disk)` capped sub-light. The line-of-sight component depends on tilt: at azimuth `φ`, a disk-tangent vector has world-frame z-component `cos(φ) · sin(tilt)`, so the approaching side of the disk receives a factor `δ³ = 1/(γ(1−v_los))³` while the receding side dims by the reciprocal. With the default `tilt = 1.2 rad` this produces the strongly asymmetric "one bright crescent" look familiar from the Interstellar / EHT images.
3. **Gravitational redshift** — emission is multiplied by `√(1 − 0.5·E/r_disk)` to capture photon energy loss climbing out of the BH potential well.
4. **Differential rotation** — the disk is given an azimuthal procedural texture (three superposed sine harmonics) sheared by Kepler's third law `ω(r) ∝ r^(-3/2)`. Inner rings rotate visibly faster than outer rings, so over time the texture shears around the BH. The motion is driven by `u_time` (elapsed seconds from BH spawn, wrapped at 1000s by the caller to keep float32 precision) and scaled by `u_rotation_speed` (rad/s at the inner edge — see `BH_DISK_ROTATION_SPEED` in [[config]]). Setting the speed to `0` freezes the procedural texture; the Doppler asymmetry and rest of the physics still hold.

The disk emission is composited additively onto the lensed background and clamped to `[0, 1]`. Setting `u_disk_brightness = 0` disables the disk visually for a "lensing only" debug view.

---

## Orientation & Colour

End-to-end the renderer treats pixel bytes as opaque, which lets it skip both vertical flips and BGR↔RGB conversions:

- The input frame is BGR uint8 with row 0 at the top (OpenCV convention).
- `texture.write(frame.tobytes())` puts row 0 at the start of texture memory.
- The fullscreen quad maps clip `(-1, -1)` → uv `(0, 0)`. Combined with GL's bottom-up `glReadPixels` semantics, the byte returned to `numpy[0, 0]` is the same pixel as `frame[0, 0]`.
- The shader treats `texture(u_frame, uv).rgb` as whatever was uploaded (BGR), and `cv2.imshow` keeps receiving BGR.

`bh_center` is therefore passed in OpenCV coords: `(x, y)` with `y = 0` at the top of the displayed image. No translation layer is needed between the BH's stored position and the shader uniform.

---

## `LensingRenderer`

### `__init__(width, height)`

| Parameter | Type | Description |
|---|---|---|
| `width` | `int` | Frame width in pixels |
| `height` | `int` | Frame height in pixels |

Creates a standalone ModernGL context, compiles the lensing program, allocates the input texture and output framebuffer, and pre-allocates the read-back ndarray. Idempotent constructor — only fails if the platform cannot provide an OpenGL 3.3+ standalone context. On Jetson this routes through EGL automatically.

### `render(frame_bgr, bh_center, einstein_px, *, disk_inner_px, disk_outer_px, disk_tilt_rad, disk_brightness, time_seconds, rotation_speed) → np.ndarray`

| Parameter | Type | Description |
|---|---|---|
| `frame_bgr` | `np.ndarray (H, W, 3) uint8` | Input BGR frame from the camera loop |
| `bh_center` | `(float, float)` | BH centre in OpenCV pixel coords |
| `einstein_px` | `float` | Einstein radius in pixels — controls the size of the lensing region |
| `disk_inner_px` | `float` | Disk inner edge in **disk-frame** pixels (pre-tilt; the screen-space vertical extent is `disk_inner_px · cos(tilt)`) |
| `disk_outer_px` | `float` | Disk outer edge in disk-frame pixels |
| `disk_tilt_rad` | `float` | Disk tilt: 0 = face-on, π/2 = edge-on |
| `disk_brightness` | `float` | Overall emission multiplier; 0 hides the disk |
| `time_seconds` | `float` | Elapsed seconds — drives the rotating procedural texture. The caller must wrap it to a small range (e.g. `t % 1000`) so GPU float32 precision stays intact during long runs. |
| `rotation_speed` | `float` | Angular speed at the inner edge (rad/s). Outer rings rotate slower (Keplerian). |

All keyword-only params travel together and a positional list would be unreadable.

Returns the lensed BGR frame as a `(H, W, 3) uint8` ndarray. The returned array is a **reused internal buffer**: the caller must `np.copyto` (or otherwise consume) before calling `render` again.

Raises `ValueError` if `frame_bgr.shape[:2]` does not match the renderer's `(height, width)`.

### `release()`

Releases all GL objects (program, textures, framebuffer, VAO, VBO, context). Optional — Python GC also frees these eventually, but explicit release is cleaner during shutdown.

---

## Shader Files

### `shaders/fullscreen.vert`

Trivial passthrough vertex shader. Reads `in_pos` (clip-space xy) and `in_uv` (texture coords), forwards `v_uv` to the fragment stage.

### `shaders/black_hole.frag`

Implements the Schwarzschild thin-lens model plus the accretion disk described above. Uniforms:

| Uniform | Type | Purpose |
|---|---|---|
| `u_frame` | `sampler2D` | Camera frame (uploaded as BGR but treated as opaque RGB by GL) |
| `u_bh_center` | `vec2` | BH centre in pixel coords |
| `u_einstein_px` | `float` | Einstein radius in pixels |
| `u_resolution` | `vec2` | Frame size, set once at construction |
| `u_disk_inner_px` | `float` | Disk inner edge (disk-frame px) |
| `u_disk_outer_px` | `float` | Disk outer edge (disk-frame px) |
| `u_disk_tilt_rad` | `float` | Disk tilt angle (radians) |
| `u_disk_brightness` | `float` | Disk emission multiplier |
| `u_time` | `float` | Elapsed seconds, drives disk rotation |
| `u_rotation_speed` | `float` | Angular speed at the disk's inner edge (rad/s) |

---

## Extending

| Goal | Where to add |
|---|---|
| New BH parameter (e.g. mass slider) | New uniform in `black_hole.frag`, new `program[...]` assignment in `render()` |
| Disk colour palette | Tweak the `hot`/`mid`/`cool` vec3 constants in `sample_disk()` |
| Animated tilt / rotation | Promote `disk_tilt_rad` (and/or a phase uniform) to be driven by frame counter from the camera loop |
| Higher-order photon ring | Add a thin-ring sample at `r = 1.5 · E` with extra Doppler weighting; would require breaking the strict thin-lens approximation |
| Multiple BHs | Promote `u_bh_center` and `u_einstein_px` to arrays + add `u_num_bh`, loop in the shader |
| Different effect entirely | New shader pair under `shaders/`, new program in the same `ctx`, new `render_*` method |

See also: [[interactables]], [[modules/ui_manager]], [[architecture]]
