#include "core/pcb/gerber.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <memory>
#include <numbers>
#include <string>
#include <variant>

namespace lumacut::pcb {
namespace {

constexpr double kTol = 0.002;
constexpr double kPi = std::numbers::pi;
inline double rad(double deg) { return deg * kPi / 180; }

Poly rotatePts(Poly poly, double deg) {
    if (deg == 0) return poly;
    const double c = std::cos(rad(deg)), s = std::sin(rad(deg));
    for (Pt& p : poly) p = {p.x * c - p.y * s, p.x * s + p.y * c};
    return poly;
}
Poly rectPoly(double cx, double cy, double w, double h) {
    return {{cx - w / 2, cy - h / 2}, {cx + w / 2, cy - h / 2}, {cx + w / 2, cy + h / 2}, {cx - w / 2, cy + h / 2}};
}
Poly holePoly(double d) {
    Poly c = circle(0, 0, d / 2, kTol);
    std::reverse(c.begin(), c.end());
    return c;
}
Poly obround(double w, double h) {
    if (std::abs(w - h) < 1e-9) return circle(0, 0, w / 2, kTol);
    const double r = std::min(w, h) / 2;
    const int n = std::max(6, int(std::ceil(circle(0, 0, r, kTol).size() / 2.0)));
    Poly out;
    const auto arc = [&](double cx, double cy, double a0) {
        for (int i = 0; i <= n; ++i) {
            const double a = a0 + double(i) / n * kPi;
            out.push_back({cx + r * std::cos(a), cy + r * std::sin(a)});
        }
    };
    if (w > h) { arc(w / 2 - r, 0, -kPi / 2); arc(-w / 2 + r, 0, kPi / 2); }
    else { arc(0, h / 2 - r, 0); arc(0, -h / 2 + r, kPi); }
    return out;
}
Polys scaled(Polys polys, double unit) {
    for (Poly& p : polys) for (Pt& q : p) { q.x *= unit; q.y *= unit; }
    return polys;
}
double toNum(std::string_view s) { return std::strtod(std::string(s).c_str(), nullptr); }
bool allDigits(std::string_view s) { return !s.empty() && std::all_of(s.begin(), s.end(), [](char c) { return std::isdigit(uchar(c)); }); }
std::vector<std::string_view> split(std::string_view s, char sep) {
    std::vector<std::string_view> out;
    size_t a = 0;
    for (;;) {
        const size_t b = s.find(sep, a);
        out.push_back(s.substr(a, b == std::string_view::npos ? std::string_view::npos : b - a));
        if (b == std::string_view::npos) return out;
        a = b + 1;
    }
}
std::string noSpace(std::string_view s) {
    std::string out;
    out.reserve(s.size());
    for (char c : s) if (!std::isspace(uchar(c))) out.push_back(c);
    return out;
}
/** Leading float like JavaScript parseFloat: "1.5X" gives 1.5, nothing gives 0. */
double leadNum(std::string_view s) {
    const std::string t(s);
    return std::strtod(t.c_str(), nullptr);
}

// ---- Aperture macros ----

struct MacroAssign { int var; std::string expr; };
struct MacroPrim { int prim; std::vector<std::string> args; };
struct Macro {
    std::string name;
    std::vector<std::variant<MacroAssign, MacroPrim>> lines;
};

Macro parseMacro(const std::vector<std::string>& blocks) {
    Macro m;
    m.name = blocks[0].substr(2);
    for (size_t k = 1; k < blocks.size(); ++k) {
        const std::string& b = blocks[k];
        if (b.empty()) continue;
        if (b[0] == '$') {
            const size_t eq = b.find('=');
            if (eq != std::string::npos && allDigits(std::string_view(b).substr(1, eq - 1))) {
                m.lines.push_back(MacroAssign{std::atoi(b.c_str() + 1), b.substr(eq + 1)});
                continue;
            }
        }
        const auto parts = split(b, ',');
        if (!allDigits(parts[0])) continue;
        const int prim = std::atoi(std::string(parts[0]).c_str());
        if (prim == 0) continue;   // comment
        MacroPrim p{prim, {}};
        for (size_t i = 1; i < parts.size(); ++i) p.args.emplace_back(parts[i]);
        m.lines.push_back(std::move(p));
    }
    return m;
}

using WarnFn = std::function<void(const QString&)>;

Polys expandMacro(const Macro& m, const std::vector<double>& params, double unit, const WarnFn& warn) {
    std::map<int, double> vars;
    for (size_t i = 0; i < params.size(); ++i) vars[int(i) + 1] = params[i];
    const auto sc = [unit](Poly p) { for (Pt& q : p) { q.x *= unit; q.y *= unit; } return p; };
    Polys acc;
    for (const auto& line : m.lines) {
        if (const auto* as = std::get_if<MacroAssign>(&line)) { vars[as->var] = evalMacroExpr(as->expr, vars); continue; }
        const auto& pl = std::get<MacroPrim>(line);
        std::vector<double> a;
        for (const std::string& e : pl.args) a.push_back(e.empty() ? 0 : evalMacroExpr(e, vars));
        const auto arg = [&](size_t i, double def = 0) { return i < a.size() ? a[i] : def; };
        Polys shape;
        bool on = true;
        switch (pl.prim) {
        case 1:   // circle: exposure, diameter, x, y, rotation
            on = arg(0) != 0;
            shape = {sc(rotatePts(circle(arg(2), arg(3), arg(1) / 2, kTol / unit), arg(4)))};
            break;
        case 2: case 20: {   // vector line: exposure, width, x0, y0, x1, y1, rotation
            on = arg(0) != 0;
            const double dx = arg(4) - arg(2), dy = arg(5) - arg(3);
            double len = std::hypot(dx, dy);
            if (len == 0) len = 1e-9;
            const double nx = -dy / len * arg(1) / 2, ny = dx / len * arg(1) / 2;
            Poly pts{{arg(2) + nx, arg(3) + ny}, {arg(2) - nx, arg(3) - ny}, {arg(4) - nx, arg(5) - ny}, {arg(4) + nx, arg(5) + ny}};
            shape = cleanEvenOdd({sc(rotatePts(pts, arg(6)))});
            break;
        }
        case 21:   // centre rectangle: exposure, w, h, cx, cy, rotation
            on = arg(0) != 0;
            shape = {sc(rotatePts(rectPoly(arg(3), arg(4), arg(1), arg(2)), arg(5)))};
            break;
        case 22:   // lower-left rectangle: exposure, w, h, x, y, rotation
            on = arg(0) != 0;
            shape = {sc(rotatePts(rectPoly(arg(3) + arg(1) / 2, arg(4) + arg(2) / 2, arg(1), arg(2)), arg(5)))};
            break;
        case 4: {   // outline: exposure, n, x0, y0, ... xn, yn, rotation
            on = arg(0) != 0;
            const int n = int(std::lround(arg(1)));
            Poly pts;
            for (int i = 0; i <= n; ++i) pts.push_back({arg(2 + 2 * i), arg(3 + 2 * i)});
            shape = cleanEvenOdd({sc(rotatePts(pts, arg(4 + 2 * n)))});
            break;
        }
        case 5: {   // regular polygon: exposure, corners, x, y, diameter, rotation
            on = arg(0) != 0;
            const int n = std::max(3, int(std::lround(arg(1))));
            const double r = arg(4) / 2;
            Poly pts;
            for (int i = 0; i < n; ++i) { const double t = 2 * kPi * i / n; pts.push_back({arg(2) + r * std::cos(t), arg(3) + r * std::sin(t)}); }
            shape = cleanEvenOdd({sc(rotatePts(pts, arg(5)))});
            break;
        }
        case 6: {   // moire: x, y, outer d, ring thickness, gap, max rings, cross thickness, cross length, rotation
            const double cx = arg(0), cy = arg(1), th = arg(3), gap = arg(4), ct = arg(6), cl = arg(7), rot = arg(8);
            Polys rings;
            double d = arg(2);
            for (int i = 0; i < arg(5) && d > 0; ++i) {
                Polys inner;
                if (d - 2 * th > 0) inner.push_back(circle(cx, cy, d / 2 - th, kTol / unit));
                rings = addPolys(rings, subtractPolys({circle(cx, cy, d / 2, kTol / unit)}, inner));
                d -= 2 * (th + gap);
            }
            const Polys cross = unionPolys({rectPoly(cx, cy, cl, ct), rectPoly(cx, cy, ct, cl)});
            for (Poly& p : addPolys(rings, cross)) shape.push_back(sc(rotatePts(p, rot)));
            break;
        }
        case 7: {   // thermal: x, y, outer d, inner d, gap, rotation
            const double cx = arg(0), cy = arg(1), od = arg(2), id = arg(3), gap = arg(4), rot = arg(5);
            const Polys ring = subtractPolys({circle(cx, cy, od / 2, kTol / unit)}, {circle(cx, cy, id / 2, kTol / unit)});
            const Polys bars = unionPolys({rectPoly(cx, cy, od + 1, gap), rectPoly(cx, cy, gap, od + 1)});
            for (Poly& p : subtractPolys(ring, bars)) shape.push_back(sc(rotatePts(p, rot)));
            break;
        }
        default:
            warn(QStringLiteral("Makro %1: Grundform %2 ist unbekannt und fehlt im Bild.").arg(QString::fromStdString(m.name)).arg(pl.prim));
            continue;
        }
        acc = on ? addPolys(acc, shape) : subtractPolys(acc, shape);
    }
    return acc;
}

// ---- Apertures ----

enum class ApKind { C, R, O, P, M };
struct Aperture {
    ApKind kind = ApKind::M;
    Polys polys;
    double d = 0, w = 0, h = 0;
};

Aperture makeAperture(const std::string& tpl, const std::vector<double>& params, double unit,
                      const std::map<std::string, Macro>& macros, const WarnFn& warn) {
    std::vector<double> u;
    for (double p : params) u.push_back(p * unit);
    const auto at = [&](size_t i) { return i < u.size() ? u[i] : 0.0; };
    const auto withHole = [](Poly outer, double d) { Polys r{std::move(outer)}; if (d > 0) r.push_back(holePoly(d)); return r; };
    if (auto it = macros.find(tpl); it != macros.end()) return {ApKind::M, expandMacro(it->second, params, unit, warn)};
    Aperture a;
    if (tpl == "C") { a.kind = ApKind::C; a.d = at(0); a.polys = withHole(circle(0, 0, at(0) / 2, kTol), at(1)); return a; }
    if (tpl == "R") { a.kind = ApKind::R; a.w = at(0); a.h = at(1); a.polys = withHole(rectPoly(0, 0, at(0), at(1)), at(2)); return a; }
    if (tpl == "O") { a.kind = ApKind::O; a.w = at(0); a.h = at(1); a.polys = withHole(obround(at(0), at(1)), at(2)); return a; }
    if (tpl == "P") {
        const int n = std::max(3, int(std::lround(params.size() > 1 ? params[1] : 3)));
        const double rot = params.size() > 2 ? params[2] : 0, r = at(0) / 2;
        Poly pts;
        for (int i = 0; i < n; ++i) { const double t = 2 * kPi * i / n + rad(rot); pts.push_back({r * std::cos(t), r * std::sin(t)}); }
        a.kind = ApKind::P; a.d = at(0); a.polys = withHole(pts, at(3));
        return a;
    }
    warn(QStringLiteral("Blende mit unbekanntem Makro %1: fehlt im Bild.").arg(QString::fromStdString(tpl)));
    return a;
}

double sweep(double a0, double a1, bool cw, bool full) {
    if (full) return cw ? -2 * kPi : 2 * kPi;
    double s = a1 - a0;
    if (cw) { while (s > 0) s -= 2 * kPi; while (s <= -2 * kPi) s += 2 * kPi; }
    else { while (s < 0) s += 2 * kPi; while (s >= 2 * kPi) s -= 2 * kPi; }
    return s;
}

Poly convexHull(std::vector<Pt> pts) {
    std::sort(pts.begin(), pts.end(), [](const Pt& a, const Pt& b) { return a.x < b.x || (a.x == b.x && a.y < b.y); });
    const auto cross = [](const Pt& o, const Pt& a, const Pt& b) { return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x); };
    Poly lo, up;
    for (const Pt& p : pts) { while (lo.size() >= 2 && cross(lo[lo.size() - 2], lo.back(), p) <= 0) lo.pop_back(); lo.push_back(p); }
    for (auto it = pts.rbegin(); it != pts.rend(); ++it) { while (up.size() >= 2 && cross(up[up.size() - 2], up.back(), *it) <= 0) up.pop_back(); up.push_back(*it); }
    lo.pop_back(); up.pop_back();
    lo.insert(lo.end(), up.begin(), up.end());
    return lo;
}

struct Format { int xi = 2, xd = 4, yi = 2, yd = 4; bool trailing = false; };
struct Op { bool dark; Polys polys; };

bool isComment(std::string_view b) {
    size_t i = 0;
    while (i < b.size() && std::isspace(uchar(b[i]))) ++i;
    if (i >= b.size() || b[i] != 'G') return false;
    ++i;
    if (i < b.size() && b[i] == '0') ++i;
    if (i >= b.size() || b[i] != '4') return false;
    ++i;
    return i >= b.size() || !std::isdigit(uchar(b[i]));
}

}  // namespace

