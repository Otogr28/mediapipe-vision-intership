"""Offscreen ModernGL renderer for screen-space GPU effects.

`LensingRenderer` owns a standalone GL context, a fullscreen quad, and a
shader program implementing Schwarzschild thin-lens gravitational
lensing for a single black hole. The renderer is reusable for any
future GPU pass that fits the same "frame in, frame out" pattern.

Orientation & color handling:
- The input frame is BGR uint8 with row 0 at the top (OpenCV convention).
- Bytes are uploaded as opaque pixel data — no BGR<->RGB conversion is
  performed, so cv2.imshow keeps receiving BGR end-to-end.
- The fullscreen quad maps clip (-1,-1) -> uv (0,0). Combined with GL's
  bottom-up glReadPixels convention, the read-back buffer's row 0
  matches the input's row 0 so orientation is preserved across the full
  GPU roundtrip.
"""

from pathlib import Path

import moderngl
import numpy as np


SHADER_DIR = Path(__file__).parent / "shaders"


class LensingRenderer:
    def __init__(self, width, height):
        self.width = width
        self.height = height

        self.ctx = moderngl.create_standalone_context()

        vert_src = (SHADER_DIR / "fullscreen.vert").read_text()
        frag_src = (SHADER_DIR / "black_hole.frag").read_text()
        self.program = self.ctx.program(
            vertex_shader=vert_src,
            fragment_shader=frag_src,
        )

        quad = np.array([
            -1.0, -1.0, 0.0, 0.0,
             1.0, -1.0, 1.0, 0.0,
            -1.0,  1.0, 0.0, 1.0,
             1.0,  1.0, 1.0, 1.0,
        ], dtype="f4")
        self.vbo = self.ctx.buffer(quad.tobytes())
        self.vao = self.ctx.vertex_array(
            self.program,
            [(self.vbo, "2f 2f", "in_pos", "in_uv")],
        )

        self.frame_tex = self.ctx.texture((width, height), 3, dtype="f1")
        self.frame_tex.repeat_x = False
        self.frame_tex.repeat_y = False
        self.frame_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)

        self.fbo_color = self.ctx.texture((width, height), 3, dtype="f1")
        self.fbo = self.ctx.framebuffer(color_attachments=[self.fbo_color])

        self.program["u_resolution"].value = (float(width), float(height))

        self._out = np.empty((height, width, 3), dtype=np.uint8)

    def render(self, frame_bgr, bh_center, einstein_px, *,
               disk_inner_px, disk_outer_px, disk_tilt_rad, disk_brightness,
               time_seconds, rotation_speed):
        """Apply lensing to `frame_bgr`. Returns the distorted BGR frame.

        `bh_center` is `(x, y)` in OpenCV pixel coords (y = 0 at top).
        `einstein_px` is the screen-space Einstein radius in pixels.

        Accretion disk params (keyword-only because they always travel
        together and a positional list would be unreadable):
        - `disk_inner_px`, `disk_outer_px`: disk extent in disk-frame
          pixels. The disk is sampled in the *un-projected* disk plane
          so these are pre-tilt radii.
        - `disk_tilt_rad`: 0 face-on, pi/2 edge-on.
        - `disk_brightness`: emission multiplier; 0 = no disk.
        - `time_seconds`: elapsed seconds, drives the rotating texture.
          The caller is responsible for wrapping it to a small range
          (e.g. `t % 1000`) to keep GPU float32 precision intact.
        - `rotation_speed`: angular speed at the inner edge (rad/s).
          Outer rings spin slower per Kepler's third law.
        """
        h, w, _ = frame_bgr.shape
        if w != self.width or h != self.height:
            raise ValueError(
                f"Frame {w}x{h} does not match renderer {self.width}x{self.height}"
            )

        self.frame_tex.write(np.ascontiguousarray(frame_bgr).tobytes())
        self.frame_tex.use(location=0)
        self.program["u_frame"].value = 0
        self.program["u_bh_center"].value = (float(bh_center[0]), float(bh_center[1]))
        self.program["u_einstein_px"].value = float(einstein_px)
        self.program["u_disk_inner_px"].value = float(disk_inner_px)
        self.program["u_disk_outer_px"].value = float(disk_outer_px)
        self.program["u_disk_tilt_rad"].value = float(disk_tilt_rad)
        self.program["u_disk_brightness"].value = float(disk_brightness)
        self.program["u_time"].value = float(time_seconds)
        self.program["u_rotation_speed"].value = float(rotation_speed)

        self.fbo.use()
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)
        self.vao.render(moderngl.TRIANGLE_STRIP)

        self.fbo.read_into(self._out, components=3, dtype="f1")
        return self._out

    def release(self):
        for obj in (self.vao, self.vbo, self.frame_tex, self.fbo_color,
                    self.fbo, self.program, self.ctx):
            try:
                obj.release()
            except Exception:
                pass
