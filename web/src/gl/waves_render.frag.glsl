#version 300 es

// Waves display pass: sample the sim field (LINEAR-filtered up from sim
// resolution) and map it to a translucent water tint over the camera —
// crests toward icy white, troughs toward deep blue, transparent where
// the water is calm. Output is premultiplied alpha (the canvas' default
// compositing mode).

precision highp float;

uniform sampler2D u_field;

in  vec2 v_uv;
out vec4 f_color;

const vec3 CREST  = vec3(0.75, 0.93, 1.00);
const vec3 TROUGH = vec3(0.08, 0.28, 0.55);

void main() {
    float u = texture(u_field, v_uv).r;
    float m = 0.5 + 0.5 * tanh(u * 1.4);
    vec3 col = mix(TROUGH, CREST, m);
    float a = clamp(abs(u) * 0.5, 0.0, 0.65);
    f_color = vec4(col * a, a);
}
