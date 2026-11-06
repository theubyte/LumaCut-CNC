#include "core/geometry.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <numbers>
#include <set>
#include <stdexcept>

namespace lumacut {
namespace {

constexpr double kDegToRad = 0.017453292519943295;

/** Ab dieser Pfadzahl lohnt das Raster gegenüber der linearen Suche. */
constexpr size_t kGridFrom = 2000;

/**
 * Lineare Suche wie Kotlin: kleinste Entfernung, bei Gleichstand der erste Pfad, dort der Anfang vor dem Ende.
 * Quadrat zuerst: hypot nur für Kandidaten, die wirklich näher sein können.
 */
std::vector<PathOrder> orderLinear(const PolySet& paths, const std::vector<uint32_t>& ids, Pt start) {
    size_t n = ids.size();
    std::vector<double> fx(n), fy(n), lx(n), ly(n);
    std::vector<uint8_t> closed(n);
    std::vector<uint32_t> idx(ids);
    for (size_t i = 0; i < n; ++i) {
        const PolyView p = paths[ids[i]];
        fx[i] = p.front().x; fy[i] = p.front().y; lx[i] = p.back().x; ly[i] = p.back().y;
        closed[i] = isClosed(p) ? 1 : 0;
    }
    std::vector<PathOrder> out;
    out.reserve(n);
    double atX = start.x, atY = start.y;
    while (n > 0) {
        size_t best = 0;
        double bestDist = std::numeric_limits<double>::max(), bestSq = std::numeric_limits<double>::infinity();
        bool reverse = false;
        for (size_t i = 0; i < n; ++i) {
            double dx = atX - fx[i], dy = atY - fy[i], sq = dx * dx + dy * dy;
            if (sq <= bestSq) {
                const double d = hypotJ(dx, dy);
                if (d < bestDist) { bestDist = d; best = i; reverse = false; bestSq = d * d * 1.000000001; }
            }
            if (!closed[i]) {
                dx = atX - lx[i]; dy = atY - ly[i]; sq = dx * dx + dy * dy;
                if (sq <= bestSq) {
                    const double d = hypotJ(dx, dy);
                    if (d < bestDist) { bestDist = d; best = i; reverse = true; bestSq = d * d * 1.000000001; }
                }
            }
        }
        out.push_back({idx[best], reverse});
        atX = reverse ? fx[best] : lx[best];
        atY = reverse ? fy[best] : ly[best];
        const auto cut = [&](auto& v) { std::move(v.begin() + std::ptrdiff_t(best) + 1, v.begin() + std::ptrdiff_t(n), v.begin() + std::ptrdiff_t(best)); };
        cut(fx); cut(fy); cut(lx); cut(ly); cut(closed); cut(idx);
        --n;
    }
    return out;
}

/**
 * Gleiches Ergebnis wie orderLinear, aber über ein Raster der Pfad-Enden: gewählt wird das kleinste (Entfernung,
 * Position, Umdrehen), und das Raster schließt nur aus, was sicher weiter weg liegt. Damit bleiben auch
 * Gleichstände wie in Kotlin (tests/test_core.cpp vergleicht beide).
 */
std::vector<PathOrder> orderGrid(const PolySet& paths, const std::vector<uint32_t>& ids, Pt start) {
    struct End { double x, y; uint32_t pos; bool reverse; };
    const size_t n = ids.size();
    double minX = HUGE_VAL, minY = HUGE_VAL, maxX = -HUGE_VAL, maxY = -HUGE_VAL;
    std::vector<End> ends;
    ends.reserve(n * 2);
    for (size_t i = 0; i < n; ++i) {
        const PolyView p = paths[ids[i]];
        ends.push_back({p.front().x, p.front().y, uint32_t(i), false});
        if (!isClosed(p)) ends.push_back({p.back().x, p.back().y, uint32_t(i), true});
    }
    for (const End& e : ends) {
        minX = std::min(minX, e.x); maxX = std::max(maxX, e.x);
        minY = std::min(minY, e.y); maxY = std::max(maxY, e.y);
    }
    const double spanX = std::max(maxX - minX, 1e-9), spanY = std::max(maxY - minY, 1e-9);
    const double cell = std::max(std::sqrt(spanX * spanY / double(ends.size())), std::max(spanX, spanY) / 4096);
    const int cols = int(spanX / cell) + 1, rows = int(spanY / cell) + 1;
    const auto cellX = [&](double x) { return std::clamp(int((x - minX) / cell), 0, cols - 1); };
    const auto cellY = [&](double y) { return std::clamp(int((y - minY) / cell), 0, rows - 1); };
    std::vector<std::vector<End>> grid(size_t(cols) * rows);
    for (const End& e : ends) grid[size_t(cellY(e.y)) * cols + cellX(e.x)].push_back(e);
    std::vector<uint8_t> used(n, 0);
    std::vector<PathOrder> out;
    out.reserve(n);
    double atX = start.x, atY = start.y;
    for (size_t left = n; left > 0; --left) {
        const int cx = cellX(atX), cy = cellY(atY);
        double bestD = std::numeric_limits<double>::max();
        uint32_t bestPos = 0;
        bool bestRev = false, found = false;
        double bestEndX = 0, bestEndY = 0;
        const auto scan = [&](int gx, int gy) {
            std::vector<End>& c = grid[size_t(gy) * cols + gx];
            for (size_t k = 0; k < c.size();) {
                const End& e = c[k];
                if (used[e.pos]) { c[k] = c.back(); c.pop_back(); continue; }
                const double d = hypotJ(atX - e.x, atY - e.y);
                if (!found || d < bestD || (d == bestD && (e.pos < bestPos || (e.pos == bestPos && !e.reverse && bestRev)))) {
                    found = true; bestD = d; bestPos = e.pos; bestRev = e.reverse;
                }
                ++k;
            }
        };
        const int maxR = std::max({cx, cols - 1 - cx, cy, rows - 1 - cy});
        for (int r = 0; r <= maxR; ++r) {
            if (found && (r - 1) * cell > bestD * 1.000000001) break;
            if (r == 0) { scan(cx, cy); continue; }
            const int x0 = cx - r, x1 = cx + r, y0 = cy - r, y1 = cy + r;
            for (int x = std::max(x0, 0); x <= std::min(x1, cols - 1); ++x) {
                if (y0 >= 0) scan(x, y0);
                if (y1 < rows) scan(x, y1);
            }
            for (int y = std::max(y0 + 1, 0); y <= std::min(y1 - 1, rows - 1); ++y) {
                if (x0 >= 0) scan(x0, y);
                if (x1 < cols) scan(x1, y);
            }
        }
        used[bestPos] = 1;
        out.push_back({ids[bestPos], bestRev});
        const PolyView p = paths[ids[bestPos]];
        const Pt e = bestRev ? p.front() : p.back();
        bestEndX = e.x; bestEndY = e.y;
        atX = bestEndX; atY = bestEndY;
    }
    return out;
}

std::vector<PathOrder> orderSubset(const PolySet& paths, const std::vector<uint32_t>& ids, Pt start) {
    return ids.size() >= kGridFrom ? orderGrid(paths, ids, start) : orderLinear(paths, ids, start);
}

bool insidePoly(PolyView poly, Pt pt) {
    bool c = false;
    for (size_t i = 1; i < poly.size(); ++i) {
        const Pt a = poly[i - 1], b = poly[i];
        if ((a.y > pt.y) != (b.y > pt.y) && pt.x < (b.x - a.x) * (pt.y - a.y) / (b.y - a.y) + a.x) c = !c;
    }
    return c;
}

}  // namespace

PolySet hatch(const PolySet& polys, double spacing) {
    if (!(spacing > 0.01)) throw std::invalid_argument("Zeilenabstand zu klein");
    std::vector<uint32_t> usable;
    for (size_t i = 0; i < polys.size(); ++i) if (polys[i].size() >= 3) usable.push_back(uint32_t(i));
    PolySet result;
    if (usable.empty()) return result;
    Box box{HUGE_VAL, HUGE_VAL, -HUGE_VAL, -HUGE_VAL};
    for (uint32_t i : usable) box = box.united(*boundsOf(polys[i]));
    std::vector<double> ys;
    for (double y = box.minY + spacing / 2; y <= box.maxY; y += spacing) ys.push_back(y);
    std::vector<std::vector<double>> rows(ys.size());
    const auto edge = [&](Pt a, Pt b) {
        if (a.y == b.y) return;
        const double lo = a.y < b.y ? a.y : b.y, hi = a.y < b.y ? b.y : a.y;
        // Zeilen mit lo <= y < hi: genau die Bedingung (a.y <= y && b.y > y) || (b.y <= y && a.y > y).
        size_t i = size_t(std::lower_bound(ys.begin(), ys.end(), lo) - ys.begin());
        for (; i < ys.size() && ys[i] < hi; ++i) rows[i].push_back(a.x + (ys[i] - a.y) * (b.x - a.x) / (b.y - a.y));
    };
    for (uint32_t k : usable) {
        const PolyView poly = polys[k];
        for (size_t i = 1; i < poly.size(); ++i) edge(poly[i - 1], poly[i]);
        if (!isClosed(poly)) edge(poly.back(), poly.front());
    }
    for (size_t row = 0; row < ys.size(); ++row) {
        std::vector<double>& xs = rows[row];
        if (xs.size() < 2) continue;
        std::sort(xs.begin(), xs.end());
        const double y = ys[row];
        const auto addSeg = [&](size_t k, bool forward) {
            if (forward) result.add({Pt{xs[k], y}, Pt{xs[k + 1], y}});
            else result.add({Pt{xs[k + 1], y}, Pt{xs[k], y}});
        };
        if (row % 2 == 0) {
            for (size_t k = 0; k + 1 < xs.size(); k += 2)
                if (xs[k + 1] - xs[k] > 1e-6) addSeg(k, true);
        } else {
            for (size_t k = (xs.size() / 2) * 2; k >= 2; k -= 2)
                if (xs[k - 1] - xs[k - 2] > 1e-6) addSeg(k - 2, false);
        }
    }
    return result;
}

std::vector<PathOrder> orderPathsIndexed(const PolySet& paths, Pt start) {
    std::vector<uint32_t> ids;
    ids.reserve(paths.size());
    for (size_t i = 0; i < paths.size(); ++i) if (paths[i].size() >= 2) ids.push_back(uint32_t(i));
    return orderSubset(paths, ids, start);
}

std::vector<PathOrder> orderForCuttingIndexed(const PolySet& paths, Pt start) {
    std::vector<uint32_t> ids;
    ids.reserve(paths.size());
    for (size_t i = 0; i < paths.size(); ++i) if (paths[i].size() >= 2) ids.push_back(uint32_t(i));
    if (ids.size() < 2 || ids.size() > 1500) return orderSubset(paths, ids, start);
    const size_t n = ids.size();
    std::vector<uint8_t> closed(n);
    std::vector<Box> boxes(n);
    std::vector<double> area(n);
    std::vector<uint32_t> byArea(n);
    for (size_t i = 0; i < n; ++i) {
        const PolyView q = paths[ids[i]];
        closed[i] = q.size() >= 4 && isClosed(q);
        boxes[i] = *boundsOf(q);
        area[i] = boxes[i].width() * boxes[i].height();
        byArea[i] = uint32_t(i);
    }
    std::vector<int> height(n, 0);
    std::stable_sort(byArea.begin(), byArea.end(), [&](uint32_t a, uint32_t b) { return area[a] < area[b]; });
    for (const uint32_t i : byArea) {
        if (!closed[i]) continue;
        int h = 0;
        const PolyView outer = paths[ids[i]];
        for (size_t j = 0; j < n; ++j) {
            if (j == i || area[j] >= area[i]) continue;
            if (!boxes[i].contains({boxes[j].minX, boxes[j].minY}) || !boxes[i].contains({boxes[j].maxX, boxes[j].maxY})) continue;
            if (insidePoly(outer, paths[ids[j]].front())) h = std::max(h, height[j] + 1);
        }
        height[i] = h;
    }
    std::vector<PathOrder> out;
    out.reserve(n);
    Pt at = start;
    const std::set<int> levels(height.begin(), height.end());
    for (const int level : levels) {
        std::vector<uint32_t> tierIds;
        for (size_t i = 0; i < n; ++i) if (height[i] == level) tierIds.push_back(ids[i]);
        const std::vector<PathOrder> tier = orderSubset(paths, tierIds, at);
        if (!tier.empty()) {
            const PolyView last = paths[tier.back().index];
            at = tier.back().reversed ? last.front() : last.back();
        }
        out.insert(out.end(), tier.begin(), tier.end());
    }
    return out;
}

PolySet applyOrder(const PolySet& paths, const std::vector<PathOrder>& order) {
    PolySet out;
    size_t total = 0;
    for (const PathOrder& o : order) total += paths[o.index].size();
    out.reserve(order.size(), total);
    for (const PathOrder& o : order) {
        const PolyView p = paths[o.index];
        const std::span<Pt> d = out.addUninitialized(p.size());
        if (o.reversed) std::reverse_copy(p.begin(), p.end(), d.begin());
        else std::copy(p.begin(), p.end(), d.begin());
    }
    return out;
}
PolySet orderPaths(const PolySet& paths, Pt start) { return applyOrder(paths, orderPathsIndexed(paths, start)); }
PolySet orderForCutting(const PolySet& paths, Pt start) { return applyOrder(paths, orderForCuttingIndexed(paths, start)); }

Poly simplify(PolyView points, double tolerance) {
    if (points.size() < 3) return Poly(points.begin(), points.end());
    std::vector<uint8_t> keep(points.size(), 0);
    keep.front() = keep.back() = 1;
    std::vector<std::pair<uint32_t, uint32_t>> stack{{0u, uint32_t(points.size() - 1)}};
    while (!stack.empty()) {
        const auto [a, b] = stack.back();
        stack.pop_back();
        double maxD = 0;
        int64_t idx = -1;
        const Pt pa = points[a], pb = points[b];
        const double len = dist(pa, pb);
        for (uint32_t i = a + 1; i < b; ++i) {
            const Pt p = points[i];
            const double d = len < 1e-12 ? dist(p, pa) : std::fabs((pb.x - pa.x) * (pa.y - p.y) - (pa.x - p.x) * (pb.y - pa.y)) / len;
            if (d > maxD) { maxD = d; idx = i; }
        }
        if (idx >= 0 && maxD > tolerance) {
            keep[size_t(idx)] = 1;
            stack.push_back({a, uint32_t(idx)});
            stack.push_back({uint32_t(idx), b});
        }
    }
    Poly out;
    for (size_t i = 0; i < points.size(); ++i) if (keep[i]) out.push_back(points[i]);
    return out;
}

namespace Shapes {
Poly rect(double w, double h, double radius) {
    if (radius <= 0) return {{0, 0}, {w, 0}, {w, h}, {0, h}, {0, 0}};
    const double r = std::min(radius, std::min(w, h) / 2);
    Poly out;
    out.reserve(37);
    const auto arc = [&](double cx, double cy, double from) {
        for (int k = 0; k <= 8; ++k) {
            const double a = (from + 90.0 * k / 8) * kDegToRad;
            out.push_back({cx + r * std::cos(a), cy + r * std::sin(a)});
        }
    };
    arc(w - r, r, 270.0); arc(w - r, h - r, 0.0); arc(r, h - r, 90.0); arc(r, r, 180.0);
    out.push_back(out.front());
    return out;
}
Poly ellipse(double w, double h, double segmentMm) {
    const double pi = std::numbers::pi;
    const double rx = w / 2, ry = h / 2;
    const int n = std::max(24, int(pi * (rx + ry) / segmentMm));
    Poly out(size_t(n) + 1);
    for (int k = 0; k <= n; ++k) {
        const double a = 2 * pi * k / n;
        out[size_t(k)] = {rx + rx * std::cos(a), ry + ry * std::sin(a)};
    }
    return out;
}
Poly polygon(int sides, double w, double h) {
    const double pi = std::numbers::pi;
    const int n = std::clamp(sides, 3, 64);
    Poly out(size_t(n) + 1);
    for (int k = 0; k <= n; ++k) {
        const double a = -pi / 2 + 2 * pi * k / n;
        out[size_t(k)] = {w / 2 + w / 2 * std::cos(a), h / 2 + h / 2 * std::sin(a)};
    }
    return out;
}
}  // namespace Shapes

}  // namespace lumacut
