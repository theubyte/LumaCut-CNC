#version 440
// The burn map on screen: one quad over the job's bounding box.
layout(std140, binding = 0) uniform Buf {
    mat4 mmToClip;
    vec4 rectMm;       // x0 y0 x1 y1
    float opacity;
    float lod;         // mip level one finer than a screen pixel
};
layout(location = 0) out vec2 vUv;
void main() {
    vUv = vec2(gl_VertexIndex & 1, (gl_VertexIndex >> 1) & 1);
    gl_Position = mmToClip * vec4(mix(rectMm.xy, rectMm.zw, vUv), 0.0, 1.0);
}
