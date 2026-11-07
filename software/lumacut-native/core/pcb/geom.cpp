#include "core/pcb/geom.h"

#include <clipper2/clipper.h>
#include <algorithm>
#include <cmath>
#include <numbers>

namespace lumacut::pcb {
namespace {

using namespace Clipper2Lib;

constexpr double kScale = 1e4;
constexpr double kArcTolMm = 0.002;

inline int64_t toInt(double v) { return int64_t(std::llround(v * kScale)); }

Paths64 toPaths(const Polys& polys, bool closedOnly = true) {
    Paths64 out;
    out.reserve(polys.size());
    for (const Poly& poly : polys) {
        Path64 path;
        path.reserve(poly.size());
        for (const Pt& p : poly) {
            const Point64 q(toInt(p.x), toInt(p.y));
            if (path.empty() || path.back() != q) path.push_back(q);
        }
        if (closedOnly) {
            if (path.size() > 1 && path.front() == path.back()) path.pop_back();
            if (path.size() < 3) continue;
        } else if (path.size() < 2) continue;
        out.push_back(std::move(path));
    }
    return out;
}
Polys fromClosed(const Paths64& paths) {
    Polys out;
    out.reserve(paths.size());
    for (const Path64& p : paths) {
        if (p.size() < 3) continue;
        Poly q;
        q.reserve(p.size() + 1);
        for (const Point64& v : p) q.push_back({double(v.x) / kScale, double(v.y) / kScale});
        q.push_back(q.front());
        out.push_back(std::move(q));
    }
    return out;
}
Polys run(ClipType op, const Polys& subject, const Polys& clip, FillRule fill) {
    Clipper64 c;
    c.AddSubject(toPaths(subject));
    if (!clip.empty()) c.AddClip(toPaths(clip));
    Paths64 sol;
    c.Execute(op, fill, sol);
    return fromClosed(sol);
}

}  // namespace

Polys unionPolys(const Polys& polys) { return polys.empty() ? Polys{} : run(ClipType::Union, polys, {}, FillRule::NonZero); }
Polys cleanEvenOdd(const Polys& polys) { return polys.empty() ? Polys{} : run(ClipType::Union, polys, {}, FillRule::EvenOdd); }
Polys addPolys(const Polys& a, const Polys& b) {
    Polys all = a;
    all.insert(all.end(), b.begin(), b.end());
    return unionPolys(all);
}
Polys subtractPolys(const Polys& a, const Polys& b) {
    if (a.empty()) return {};
    if (b.empty()) return a;
    return run(ClipType::Difference, a, b, FillRule::NonZero);
}
Polys intersectPolys(const Polys& a, const Polys& b) {
    if (a.empty() || b.empty()) return {};
    return run(ClipType::Intersection, a, b, FillRule::NonZero);
}

Polys offsetPolys(const Polys& polys, double deltaMm) {
    if (polys.empty()) return {};
    if (deltaMm == 0) return polys;
    ClipperOffset co(2.0, kArcTolMm * kScale);
    co.AddPaths(toPaths(polys), JoinType::Round, EndType::Polygon);
    Paths64 sol;
    co.Execute(deltaMm * kScale, sol);
    return fromClosed(sol);
}

Polys strokePolyline(const Poly& line, double diameterMm) {
    if (line.empty() || diameterMm <= 0) return {};
    Paths64 in = toPaths({line}, false);
    if (in.empty()) {   // a single point: a dot
        Poly c = circle(line.front().x, line.front().y, diameterMm / 2);
        return {closed(std::move(c))};
    }
    ClipperOffset co(2.0, kArcTolMm * kScale);
    co.AddPaths(in, JoinType::Round, EndType::Round);
    Paths64 sol;
    co.Execute(diameterMm / 2 * kScale, sol);
    return fromClosed(sol);
}

Polys clipLines(const Polys& lines, const Polys& region) {
    if (lines.empty() || region.empty()) return {};
    Clipper64 c;
    c.AddOpenSubject(toPaths(lines, false));
    c.AddClip(toPaths(region));
    Paths64 closedSol, openSol;
    c.Execute(ClipType::Intersection, FillRule::NonZero, closedSol, openSol);
    Polys out;
    out.reserve(openSol.size());
    for (const Path64& p : openSol) {
        if (p.size() < 2) continue;
        Poly q;
        q.reserve(p.size());
        for (const Point64& v : p) q.push_back({double(v.x) / kScale, double(v.y) / kScale});
        out.push_back(std::move(q));
    }
    return out;
}

double ringArea(const Poly& p) {
    double a = 0;
    const size_t n = p.size();
    for (size_t i = 0; i < n; ++i) {
        const Pt& u = p[i];
        const Pt& v = p[(i + 1) % n];
        a += u.x * v.y - v.x * u.y;
    }
    return a / 2;
}
double polysArea(const Polys& polys) {
    double s = 0;
    for (const Poly& p : polys) s += ringArea(p);
    return s;
}
bool pointInPolys(double x, double y, const Polys& polys) {
    bool inside = false;
    for (const Poly& p : polys) {
        const size_t n = p.size();
        for (size_t i = 0, j = n - 1; i < n; j = i++) {
            const Pt& a = p[i];
            const Pt& b = p[j];
            if ((a.y > y) != (b.y > y) && x < a.x + (y - a.y) * (b.x - a.x) / (b.y - a.y)) inside = !inside;
        }
    }
    return inside;
}
Poly circle(double cx, double cy, double r, double tolMm) {
    if (r <= 0) return {};
    const double step = std::acos(1 - std::min(tolMm, r) / r);
    const int n = 4 * std::max(2, std::min(180, int(std::ceil(std::numbers::pi / step / 4))));
    Poly out;
    out.reserve(size_t(n));
    for (int i = 0; i < n; ++i) {
        const double a = double(i) / n * 2 * std::numbers::pi;
        out.push_back({cx + r * std::cos(a), cy + r * std::sin(a)});
    }
    return out;
}
std::optional<Box> boundsOfPolys(const Polys& polys) {
    std::optional<Box> b;
    for (const Poly& p : polys)
        for (const Pt& q : p) {
            if (!b) b = Box{q.x, q.y, q.x, q.y};
            else {
                b->minX = std::min(b->minX, q.x); b->maxX = std::max(b->maxX, q.x);
                b->minY = std::min(b->minY, q.y); b->maxY = std::max(b->maxY, q.y);
            }
        }
    return b;
}

}  // namespace lumacut::pcb
