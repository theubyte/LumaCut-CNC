#include "core/create.h"
#include "core/contour.h"
#include "core/extras.h"
#include "core/geometry.h"
#include "core/tools.h"

#include <algorithm>
#include <cmath>
#include <numbers>

namespace lumacut {
namespace {

constexpr double kPi = std::numbers::pi;

Poly fitBox(PolyView poly, double w, double h) {
    Poly out(poly.begin(), poly.end());
    const auto b = boundsOf(poly);
    if (!b) return out;
    for (Pt& p : out) p = {(p.x - b->minX) / std::max(b->width(), 1e-9) * w, (p.y - b->minY) / std::max(b->height(), 1e-9) * h};
    return out;
}
PolySet moved(const PolySet& l, double dx, double dy) {
    PolySet out = l;
    for (Pt& p : out.allPoints()) p = {p.x + dx, p.y + dy};
    return out;
}
Poly movedPoly(PolyView l, double dx, double dy) {
    Poly out(l.begin(), l.end());
    for (Pt& p : out) p = {p.x + dx, p.y + dy};
    return out;
}
Poly circle(double cx, double cy, double d) { return movedPoly(Shapes::ellipse(d, d), cx - d / 2, cy - d / 2); }
PolySet single(const Poly& p) { PolySet s; s.add(p); return s; }

}  // namespace

Poly makeShape(ShapeKind kind, double w, double h) {
    switch (kind) {
        case ShapeKind::Star: return fitBox(ShapeLib::star(5, w, h), w, h);
        case ShapeKind::Heart: return fitBox(ShapeLib::heart(w, h), w, h);
        case ShapeKind::Arrow: {
            const Poly p{{0, h * .3}, {w * .6, h * .3}, {w * .6, 0}, {w, h / 2}, {w * .6, h}, {w * .6, h * .7}, {0, h * .7}, {0, h * .3}};
            return fitBox(p, w, h);
        }
        case ShapeKind::Cross: {
            const double a = w / 3, b = h / 3;
            const Poly p{{a, 0}, {2 * a, 0}, {2 * a, b}, {w, b}, {w, 2 * b}, {2 * a, 2 * b}, {2 * a, h}, {a, h}, {a, 2 * b}, {0, 2 * b}, {0, b}, {a, b}, {a, 0}};
            return fitBox(p, w, h);
        }
        case ShapeKind::Bubble: {
            const Poly body = Shapes::rect(w, h * .78, std::min(w, h * .78) * .25);
            const Poly tail{{w * .18, h * .7}, {w * .12, h}, {w * .42, h * .7}, {w * .18, h * .7}};
            const PolySet res = Booleans::apply({single(body), single(tail)}, RasterBooleanOp::Union);
            std::optional<PolyView> best;
            double bestA = -HUGE_VAL;
            for (PolyView q : res) {
                const Box b = *boundsOf(q);
                const double a = b.width() * b.height();
                if (a > bestA) { bestA = a; best = q; }
            }
            return fitBox(best ? *best : PolyView(body), w, h);
        }
        case ShapeKind::Drop: {
            Poly out;
            out.reserve(121);
            for (int k = 0; k <= 120; ++k) {
                const double t = 2 * kPi * k / 120;
                out.push_back({w / 2 + w / 2 * std::sin(t) * std::sin(t / 2), h - h * (1 + std::cos(t)) / 2});
            }
            return fitBox(out, w, h);
        }
    }
    return {};
}

namespace Curves {
Poly catmullRom(PolyView points, bool closed, int steps) {
    if (points.size() < 3) {
        Poly out(points.begin(), points.end());
        if (closed && points.size() >= 2) out.push_back(points.front());
        return out;
    }
    Poly p;
    if (closed) p.assign(points.begin(), points.end());
    else {
        p.push_back(points.front());
        p.insert(p.end(), points.begin(), points.end());
        p.push_back(points.back());
    }
    const size_t n = p.size(), spans = closed ? n : n - 3;
    Poly out;
    out.reserve(spans * size_t(steps) + 1);
    for (size_t i = 0; i < spans; ++i) {
        const Pt p0 = closed ? p[(i + n - 1) % n] : p[i];
        const Pt p1 = closed ? p[i] : p[i + 1];
        const Pt p2 = closed ? p[(i + 1) % n] : p[i + 2];
        const Pt p3 = closed ? p[(i + 2) % n] : p[i + 3];
        for (int s = 0; s < steps; ++s) {
            const double t = double(s) / steps, t2 = t * t, t3 = t2 * t;
            const auto c = [&](double a, double b, double cc, double d) {
                return 0.5 * (2 * b + (-a + cc) * t + (2 * a - 5 * b + 4 * cc - d) * t2 + (-a + 3 * b - 3 * cc + d) * t3);
            };
            out.push_back({c(p0.x, p1.x, p2.x, p3.x), c(p0.y, p1.y, p2.y, p3.y)});
        }
    }
    out.push_back(closed ? out.front() : points.back());
    return out;
}
}  // namespace Curves

Parts normalizeParts(const Parts& q) {
    PolySet all = q.engrave;
    all.append(q.cut);
    all.append(q.marks);
    const auto b = boundsOf(all);
    if (!b) return q;
    Parts out;
    out.engrave = moved(q.engrave, -b->minX, -b->minY);
    out.cut = moved(q.cut, -b->minX, -b->minY);
    out.marks = moved(q.marks, -b->minX, -b->minY);
    for (const auto& [v, s] : q.labels) out.labels.push_back({Pt{v.x - b->minX, v.y - b->minY}, s});
    return out;
}

KotlinRandom::KotlinRandom(int seed) {
    const int32_t s1 = seed, s2 = s1 >> 31;
    x = uint32_t(s1);
    y = uint32_t(s2);
    v = ~uint32_t(s1);
    addend = (uint32_t(s1) << 10) ^ (uint32_t(s2) >> 4);
    for (int i = 0; i < 64; ++i) nextInt();
}
int KotlinRandom::nextInt() {
    uint32_t t = x;
    t = t ^ (t >> 2);
    x = y;
    y = z;
    z = w;
    const uint32_t v0 = v;
    w = v0;
    t = (t ^ (t << 1)) ^ v0 ^ (v0 << 4);
    v = t;
    addend += 362437u;
    return int(t + addend);
}
bool KotlinRandom::nextBoolean() { return (uint32_t(nextInt()) >> 31) != 0; }

namespace Personalize {
PolySet fitHeight(const PolySet& paths, double h) {
    const auto b = boundsOf(paths);
    if (!b) return paths;
    const double k = h / std::max(b->height(), 1e-9);
    PolySet out = paths;
    for (Pt& v : out.allPoints()) v = {b->minX + (v.x - b->minX) * k, b->minY + (v.y - b->minY) * k};
    return out;
}
Parts tag(const PolySet& text, TagStyle style, std::optional<double> holeMm) {
    const auto tb = boundsOf(text);
    if (!tb) return {};
    const std::optional<double> hole = holeMm && *holeMm > 0 ? holeMm : std::nullopt;
    const Pt c = tb->center();
    const double tw = tb->width(), th = tb->height();
    Parts r;
    r.engrave = text;
    switch (style) {
        case TagStyle::Keychain: {
            const double m = std::max(3.0, th * 0.3);
            PolySet outline = Contour::fromPolys(text, m, 8, true);
            PolySet cut;
            if (hole) {
                const double ring = *hole + 6, cx = tb->minX - m - ring / 2 + 2, cy = c.y;
                outline = Booleans::apply({outline, single(circle(cx, cy, ring))}, RasterBooleanOp::Union);
                cut.add(circle(cx, cy, *hole));
            }
            r.cut = outline;
            r.cut.append(cut);
            break;
        }
        case TagStyle::Plate: {
            const double pad = std::max(4.0, th * 0.4), extra = hole ? *hole + 4 : 0;
            const double w = tw + 2 * pad + extra, h = th + 2 * pad, x0 = tb->minX - pad - extra, y0 = tb->minY - pad;
            r.cut.add(movedPoly(Shapes::rect(w, h, std::min(w, h) * 0.25), x0, y0));
            if (hole) r.cut.add(circle(x0 + pad / 2 + *hole / 2 + 1, c.y, *hole));
            break;
        }
        case TagStyle::Heart: {
            const double w = std::max(tw * 1.55, th * 3), h = w * 0.9, x0 = c.x - w / 2, y0 = c.y - h * 0.42;
            r.cut.add(movedPoly(ShapeLib::heart(w, h), x0, y0));
            if (hole) r.cut.add(circle(x0 + w * 0.27, y0 + h * 0.2, *hole));
            break;
        }
        case TagStyle::Round: {
            const double d = std::max(tw + 2 * std::max(5.0, th * 0.5), th * 3) + (hole ? *hole * 2 : 0);
            r.cut.add(circle(c.x, c.y, d));
            if (hole) r.cut.add(circle(c.x, c.y - d / 2 + *hole, *hole));
            break;
        }
    }
    return normalizeParts(r);
}
Parts emblem(const PolySet& initials, const std::optional<PolySet>& top, const std::optional<PolySet>& bottom, double diameter) {
    const double r = diameter / 2;
    const Pt c{r, r};
    const bool arcs = top.has_value() || bottom.has_value();
    const PolySet mid = fitHeight(initials, diameter * (arcs ? 0.28 : 0.42));
    Parts out;
    if (const auto mb = boundsOf(mid)) {
        const double k = std::min(1.0, (arcs ? diameter * 0.55 : diameter * 0.7) / mb->width());
        const Pt mc = mb->center();
        PolySet e = mid;
        for (Pt& v : e.allPoints()) v = {c.x + (v.x - mc.x) * k, c.y + (v.y - mc.y) * k};
        out.engrave.append(e);
    }
    const double band = diameter * 0.09;
    const auto arc = [&](const std::optional<PolySet>& text, bool upper) {
        if (!text) return;
        const PolySet t = fitHeight(*text, band);
        const auto b = boundsOf(t);
        if (!b) return;
        const double r0 = upper ? diameter * 0.335 : diameter * 0.425, maxLen = kPi * r0 * 0.85, bw = b->width();
        PolySet flat = t;
        if (bw > maxLen)
            for (Pt& v : flat.allPoints()) v = {b->minX + (v.x - b->minX) * maxLen / bw, b->maxY - (b->maxY - v.y) * maxLen / bw};
        const PolySet bent = ArcText::bend(flat, upper ? r0 : -r0);
        out.engrave.append(upper ? moved(bent, c.x, c.y - r0) : moved(bent, c.x, c.y + r0));
    };
    arc(top, true);
    arc(bottom, false);
    out.cut.add(circle(c.x, c.y, diameter));
    out.marks.add(circle(c.x, c.y, diameter - 6));
    if (arcs) out.marks.add(circle(c.x, c.y, diameter * 0.62));
    return out;
}
PolySet frame(const Box& box, FrameStyle style, double marginMm) {
    const double x = box.minX - marginMm, y = box.minY - marginMm, w = box.width() + 2 * marginMm, h = box.height() + 2 * marginMm;
    const auto rect = [&](double dx, double r) { return movedPoly(Shapes::rect(w + 2 * dx, h + 2 * dx, r), x - dx, y - dx); };
    PolySet out;
    switch (style) {
        case FrameStyle::Simple: out.add(rect(0, 0)); break;
        case FrameStyle::Rounded: out.add(rect(0, std::min(w, h) * 0.12)); break;
        case FrameStyle::Double: out.add(rect(0, 0)); out.add(rect(2.5, 0)); break;
        case FrameStyle::Oval: {
            const double ew = box.width() * 1.4142 + 2 * marginMm, eh = box.height() * 1.4142 + 2 * marginMm;
            const Pt c = box.center();
            out.add(movedPoly(Shapes::ellipse(ew, eh), c.x - ew / 2, c.y - eh / 2));
            break;
        }
        case FrameStyle::Dashed: return dashes(rect(0, 0), 4, 2.5);
    }
    return out;
}
PolySet dashes(PolyView poly, double dash, double gap) {
    PolySet out;
    Poly cur{poly[0]};
    bool on = true;
    double left = dash;
    for (size_t i = 1; i < poly.size(); ++i) {
        const Pt a = poly[i - 1], b = poly[i];
        const double total = dist(a, b);
        Pt from = a;
        double segLeft = total;
        while (segLeft > 1e-9) {
            const double step = std::min(segLeft, left), k = step / total;
            const Pt to{from.x + (b.x - a.x) * k, from.y + (b.y - a.y) * k};
            if (on) cur.push_back(to);
            from = to;
            segLeft -= step;
            left -= step;
            if (left <= 1e-9) {
                if (on && cur.size() > 1) out.add(cur);
                on = !on;
                left = on ? dash : gap;
                cur.assign(1, from);
            }
        }
    }
    if (on && cur.size() > 1) out.add(cur);
    return out;
}
Parts ruler(int lengthMm, double widthMm, std::optional<double> holeMm) {
    const double x0 = 5, w = lengthMm + 2 * x0 + (holeMm ? *holeMm + 4 : 0);
    Parts out;
    out.cut.add(Shapes::rect(w, widthMm, 2));
    if (holeMm) out.cut.add(circle(w - x0 / 2 - *holeMm / 2 - 1, widthMm / 2, *holeMm));
    for (int i = 0; i <= lengthMm; ++i) {
        const double len = i % 10 == 0 ? widthMm * 0.42 : i % 5 == 0 ? widthMm * 0.3 : widthMm * 0.18;
        out.marks.add({Pt{x0 + i, 0}, Pt{x0 + i, len}});
        if (i % 10 == 0) out.labels.push_back({Pt{x0 + i, widthMm * 0.42 + 1.5}, QString::number(i / 10)});
    }
    return out;
}
PolySet puzzle(double w, double h, int cols, int rows, int seed) {
    KotlinRandom rnd(seed);
    static constexpr double profile[][2] = {{0, 0}, {0.34, 0}, {0.40, 0.02}, {0.38, 0.10}, {0.35, 0.18}, {0.40, 0.25}, {0.50, 0.27}, {0.60, 0.25}, {0.65, 0.18}, {0.62, 0.10}, {0.60, 0.02}, {0.66, 0}, {1, 0}};
    const double cw = w / cols, ch = h / rows, knob = std::min(cw, ch);
    const auto edge = [&](Pt a, Pt b) {
        const double sign = rnd.nextBoolean() ? 1 : -1, dx = b.x - a.x, dy = b.y - a.y, nx = -dy / dist(a, b), ny = dx / dist(a, b);
        Poly pts;
        for (const auto& q : profile) pts.push_back({a.x + dx * q[0] + nx * q[1] * knob * sign, a.y + dy * q[0] + ny * q[1] * knob * sign});
        return Curves::catmullRom(pts, false, 8);
    };
    PolySet out;
    out.add(Shapes::rect(w, h));
    for (int i = 1; i < cols; ++i) {
        Poly line;
        for (int j = 0; j < rows; ++j) {
            const Poly e = edge({i * cw, j * ch}, {i * cw, (j + 1) * ch});
            line.insert(line.end(), e.begin() + (line.empty() ? 0 : 1), e.end());
        }
        out.add(line);
    }
    for (int j = 1; j < rows; ++j) {
        Poly line;
        for (int i = 0; i < cols; ++i) {
            const Poly e = edge({i * cw, j * ch}, {(i + 1) * cw, j * ch});
            line.insert(line.end(), e.begin() + (line.empty() ? 0 : 1), e.end());
        }
        out.add(line);
    }
    return out;
}
}  // namespace Personalize

}  // namespace lumacut
