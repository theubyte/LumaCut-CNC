/** Bilder per QImage: PNG, JPG, WebP, BMP, GIF. Graustufen, EXIF-Drehung, Auflösung aus der Datei. PDF über das Qt-PDF-Bildformat. */
#include "core/image.h"
#include "core/import/vector.h"
#include "core/parallel.h"

#include <QBuffer>
#include <QImageReader>
#include <algorithm>
#include <cmath>
#include <cstring>

namespace lumacut::import {
namespace {

constexpr qint64 MAX_PIXELS = 200'000'000;
constexpr int ALLOCATION_LIMIT_MB = 1024;

inline uint32_t be32(const char* p) { return uint32_t(uint8_t(p[0])) << 24 | uint32_t(uint8_t(p[1])) << 16 | uint32_t(uint8_t(p[2])) << 8 | uint8_t(p[3]); }
inline uint32_t be16(const char* p) { return uint32_t(uint8_t(p[0])) << 8 | uint8_t(p[1]); }
inline uint32_t le32(const char* p) { return uint32_t(uint8_t(p[3])) << 24 | uint32_t(uint8_t(p[2])) << 16 | uint32_t(uint8_t(p[1])) << 8 | uint8_t(p[0]); }

std::optional<double> acceptDpi(double dpi) {
    if (dpi >= 30 && dpi <= 4800 && std::fabs(dpi - 72) > 0.5 && std::fabs(dpi - 96) > 0.5) return dpi;
    return std::nullopt;
}

/** Orientierung aus einem TIFF-Block (EXIF), 1 wenn nichts Brauchbares drinsteht. */
int tiffOrientation(const char* d, qint64 n) {
    if (n < 8) return 1;
    const bool little = d[0] == 'I' && d[1] == 'I';
    if (!little && !(d[0] == 'M' && d[1] == 'M')) return 1;
    const auto r16 = [&](qint64 o) { return little ? uint32_t(uint8_t(d[o])) | uint32_t(uint8_t(d[o + 1])) << 8 : be16(d + o); };
    const auto r32 = [&](qint64 o) { return little ? le32(d + o) : be32(d + o); };
    if (r16(2) != 42) return 1;
    const qint64 ifd = r32(4);
    if (ifd + 2 > n) return 1;
    const uint32_t count = r16(ifd);
    for (uint32_t i = 0; i < count; ++i) {
        const qint64 e = ifd + 2 + 12 * qint64(i);
        if (e + 12 > n) return 1;
        if (r16(e) == 0x0112) {
            const uint32_t v = r16(e + 8);
            return v >= 1 && v <= 8 ? int(v) : 1;
        }
    }
    return 1;
}

Gray orientGray(const Gray& src, int w, int h, int o, int& outW, int& outH) {
    const bool swap = o >= 5;
    outW = swap ? h : w;
    outH = swap ? w : h;
    Gray out(size_t(outW) * size_t(outH));
    const int ow = outW;
    parallelBlocks(outH, 32, [&](std::ptrdiff_t y0, std::ptrdiff_t y1) {
        for (int y = int(y0); y < y1; ++y) {
            uint8_t* row = out.data() + size_t(y) * size_t(ow);
            for (int x = 0; x < ow; ++x) {
                int sx = x, sy = y;
                switch (o) {
                case 2: sx = w - 1 - x; break;
                case 3: sx = w - 1 - x; sy = h - 1 - y; break;
                case 4: sy = h - 1 - y; break;
                case 5: sx = y; sy = x; break;
                case 6: sx = y; sy = h - 1 - x; break;
                case 7: sx = w - 1 - y; sy = h - 1 - x; break;
                case 8: sx = w - 1 - y; sy = x; break;
                default: break;
                }
                row[x] = src[size_t(sy) * size_t(w) + size_t(sx)];
            }
        }
    });
    return out;
}

/** Flächenmittel, mehrkernig. */
Gray scaleArea(const Gray& src, int w, int h, int outW, int outH) {
    Gray out(size_t(outW) * size_t(outH));
    parallelBlocks(outH, 8, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
        for (qint64 y = a; y < b; ++y) {
            const qint64 y0 = y * h / outH, y1 = std::max(y0 + 1, (y + 1) * h / outH);
            uint8_t* row = out.data() + size_t(y) * size_t(outW);
            for (qint64 x = 0; x < outW; ++x) {
                const qint64 x0 = x * w / outW, x1 = std::max(x0 + 1, (x + 1) * w / outW);
                uint64_t sum = 0;
                for (qint64 v = y0; v < y1; ++v) {
                    const uint8_t* s = src.data() + size_t(v) * size_t(w);
                    for (qint64 u = x0; u < x1; ++u) sum += s[u];
                }
                const uint64_t n = uint64_t((y1 - y0) * (x1 - x0));
                row[x] = uint8_t((sum + n / 2) / n);
            }
        }
    });
    return out;
}

Gray grayOfImage(const QImage& image) {
    const QImage rgba = image.convertToFormat(QImage::Format_RGBA8888);
    const int w = rgba.width(), h = rgba.height();
    if (rgba.bytesPerLine() == w * 4) return grayFromRgba(std::span<const uint8_t>(rgba.constBits(), size_t(w) * size_t(h) * 4), w, h);
    std::vector<uint8_t> packed(size_t(w) * size_t(h) * 4);
    for (int y = 0; y < h; ++y) std::memcpy(packed.data() + size_t(y) * size_t(w) * 4, rgba.constScanLine(y), size_t(w) * 4);
    return grayFromRgba(packed, w, h);
}

Raster finish(Gray gray, int w, int h, int maxSide) {
    const double k = std::min(1.0, double(maxSide) / std::max(w, h));
    if (k >= 1) return Raster::ofGray(w, h, std::move(gray));
    const int outW = std::max(1, int(std::lround(w * k))), outH = std::max(1, int(std::lround(h * k)));
    return Raster::ofGray(outW, outH, scaleArea(gray, w, h, outW, outH));
}

}  // namespace

