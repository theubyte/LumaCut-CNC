#version 440
// The map holds summed premultiplied ink and coverage. Divide to get the mean ink colour, clamp the coverage.
layout(std140, binding = 0) uniform Buf {
    mat4 mmToClip;
    vec4 rectMm;
    float opacity;
    float lod;         // mip level one finer than a screen pixel
};
layout(binding = 1) uniform sampler2D map;
layout(location = 0) in vec2 vUv;
layout(location = 0) out vec4 fragColor;
void main() {
    // A tent filter two screen pixels wide, over a mip level that still resolves the lines. A line spacing near
    // the pixel size would come out of a plain mipmap lookup as a beat pattern; this is what removes the moire.
    vec2 dx = dFdx(vUv) * 0.67, dy = dFdy(vUv) * 0.67;
    vec4 t = vec4(0.0);
    for (int y = -1; y <= 1; ++y)
        for (int x = -1; x <= 1; ++x)
            t += textureLod(map, vUv + dx * float(x) + dy * float(y), lod) * float((2 - abs(x)) * (2 - abs(y)));
    t /= 16.0;
    if (t.a <= 0.0) discard;
    float a = min(t.a, 1.0);
    fragColor = vec4(t.rgb / t.a, 1.0) * a * opacity;
}
