#version 300 es

// Waves display pass: sample the sim field (LINEAR-filtered up from sim
// resolution) and map it to a translucent water tint over the camera —
// crests toward icy white, troughs toward deep blue, transparent where
// the water is calm. Output is premultiplied alpha (the canvas' default
// compositing mode).
//
// GAIN/MAX_ALPHA mirror config.WAVE_DISPLAY_* — keep in sync. The tone curve
// is tanh, not a linear ramp: the field's amplitude scales with the number of
// live sources (max|u| ~0.5 for one, ~1.2 for six), so a ramp bright enough
// for one source would white out at six. tanh is steep near zero (faint
// ripples read clearly) and saturates gently (six sources land just above one).

precision highp float;

uniform sampler2D u_field;

in  vec2 v_uv;
out vec4 f_color;

const vec3  CREST     = vec3(0.75, 0.93, 1.00);
const vec3  TROUGH    = vec3(0.08, 0.28, 0.55);
const float GAIN      = 1.8;
const float MAX_ALPHA = 0.85;

void main() {
    // v_uv is top-left origin (frame coords); the field texture is written
    // bottom-origin via gl_FragCoord (see waves_step.frag's orientation note),
    // so flip v to sample the cell that belongs to this screen position.
    float u = texture(u_field, vec2(v_uv.x, 1.0 - v_uv.y)).r;
    float m = 0.5 + 0.5 * tanh(u * 1.4);
    vec3 col = mix(TROUGH, CREST, m);
    float a = MAX_ALPHA * tanh(abs(u) * GAIN);
    f_color = vec4(col * a, a);
}