double evalMacroExpr(std::string_view src, const std::map<int, double>& vars) {
    const std::string s = noSpace(src);
    size_t i = 0;
    const auto fail = [&]() -> double { throw GerberError("Makro-Ausdruck: " + std::string(src)); };
    std::function<double()> sum;
    std::function<double()> num = [&]() -> double {
        if (i >= s.size()) return fail();
        const char c = s[i];
        if (c == '-') { ++i; return -num(); }
        if (c == '+') { ++i; return num(); }
        if (c == '(') { ++i; const double v = sum(); if (i < s.size() && s[i] == ')') ++i; return v; }
        if (c == '$') {
            size_t j = i + 1;
            while (j < s.size() && std::isdigit(uchar(s[j]))) ++j;
            if (j == i + 1) return fail();
            const int k = std::atoi(s.c_str() + i + 1);
            i = j;
            auto it = vars.find(k);
            return it == vars.end() ? 0.0 : it->second;
        }
        size_t j = i;
        bool digits = false;
        while (j < s.size() && std::isdigit(uchar(s[j]))) { ++j; digits = true; }
        if (j < s.size() && s[j] == '.') { ++j; while (j < s.size() && std::isdigit(uchar(s[j]))) { ++j; digits = true; } }
        if (!digits) return fail();
        const double v = toNum(std::string_view(s).substr(i, j - i));
        i = j;
        return v;
    };
    const auto prod = [&]() {
        double v = num();
        for (;;) {
            if (i < s.size() && (s[i] == 'x' || s[i] == 'X')) { ++i; v *= num(); }
            else if (i < s.size() && s[i] == '/') { ++i; v /= num(); }
            else return v;
        }
    };
    sum = [&]() {
        double v = prod();
        for (;;) {
            if (i < s.size() && s[i] == '+') { ++i; v += prod(); }
            else if (i < s.size() && s[i] == '-') { ++i; v -= prod(); }
            else return v;
        }
    };
    return sum();
}

