#version 440
// Soft edge in pixels instead of MSAA. vHalf: half the line width in device pixels.
layout(location = 0) in float vEdge;
layout(location = 1) in float vHalf;
layout(location = 2) in vec4 vColor;      // premultiplied
layout(location = 0) out vec4 fragColor;
void main() {
    float a = clamp(vHalf + 0.5 - abs(vEdge), 0.0, 1.0);
    if (a <= 0.0) discard;
    fragColor = vColor * a;
}
