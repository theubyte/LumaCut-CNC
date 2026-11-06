#version 440
layout(location = 0) in float vEdge;
layout(location = 1) in vec4 vColor;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform Buf {
    mat4 mmToClip;
    vec2 viewportPx;
    float halfWidthPx;
    float showTravel;
    vec4 cutColor;
    vec4 travelColor;
};

void main() {
    float d = abs(vEdge);
    float a = clamp(halfWidthPx + 0.5 - d, 0.0, 1.0);
    if (vColor.a <= 0.0 || a <= 0.0) discard;
    fragColor = vec4(vColor.rgb * vColor.a * a, vColor.a * a);   // premultiplied
}
