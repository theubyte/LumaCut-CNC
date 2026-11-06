#version 440
// One edge of a stage element as one instance. Transform and state come from the element texture.
layout(location = 0) in vec2 corner;      // x: 0..1 along, y: -1..1 across
layout(location = 1) in vec4 seg;         // element-local mm
layout(location = 2) in uint elem;
layout(std140, binding = 0) uniform Buf {
    mat4 mmToClip;
    vec2 viewportPx;
    float halfWidthPx;
    float selectedHalfPx;
    vec4 color;
    vec4 selectedColor;
};
layout(binding = 1) uniform sampler2D elems;   // 2 texels per element: transform and state
const uint HOLE = 0x7fffffffu;
layout(location = 0) out float vEdge;
layout(location = 1) out float vHalf;
layout(location = 2) out vec4 vColor;
void main() {
    uint slot = elem & 0x7fffffffu;
    vEdge = 0.0; vHalf = 0.0; vColor = vec4(0.0);
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    if (slot == HOLE) return;
    ivec2 tc = ivec2(int(slot % 512u) * 2, int(slot / 512u));
    vec4 t0 = texelFetch(elems, tc, 0), t1 = texelFetch(elems, tc + ivec2(1, 0), 0);
    if (t0.w < 0.5) return;               // hidden
    vec2 w0 = vec2(dot(t0.xy, seg.xy) + t0.z, dot(t1.xy, seg.xy) + t1.z);
    vec2 w1 = vec2(dot(t0.xy, seg.zw) + t0.z, dot(t1.xy, seg.zw) + t1.z);
    vec4 a = mmToClip * vec4(w0, 0.0, 1.0), b = mmToClip * vec4(w1, 0.0, 1.0);
    vec2 pa = a.xy * viewportPx * 0.5, pb = b.xy * viewportPx * 0.5;
    vec2 dir = pb - pa;
    float len = length(dir);
    dir = len > 1e-5 ? dir / len : vec2(1.0, 0.0);
    bool selected = t0.w > 1.5;
    float hw = selected ? selectedHalfPx : halfWidthPx;
    float grown = hw + 0.75;
    vec2 p = mix(pa - dir * 0.5, pb + dir * 0.5, corner.x) + vec2(-dir.y, dir.x) * corner.y * grown;
    gl_Position = vec4(p / (viewportPx * 0.5), 0.0, 1.0);
    vEdge = corner.y * grown;
    vHalf = hw;
    vColor = selected ? selectedColor : color;
}
