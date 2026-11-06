#version 440
// Selection frame, handles, rubber band: bed mm, constant width in pixels, colour per instance.
layout(location = 0) in vec2 corner;
layout(location = 1) in vec4 seg;
layout(location = 2) in vec4 col;
layout(location = 3) in float halfPx;
layout(std140, binding = 0) uniform Buf {
    mat4 mmToClip;
    vec2 viewportPx;
    float halfWidthPx;
    float selectedHalfPx;
    vec4 color;
    vec4 selectedColor;
};
layout(location = 0) out float vEdge;
layout(location = 1) out float vHalf;
layout(location = 2) out vec4 vColor;
void main() {
    vec4 a = mmToClip * vec4(seg.xy, 0.0, 1.0), b = mmToClip * vec4(seg.zw, 0.0, 1.0);
    vec2 pa = a.xy * viewportPx * 0.5, pb = b.xy * viewportPx * 0.5;
    vec2 dir = pb - pa;
    float len = length(dir);
    dir = len > 1e-5 ? dir / len : vec2(1.0, 0.0);
    float grown = halfPx + 0.75;
    vec2 p = mix(pa, pb, corner.x) + vec2(-dir.y, dir.x) * corner.y * grown;
    gl_Position = vec4(p / (viewportPx * 0.5), 0.0, 1.0);
    vEdge = corner.y * grown;
    vHalf = halfPx;
    vColor = vec4(col.rgb * col.a, col.a);
}
