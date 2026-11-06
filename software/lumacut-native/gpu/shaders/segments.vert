#version 440
// One instance = one straight toolpath segment, expanded to a screen-space quad with a soft edge.
layout(location = 0) in vec2 corner;      // x: 0..1 along the segment, y: -1..1 across
layout(location = 1) in vec4 seg;         // x0 y0 x1 y1 in mm
layout(location = 2) in float power;      // 0 = travel, else 1..255 normalised

layout(std140, binding = 0) uniform Buf {
    mat4 mmToClip;
    vec2 viewportPx;
    float halfWidthPx;
    float showTravel;
    vec4 cutColor;
    vec4 travelColor;
};
layout(location = 0) out float vEdge;
layout(location = 1) out vec4 vColor;

void main() {
    vec4 a = mmToClip * vec4(seg.xy, 0.0, 1.0);
    vec4 b = mmToClip * vec4(seg.zw, 0.0, 1.0);
    vec2 pa = a.xy * viewportPx * 0.5, pb = b.xy * viewportPx * 0.5;
    vec2 dir = pb - pa;
    float len = length(dir);
    dir = len > 1e-4 ? dir / len : vec2(1.0, 0.0);
    vec2 nrm = vec2(-dir.y, dir.x);
    bool travel = power <= 0.0;
    float hw = travel ? 0.6 : halfWidthPx + 0.75;   // 0.75: room for the soft edge
    vec2 p = mix(pa - dir * hw, pb + dir * hw, corner.x) + nrm * corner.y * hw;
    gl_Position = vec4(p / (viewportPx * 0.5), 0.0, 1.0);
    vEdge = corner.y * hw;
    if (travel) {
        vColor = showTravel > 0.5 ? travelColor : vec4(0.0);
    } else {
        // Darker with more power, never fully transparent: weak lines must stay visible.
        float k = 0.25 + 0.75 * power;
        vColor = vec4(cutColor.rgb, cutColor.a * k);
    }
}