std::optional<double> readDpi(const QByteArray& bytes) {
    const char* b = bytes.constData();
    const qint64 n = bytes.size();
    if (n >= 8 && uint8_t(b[0]) == 0x89 && b[1] == 'P') {
        for (qint64 p = 8; p + 12 <= n;) {
            const qint64 len = be32(b + p);
            const char* type = b + p + 4;
            if (std::memcmp(type, "pHYs", 4) == 0 && len >= 9 && p + 17 <= n)
                return b[p + 16] == 1 ? acceptDpi(be32(b + p + 8) * 0.0254) : std::nullopt;
            if (std::memcmp(type, "IDAT", 4) == 0) return std::nullopt;
            p += 12 + len;
        }
        return std::nullopt;
    }
    if (n >= 4 && uint8_t(b[0]) == 0xFF && uint8_t(b[1]) == 0xD8) {
        for (qint64 p = 2; p + 4 < n && uint8_t(b[p]) == 0xFF;) {
            const uint8_t marker = uint8_t(b[p + 1]);
            const qint64 len = be16(b + p + 2);
            if (marker == 0xE0 && p + 14 <= n && std::memcmp(b + p + 4, "JFIF", 4) == 0) {
                const uint8_t unit = uint8_t(b[p + 11]);
                const uint32_t x = be16(b + p + 12);
                return unit == 1 ? acceptDpi(x) : unit == 2 ? acceptDpi(x * 2.54) : std::nullopt;
            }
            if (marker == 0xDA) return std::nullopt;
            p += 2 + len;
        }
    }
    return std::nullopt;
}

