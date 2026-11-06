#version 440
layout(std140, binding = 0) uniform Buf {
    mat4 unitToClip;
    float opacity;
};
layout(binding = 1) uniform sampler2D tex;
layout(location = 0) in vec2 vUv;
layout(location = 0) out vec4 fragColor;
void main() { fragColor = texture(tex, vUv) * opacity; }   // premultiplied texture
