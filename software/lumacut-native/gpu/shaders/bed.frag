#version 440
// Works per device pixel, so grid lines stay exactly one pixel wide and even: no blur, no moire at any zoom.
layout(std140, binding = 0) uniform Buf {
    mat4 clip;
    vec2 bed; vec2 pan;
    float zoom; float dpr; float parkW; float parkH;
    float showGrid;
    vec4 sheet; vec4 grid; vec4 gridMajor; vec4 edge; vec4 park;
};
layout(location = 0) in vec2 vPx;
layout(location = 0) out vec4 fragColor;

bool onLine(float px, float offs, float stepPx) {
    float k = floor((px + 0.5 - offs) / stepPx + 0.5);
    return floor(k * stepPx + offs) == px;
}
vec3 over(vec3 under, vec4 c) { return mix(under, c.rgb, c.a); }

void main() {
    vec2 px = floor(vPx);
    vec2 lo = floor(pan), hi = floor(pan + bed * zoom);
    if (any(lessThan(px, lo)) || any(greaterThan(px, hi))) {
        vec2 d = max(lo - vPx, vPx - hi);
        float dist = length(max(d, vec2(0.0)));
        float k = 1.0 - smoothstep(0.0, 22.0 * dpr, dist);
        fragColor = vec4(0.0, 0.0, 0.0, 0.13 * k * k);
        return;
    }
    vec3 c = sheet.rgb;
    float z = zoom / dpr;   // grid steps follow what the eye sees, as in the editor
    float minor = z >= 70.0 ? 0.1 : z >= 7.0 ? 1.0 : z >= 3.0 ? 5.0 : z >= 1.0 ? 10.0 : 50.0;
    float major = z >= 70.0 ? 1.0 : z >= 7.0 ? 10.0 : z >= 1.0 ? 50.0 : 100.0;
    if (showGrid > 0.5) {
        float minorPx = minor * zoom, majorPx = major * zoom;
        float fade = smoothstep(4.0 * dpr, 9.0 * dpr, minorPx);
        if (onLine(px.x, pan.x, majorPx) || onLine(px.y, pan.y, majorPx)) c = over(c, gridMajor);
        else if (onLine(px.x, pan.x, minorPx) || onLine(px.y, pan.y, minorPx)) c = over(c, vec4(grid.rgb, grid.a * fade));
    }
    vec2 parkLo = vec2(pan.x + (bed.x - parkW) * zoom, pan.y), parkHi = vec2(pan.x + bed.x * zoom, pan.y + parkH * zoom);
    if (parkW > 0.0 && px.x >= floor(parkLo.x) && px.y < floor(parkHi.y)) {
        c = over(c, park);
        float period = 8.0 * dpr;
        if (mod(px.x - px.y - pan.x + pan.y, period) < 1.25 * dpr) c = over(c, park);
        if (px.x == floor(parkLo.x) || px.y == floor(parkHi.y) - 1.0) c = over(c, vec4(park.rgb, min(1.0, park.a * 4.0)));
    }
    if (px.x == lo.x || px.y == lo.y || px.x == hi.x || px.y == hi.y) c = edge.rgb;
    fragColor = vec4(c, 1.0);
}