GerberResult parseGerber(std::string_view text) {
    GerberResult res;
    const WarnFn warn = [&res](const QString& s) { if (!res.warnings.contains(s)) res.warnings.push_back(s); };
    std::optional<Format> fmt;
    bool fmtWarned = false;
    double unit = 1;
    bool unitSeen = false;
    std::map<std::string, Macro> macros;
    std::map<int, Aperture> apertures;
    const Aperture* cur = nullptr;
    int curCode = 0;
    double x = 0, y = 0;
    int interp = 1;
    int quadrant = 0;   // 0 unset, 1 single (G74), 2 multi (G75)
    int lastD = 0;
    bool inRegion = false;
    Poly contour;
    Polys regionOut;
    bool dark = true;
    std::optional<Poly> chain;
    const Aperture* chainAp = nullptr;
    double offX = 0, offY = 0;
    std::string mirror;
    double rotateDeg = 0, scaleBy = 1;
    bool incremental = false;
    std::vector<Op> ops;
    struct SR { int x, y; double i, j; size_t opStart, flashStart; };
    std::optional<SR> sr;

    const auto push = [&](Polys polys) { if (!polys.empty()) ops.push_back({dark, std::move(polys)}); };

    const auto flushChain = [&]() {
        std::optional<Poly> line = std::move(chain);
        const Aperture* ap = chainAp;
        chain.reset();
        chainAp = nullptr;
        if (!line || !ap) return;
        const double w = (ap->d > 0 ? ap->d : std::min(ap->w, ap->h)) * scaleBy;
        if (dark) {
            res.strokes.push_back({*line, w});
            if (w > 0.001 && (!res.minStrokeWidth || w < *res.minStrokeWidth)) res.minStrokeWidth = w;
        }
        if (ap->kind == ApKind::C || ap->kind == ApKind::P || ap->kind == ApKind::O) {
            if (ap->kind != ApKind::C) warn(QStringLiteral("Linien mit nicht runder Blende sind als runder Stift genähert."));
            if (w > 0) push(strokePolyline(*line, w));
        } else if (ap->kind == ApKind::R) {
            Polys out;
            const double hw = ap->w / 2 * scaleBy, hh = ap->h / 2 * scaleBy;
            for (size_t i = 1; i < line->size(); ++i) {
                const Pt a = (*line)[i - 1], b = (*line)[i];
                out.push_back(convexHull({{a.x - hw, a.y - hh}, {a.x + hw, a.y - hh}, {a.x + hw, a.y + hh}, {a.x - hw, a.y + hh},
                                          {b.x - hw, b.y - hh}, {b.x + hw, b.y - hh}, {b.x + hw, b.y + hh}, {b.x - hw, b.y + hh}}));
            }
            push(unionPolys(out));
        } else {
            warn(QStringLiteral("Linien mit Makro-Blende sind laut Gerber nicht erlaubt und fehlen im Bild."));
        }
    };

    const auto parseCoord = [&](std::string_view raw, bool isX) -> double {
        if (raw.find('.') != std::string_view::npos) return toNum(raw) * unit;
        if (!fmt) {
            fmt = Format{};
            if (!fmtWarned) { warn(QStringLiteral("Koordinaten ohne Formatangabe: als 2.4 gelesen.")); fmtWarned = true; }
        }
        const bool neg = !raw.empty() && raw[0] == '-';
        std::string digits(raw.substr(!raw.empty() && (raw[0] == '-' || raw[0] == '+') ? 1 : 0));
        const int ints = isX ? fmt->xi : fmt->yi, decs = isX ? fmt->xd : fmt->yd;
        if (fmt->trailing && int(digits.size()) < ints + decs) digits.append(size_t(ints + decs) - digits.size(), '0');
        if (digits.empty()) digits = "0";
        const double v = toNum(digits) / std::pow(10.0, decs);
        return (neg ? -v : v) * unit;
    };

    const auto applyObj = [&](const Polys& polys) -> Polys {
        if (mirror.empty() && rotateDeg == 0 && scaleBy == 1) return polys;
        const bool flipX = mirror.find('X') != std::string::npos, flipY = mirror.find('Y') != std::string::npos;
        Polys out;
        for (const Poly& p : polys) {
            Poly q;
            for (const Pt& v : p) q.push_back({(flipX ? -v.x : v.x) * scaleBy, (flipY ? -v.y : v.y) * scaleBy});
            q = rotatePts(std::move(q), rotateDeg);
            if (flipX != flipY) std::reverse(q.begin(), q.end());
            out.push_back(std::move(q));
        }
        return out;
    };

    const auto arcPoints = [&](double sx, double sy, double ex, double ey, double i, double j, bool cw) -> Poly {
        double cx = sx + i, cy = sy + j;
        if (quadrant == 1) {
            // Offsets are unsigned here: the centre is the candidate with a sweep of up to 90 degrees.
            double best = 1e300;
            for (const auto& [a, b] : {std::pair{1, 1}, std::pair{1, -1}, std::pair{-1, 1}, std::pair{-1, -1}}) {
                const double ccx = sx + a * std::abs(i), ccy = sy + b * std::abs(j);
                const double sw = std::abs(sweep(std::atan2(sy - ccy, sx - ccx), std::atan2(ey - ccy, ex - ccx), cw, false));
                const double err = std::abs(std::hypot(sx - ccx, sy - ccy) - std::hypot(ex - ccx, ey - ccy)) + (sw > kPi / 2 + 1e-3 ? 1000 : 0);
                if (err < best) { best = err; cx = ccx; cy = ccy; }
            }
        }
        const double r0 = std::hypot(sx - cx, sy - cy), r1 = std::hypot(ex - cx, ey - cy), r = (r0 + r1) / 2;
        if (r < 1e-9) return {{ex, ey}};
        if (std::abs(r0 - r1) > 0.05)
            warn(QStringLiteral("Bogen bei X%1 Y%2: Mittelpunkt passt nicht zu Anfang und Ende, Form kann abweichen.")
                     .arg(ex, 0, 'f', 2).arg(ey, 0, 'f', 2));
        const bool full = quadrant != 1 && std::hypot(sx - ex, sy - ey) < 1e-6;
        const double a0 = std::atan2(sy - cy, sx - cx);
        const double sw = sweep(a0, std::atan2(ey - cy, ex - cx), cw, full);
        const double stepRad = 2 * std::acos(1 - std::min(kTol, r) / r);
        const int n = std::max(1, int(std::ceil(std::abs(sw) / stepRad)));
        Poly out;
        for (int k = 1; k < n; ++k) {
            const double t = a0 + sw * k / n, rr = r0 + (r1 - r0) * k / n;
            out.push_back({cx + rr * std::cos(t), cy + rr * std::sin(t)});
        }
        out.push_back({ex, ey});
        return out;
    };

    const auto closeContour = [&]() {
        if (contour.size() >= 3) {
            for (Poly& p : cleanEvenOdd({contour})) regionOut.push_back(std::move(p));
            res.regionCount++;
        }
        contour.clear();
    };

    const auto dataBlock = [&](std::string_view b) {
        if (b.empty()) return;
        if (isComment(b)) {
            // X2 attributes may sit in comments: G04 #@! TF.FileFunction,Copper,L1,Top
            static const std::string_view key = "#@!TF.FileFunction,";
            if (const size_t p = b.find(key); p != std::string_view::npos && res.fileFunction.isEmpty())
                res.fileFunction = QString::fromStdString(std::string(b.substr(p + key.size())));
            return;
        }
        std::optional<std::string_view> cx, cy, ci, cj;
        std::optional<int> d;
        size_t k = 0;
        while (k < b.size()) {
            const char letter = b[k];
            if (!std::strchr("GMXYIJD", letter) || letter == 0) { ++k; continue; }
            size_t e = k + 1;
            if (e < b.size() && (b[e] == '+' || b[e] == '-')) ++e;
            const size_t numStart = k + 1;
            while (e < b.size() && (std::isdigit(uchar(b[e])) || b[e] == '.')) ++e;
            const std::string_view v = b.substr(numStart, e - numStart);
            k = e;
            if (v.empty() || v == "+" || v == "-") continue;
            switch (letter) {
            case 'G': {
                const int g = std::atoi(std::string(v).c_str());
                if (g == 1 || g == 2 || g == 3) interp = g;
                else if (g == 36) { flushChain(); inRegion = true; regionOut.clear(); contour.clear(); }
                else if (g == 37) { closeContour(); push(std::move(regionOut)); regionOut.clear(); inRegion = false; }
                else if (g == 74) quadrant = 1;
                else if (g == 75) quadrant = 2;
                else if (g == 70) { unit = 25.4; res.inch = true; unitSeen = true; }
                else if (g == 71) { unit = 1; res.inch = false; unitSeen = true; }
                else if (g == 90) incremental = false;
                else if (g == 91) incremental = true;
                break;
            }
            case 'X': cx = v; break;
            case 'Y': cy = v; break;
            case 'I': ci = v; break;
            case 'J': cj = v; break;
            case 'D': d = std::atoi(std::string(v).c_str()); break;
            default: break;
            }
        }
        if (d && *d >= 10) {
            flushChain();
            curCode = *d;
            auto it = apertures.find(*d);
            cur = it == apertures.end() ? nullptr : &it->second;
            if (!cur) warn(QStringLiteral("Blende D%1 ist nicht definiert: was sie zeichnet, fehlt im Bild.").arg(*d));
            return;
        }
        const bool hasCoord = cx || cy;
        if (!d) {
            if (!hasCoord) return;
            d = lastD ? lastD : 2;
        }
        lastD = *d;
        const double nx = cx ? (incremental ? x : offX) + parseCoord(*cx, true) : x;
        const double ny = cy ? (incremental ? y : offY) + parseCoord(*cy, false) : y;
        const double i = ci ? parseCoord(*ci, true) : 0, j = cj ? parseCoord(*cj, false) : 0;

        if (*d == 2) {
            flushChain();
            if (inRegion) { closeContour(); contour = {{nx, ny}}; }
        } else if (*d == 1) {
            if (interp != 1 && quadrant == 0) warn(QStringLiteral("Bogen ohne G74/G75: als G75 gelesen."));
            const Poly seg = interp == 1 ? Poly{{nx, ny}} : arcPoints(x, y, nx, ny, i, j, interp == 2);
            if (inRegion) {
                if (contour.empty()) contour.push_back({x, y});
                contour.insert(contour.end(), seg.begin(), seg.end());
            } else if (cur) {
                if (!chain || chainAp != cur) { flushChain(); chain = Poly{{x, y}}; chainAp = cur; }
                chain->insert(chain->end(), seg.begin(), seg.end());
            }
        } else if (*d == 3) {
            flushChain();
            if (inRegion) warn(QStringLiteral("D03 innerhalb einer Region ist nicht erlaubt und wurde übergangen."));
            else if (cur) {
                Polys local = applyObj(cur->polys);
                const auto bb = boundsOfPolys(local);
                for (Poly& p : local) for (Pt& q : p) { q.x += nx; q.y += ny; }
                push(std::move(local));
                if (dark && bb) res.flashes.push_back({nx, ny, bb->width(), bb->height(), curCode});
            }
        }
        x = nx;
        y = ny;
    };

    const auto closeStepRepeat = [&]() {
        if (!sr) return;
        flushChain();
        const std::vector<Op> baseOps(ops.begin() + ptrdiff_t(sr->opStart), ops.end());
        const std::vector<GerberFlash> baseFlash(res.flashes.begin() + ptrdiff_t(sr->flashStart), res.flashes.end());
        for (int ix = 0; ix < sr->x; ++ix)
            for (int iy = 0; iy < sr->y; ++iy) {
                if (!ix && !iy) continue;
                const double dx = ix * sr->i, dy = iy * sr->j;
                for (const Op& o : baseOps) {
                    Op c = o;
                    for (Poly& p : c.polys) for (Pt& q : p) { q.x += dx; q.y += dy; }
                    ops.push_back(std::move(c));
                }
                for (GerberFlash f : baseFlash) { f.x += dx; f.y += dy; res.flashes.push_back(f); }
            }
        sr.reset();
    };

    const auto extended = [&](const std::vector<std::string>& blocks) {
        if (blocks.empty()) return;
        if (blocks[0].rfind("AM", 0) == 0) { Macro m = parseMacro(blocks); macros[m.name] = std::move(m); return; }
        for (const std::string& b : blocks) {
            const std::string code = b.substr(0, 2);
            if (code == "FS") {
                // FS [LTD]? [AI]? (N..)? (G..)? X i d Y i d
                size_t p = 2;
                bool trailing = false, inc = false;
                if (p < b.size() && (b[p] == 'L' || b[p] == 'T' || b[p] == 'D')) { trailing = b[p] == 'T'; ++p; }
                if (p < b.size() && (b[p] == 'A' || b[p] == 'I')) { inc = b[p] == 'I'; ++p; }
                const size_t xp = b.find('X', p), yp = b.find('Y', p);
                const auto ok2 = [&](size_t q) { return q != std::string::npos && q + 2 < b.size() && std::isdigit(uchar(b[q + 1])) && std::isdigit(uchar(b[q + 2])); };
                if (!ok2(xp) || !ok2(yp)) {
                    warn(QStringLiteral("Format nicht lesbar: %1").arg(QString::fromStdString(b)));
                    continue;
                }
                fmt = Format{b[xp + 1] - '0', b[xp + 2] - '0', b[yp + 1] - '0', b[yp + 2] - '0', trailing};
                incremental = inc;
            } else if (code == "MO") {
                if (b.rfind("MOIN", 0) == 0) { unit = 25.4; res.inch = true; } else { unit = 1; res.inch = false; }
                unitSeen = true;
            } else if (code == "AD") {
                // ADD<n><template>[,<params>]
                size_t p = 3;
                if (b.size() < 4 || b[2] != 'D') { warn(QStringLiteral("Blende nicht lesbar: %1").arg(QString::fromStdString(b))); continue; }
                while (p < b.size() && std::isdigit(uchar(b[p]))) ++p;
                if (p == 3 || p >= b.size()) { warn(QStringLiteral("Blende nicht lesbar: %1").arg(QString::fromStdString(b))); continue; }
                const int num = std::atoi(b.c_str() + 3);
                const size_t comma = b.find(',', p);
                const std::string tpl = b.substr(p, comma == std::string::npos ? std::string::npos : comma - p);
                std::vector<double> params;
                if (comma != std::string::npos)
                    for (std::string_view s : split(std::string_view(b).substr(comma + 1), 'X'))
                        if (!s.empty()) params.push_back(leadNum(s));
                apertures[num] = makeAperture(tpl, params, unit, macros, warn);
                if (cur && curCode == num) cur = &apertures[num];
            } else if (code == "LP") { flushChain(); dark = b.size() < 3 || b[2] != 'C'; }
            else if (code == "LM") { flushChain(); mirror = b.substr(2) == "N" ? std::string() : b.substr(2); }
            else if (code == "LR") { flushChain(); rotateDeg = leadNum(std::string_view(b).substr(2)); }
            else if (code == "LS") { flushChain(); const double v = leadNum(std::string_view(b).substr(2)); scaleBy = v ? v : 1; }
            else if (code == "SR") {
                closeStepRepeat();
                flushChain();
                const auto field = [&](char c, double def) {
                    const size_t q = b.find(c, 2);
                    return q == std::string::npos ? def : leadNum(std::string_view(b).substr(q + 1));
                };
                const int nx = int(field('X', 1)), ny = int(field('Y', 1));
                if (nx > 1 || ny > 1) sr = SR{std::max(1, nx), std::max(1, ny), field('I', 0) * unit, field('J', 0) * unit, ops.size(), res.flashes.size()};
            } else if (code == "OF") {
                const size_t a = b.find('A'), bb = b.find('B');
                offX = a == std::string::npos ? 0 : leadNum(std::string_view(b).substr(a + 1)) * unit;
                offY = bb == std::string::npos ? 0 : leadNum(std::string_view(b).substr(bb + 1)) * unit;
            } else if (code == "TF") {
                static const std::string key = "TF.FileFunction,";
                if (b.rfind(key, 0) == 0) res.fileFunction = QString::fromStdString(b.substr(key.size()));
            } else if (code == "AB") warn(QStringLiteral("Blockblenden (%AB) werden nicht unterstützt: was sie zeichnen, fehlt im Bild."));
            else if (code == "IP") { if (b != "IPPOS") warn(QStringLiteral("Negatives Gesamtbild (%IPNEG) wird nicht unterstützt: das Bild ist nicht invertiert.")); }
            else if (code == "MI" || code == "SF" || code == "IR") warn(QStringLiteral("Veralteter Befehl %%1 wird nicht unterstützt, Maße können abweichen.").arg(QString::fromStdString(code)));
            // TA, TO, TD, LN, AS, IN: no effect on the image
        }
    };

    // Blocks: extended (%...%) commands stay together, whitespace goes.
    size_t i = 0;
    bool stop = false;
    while (i < text.size() && !stop) {
        if (text[i] == '%') {
            const size_t end = text.find('%', i + 1);
            if (end == std::string_view::npos) break;
            const std::string body = noSpace(text.substr(i + 1, end - i - 1));
            std::vector<std::string> blocks;
            for (std::string_view s : split(body, '*')) if (!s.empty()) blocks.emplace_back(s);
            extended(blocks);
            i = end + 1;
        } else {
            const size_t star = text.find('*', i);
            if (star == std::string_view::npos) break;
            const size_t next = text.find('%', i);
            // A comment may contain a percent sign; only outside comments does it open an extended command.
            if (next != std::string_view::npos && next < star && !isComment(text.substr(i, next - i))) { i = next; continue; }
            const std::string b = noSpace(text.substr(i, star - i));
            i = star + 1;
            if (b == "M02" || b == "M00" || b == "M2") { stop = true; break; }
            dataBlock(b);
        }
    }
    flushChain();
    closeStepRepeat();
    if (inRegion) { closeContour(); push(std::move(regionOut)); warn(QStringLiteral("Region ohne Abschluss G37.")); }
    if (!fmt && !unitSeen && ops.empty()) throw GerberError("Keine Gerber-Daten erkannt.");
    if (!unitSeen) warn(QStringLiteral("Keine Einheit angegeben: als Millimeter gelesen."));

    Polys acc;
    for (size_t k = 0; k < ops.size();) {
        const bool isDark = ops[k].dark;
        Polys batch;
        while (k < ops.size() && ops[k].dark == isDark) { batch.insert(batch.end(), ops[k].polys.begin(), ops[k].polys.end()); ++k; }
        const Polys solid = unionPolys(batch);
        acc = isDark ? addPolys(acc, solid) : subtractPolys(acc, solid);
    }
    res.polys = std::move(acc);
    res.bounds = boundsOfPolys(res.polys);
    res.area = polysArea(res.polys);
    return res;
}

}  // namespace lumacut::pcb
