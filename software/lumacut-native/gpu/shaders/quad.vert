#version 440
// A textured quad: unit square through a matrix. Used for stage images and the image preview.
layout(std140, binding = 0) uniform Buf {
    mat4 unitToClip;
    float opacity;
};
layout(location = 0) out vec2 vUv;
void main() {
    vUv = vec2(gl_VertexIndex & 1, (gl_VertexIndex >> 1) & 1);
    gl_Position = unitToClip * vec4(vUv, 0.0, 1.0);
}
