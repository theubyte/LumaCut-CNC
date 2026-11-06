#include "core/image.h"
#include "core/parallel.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <stdexcept>

namespace lumacut {
namespace {

/** Math.round: halbe nach oben, auch knapp unter .5 korrekt (floor(x + 0.5) wäre es nicht). */
inline double jround(double x) {
    const double f = std::floor(x);
    return x - f >= 0.5 ? f + 1 : f;
}
inline uint8_t clampByte(double v) { return v < 0 ? uint8_t(0) : v > 255 ? uint8_t(255) : uint8_t(v); }

struct Tap { int dx, dy; float wt; };

/**
 * Fehlerdiffusion in 32-Bit-Float wie Kotlin (FloatArray). err * wt / div in genau dieser Reihenfolge,
 * jedes Zwischenergebnis in float: das Muster hängt am letzten Bit. Nur drei Zeilen im Speicher.
 */
template <size_t N>
Gray diffuse(GrayView src, int w, int h, const Tap (&taps)[N], float div) {
    Gray out(size_t(w) * h);
    constexpr int kMargin = 2;  // Randplatz links und rechts, dann entfällt der x-Test
    const size_t stride = size_t(w) + 2 * kMargin;
    std::vector<float> rows(stride * 3, 0.0f);
    float* r[3] = {rows.data(), rows.data() + stride, rows.data() + 2 * stride};
    auto load = [&](float* row, int y) {
        std::fill(row, row + kMargin, 0.0f);
        std::fill(row + kMargin + w, row + stride, 0.0f);
        if (y < h) for (int x = 0; x < w; ++x) row[kMargin + x] = float(src[size_t(y) * w + x]);
        else std::fill(row + kMargin, row + kMargin + w, 0.0f);
    };
    load(r[0], 0);
    load(r[1], 1);
    load(r[2], 2);
    for (int y = 0; y < h; ++y) {
        float* cur = r[0] + kMargin;
        uint8_t* o = out.data() + size_t(y) * w;
        for (int x = 0; x < w; ++x) {
            const float val = cur[x];
            const int q = val < 128.0f ? 0 : 255;
            o[x] = uint8_t(q);
            const float err = val - float(q);
            for (const Tap& t : taps) r[t.dy][kMargin + x + t.dx] += err * t.wt / div;
        }
        std::swap(r[0], r[1]);
        std::swap(r[1], r[2]);
        load(r[2], y + 3);
    }
    return out;
}

constexpr Tap FLOYD[] = {{1, 0, 7}, {-1, 1, 3}, {0, 1, 5}, {1, 1, 1}};
constexpr Tap JARVIS[] = {{1, 0, 7}, {2, 0, 5}, {-2, 1, 3}, {-1, 1, 5}, {0, 1, 7}, {1, 1, 5}, {2, 1, 3}, {-2, 2, 1}, {-1, 2, 3}, {0, 2, 5}, {1, 2, 3}, {2, 2, 1}};
constexpr Tap STUCKI[] = {{1, 0, 8}, {2, 0, 4}, {-2, 1, 2}, {-1, 1, 4}, {0, 1, 8}, {1, 1, 4}, {2, 1, 2}, {-2, 2, 1}, {-1, 2, 2}, {0, 2, 4}, {1, 2, 2}, {2, 2, 1}};

}  // namespace

Gray sharpen(GrayView src, int w, int h, double amount) {
    Gray out(src.size());
    parallelBlocks(h, 16, [&](std::ptrdiff_t y0, std::ptrdiff_t y1) {
        for (std::ptrdiff_t y = y0; y < y1; ++y) {
            const int ya = int(std::max<std::ptrdiff_t>(y - 1, 0)), yb = int(std::min<std::ptrdiff_t>(y + 1, h - 1));
            for (int x = 0; x < w; ++x) {
                const int xa = std::max(x - 1, 0), xb = std::min(x + 1, w - 1);
                int sum = 0;
                for (int yy = ya; yy <= yb; ++yy) {
                    const uint8_t* row = src.data() + size_t(yy) * w;
                    for (int xx = xa; xx <= xb; ++xx) sum += row[xx];
                }
                const int n = (yb - ya + 1) * (xb - xa + 1);
                const double blur = double(sum) / n;
                const double c = src[size_t(y) * w + x];
                out[size_t(y) * w + x] = clampByte(jround(c + (c - blur) * amount * 2));
            }
        }
    });
    return out;
}

Gray adjustGray(GrayView gray, int w, int h, const ImageAdjust& a) {
    if (a.isDefault()) return Gray(gray.begin(), gray.end());
    Gray sharpened;
    GrayView v = gray;
    if (a.sharpen > 0) {
        sharpened = sharpen(gray, w, h, a.sharpen / 100.0);
        v = sharpened;
    }
    const double factor = (100 + std::clamp(a.contrast, -100, 100)) / 100.0;
    const double shift = std::clamp(a.brightness, -100, 100) * 2.55;
    uint8_t lut[256];
    for (int g = 0; g < 256; ++g) {
        double x = (g - 128) * factor + 128 + shift;
        x = x < 0.0 ? 0.0 : x > 255.0 ? 255.0 : x;
        lut[g] = clampByte(jround(a.invert ? 255 - x : x));
    }
    Gray out(v.size());
    parallelBlocks(std::ptrdiff_t(v.size()), 1 << 16, [&](std::ptrdiff_t i0, std::ptrdiff_t i1) {
        for (std::ptrdiff_t i = i0; i < i1; ++i) out[size_t(i)] = lut[v[size_t(i)]];
    });
    return out;
}

Gray binarize(GrayView src, int w, int h, ImageMode mode) {
    switch (mode) {
        case ImageMode::Threshold: {
            Gray out(src.size());
            parallelBlocks(std::ptrdiff_t(src.size()), 1 << 16, [&](std::ptrdiff_t i0, std::ptrdiff_t i1) {
                for (std::ptrdiff_t i = i0; i < i1; ++i) out[size_t(i)] = src[size_t(i)] < 128 ? 0 : 255;
            });
            return out;
        }
        case ImageMode::Dither: return diffuse(src, w, h, FLOYD, 16.0f);
        case ImageMode::DitherJarvis: return diffuse(src, w, h, JARVIS, 48.0f);
        case ImageMode::DitherStucki: return diffuse(src, w, h, STUCKI, 42.0f);
        default: return Gray(src.begin(), src.end());
    }
}

Gray sampleGray(GrayView gray, int width, int height, int cols, int rows) {
    Gray out(size_t(rows) * cols);
    std::vector<int> px(static_cast<size_t>(cols));
    for (int c = 0; c < cols; ++c) px[size_t(c)] = std::min(width - 1, int((c + 0.5) * width / cols));
    parallelBlocks(rows, 16, [&](std::ptrdiff_t r0, std::ptrdiff_t r1) {
        for (std::ptrdiff_t r = r0; r < r1; ++r) {
            const size_t py = size_t(std::min(height - 1, int((double(r) + 0.5) * height / rows))) * width;
            uint8_t* o = out.data() + size_t(r) * cols;
            for (int c = 0; c < cols; ++c) o[c] = gray[py + size_t(px[size_t(c)])];
        }
    });
    return out;
}

Gray jobLevels(const Raster& r, int cols, int rows, const ImageAdjust& a, ImageMode mode) {
    const std::vector<uint8_t>& g = r.gray();
    if (qint64(g.size()) < qint64(r.width()) * r.height() || r.width() <= 0 || r.height() <= 0) throw std::invalid_argument("Ungültige Bilddaten");
    Gray s = sampleGray(g, r.width(), r.height(), cols, rows);
    if (!a.isDefault()) s = adjustGray(s, cols, rows, a);
    if (mode != ImageMode::Grayscale) s = binarize(s, cols, rows, mode);
    return s;
}

QByteArray encodeBase64(GrayView bytes) {
    static const char A[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    const size_t n = bytes.size();
    QByteArray out(qsizetype((n + 2) / 3 * 4), Qt::Uninitialized);
    char* o = out.data();
    const uint8_t* s = bytes.data();
    size_t groups = n / 3;
    parallelBlocks(std::ptrdiff_t(groups), 1 << 16, [&](std::ptrdiff_t g0, std::ptrdiff_t g1) {
        char* q = o + g0 * 4;
        const uint8_t* p = s + g0 * 3;
        for (std::ptrdiff_t g = g0; g < g1; ++g, p += 3, q += 4) {
            q[0] = A[p[0] >> 2];
            q[1] = A[((p[0] & 3) << 4) | (p[1] >> 4)];
            q[2] = A[((p[1] & 15) << 2) | (p[2] >> 6)];
            q[3] = A[p[2] & 63];
        }
    });
    const size_t rest = n - groups * 3;
    if (rest) {
        const uint8_t a = s[groups * 3], b = rest > 1 ? s[groups * 3 + 1] : 0;
        char* q = o + groups * 4;
        q[0] = A[a >> 2];
        q[1] = A[((a & 3) << 4) | (b >> 4)];
        q[2] = rest > 1 ? A[(b & 15) << 2] : '=';
        q[3] = '=';
    }
    return out;
}

Gray decodeBase64(QByteArrayView b64) {
    static const auto lut = [] {
        std::array<int8_t, 256> t{};
        t.fill(-1);
        const char* A = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        for (int i = 0; i < 64; ++i) t[uint8_t(A[i])] = int8_t(i);
        return t;
    }();
    size_t n = size_t(b64.size());
    const char* s = b64.data();
    while (n > 0 && s[n - 1] == '=') --n;
    Gray out(n / 4 * 3 + (n % 4 == 3 ? 2 : n % 4 == 2 ? 1 : 0));
    if (n % 4 == 1) throw std::invalid_argument("Ungültige Bilddaten");
    const size_t groups = n / 4;
    std::atomic_bool bad{false};
    parallelBlocks(std::ptrdiff_t(groups), 1 << 16, [&](std::ptrdiff_t g0, std::ptrdiff_t g1) {
        const char* p = s + g0 * 4;
        uint8_t* o = out.data() + g0 * 3;
        int check = 0;
        for (std::ptrdiff_t g = g0; g < g1; ++g, p += 4, o += 3) {
            const int a = lut[uint8_t(p[0])], b = lut[uint8_t(p[1])], c = lut[uint8_t(p[2])], d = lut[uint8_t(p[3])];
            check |= a | b | c | d;
            o[0] = uint8_t((a << 2) | (b >> 4));
            o[1] = uint8_t((b << 4) | (c >> 2));
            o[2] = uint8_t((c << 6) | d);
        }
        if (check < 0) bad = true;
    });
    size_t rest = n % 4;
    if (rest) {
        const char* p = s + groups * 4;
        uint8_t* o = out.data() + groups * 3;
        const int a = lut[uint8_t(p[0])], b = lut[uint8_t(p[1])], c = rest == 3 ? lut[uint8_t(p[2])] : 0;
        if ((a | b | c) < 0) bad = true;
        o[0] = uint8_t((a << 2) | (b >> 4));
        if (rest == 3) o[1] = uint8_t((b << 4) | (c >> 2));
    }
    if (bad) throw std::invalid_argument("Ungültige Bilddaten");
    return out;
}

Gray grayFromRgba(std::span<const uint8_t> rgba, int w, int h) {
    Gray out(size_t(w) * h);
    parallelBlocks(h, 16, [&](std::ptrdiff_t y0, std::ptrdiff_t y1) {
        for (std::ptrdiff_t y = y0; y < y1; ++y) {
            const uint8_t* p = rgba.data() + size_t(y) * w * 4;
            uint8_t* o = out.data() + size_t(y) * w;
            for (int x = 0; x < w; ++x, p += 4) {
                const double a = p[3] / 255.0, l = 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2];
                o[x] = clampByte(jround(l * a + 255 * (1 - a)));
            }
        }
    });
    return out;
}

PreviewImage previewRgba(const Raster& r, const PreviewOptions& opt) {
    int cols = opt.cols > 0 ? opt.cols : r.width(), rows = opt.rows > 0 ? opt.rows : r.height();
    if (qint64(cols) * rows > opt.maxPixels) {
        const double k = std::sqrt(double(opt.maxPixels) / (double(cols) * rows));
        cols = std::max(1, int(std::floor(cols * k)));
        rows = std::max(1, int(std::floor(rows * k)));
    }
    const Gray levels = jobLevels(r, cols, rows, opt.adjust, opt.mode);
    PreviewImage out;
    out.width = cols;
    out.height = rows;
    out.rgba.resize(levels.size() * 4);
    parallelBlocks(std::ptrdiff_t(levels.size()), 1 << 16, [&](std::ptrdiff_t i0, std::ptrdiff_t i1) {
        uint8_t* p = out.rgba.data() + size_t(i0) * 4;
        for (std::ptrdiff_t i = i0; i < i1; ++i, p += 4) {
            const uint8_t g = levels[size_t(i)];
            if (opt.transparentWhite) { p[0] = p[1] = p[2] = 0; p[3] = uint8_t(255 - g); }
            else { p[0] = p[1] = p[2] = g; p[3] = 255; }
        }
    });
    return out;
}

}  // namespace lumacut
