#version 440
// Stencil step of the even-odd fill: every edge of a closed path spans a triangle with the element centre, the
// local origin. Parity only depends on the closed outline, so the centre may be per element, which keeps the
// triangles small. Colour writes are off.
layout(location = 0) in vec2 weight;      // (0,0) centre, (1,0) edge start, (0,1) edge end
layout(location = 1) in vec4 seg;
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
void main() {
    uint slot = elem & 0x7fffffffu;
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    if (slot == HOLE || (elem & 0x80000000u) != 0u) return;    // open path: stroke only
    ivec2 tc = ivec2(int(slot % 512u) * 2, int(slot / 512u));
    vec4 t0 = texelFetch(elems, tc, 0), t1 = texelFetch(elems, tc + ivec2(1, 0), 0);
    if (t0.w < 0.5) return;
    vec2 l = seg.xy * weight.x + seg.zw * weight.y;
    gl_Position = mmToClip * vec4(dot(t0.xy, l) + t0.z, dot(t1.xy, l) + t1.z, 0.0, 1.0);
}
