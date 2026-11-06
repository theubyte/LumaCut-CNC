#include "core/curves.h"

#include <algorithm>
#include <cmath>

namespace lumacut {
namespace {

Pt mid(Pt a, Pt b) { return {(a.x + b.x) / 2, (a.y + b.y) / 2}; }

void cubicInto(Poly& out, Pt a, Pt b, Pt c, Pt d, double tol, int depth = 0) {
    const double ux = 3 * b.x - 2 * a.x - d.x, uy = 3 * b.y - 2 * a.y - d.y;
    const double vx = 3 * c.x - a.x - 2 * d.x, vy = 3 * c.y - a.y - 2 * d.y;
    const double flat = std::max(ux * ux, vx * vx) + std::max(uy * uy, vy * vy);
    if (depth >= 12 || flat <= 16 * tol * tol) { out.push_back(d); return; }
    const Pt ab = mid(a, b), bc = mid(b, c), cd = mid(c, d), abc = mid(ab, bc), bcd = mid(bc, cd), m = mid(abc, bcd);
    cubicInto(out, a, ab, abc, m, tol, depth + 1);
    cubicInto(out, m, bcd, cd, d, tol, depth + 1);
}

CurveNode mapNode(const CurveNode& n, const std::function<Pt(Pt)>& f) {
    const Pt p = f({n.x, n.y});
    CurveNode out;
    out.x = p.x;
    out.y = p.y;
    if (n.hasIn()) { const Pt q = f(n.handleIn()); out.hx1 = q.x; out.hy1 = q.y; }
    if (n.hasOut()) { const Pt q = f(n.handleOut()); out.hx2 = q.x; out.hy2 = q.y; }
    out.smooth = n.smooth;
    return out;
}
CurvePath replaced(const CurvePath& path, size_t i, CurveNode n) {
    CurvePath out = path;
    out.nodes[i] = std::move(n);
    return out;
}
Pt spanPoint(const CurveNode& a, const CurveNode& d, double t) {
    const Pt b = a.handleOut(), c = d.handleIn();
    const double u = 1 - t;
    return {u * u * u * a.x + 3 * u * u * t * b.x + 3 * u * t * t * c.x + t * t * t * d.x,
            u * u * u * a.y + 3 * u * u * t * b.y + 3 * u * t * t * c.y + t * t * t * d.y};
}

}  // namespace

Poly flattenCurve(const CurvePath& path, double tol) {
    const std::vector<CurveNode>& n = path.nodes;
    if (n.empty()) return {};
    Poly out{{n[0].x, n[0].y}};
    const size_t spans = path.closed ? n.size() : n.size() - 1;
    for (size_t i = 0; i < spans; ++i) {
        const CurveNode& a = n[i];
        const CurveNode& d = n[(i + 1) % n.size()];
        if (a.hasOut() || d.hasIn()) cubicInto(out, {a.x, a.y}, a.handleOut(), d.handleIn(), {d.x, d.y}, tol);
        else out.push_back({d.x, d.y});
    }
    return out;
}
PolySet flattenCurves(const std::vector<CurvePath>& paths, double tol) {
    PolySet out;
    for (const CurvePath& p : paths) {
        const Poly f = flattenCurve(p, tol);
        if (f.size() >= 2) out.add(f);
    }
    return out;
}
std::vector<CurvePath> curvesFromPaths(const PolySet& polys) {
    std::vector<CurvePath> out;
    out.reserve(polys.size());
    for (PolyView poly : polys) {
        CurvePath c;
        c.closed = poly.size() > 2 && dist(poly.front(), poly.back()) < 1e-6;
        const size_t n = c.closed ? poly.size() - 1 : poly.size();
        c.nodes.reserve(n);
        for (size_t i = 0; i < n; ++i) { CurveNode k; k.x = poly[i].x; k.y = poly[i].y; c.nodes.push_back(k); }
        out.push_back(std::move(c));
    }
    return out;
}
CurvePath ellipseCurve(double w, double h) {
    const double rx = w / 2, ry = h / 2, kx = rx * HANDLE_K, ky = ry * HANDLE_K;
    const auto node = [](double x, double y, double a, double b, double c, double d) {
        CurveNode n;
        n.x = x; n.y = y; n.hx1 = a; n.hy1 = b; n.hx2 = c; n.hy2 = d; n.smooth = true;
        return n;
    };
    CurvePath p;
    p.closed = true;
    p.nodes = {node(rx, 0, rx - kx, 0, rx + kx, 0), node(w, ry, w, ry - ky, w, ry + ky),
               node(rx, h, rx + kx, h, rx - kx, h), node(0, ry, 0, ry + ky, 0, ry - ky)};
    return p;
}
CurvePath rectCurve(double w, double h) {
    CurvePath p;
    p.closed = true;
    const auto node = [](double x, double y) { CurveNode n; n.x = x; n.y = y; return n; };
    p.nodes = {node(0, 0), node(w, 0), node(w, h), node(0, h)};
    return p;
}
std::vector<CurvePath> mapCurves(const std::vector<CurvePath>& paths, const std::function<Pt(Pt)>& f) {
    std::vector<CurvePath> out = paths;
    for (CurvePath& c : out) for (CurveNode& n : c.nodes) n = mapNode(n, f);
    return out;
}
CurvePath moveNode(const CurvePath& path, size_t i, Pt to) {
    const CurveNode& n = path.nodes[i];
    const double dx = to.x - n.x, dy = to.y - n.y;
    return replaced(path, i, mapNode(n, [&](Pt p) { return Pt{p.x + dx, p.y + dy}; }));
}
CurvePath moveHandle(const CurvePath& path, size_t i, bool outHandle, Pt to) {
    CurveNode n = path.nodes[i];
    if (outHandle) { n.hx2 = to.x; n.hy2 = to.y; } else { n.hx1 = to.x; n.hy1 = to.y; }
    const Pt self{n.x, n.y};
    const Pt other = outHandle ? n.handleIn() : n.handleOut();
    const double otherLen = dist(other, self), len = dist(to, self);
    if (n.smooth && otherLen > 1e-9 && len > 1e-9) {
        const double ox = n.x - (to.x - n.x) / len * otherLen, oy = n.y - (to.y - n.y) / len * otherLen;
        if (outHandle) { n.hx1 = ox; n.hy1 = oy; } else { n.hx2 = ox; n.hy2 = oy; }
    }
    return replaced(path, i, std::move(n));
}
CurvePath toggleSmooth(const CurvePath& path, size_t i) {
    const CurveNode& n = path.nodes[i];
    const size_t N = path.nodes.size();
    if (n.hasIn() || n.hasOut()) { CurveNode c; c.x = n.x; c.y = n.y; return replaced(path, i, c); }
    const CurveNode* prev = path.closed || i > 0 ? &path.nodes[(i + N - 1) % N] : nullptr;
    const CurveNode* next = path.closed || i + 1 < N ? &path.nodes[(i + 1) % N] : nullptr;
    const Pt self{n.x, n.y};
    const Pt from = prev ? Pt{prev->x, prev->y} : self, to = next ? Pt{next->x, next->y} : self;
    const double dx = to.x - from.x, dy = to.y - from.y;
    double l = hypotJ(dx, dy);
    if (l == 0) l = 1;
    const double a = prev ? dist(from, self) / 3 : 0, b = next ? dist(to, self) / 3 : 0;
    CurveNode c;
    c.x = n.x; c.y = n.y;
    c.hx1 = n.x - dx / l * a; c.hy1 = n.y - dy / l * a;
    c.hx2 = n.x + dx / l * b; c.hy2 = n.y + dy / l * b;
    c.smooth = true;
    return replaced(path, i, c);
}
std::optional<CurvePath> deleteNode(const CurvePath& path, size_t i) {
    if (path.nodes.size() <= (path.closed ? 3u : 2u)) return std::nullopt;
    CurvePath out = path;
    out.nodes.erase(out.nodes.begin() + std::ptrdiff_t(i));
    return out;
}
std::optional<CurveHit> nearestOnCurve(const CurvePath& path, Pt p) {
    const std::vector<CurveNode>& n = path.nodes;
    std::optional<CurveHit> best;
    if (n.empty()) return best;
    const size_t spans = path.closed ? n.size() : n.size() - 1;
    for (size_t s = 0; s < spans; ++s) {
        const CurveNode& a = n[s];
        const CurveNode& d = n[(s + 1) % n.size()];
        if (!a.hasOut() && !d.hasIn()) {
            const double dx = d.x - a.x, dy = d.y - a.y, l2 = dx * dx + dy * dy;
            const double t = l2 > 0 ? std::max(0.0, std::min(1.0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2)) : 0;
            const double q = dist(p, {a.x + dx * t, a.y + dy * t});
            if (!best || q < best->dist) best = CurveHit{s, t, q};
        } else {
            for (int k = 0; k <= 32; ++k) {
                const double t = k / 32.0, q = dist(p, spanPoint(a, d, t));
                if (!best || q < best->dist) best = CurveHit{s, t, q};
            }
        }
    }
    return best;
}
CurvePath insertNode(const CurvePath& path, size_t span, double t) {
    CurvePath out = path;
    const std::vector<CurveNode>& n = path.nodes;
    const CurveNode& a = n[span];
    const size_t ib = (span + 1) % n.size();
    const CurveNode& d = n[ib];
    if (!a.hasOut() && !d.hasIn()) {
        CurveNode m;
        m.x = a.x + (d.x - a.x) * t;
        m.y = a.y + (d.y - a.y) * t;
        out.nodes.insert(out.nodes.begin() + std::ptrdiff_t(span) + 1, m);
        return out;
    }
    const auto lerp = [&](Pt p, Pt q) { return Pt{p.x + (q.x - p.x) * t, p.y + (q.y - p.y) * t}; };
    const Pt pa{a.x, a.y}, pd{d.x, d.y}, b = a.handleOut(), c = d.handleIn();
    const Pt ab = lerp(pa, b), bc = lerp(b, c), cd = lerp(c, pd), abc = lerp(ab, bc), bcd = lerp(bc, cd), m = lerp(abc, bcd);
    out.nodes[span].hx2 = ab.x;
    out.nodes[span].hy2 = ab.y;
    out.nodes[ib].hx1 = cd.x;
    out.nodes[ib].hy1 = cd.y;
    CurveNode k;
    k.x = m.x; k.y = m.y; k.hx1 = abc.x; k.hy1 = abc.y; k.hx2 = bcd.x; k.hy2 = bcd.y; k.smooth = true;
    out.nodes.insert(out.nodes.begin() + std::ptrdiff_t(span) + 1, k);
    return out;
}
size_t nodeCount(const std::vector<CurvePath>& paths) {
    size_t n = 0;
    for (const CurvePath& p : paths) n += p.nodes.size();
    return n;
}

}  // namespace lumacut
