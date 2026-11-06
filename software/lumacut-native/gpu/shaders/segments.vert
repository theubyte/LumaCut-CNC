#version 440
// One instance = one straight toolpath segment, expanded to a screen-space quad with a soft edge.
layout(location = 0) in vec2 corner;      // x: 0..1 along the segment, y: -1..1 across
layout(location = 1) in vec4 seg;         // x0 y0 x1 y1 in mm
layout(location = 2) in float power;      // 0 = travel, else 0..1

layout(std140, binding = 0) uniform Buf {
    mat4 mmToClip;
    vec2 viewportPx;
    float halfWidthPx;    // vector look: constant line width
    float spotPx;         // raster look: width of the real laser line in px, 0 = vector look
    vec4 highColor;
    vec4 lowColor;
    vec4 travelColor;
    vec4 sheetColor;
    float showTravel;
    float opacity;
};
layout(location = 0) out float vEdge;
layout(location = 1) out float vHalf;
layout(location = 2) out vec4 vColor;

void main() {
    bool travel = power <= 0.0;
    if (travel && showTravel < 0.5) {     // degenerate, costs no fragments
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        vEdge = 0.0; vHalf = 0.0; vColor = vec4(0.0);
        return;
    }
    vec4 a = mmToClip * vec4(seg.xy, 0.0, 1.0);
    vec4 b = mmToClip * vec4(seg.zw, 0.0, 1.0);
    vec2 pa = a.xy * viewportPx * 0.5, pb = b.xy * viewportPx * 0.5;
    vec2 dir = pb - pa;
    float len = length(dir);
    dir = len > 1e-5 ? dir / len : vec2(1.0, 0.0);
    vec2 nrm = vec2(-dir.y, dir.x);

    // Raster look: a line thinner than a pixel is one soft pixel with lower coverage, which is what
    // it really covers. Dense hatching therefore averages to the right tone instead of beating against the pixels.
    float hw = spotPx > 0.0 ? max(spotPx * 0.5, 0.5) : (travel ? min(halfWidthPx, 0.5) : halfWidthPx);
    float coverage = spotPx > 0.0 ? min(spotPx, 1.0) : 1.0;
    float grown = hw + 0.75;
    // Neighbours in a row meet exactly: without overlap there are no beads where segments join.
    float cap = spotPx > 0.0 ? 0.0 : 0.5;
    vec2 p = mix(pa - dir * cap, pb + dir * cap, corner.x) + nrm * corner.y * grown;
    gl_Position = vec4(p / (viewportPx * 0.5), 0.0, 1.0);
    vEdge = corner.y * grown;
    vHalf = hw;
    if (travel) {
        vColor = vec4(travelColor.rgb, 1.0) * travelColor.a * coverage * opacity;
    } else {
        // Strength as in the job view: a faint power stays visible, full power reads solid. Opaque against
        // the sheet, so joints and retraced lines do not add up.
        float p01 = clamp(power, 0.0, 1.0);
        float tone = 0.3 + 0.7 * pow(p01, 0.75);
        vec3 ink = mix(lowColor.rgb, highColor.rgb, p01);
        vColor = vec4(mix(sheetColor.rgb, ink, tone), 1.0) * coverage * opacity;
    }
}
