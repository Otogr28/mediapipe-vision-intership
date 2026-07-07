#version 300 es

// Fullscreen triangle. v_uv has a TOP-LEFT origin so that
// `v_uv * u_resolution` reproduces OpenCV pixel coordinates (y down) —
// the backend's bh_center passes through unchanged, and since browser
// texture uploads put image row 0 at texel v=0, sampling with this uv is
// self-consistent with no UNPACK_FLIP_Y (which would force a CPU flip on
// every streamed frame).

layout(location = 0) in vec2 in_pos;
out vec2 v_uv;

void main() {
    v_uv = vec2((in_pos.x + 1.0) * 0.5, (1.0 - in_pos.y) * 0.5);
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
