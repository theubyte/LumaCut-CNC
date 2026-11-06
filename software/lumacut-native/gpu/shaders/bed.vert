#version 440
// Bed rectangle in device pixels, grown for the drop shadow. No vertex buffer: four corners from the vertex index.
layout(std140, binding = 0) uniform Buf {
    mat4 clip;
    vec2 bed; vec2 pan;
    float zoom; float dpr; float parkW; float parkH;
    float showGrid;
    vec4 sheet; vec4 grid; vec4 gridMajor; vec4 edge; vec4 park;
};
layout(location = 0) out vec2 vPx;
void main() {
    vec2 c = vec2(gl_VertexIndex & 1, (gl_VertexIndex >> 1) & 1);
    float grow = 24.0 * dpr;
    vec2 a = pan - vec2(grow), b = pan + bed * zoom + vec2(grow);
    vPx = mix(a, b, c);
    gl_Position = clip * vec4(vPx, 0.0, 1.0);
}
