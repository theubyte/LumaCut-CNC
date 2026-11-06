#version 440
layout(std140, binding = 0) uniform Buf {
    mat4 mmToClip;
    vec2 viewportPx;
    float halfWidthPx;
    float selectedHalfPx;
    vec4 color;
    vec4 selectedColor;
};
layout(location = 0) out vec4 fragColor;
void main() { fragColor = color; }
