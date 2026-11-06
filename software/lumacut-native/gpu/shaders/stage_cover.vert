#version 440
// Cover step: the whole target, the stencil test decides. No vertex buffer.
void main() {
    vec2 c = vec2(gl_VertexIndex & 1, (gl_VertexIndex >> 1) & 1);
    gl_Position = vec4(c * 2.0 - 1.0, 0.0, 1.0);
}
