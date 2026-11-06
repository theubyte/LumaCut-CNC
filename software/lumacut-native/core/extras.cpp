#include "core/extras.h"
#include "core/geometry.h"

#include <algorithm>
#include <cmath>
#include <numbers>
#include <stdexcept>

namespace lumacut {
namespace {
Poly stretch(const Poly& raw, double w, double h) {
    const Box b = *boundsOf(PolyView(raw));
    const double bw = b.width(), bh = b.height();
    Poly out(raw.size());
    for (size_t i = 0; i < raw.size(); ++i) out[i] = {(raw[i].x - b.minX) / bw * w, (raw[i].y - b.minY) / bh * h};
    return out;
}
}  // namespace

namespace ArcText {
PolySet bend(const PolySet& paths, double radiusMm) {
    if (!(std::fabs(radiusMm) >= 1)) throw std::invalid_argument("Radius mindestens 1 mm");
    const auto box = boundsOf(paths);
    if (!box) return paths;
    const double r0 = std::fabs(radiusMm), cx = (box->minX + box->maxX) / 2, base = box->maxY;
    PolySet out = paths;
    for (Pt& p : out.allPoints()) {
        const double theta = (p.x - cx) / r0, above = base - p.y;
        if (radiusMm > 0) {
            const double r = r0 + above;
            p = {r * std::sin(theta), r0 - r * std::cos(theta)};
        } else {
            const double r = std::max(0.01, r0 - above);
            p = {r * std::sin(theta), r * std::cos(theta) - r0};
        }
    }
    return out;
}
}  // namespace ArcText

namespace Arrange {
std::vector<Pt> gridOffsets(const Box& piece, int nx, int ny, double gapX, double gapY) {
    if (!(nx >= 1 && nx <= 50 && ny >= 1 && ny <= 50)) throw std::invalid_argument("Höchstens 50 Stück je Richtung");
    std::vector<Pt> out;
    const double w = piece.width(), h = piece.height();
    for (int j = 0; j < ny; ++j)
        for (int i = 0; i < nx; ++i) {
            if (i == 0 && j == 0) continue;
            out.push_back({i * (w + gapX), j * (h + gapY)});
        }
    return out;
}
std::vector<Pt> inside(const Box& piece, const std::vector<Pt>& offsets) {
    std::vector<Pt> out;
    for (const Pt o : offsets)
        if (Work::contains(Box{piece.minX + o.x, piece.minY + o.y, piece.maxX + o.x, piece.maxY + o.y})) out.push_back(o);
    return out;
}
}  // namespace Arrange

namespace ShapeLib {
Poly heart(double w, double h) {
    const int n = 120;
    Poly raw;
    raw.reserve(n + 1);
    for (int k = 0; k <= n; ++k) {
        const double t = 2 * std::numbers::pi * k / n, s = std::sin(t);
        raw.push_back({16 * (s * s * s), -(13 * std::cos(t) - 5 * std::cos(2 * t) - 2 * std::cos(3 * t) - std::cos(4 * t))});
    }
    return stretch(raw, w, h);
}
Poly star(int points, double w, double h, double innerRatio) {
    const int n = std::clamp(points, 3, 24);
    const double inner = std::min(0.9, std::max(0.1, innerRatio));
    Poly raw;
    raw.reserve(size_t(2 * n) + 1);
    for (int k = 0; k <= 2 * n; ++k) {
        const double a = -std::numbers::pi / 2 + std::numbers::pi * k / n, r = k % 2 == 0 ? 1 : inner;
        raw.push_back({r * std::cos(a), r * std::sin(a)});
    }
    return stretch(raw, w, h);
}
PolySet pendant(double w, double h, double holeDiameter) {
    PolySet out;
    out.add(Shapes::rect(w, h, std::min(w, h) * 0.25));
    Poly hole = Shapes::ellipse(holeDiameter, holeDiameter);
    for (Pt& p : hole) p = {p.x + (w - holeDiameter) / 2, p.y + holeDiameter * 0.8};
    out.add(hole);
    return out;
}
}  // namespace ShapeLib

}  // namespace lumacut
