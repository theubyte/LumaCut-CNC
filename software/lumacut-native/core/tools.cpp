#include "core/tools.h"
#include "core/contour.h"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <stdexcept>

namespace lumacut {

namespace Align {
std::vector<Pt> offsets(const std::vector<Box>& boxes, AlignMode mode, const Box& ref) {
    const Pt rc = ref.center();
    std::vector<Pt> out;
    out.reserve(boxes.size());
    for (const Box& b : boxes) {
        const Pt c = b.center();
        switch (mode) {
            case AlignMode::Left: out.push_back({ref.minX - b.minX, 0}); break;
            case AlignMode::CenterX: out.push_back({rc.x - c.x, 0}); break;
            case AlignMode::Right: out.push_back({ref.maxX - b.maxX, 0}); break;
            case AlignMode::Top: out.push_back({0, ref.minY - b.minY}); break;
            case AlignMode::CenterY: out.push_back({0, rc.y - c.y}); break;
            case AlignMode::Bottom: out.push_back({0, ref.maxY - b.maxY}); break;
        }
    }
    return out;
}
std::vector<Pt> distribute(const std::vector<Box>& boxes, bool horizontal) {
    if (boxes.size() < 3) return std::vector<Pt>(boxes.size());
    const auto lo = [&](const Box& b) { return horizontal ? b.minX : b.minY; };
    const auto size = [&](const Box& b) { return horizontal ? b.width() : b.height(); };
    std::vector<size_t> order(boxes.size());
    std::iota(order.begin(), order.end(), size_t(0));
    std::stable_sort(order.begin(), order.end(), [&](size_t a, size_t b) { return lo(boxes[a]) < lo(boxes[b]); });
    const Box& first = boxes[order[0]];
    double end = -HUGE_VAL, sum = 0;
    for (const size_t i : order) end = std::max(end, lo(boxes[i]) + size(boxes[i]));
    for (const Box& b : boxes) sum += size(b);
    const double gap = (end - lo(first) - sum) / double(boxes.size() - 1);
    std::vector<Pt> out(boxes.size());
    double at = lo(first);
    for (const size_t i : order) {
        const double d = at - lo(boxes[i]);
        out[i] = horizontal ? Pt{d, 0} : Pt{0, d};
        at += size(boxes[i]) + gap;
    }
    return out;
}
}  // namespace Align

namespace Booleans {
PolySet apply(const std::vector<PolySet>& shapes, RasterBooleanOp op, double pxPerMm) {
    std::vector<PolySet> closed;
    for (const PolySet& s : shapes) {
        PolySet c;
        for (PolyView q : s) if (q.size() >= 3) c.add(q);
        if (!c.empty()) closed.push_back(std::move(c));
    }
    PolySet all;
    for (const PolySet& s : closed) all.append(s);
    if (closed.size() < 2) return all;
    const auto box = boundsOf(all);
    if (!box) return {};
    const double bw = box->width(), bh = box->height();
    const double p = std::min(pxPerMm, 3000 / std::max(std::max(bw, bh), 1.0));
    const double m = 2, x0 = box->minX - m, y0 = box->minY - m;
    const int w = int(std::ceil((bw + 2 * m) * p)) + 1, h = int(std::ceil((bh + 2 * m) * p)) + 1;
    std::vector<std::vector<uint8_t>> masks;
    masks.reserve(closed.size());
    for (const PolySet& s : closed) masks.push_back(Contour::rasterize(s, x0, y0, w, h, p));
    std::vector<uint8_t> out(size_t(w) * h, 0);
    for (size_t i = 0; i < out.size(); ++i) {
        if (op == RasterBooleanOp::Union) {
            for (const auto& q : masks) if (q[i]) { out[i] = 1; break; }
        } else if (op == RasterBooleanOp::Subtract) {
            uint8_t v = masks[0][i];
            for (size_t k = 1; v && k < masks.size(); ++k) if (masks[k][i]) v = 0;
            out[i] = v;
        } else {
            uint8_t v = 1;
            for (const auto& q : masks) if (!q[i]) { v = 0; break; }
            out[i] = v;
        }
    }
    return Contour::fromMask(Mask(w, h, std::move(out), p, x0, y0), 0, 0, false, 0.05);
}
}  // namespace Booleans

namespace {
Poly slicePoly(PolyView poly, double from, double to, double len) {
    const auto at = [&](double s0) -> Pt {
        double s = std::fmod(s0, len);
        for (size_t i = 1; i < poly.size(); ++i) {
            const Pt a = poly[i - 1], b = poly[i];
            const double d = dist(a, b);
            if (s <= d && d > 0) return {a.x + (b.x - a.x) * s / d, a.y + (b.y - a.y) * s / d};
            s -= d;
        }
        return poly.back();
    };
    Poly out{at(from)};
    std::vector<double> sv(poly.size());
    double s = 0;
    for (size_t i = 1; i < poly.size(); ++i) { s += dist(poly[i - 1], poly[i]); sv[i] = s; }
    for (int lap = 0; lap <= 1; ++lap)
        for (size_t i = 1; i < poly.size(); ++i) {
            const double t = sv[i] + lap * len;
            if (t > from && t < to) out.push_back(poly[i]);
        }
    out.push_back(at(to));
    return out;
}
}  // namespace

namespace Tabs {
PolySet apply(const PolySet& polys, int count, double widthMm) {
    PolySet out;
    for (PolyView poly : polys) {
        const double len = polyLength(poly);
        if (!isClosed(poly) || count < 1 || widthMm <= 0 || len < count * widthMm * 3) { out.add(poly); continue; }
        const double step = len / count;
        for (int k = 0; k < count; ++k) out.add(slicePoly(poly, (k + 0.5) * step + widthMm / 2, (k + 1.5) * step - widthMm / 2, len));
    }
    return out;
}
}  // namespace Tabs

std::vector<std::optional<Pt>> shelf(const std::vector<Box>& boxes, double w, double h, double gap) {
    constexpr double MARGIN = 1;
    std::vector<std::optional<Pt>> out(boxes.size());
    double x = MARGIN, y = MARGIN, rowH = 0;
    std::vector<size_t> order(boxes.size());
    std::iota(order.begin(), order.end(), size_t(0));
    std::stable_sort(order.begin(), order.end(), [&](size_t a, size_t b) { return boxes[a].height() > boxes[b].height(); });
    const double parkX = Bed::parkX(), parkY = Bed::parkY();
    // Die Park-Ecke sitzt am rechten Ende der oberen Reihen.
    const auto rightEnd = [&](double top) { return top < parkY ? w - parkX : w - MARGIN; };
    for (const size_t i : order) {
        const Box& b = boxes[i];
        const double bw = b.width(), bh = b.height();
        if (bw > w - 2 * MARGIN || bh > h - 2 * MARGIN) continue;
        double px = x, py = y;
        bool newRow = false;
        if (px + bw > rightEnd(py)) {
            px = MARGIN;
            py = y + rowH + gap;
            newRow = true;
            if (px + bw > rightEnd(py)) py = std::max(py, parkY);
        }
        if (py + bh > h - MARGIN) continue;
        out[i] = Pt{px - b.minX, py - b.minY};
        x = px + bw + gap;
        if (newRow) { y = py; rowH = bh; } else rowH = std::max(rowH, bh);
    }
    return out;
}

namespace Nest {
std::vector<std::optional<Placed>> place(const std::vector<Box>& boxes, double w, double h, int maxPlates) {
    if (w <= 0) w = Work::width();
    if (h <= 0) h = Work::height();
    std::vector<std::optional<Placed>> out(boxes.size());
    std::vector<size_t> rest;
    for (size_t i = 0; i < boxes.size(); ++i) if (boxes[i].width() <= w - 2 && boxes[i].height() <= h - 2) rest.push_back(i);
    int plate = 0;
    while (!rest.empty() && plate < maxPlates) {
        std::vector<Box> now;
        now.reserve(rest.size());
        for (const size_t i : rest) now.push_back(boxes[i]);
        const auto packed = shelf(now, w, h);
        std::vector<size_t> next;
        for (size_t k = 0; k < rest.size(); ++k) {
            if (packed[k]) out[rest[k]] = Placed{plate, *packed[k]};
            else next.push_back(rest[k]);
        }
        rest = std::move(next);
        ++plate;
    }
    return out;
}
}  // namespace Nest

namespace BoxMaker {
int segments(double len, double finger) {
    int n = int(std::floor(len / finger));
    if (n % 2 == 0) n -= 1;
    return std::max(1, n);
}
namespace {
Poly panel(double w, double h, double t, double finger, const char* kinds) {
    const Pt corners[4] = {{0, 0}, {w, 0}, {w, h}, {0, h}};
    const Pt dirs[4] = {{1, 0}, {0, 1}, {-1, 0}, {0, -1}};
    const Pt normals[4] = {{0, 1}, {-1, 0}, {0, -1}, {1, 0}};
    const double lengths[4] = {w, h, w, h};
    std::vector<double> offsets[4];
    for (int e = 0; e < 4; ++e) {
        if (kinds[e] == 'F') { offsets[e] = {0.0}; continue; }
        const int n = segments(lengths[e], finger);
        offsets[e].resize(size_t(n));
        for (int i = 0; i < n; ++i) offsets[e][size_t(i)] = ((i % 2 == 0) == (kinds[e] == 'A')) ? 0.0 : t;
    }
    Poly out;
    for (int e = 0; e < 4; ++e) {
        const Pt p = corners[e], u = dirs[e], v = normals[e];
        const std::vector<double>& d = offsets[e];
        const std::vector<double>& prev = offsets[(e + 3) % 4];
        const auto pt = [&](double a, double off) { return Pt{p.x + u.x * a + v.x * off, p.y + u.y * a + v.y * off}; };
        out.push_back(pt(prev.back(), d[0]));
        const double seg = lengths[e] / double(d.size());
        for (size_t k = 1; k < d.size(); ++k) {
            out.push_back(pt(seg * double(k), d[k - 1]));
            out.push_back(pt(seg * double(k), d[k]));
        }
    }
    out.push_back(out.front());
    Poly res;
    res.reserve(out.size());
    for (size_t i = 0; i < out.size(); ++i) if (i == 0 || dist(out[i], out[i - 1]) > 1e-9) res.push_back(out[i]);
    return res;
}
}  // namespace
std::vector<std::pair<QString, Poly>> panels(const BoxSpec& s) {
    if (!(s.t > 0 && s.finger > 0 && std::min(s.w, std::min(s.d, s.h)) > 4 * s.t)) throw std::invalid_argument("Box zu klein für diese Materialstärke");
    const Poly bottom = panel(s.w, s.d, s.t, s.finger, "AAAA");
    const char top = s.closed ? 'B' : 'F';
    const char frontKinds[5] = {top, 'A', 'B', 'A', 0}, sideKinds[5] = {top, 'B', 'B', 'B', 0};
    const Poly front = panel(s.w, s.h, s.t, s.finger, frontKinds);
    const Poly side = panel(s.d, s.h, s.t, s.finger, sideKinds);
    std::vector<std::pair<QString, Poly>> list{{QStringLiteral("Boden"), bottom}, {QStringLiteral("Vorne"), front}, {QStringLiteral("Hinten"), front},
                                               {QStringLiteral("Links"), side}, {QStringLiteral("Rechts"), side}};
    if (s.closed) list.push_back({QStringLiteral("Deckel"), bottom});
    return list;
}
}  // namespace BoxMaker

}  // namespace lumacut
