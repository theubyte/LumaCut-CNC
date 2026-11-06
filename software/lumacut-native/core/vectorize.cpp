#include "core/vectorize.h"
#include "core/contour.h"
#include "core/geometry.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace lumacut {
namespace {

constexpr uint8_t RIGHT = 1, DOWN = 2, LEFT = 4, UP = 8;
inline uint8_t rightOf(uint8_t d) { return d == RIGHT ? DOWN : d == DOWN ? LEFT : d == LEFT ? UP : RIGHT; }
inline uint8_t leftOf(uint8_t d) { return d == RIGHT ? UP : d == UP ? LEFT : d == LEFT ? DOWN : RIGHT; }

/** Geschlossene Schleifen in Pixelkoordinaten, nur Eckpunkte. Das Motiv liegt in Fahrtrichtung rechts: außen positive Fläche, Loch negative. */
std::vector<std::vector<int>> traceLoops(const std::vector<uint8_t>& ink, int w, int h) {
    const size_t vw = size_t(w) + 1;
    std::vector<uint8_t> orig(vw * (size_t(h) + 1), 0);
    const auto at = [&](int x, int y) { return x >= 0 && y >= 0 && x < w && y < h && ink[size_t(y) * w + x] == 1; };
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x) {
            if (!ink[size_t(y) * w + x]) continue;
            if (!at(x, y - 1)) orig[size_t(y) * vw + x] |= RIGHT;
            if (!at(x + 1, y)) orig[size_t(y) * vw + x + 1] |= DOWN;
            if (!at(x, y + 1)) orig[size_t(y + 1) * vw + x + 1] |= LEFT;
            if (!at(x - 1, y)) orig[size_t(y + 1) * vw + x] |= UP;
        }
    std::vector<uint8_t> open = orig;
    std::vector<std::vector<int>> loops;
    for (size_t start = 0; start < open.size(); ++start) {
        while (open[start]) {
            const int sx = int(start % vw), sy = int(start / vw);
            const uint8_t startDir = uint8_t(open[start] & -open[start]);
            std::vector<int> pts;
            int x = sx, y = sy;
            uint8_t dir = startDir, prev = 0;
            for (;;) {
                if (dir != prev) { pts.push_back(x); pts.push_back(y); }
                open[size_t(y) * vw + x] &= uint8_t(~dir);
                if (dir == RIGHT) ++x;
                else if (dir == DOWN) ++y;
                else if (dir == LEFT) --x;
                else --y;
                prev = dir;
                // Am Sattelpunkt rechts abbiegen: Diagonale Pixel bleiben getrennt.
                const uint8_t f = orig[size_t(y) * vw + x], right = rightOf(prev), left = leftOf(prev);
                dir = (f & right) ? right : (f & prev) ? prev : left;
                if (x == sx && y == sy && dir == startDir) break;
            }
            if (pts.size() >= 6) loops.push_back(std::move(pts));
        }
    }
    return loops;
}

/** Douglas-Peucker für geschlossene Ringe: am fernsten Punkt teilen, damit der Startpunkt keine Sonderrolle hat. */
Poly simplifyRing(const Poly& ring, double tol) {
    const size_t n = ring.size();
    if (n < 4) return ring;
    size_t far_ = 0;
    double best = -1;
    for (size_t i = 1; i < n; ++i) {
        const double dx = ring[i].x - ring[0].x, dy = ring[i].y - ring[0].y, d = dx * dx + dy * dy;
        if (d > best) { best = d; far_ = i; }
    }
    const Poly a = simplify(PolyView(ring).subspan(0, far_ + 1), tol);
    Poly tail(ring.begin() + std::ptrdiff_t(far_), ring.end());
    tail.push_back(ring[0]);
    const Poly b = simplify(tail, tol);
    Poly out;
    out.reserve(a.size() + b.size());
    out.insert(out.end(), a.begin(), a.end() - 1);
    out.insert(out.end(), b.begin(), b.end() - 1);
    return out;
}
Poly chaikin(const Poly& ring) {
    Poly out;
    out.reserve(ring.size() * 2);
    for (size_t i = 0; i < ring.size(); ++i) {
        const Pt p = ring[i], q = ring[(i + 1) % ring.size()];
        out.push_back({0.75 * p.x + 0.25 * q.x, 0.75 * p.y + 0.25 * q.y});
        out.push_back({0.25 * p.x + 0.75 * q.x, 0.25 * p.y + 0.75 * q.y});
    }
    return out;
}

}  // namespace

PolySet vectorize(GrayView gray, int w, int h, const VectorizeOptions& o) {
    if (!(w > 0 && h > 0) || qint64(gray.size()) != qint64(w) * h) throw std::invalid_argument("Ungültige Bilddaten");
    std::vector<uint8_t> ink(gray.size());
    for (size_t i = 0; i < ink.size(); ++i) ink[i] = (o.invert ? gray[i] >= o.threshold : gray[i] < o.threshold) ? 1 : 0;
    const double sx = o.widthMm.value_or(w) / w, sy = o.heightMm.value_or(h) / h;
    const double tol = o.toleranceMm.value_or(0.75 * std::min(sx, sy));
    const double minArea = o.minAreaMm2.value_or(4 * sx * sy);
    struct Found { Poly poly; double area; };
    std::vector<Found> found;
    for (const std::vector<int>& loop : traceLoops(ink, w, h)) {
        Poly ring;
        ring.reserve(loop.size() / 2);
        for (size_t i = 0; i < loop.size(); i += 2) ring.push_back({loop[i] * sx, loop[i + 1] * sy});
        Poly s = simplifyRing(ring, tol);
        if (s.size() < 3) s = ring;
        if (o.smooth) s = chaikin(s);
        s.push_back(s.front());
        const double area = polyArea(s);
        if (std::fabs(area) < minArea) continue;
        if (o.outerOnly && area < 0) continue;
        found.push_back({std::move(s), area});
    }
    // Größte zuerst: jede Außenkontur steht vor den Löchern, die in ihr liegen.
    std::stable_sort(found.begin(), found.end(), [](const Found& a, const Found& b) { return std::fabs(a.area) > std::fabs(b.area); });
    PolySet out;
    for (const Found& f : found) out.add(f.poly);
    return out;
}
PolySet vectorizeRaster(const Raster& r, const VectorizeOptions& o) { return vectorize(r.gray(), r.width(), r.height(), o); }

}  // namespace lumacut