int exifOrientation(const QByteArray& bytes) {
    const char* b = bytes.constData();
    const qint64 n = bytes.size();
    if (n >= 4 && uint8_t(b[0]) == 0xFF && uint8_t(b[1]) == 0xD8) {
        for (qint64 p = 2; p + 4 <= n && uint8_t(b[p]) == 0xFF;) {
            const uint8_t marker = uint8_t(b[p + 1]);
            const qint64 len = be16(b + p + 2);
            if (marker == 0xE1 && len >= 8 && p + 2 + len <= n && std::memcmp(b + p + 4, "Exif\0\0", 6) == 0) return tiffOrientation(b + p + 10, len - 8);
            if (marker == 0xDA || len < 2) return 1;
            p += 2 + len;
        }
        return 1;
    }
    if (n >= 8 && uint8_t(b[0]) == 0x89 && b[1] == 'P') {
        for (qint64 p = 8; p + 12 <= n;) {
            const qint64 len = be32(b + p);
            if (std::memcmp(b + p + 4, "eXIf", 4) == 0 && p + 8 + len <= n) return tiffOrientation(b + p + 8, len);
            p += 12 + len;
        }
        return 1;
    }
    if (n >= 12 && std::memcmp(b, "RIFF", 4) == 0 && std::memcmp(b + 8, "WEBP", 4) == 0) {
        for (qint64 p = 12; p + 8 <= n;) {
            const qint64 len = le32(b + p + 4);
            if (std::memcmp(b + p, "EXIF", 4) == 0 && p + 8 + len <= n) {
                const char* d = b + p + 8;
                const bool prefix = len >= 6 && std::memcmp(d, "Exif\0\0", 6) == 0;
                return prefix ? tiffOrientation(d + 6, len - 6) : tiffOrientation(d, len);
            }
            p += 8 + len + (len & 1);
        }
    }
    return 1;
}

Raster rasterFromImage(const QImage& image, int maxSide) {
    return finish(grayOfImage(image), image.width(), image.height(), maxSide);
}

DecodedImage decodeImage(const QByteArray& bytes, int maxSide) {
    QByteArray copy = bytes;
    QBuffer buffer(&copy);
    buffer.open(QIODevice::ReadOnly);
    QImageReader reader(&buffer);
    reader.setDecideFormatFromContent(true);
    reader.setAutoTransform(false);     // wir drehen selbst, auch für PNG und WebP
    reader.setAllocationLimit(ALLOCATION_LIMIT_MB);
    const QSize size = reader.size();
    if (size.isValid() && qint64(size.width()) * size.height() > MAX_PIXELS)
        throw ImportError(QStringLiteral("Das Bild ist mit %1 × %2 Pixeln zu groß. Bitte verkleinert speichern.").arg(size.width()).arg(size.height()));
    const int frames = std::max(1, reader.imageCount());
    QImage image;
    if (!reader.read(&image) || image.isNull() || image.width() <= 0 || image.height() <= 0)
        throw ImportError(QStringLiteral("Dieses Bildformat lässt sich nicht lesen. Bitte als PNG oder JPG speichern."));
    int w = image.width(), h = image.height();
    Gray gray = grayOfImage(image);
    image = QImage();
    const int o = exifOrientation(bytes);
    if (o > 1) {
        int ow = 0, oh = 0;
        gray = orientGray(gray, w, h, o, ow, oh);
        w = ow;
        h = oh;
    }
    DecodedImage out;
    out.originalWidth = w;
    out.originalHeight = h;
    out.frames = frames;
    out.raster = finish(std::move(gray), w, h, maxSide);
    return out;
}

PdfPage renderPdf(const QByteArray& bytes) {
    const QString cannot = QStringLiteral("Das PDF lässt sich nicht lesen (verschlüsselt oder beschädigt). Als Bild oder SVG exportieren.");
    if (!QImageReader::supportedImageFormats().contains("pdf"))
        throw ImportError(QStringLiteral("PDF wird in dieser Installation nicht gelesen. Bitte als SVG, DXF oder Bild speichern."));
    QByteArray copy = bytes;
    QBuffer buffer(&copy);
    buffer.open(QIODevice::ReadOnly);
    QImageReader reader(&buffer, "pdf");
    reader.setAllocationLimit(ALLOCATION_LIMIT_MB);
    const QSize points = reader.size();
    if (!points.isValid() || points.isEmpty()) throw ImportError(cannot);
    PdfPage out;
    out.widthMm = points.width() * 25.4 / 72;
    out.heightMm = points.height() * 25.4 / 72;
    out.pages = std::max(1, reader.imageCount());
    const double pxPerMm = std::min(10.0, MAX_RASTER_SIDE / std::max(out.widthMm, out.heightMm));
    reader.setScaledSize(QSize(std::max(1, int(std::lround(out.widthMm * pxPerMm))), std::max(1, int(std::lround(out.heightMm * pxPerMm)))));
    QImage image;
    if (!reader.read(&image) || image.isNull()) throw ImportError(cannot);
    // Durchsichtiger Seitenhintergrund zählt wie weißes Papier.
    out.raster = rasterFromImage(image);
    return out;
}

}  // namespace lumacut::import
