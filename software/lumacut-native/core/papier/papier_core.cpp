#include "core/papier/papier_net.h"
#include "core/boolean.h"
#include "core/extras.h"
#include "core/geometry.h"
#include <QHash>
#include <algorithm>
#include <map>
#include <random>
#include <set>

namespace lumacut::Papier {

// ---- Papier und Bögen ----

const std::vector<Stock>& stocks() {
    // Vorschläge, auf dieser Maschine nicht geprüft. Anker: Karton 1 mm schneidet laut Materialliste mit 45 % bei 1200.
    static const std::vector<Stock> list = {
        {QStringLiteral("papier80"), QStringLiteral("Papier 80 g (0,1 mm)"), 0.1, 18, 2500, 8, 4000, 8, 5000, 10, 5000},
        {QStringLiteral("papier120"), QStringLiteral("Papier 120 g (0,15 mm)"), 0.15, 20, 2200, 8, 3800, 8, 5000, 11, 5000},
        {QStringLiteral("karton160"), QStringLiteral("Tonpapier 160 g (0,2 mm)"), 0.2, 24, 2000, 9, 3500, 8, 4500, 12, 4500},
        {QStringLiteral("karton220"), QStringLiteral("Tonkarton 220 g (0,28 mm)"), 0.28, 28, 1800, 10, 3200, 8, 4500, 13, 4500},
        {QStringLiteral("karton300"), QStringLiteral("Fotokarton 300 g (0,38 mm)"), 0.38, 34, 1500, 12, 3000, 9, 4000, 14, 4000},
        {QStringLiteral("graupappe"), QStringLiteral("Graupappe 1 mm"), 1.0, 45, 1200, 16, 2500, 10, 3500, 18, 3500},
        {QStringLiteral("wellpappe"), QStringLiteral("Wellpappe E-Welle 1,5 mm"), 1.5, 55, 900, 18, 2000, 10, 3000, 20, 3000},
    };
    return list;
}
const Stock& stockById(const QString& id) {
    for (const Stock& s : stocks()) if (s.id == id) return s;
    return stocks()[4];
}
const std::vector<Sheet>& sheets() {
    static const std::vector<Sheet> list = {
        {QStringLiteral("a4"), QStringLiteral("A4 hoch (210 × 297)"), 210, 297},
        {QStringLiteral("a4q"), QStringLiteral("A4 quer (297 × 210)"), 297, 210},
        {QStringLiteral("a5"), QStringLiteral("A5 hoch (148 × 210)"), 148, 210},
        {QStringLiteral("a5q"), QStringLiteral("A5 quer (210 × 148)"), 210, 148},
        {QStringLiteral("a6"), QStringLiteral("A6 hoch (105 × 148)"), 105, 148},
        {QStringLiteral("sq30"), QStringLiteral("30 × 30 cm (305 × 305)"), 305, 305},
        {QStringLiteral("letter"), QStringLiteral("Letter (216 × 279)"), 216, 279},
        {QStringLiteral("bett"), QStringLiteral("Ganze Arbeitsfläche"), 0, 0},
    };
    return list;
}
const Sheet& sheetById(const QString& id) {
    for (const Sheet& s : sheets()) if (s.id == id) return s;
    return sheets()[0];
}

// ---- Geometrie ----

Poly movedP(Poly p, double dx, double dy) { for (Pt& q : p) q = {q.x + dx, q.y + dy}; return p; }
Poly rotatedP(Poly p, double ang, Pt c) { for (Pt& q : p) q = prot(q, ang, c); return p; }
Poly closedP(Poly p) {
    if (p.size() > 1 && !(p.front() == p.back())) p.push_back(p.front());
    return p;
}
Poly fitTo(const Poly& p, double x, double y, double w, double h) {
    double x0 = 1e18, y0 = 1e18, x1 = -1e18, y1 = -1e18;
    for (const Pt& q : p) { x0 = std::min(x0, q.x); y0 = std::min(y0, q.y); x1 = std::max(x1, q.x); y1 = std::max(y1, q.y); }
    const double sx = x1 > x0 ? w / (x1 - x0) : 1, sy = y1 > y0 ? h / (y1 - y0) : 1;
    Poly out;
    out.reserve(p.size());
    for (const Pt& q : p) out.push_back({x + (q.x - x0) * sx, y + (q.y - y0) * sy});
    return out;
}
double areaP(const Poly& p) {
    double a = 0;
    for (size_t i = 0; i + 1 < p.size(); ++i) a += p[i].x * p[i + 1].y - p[i + 1].x * p[i].y;
    if (!p.empty() && !(p.front() == p.back())) a += p.back().x * p.front().y - p.front().x * p.back().y;
    return a / 2;
}
bool insideP(Pt q, const Poly& poly) {
    bool in = false;
    const size_t n = poly.size();
    for (size_t i = 0, j = n - 1; i < n; j = i++) {
        const Pt a = poly[i], b = poly[j];
        if ((a.y > q.y) != (b.y > q.y) && q.x < (b.x - a.x) * (q.y - a.y) / (b.y - a.y) + a.x) in = !in;
    }
    return in;
}
Poly circleP(Pt c, double dia) { return movedP(Shapes::ellipse(dia, dia, 0.3), c.x - dia / 2, c.y - dia / 2); }
Poly rectP(double x, double y, double w, double h, double r) { return movedP(Shapes::rect(w, h, r), x, y); }
std::vector<Pt> regular(int n, double side, Pt c) {
    const double r = side / (2 * std::sin(PI / n));
    std::vector<Pt> out;
    for (int k = 0; k < n; ++k) out.push_back(polar(c, r, -PI / 2 - PI / n + k * 2 * PI / n));
    return out;
}
Poly arcP(Pt c, double r, double a0, double a1, double seg) {
    const int n = std::max(6, int(std::ceil(std::abs(a1 - a0) * r / std::max(0.05, seg))));
    Poly out;
    out.reserve(n + 1);
    for (int k = 0; k <= n; ++k) out.push_back(polar(c, r, a0 + (a1 - a0) * k / n));
    return out;
}
Poly bulge(Pt a, Pt b, double sag) {
    const double L = plen(psub(b, a));
    if (std::abs(sag) < 1e-6 || L < 1e-9) return {a, b};
    const double c = L / 2, s = std::abs(sag), R = (c * c + s * s) / (2 * s);
    const Pt m = plerp(a, b, 0.5), nrm = pmul(leftN(a, b), sag > 0 ? 1 : -1);
    const Pt ctr = padd(m, pmul(nrm, s - R));
    const double aa = std::atan2(a.y - ctr.y, a.x - ctr.x), ab = std::atan2(b.y - ctr.y, b.x - ctr.x);
    const Pt apex = padd(m, pmul(nrm, s));
    const double ap = std::atan2(apex.y - ctr.y, apex.x - ctr.x);
    const auto norm = [](double v) { while (v <= -PI) v += 2 * PI; while (v > PI) v -= 2 * PI; return v; };
    double d = norm(ab - aa);
    const double dp = norm(ap - aa);
    // The arc must pass the apex: go the other way round when it does not.
    if (!((d > 0 && dp > 0 && dp < d) || (d < 0 && dp < 0 && dp > d))) d = d > 0 ? d - 2 * PI : d + 2 * PI;
    Poly out = arcP(ctr, R, aa, aa + d, 0.4);
    out.front() = a;
    out.back() = b;
    return out;
}
std::vector<std::pair<Pt, Pt>> outsideOf(Pt a, Pt b, const Poly& poly) {
    std::vector<double> ts{0, 1};
    const size_t n = poly.size();
    for (size_t i = 0; i + 1 < n; ++i) {
        const Pt p = poly[i], q = poly[i + 1];
        const Pt r = psub(b, a), s = psub(q, p);
        const double den = r.x * s.y - r.y * s.x;
        if (std::abs(den) < 1e-12) continue;
        const Pt w = psub(p, a);
        const double t = (w.x * s.y - w.y * s.x) / den, u = (w.x * r.y - w.y * r.x) / den;
        if (t > 0 && t < 1 && u >= 0 && u <= 1) ts.push_back(t);
    }
    std::sort(ts.begin(), ts.end());
    std::vector<std::pair<Pt, Pt>> out;
    for (size_t i = 0; i + 1 < ts.size(); ++i) {
        if (ts[i + 1] - ts[i] < 1e-9) continue;
        const Pt m = plerp(a, b, (ts[i] + ts[i + 1]) / 2);
        if (!insideP(m, poly)) out.push_back({plerp(a, b, ts[i]), plerp(a, b, ts[i + 1])});
    }
    return out;
}
std::vector<Poly> aboveY(const Poly& line, double yMax) {
    std::vector<Poly> out;
    Poly cur;
    for (size_t i = 0; i < line.size(); ++i) {
        const Pt p = line[i];
        const bool in = p.y < yMax;
        if (i > 0) {
            const Pt q = line[i - 1];
            const bool qin = q.y < yMax;
            if (in != qin) {
                const double t = (yMax - q.y) / (p.y - q.y);
                const Pt x = plerp(q, p, t);
                if (qin) { cur.push_back(x); if (cur.size() > 1) out.push_back(cur); cur.clear(); }
                else cur.push_back(x);
            }
        }
        if (in) cur.push_back(p);
    }
    if (cur.size() > 1) out.push_back(cur);
    return out;
}
Poly unionOutline(const std::vector<Poly>& polys) {
    std::vector<PolySet> sets;
    for (const Poly& p : polys) { PolySet s; s.add(closedP(p)); sets.push_back(std::move(s)); }
    const PolySet u = booleanShapes(BooleanOp::Union, sets);
    Poly best;
    double area = -1;
    for (PolyView v : u) {
        Poly p(v.begin(), v.end());
        const double a = std::abs(areaP(p));
        if (a > area) { area = a; best = std::move(p); }
    }
    return best;
}

// ---- Motive ----

QStringList motifIds() {
    return {QStringLiteral("kreis"), QStringLiteral("oval"), QStringLiteral("rechteck"), QStringLiteral("abgerundet"), QStringLiteral("herz"),
            QStringLiteral("stern"), QStringLiteral("stern6"), QStringLiteral("blume"), QStringLiteral("tanne"), QStringLiteral("haus"),
            QStringLiteral("mond"), QStringLiteral("raute"), QStringLiteral("sechseck"), QStringLiteral("tropfen"), QStringLiteral("wolke"),
            QStringLiteral("schmetterling"), QStringLiteral("ei"), QStringLiteral("ballon"), QStringLiteral("krone"), QStringLiteral("flocke"),
            QStringLiteral("bogen")};
}
QString motifLabel(const QString& id) {
    static const QHash<QString, QString> l = {
        {"kreis", "Kreis"}, {"oval", "Oval"}, {"rechteck", "Rechteck"}, {"abgerundet", "Abgerundet"}, {"herz", "Herz"}, {"stern", "Stern"},
        {"stern6", "Stern sechszackig"}, {"blume", "Blume"}, {"tanne", "Tanne"}, {"haus", "Haus"}, {"mond", "Mond"}, {"raute", "Raute"},
        {"sechseck", "Sechseck"}, {"tropfen", "Tropfen"}, {"wolke", "Wolke"}, {"schmetterling", "Schmetterling"}, {"ei", "Ei"},
        {"ballon", "Ballon"}, {"krone", "Krone"}, {"flocke", "Schneeflocke"}, {"bogen", "Rundbogen"}};
    return l.value(id, id);
}
namespace {
Poly normPoly(const std::vector<std::pair<double, double>>& pts) {
    Poly p;
    for (auto [x, y] : pts) p.push_back({x, y});
    return closedP(p);
}
Poly polarCurve(const std::function<double(double)>& r, int n = 360) {
    Poly p;
    for (int k = 0; k < n; ++k) {
        const double a = 2 * PI * k / n;
        p.push_back(polar({}, r(a), a));
    }
    return closedP(p);
}
}  // namespace
Poly motif(const QString& id, double w, double h) {
    Poly raw;
    if (id == QLatin1String("kreis") || id == QLatin1String("oval")) raw = Shapes::ellipse(100, 100, 0.5);
    else if (id == QLatin1String("rechteck")) raw = Shapes::rect(100, 100);
    else if (id == QLatin1String("abgerundet")) raw = Shapes::rect(w, h, std::min(w, h) * 0.2);
    else if (id == QLatin1String("herz")) raw = ShapeLib::heart(100, 100);
    else if (id == QLatin1String("stern")) raw = ShapeLib::star(5, 100, 100, 0.45);
    else if (id == QLatin1String("stern6")) raw = ShapeLib::star(6, 100, 100, 0.55);
    else if (id == QLatin1String("blume")) raw = polarCurve([](double a) { return 0.62 + 0.38 * std::abs(std::cos(2.5 * a)); });
    else if (id == QLatin1String("tanne"))
        raw = normPoly({{0.5, 0}, {0.75, 0.3}, {0.63, 0.3}, {0.87, 0.6}, {0.72, 0.6}, {1, 0.88}, {0.58, 0.88}, {0.58, 1}, {0.42, 1},
                        {0.42, 0.88}, {0, 0.88}, {0.28, 0.6}, {0.13, 0.6}, {0.37, 0.3}, {0.25, 0.3}});
    else if (id == QLatin1String("haus")) raw = normPoly({{0, 0.42}, {0.5, 0}, {1, 0.42}, {1, 1}, {0, 1}});
    else if (id == QLatin1String("raute")) raw = normPoly({{0.5, 0}, {1, 0.5}, {0.5, 1}, {0, 0.5}});
    else if (id == QLatin1String("sechseck")) { const auto v = regular(6, 1, {}); raw = Poly(v.begin(), v.end()); raw = rotatedP(raw, PI / 6); }
    else if (id == QLatin1String("krone")) raw = normPoly({{0, 1}, {0, 0.25}, {0.25, 0.6}, {0.5, 0}, {0.75, 0.6}, {1, 0.25}, {1, 1}});
    else if (id == QLatin1String("tropfen")) {
        for (int k = 0; k < 240; ++k) { const double t = 2 * PI * k / 240; raw.push_back({std::sin(t) * std::pow(std::abs(std::sin(t / 2)), 1.2), -std::cos(t)}); }
    } else if (id == QLatin1String("ei")) {
        for (int k = 0; k < 240; ++k) { const double t = 2 * PI * k / 240; raw.push_back({0.78 * std::cos(t) * (1 + 0.16 * std::sin(t)), std::sin(t)}); }
    } else if (id == QLatin1String("mond")) {
        PolySet a, b;
        a.add(circleP({50, 50}, 100));
        b.add(circleP({68, 40}, 84));
        const PolySet m = booleanOp(BooleanOp::Subtract, a, b);
        double best = -1;
        for (PolyView v : m) { Poly p(v.begin(), v.end()); if (std::abs(areaP(p)) > best) { best = std::abs(areaP(p)); raw = p; } }
    } else if (id == QLatin1String("wolke")) {
        raw = unionOutline({circleP({25, 62}, 46), circleP({50, 42}, 60), circleP({76, 60}, 46), circleP({52, 72}, 46)});
    } else if (id == QLatin1String("ballon")) {
        raw = unionOutline({movedP(Shapes::ellipse(80, 92, 0.5), 10, 0), normPoly({{0.42 * 100, 0.9 * 100}, {0.58 * 100, 0.9 * 100}, {0.62 * 100, 100}, {0.38 * 100, 100}})});
    } else if (id == QLatin1String("schmetterling")) {
        const auto wing = [](double cx, double cy, double ww, double hh, double deg) {
            return rotatedP(movedP(Shapes::ellipse(ww, hh, 0.5), cx - ww / 2, cy - hh / 2), rad(deg), {cx, cy});
        };
        raw = unionOutline({wing(28, 32, 46, 56, -25), wing(72, 32, 46, 56, 25), wing(31, 74, 34, 40, 20), wing(69, 74, 34, 40, -20),
                            movedP(Shapes::ellipse(9, 74, 0.5), 45.5, 16)});
    } else if (id == QLatin1String("flocke")) {
        const PolySet f = snowflake(100, 3, 6, 4);
        double best = -1;
        for (PolyView v : f) { Poly p(v.begin(), v.end()); if (std::abs(areaP(p)) > best) { best = std::abs(areaP(p)); raw = p; } }
    } else if (id == QLatin1String("bogen")) {
        raw = unionOutline({rectP(0, 50, 100, 50), Shapes::ellipse(100, 100, 0.5)});
    } else {
        raw = Shapes::ellipse(100, 100, 0.5);
    }
    if (id == QLatin1String("abgerundet")) return closedP(raw);
    return closedP(fitTo(raw, 0, 0, w, h));
}

// ---- Ränder ----

Edge edgeFromId(const QString& id) {
    if (id == QLatin1String("wellen")) return Edge::Wave;
    if (id == QLatin1String("boegen")) return Edge::Scallop;
    if (id == QLatin1String("zacken")) return Edge::Zigzag;
    if (id == QLatin1String("spitze")) return Edge::Lace;
    return Edge::Straight;
}
EdgeLine decoratedEdge(Pt a, Pt b, Edge e, double size) {
    EdgeLine out;
    const double L = plen(psub(b, a));
    if (e == Edge::Straight || L < 1e-6 || size <= 0) { out.line = {a, b}; return out; }
    const int n = std::max(1, int(std::lround(L / size)));
    const double seg = L / n;
    const Pt u = punit(psub(b, a)), nrm = leftN(a, b);
    out.line.push_back(a);
    for (int k = 0; k < n; ++k) {
        const Pt p0 = padd(a, pmul(u, seg * k)), p1 = padd(a, pmul(u, seg * (k + 1)));
        if (e == Edge::Zigzag) {
            out.line.push_back(padd(plerp(p0, p1, 0.5), pmul(nrm, seg * 0.45)));
        } else if (e == Edge::Wave) {
            for (int j = 1; j < 16; ++j) {
                const double t = j / 16.0;
                out.line.push_back(padd(plerp(p0, p1, t), pmul(nrm, seg * 0.3 * (1 - std::cos(2 * PI * t)) / 2)));
            }
        } else {
            const double sag = seg * (e == Edge::Lace ? 0.45 : 0.38);
            const Poly arc = bulge(p0, p1, sag);
            for (size_t j = 1; j + 1 < arc.size(); ++j) out.line.push_back(arc[j]);
            if (e == Edge::Lace) out.holes.push_back(circleP(padd(plerp(p0, p1, 0.5), pmul(nrm, sag * 0.42)), seg * 0.2));
        }
        out.line.push_back(p1);
    }
    return out;
}

// ---- Schneeflocke ----

PolySet snowflake(double d, int seed, int arms, double minWidth) {
    std::mt19937 rng(uint32_t(seed) * 2654435761u + 17u);
    std::uniform_real_distribution<double> U(0, 1);
    const double R = d / 2, wSpine = std::max(minWidth, R * 0.09);
    std::vector<Poly> arm;
    const auto bar = [&](Pt a, Pt b, double w) {
        const Pt nn = pmul(leftN(a, b), w / 2), u = pmul(punit(psub(b, a)), w / 2);
        arm.push_back(closedP({psub(psub(a, nn), u), padd(psub(b, nn), u), padd(padd(b, nn), u), padd(psub(a, u), nn)}));
    };
    // Spine along -y (up), branches at 60 degrees on both sides, a diamond or a circle at the tip.
    bar({0, 0}, {0, -R * 0.82}, wSpine);
    const int branches = 2 + int(U(rng) * 3);
    for (int k = 0; k < branches; ++k) {
        const double t = 0.25 + 0.55 * (k + U(rng) * 0.6) / branches;
        const double len = R * (0.18 + 0.32 * U(rng) * (1 - t * 0.6));
        const double w = std::max(minWidth, wSpine * (0.6 + 0.3 * U(rng)));
        const Pt base{0, -R * 0.82 * t};
        for (int side : {-1, 1}) {
            const double ang = -PI / 2 + side * PI / 3;
            bar(base, polar(base, len, ang), w);
        }
    }
    const double tip = R * (0.1 + 0.08 * U(rng));
    if (U(rng) < 0.5) arm.push_back(closedP({{0, -R + 0.0}, {tip * 0.6, -R + tip}, {0, -R + 2 * tip}, {-tip * 0.6, -R + tip}}));
    else arm.push_back(circleP({0, -R + tip}, tip * 1.6));
    std::vector<Poly> all;
    for (int a = 0; a < arms; ++a) for (const Poly& p : arm) all.push_back(rotatedP(p, 2 * PI * a / arms));
    const auto hex = regular(arms, R * 0.42 * std::sin(PI / arms) * 2, {});
    all.push_back(closedP(Poly(hex.begin(), hex.end())));
    std::vector<PolySet> sets;
    for (const Poly& p : all) { PolySet s; s.add(p); sets.push_back(std::move(s)); }
    PolySet out = booleanShapes(BooleanOp::Union, sets);
    // A small star hole in the centre plate.
    PolySet hole;
    hole.add(closedP(movedP(ShapeLib::star(arms, R * 0.28, R * 0.28, 0.5), -R * 0.14, -R * 0.14)));
    return booleanOp(BooleanOp::Subtract, out, hole);
}

// ---- Netz ----

void Net::tab(Pt a, Pt b, double depth, double angA, double angB, bool mountainFold, bool withFold) {
    const double L = plen(psub(b, a));
    if (L < 1 || depth <= 0.2) return;
    const Pt u = punit(psub(b, a)), nrm = leftN(a, b);
    const double ta = std::tan(rad(std::clamp(angA, 8.0, 90.0))), tb = std::tan(rad(std::clamp(angB, 8.0, 90.0)));
    const double g = std::min(0.3, L * 0.05);
    const double room = L - 2 * g;
    // Insets must leave at least a fifth of the edge at full depth.
    const double maxDepth = room * 0.8 / (1 / ta + 1 / tb);
    depth = std::min(depth, maxDepth);
    const Pt a1 = padd(a, pmul(u, g)), b1 = psub(b, pmul(u, g));
    solid({a1, padd(padd(a1, pmul(nrm, depth)), pmul(u, depth / ta)), padd(psub(b1, pmul(u, depth / tb)), pmul(nrm, depth)), b1});
    if (withFold) fold(a1, b1, mountainFold);
}
void Net::text(const TextShaper& sh, const QString& t, double h, Pt c, double maxW, double rotDeg, bool bold) {
    if (t.trimmed().isEmpty() || h <= 0 || !sh) return;
    PolySet polys = sh(t, h, bold);
    const auto b = boundsOf(polys);
    if (!b) return;
    const double k = maxW > 0 && b->width() > maxW ? maxW / b->width() : 1;
    const Pt m = b->center();
    const double ang = rad(rotDeg);
    for (Pt& p : polys.allPoints()) p = padd(prot({(p.x - m.x) * k, (p.y - m.y) * k}, ang), c);
    engrave.append(polys);
}
void Net::window(const QString& motifId, Pt c, double w, double h) {
    if (motifId.isEmpty() || motifId == QLatin1String("none") || w < 2 || h < 2) return;
    hole(movedP(motif(motifId, w, h), c.x - w / 2, c.y - h / 2));
}
void Net::transform(const std::function<Pt(Pt)>& f) {
    for (Poly& p : solids) for (Pt& q : p) q = f(q);
    for (Poly& p : holes) for (Pt& q : p) q = f(q);
    for (PolySet* s : {&cuts, &valley, &mountain, &engrave, &mark}) for (Pt& q : s->allPoints()) q = f(q);
}
void Net::append(const Net& o) {
    solids.insert(solids.end(), o.solids.begin(), o.solids.end());
    holes.insert(holes.end(), o.holes.begin(), o.holes.end());
    cuts.append(o.cuts); valley.append(o.valley); mountain.append(o.mountain); engrave.append(o.engrave); mark.append(o.mark);
}
std::optional<Box> Net::bounds() const {
    std::optional<Box> b;
    const auto grow = [&](Pt q) { b = b ? b->united({q.x, q.y, q.x, q.y}) : Box{q.x, q.y, q.x, q.y}; };
    for (const Poly& p : solids) for (const Pt& q : p) grow(q);
    for (const PolySet* s : {&cuts, &valley, &mountain, &engrave, &mark}) for (const Pt& q : s->allPoints()) grow(q);
    return b;
}

int facesNet(Net& n, const std::vector<std::vector<Pt>>& faces, double tabDepth, bool withTabs) {
    struct E { Pt a, b; };
    const auto key = [](Pt p) { return std::make_pair(std::llround(p.x * 1000), std::llround(p.y * 1000)); };
    using K = std::pair<long long, long long>;
    std::map<std::pair<K, K>, int> count;
    std::vector<E> edges;
    for (std::vector<Pt> f : faces) {
        Poly fp(f.begin(), f.end());
        if (areaP(fp) < 0) std::reverse(f.begin(), f.end());
        n.solid(Poly(f.begin(), f.end()));
        for (size_t i = 0; i < f.size(); ++i) {
            const Pt a = f[i], b = f[(i + 1) % f.size()];
            edges.push_back({a, b});
            const K ka = key(a), kb = key(b);
            ++count[ka < kb ? std::make_pair(ka, kb) : std::make_pair(kb, ka)];
        }
    }
    std::vector<E> boundary;
    std::set<std::pair<K, K>> folded;
    for (const E& e : edges) {
        const K ka = key(e.a), kb = key(e.b);
        const auto k = ka < kb ? std::make_pair(ka, kb) : std::make_pair(kb, ka);
        if (count[k] > 1) { if (folded.insert(k).second) n.fold(e.a, e.b); }
        else boundary.push_back(e);
    }
    if (!withTabs || boundary.empty()) return 0;
    // Walk the outline: every boundary edge has the outside on its left, so they chain end to start.
    std::multimap<K, size_t> byStart;
    for (size_t i = 0; i < boundary.size(); ++i) byStart.insert({key(boundary[i].a), i});
    std::vector<size_t> cycle;
    std::vector<bool> used(boundary.size(), false);
    size_t cur = 0;
    while (cycle.size() < boundary.size()) {
        cycle.push_back(cur);
        used[cur] = true;
        const auto [lo, hi] = byStart.equal_range(key(boundary[cur].b));
        size_t next = SIZE_MAX;
        for (auto it = lo; it != hi; ++it) if (!used[it->second]) { next = it->second; break; }
        if (next == SIZE_MAX) break;
        cur = next;
    }
    const auto wedge = [](Pt v, Pt from, Pt to) {
        // Outside angle at v from ray v→from turning left to ray v→to, in degrees.
        double w = std::atan2(from.y - v.y, from.x - v.x) - std::atan2(to.y - v.y, to.x - v.x);
        while (w <= 0) w += 2 * PI;
        while (w > 2 * PI) w -= 2 * PI;
        return w * 180 / PI;
    };
    int tabs = 0;
    const size_t m = cycle.size();
    for (size_t k = 0; k < m; k += 2) {
        const E& e = boundary[cycle[k]];
        const E& prev = boundary[cycle[(k + m - 1) % m]];
        const E& next = boundary[cycle[(k + 1) % m]];
        // Free angle outside the corner at each end: the tab's bevel stays inside it, clear of the neighbour face.
        const double wa = wedge(e.a, e.b, prev.a), wb = wedge(e.b, next.b, e.a);
        const double angA = std::max(8.0, std::min(45.0, wa * 0.75)), angB = std::max(8.0, std::min(45.0, wb * 0.75));
        n.tab(e.a, e.b, tabDepth, angA, angB);
        ++tabs;
    }
    return tabs;
}

// ---- Ergebnis ----

namespace {
PolySet dashed(const PolySet& lines, const std::vector<double>& pattern, double phase) {
    if (pattern.empty()) return lines;
    PolySet out;
    for (PolyView line : lines) {
        // Walk the pattern: idx even = cut, odd = gap; rem = what is left of the current dash or gap.
        size_t idx = 0;
        double rem = pattern[0];
        double skip = phase;
        while (skip > 0) {
            const double d = std::min(skip, rem);
            rem -= d; skip -= d;
            if (rem <= 1e-9) { idx = (idx + 1) % pattern.size(); rem = pattern[idx]; }
        }
        Poly cur;
        for (size_t i = 0; i + 1 < line.size(); ++i) {
            const Pt a = line[i], b = line[i + 1];
            const double L = plen(psub(b, a));
            if (L < 1e-12) continue;
            double s = 0;
            while (s < L - 1e-12) {
                const double step = std::min(rem, L - s);
                const bool on = idx % 2 == 0;
                if (on) {
                    if (cur.empty()) cur.push_back(plerp(a, b, s / L));
                    cur.push_back(plerp(a, b, (s + step) / L));
                }
                s += step;
                rem -= step;
                if (rem <= 1e-9) {
                    if (on && cur.size() > 1) out.add(cur);
                    if (on) cur.clear();
                    idx = (idx + 1) % pattern.size();
                    rem = pattern[idx];
                }
            }
        }
        if (cur.size() > 1) out.add(cur);
    }
    return out;
}
struct Piece { QString name; PolySet cut, fold, engrave, mark; Box box; };
Piece build(const Net& n, int foldStyle) {
    Piece pc;
    pc.name = n.name;
    std::vector<PolySet> solids;
    for (const Poly& p : n.solids) { PolySet s; s.add(p); solids.push_back(std::move(s)); }
    PolySet outline = solids.empty() ? PolySet{} : booleanShapes(BooleanOp::Union, solids);
    if (!n.holes.empty() && !outline.empty()) {
        std::vector<PolySet> hs;
        for (const Poly& p : n.holes) { PolySet s; s.add(p); hs.push_back(std::move(s)); }
        outline = booleanOp(BooleanOp::Subtract, outline, booleanShapes(BooleanOp::Union, hs));
    }
    if (n.outputOutline) pc.cut = outline;
    else for (const Poly& h : n.holes) pc.cut.add(h);
    pc.cut.append(n.cuts);
    // Bergfalz durchgehend (Rillen) bzw. als Strich, Talfalz mit Punkt dazwischen.
    if (foldStyle == 0) { pc.fold = n.mountain; pc.fold.append(dashed(n.valley, {5, 1.5}, 0)); }
    else if (foldStyle == 1) { pc.fold = dashed(n.mountain, {2.5, 1.5}, 0.75); pc.fold.append(dashed(n.valley, {2.5, 1.2, 0.8, 1.2}, 0.6)); }
    else { pc.fold = dashed(n.mountain, {4, 2}, 0); pc.fold.append(dashed(n.valley, {4, 1.5, 1, 1.5}, 0)); }
    pc.engrave = n.engrave;
    pc.mark = n.mark;
    std::optional<Box> b;
    for (const PolySet* s : {&outline, &pc.cut, &pc.fold, &pc.engrave, &pc.mark}) if (const auto q = boundsOf(*s)) b = b ? b->united(*q) : *q;
    pc.box = b.value_or(Box{});
    return pc;
}
void movePiece(Piece& p, double dx, double dy) {
    for (PolySet* s : {&p.cut, &p.fold, &p.engrave, &p.mark}) for (Pt& q : s->allPoints()) q = {q.x + dx, q.y + dy};
    p.box = {p.box.minX + dx, p.box.minY + dy, p.box.maxX + dx, p.box.maxY + dy};
}
void rotatePiece(Piece& p) {
    for (PolySet* s : {&p.cut, &p.fold, &p.engrave, &p.mark}) for (Pt& q : s->allPoints()) q = {-q.y, q.x};
    p.box = {-p.box.maxY, p.box.minX, -p.box.minY, p.box.maxX};
}
Layer paperLayer(const QString& name, qint64 color, LayerMode mode, double power, double speed) {
    Layer l = newLayer(name, color, mode);
    l.powerPct = std::max(8.0, power);
    l.speed = speed;
    l.passes = 1;
    l.intervalMm = 0.1;
    return l;
}
}  // namespace

double thickness(const QVariantMap& p) { return stockById(ps(p, "stock")).t; }

GenResult finish(std::vector<Net> nets, const QVariantMap& p, QStringList notes, QStringList warnings) {
    const Stock& st = stockById(ps(p, "stock"));
    const QString fs = ps(p, "fold");
    const int foldStyle = fs == QLatin1String("perf") ? 1 : fs == QLatin1String("linie") ? 2 : 0;
    const Sheet& sh = sheetById(ps(p, "sheet"));
    const bool bed = sh.w <= 0;
    const double W = bed ? Work::width() : sh.w, H = bed ? Work::height() : sh.h;
    const double margin = bed ? 2 : 5, gap = 4;

    std::vector<Piece> pieces;
    for (const Net& n : nets) {
        Piece pc = build(n, foldStyle);
        if (pc.cut.empty() && pc.engrave.empty() && pc.mark.empty()) continue;
        movePiece(pc, -pc.box.minX, -pc.box.minY);
        pieces.push_back(std::move(pc));
    }
    if (pieces.empty()) throw GenError(QStringLiteral("Das ergibt nichts zum Lasern. Werte prüfen."));

    // Pack onto sheets, rows from the top, tallest first; turn a part by 90 degrees when only that fits.
    std::vector<size_t> order(pieces.size());
    for (size_t i = 0; i < order.size(); ++i) order[i] = i;
    std::stable_sort(order.begin(), order.end(), [&](size_t a, size_t b) { return pieces[a].box.height() > pieces[b].box.height(); });
    struct Place { int plate; double x, y; };
    std::vector<Place> place(pieces.size(), {-1, 0, 0});
    const auto fits = [&](const Piece& pc, double m) { return pc.box.width() <= W - 2 * m + 1e-6 && pc.box.height() <= H - 2 * m + 1e-6; };
    int plate = 0;
    double x = margin, y = margin, rowH = 0;
    bool plateUsed = false;
    for (size_t i : order) {
        Piece& pc = pieces[i];
        if (!fits(pc, margin) && fits(pc, 0)) {
            // Only fits without the margin: alone on its own sheet at the corner (a letter sheet the size of the sheet).
            if (plateUsed) ++plate;
            place[i] = {plate, (W - pc.box.width()) / 2, (H - pc.box.height()) / 2};
            ++plate; x = margin; y = margin; rowH = 0; plateUsed = false;
            continue;
        }
        if (!fits(pc, margin)) {
            rotatePiece(pc);
            movePiece(pc, -pc.box.minX, -pc.box.minY);
            if (!fits(pc, margin)) {
                if (fits(pc, 0)) {
                    if (plateUsed) ++plate;
                    place[i] = {plate, (W - pc.box.width()) / 2, (H - pc.box.height()) / 2};
                    ++plate; x = margin; y = margin; rowH = 0; plateUsed = false;
                    continue;
                }
                throw GenError(QStringLiteral("„%1“ ist mit %2 × %3 mm größer als der Bogen (%4 × %5 mm). Kleiner machen oder einen größeren Bogen wählen.")
                                   .arg(pc.name, Werkstatt::num(std::max(pc.box.width(), pc.box.height())), Werkstatt::num(std::min(pc.box.width(), pc.box.height())),
                                        Werkstatt::num(W), Werkstatt::num(H)));
            }
        }
        // Rotating can help a wide part fit the row too.
        if (x + pc.box.width() > W - margin + 1e-6) { x = margin; y += rowH + gap; rowH = 0; }
        if (y + pc.box.height() > H - margin + 1e-6) { ++plate; x = margin; y = margin; rowH = 0; plateUsed = false; }
        place[i] = {plate, x, y};
        plateUsed = true;
        x += pc.box.width() + gap;
        rowH = std::max(rowH, pc.box.height());
    }
    int plates = 0;
    for (const Place& pl : place) plates = std::max(plates, pl.plate + 1);
    if (plates > 30) throw GenError(QStringLiteral("Das wären mehr als 30 Bögen. Weniger Stück oder größere Bögen wählen."));

    GenResult r;
    r.center = true;
    r.freshPlate = true;
    Layer sheetL = newLayer(L_SHEET, 0xFF8A93A8LL, LayerMode::Line);
    sheetL.output = false;
    r.layers.push_back(sheetL);
    r.layers.push_back(paperLayer(L_ENGRAVE, 0xFF3FBF9FLL, LayerMode::Fill, st.engP, st.engS));
    r.layers.push_back(paperLayer(L_MARK, 0xFF6CB6FFLL, LayerMode::Line, st.markP, st.markS));
    r.layers.push_back(foldStyle == 1 ? paperLayer(L_FOLD, 0xFFFFB45CLL, LayerMode::Line, st.cutP, st.cutS)
                       : foldStyle == 2 ? paperLayer(L_FOLD, 0xFFFFB45CLL, LayerMode::Line, st.markP, st.markS)
                                        : paperLayer(L_FOLD, 0xFFFFB45CLL, LayerMode::Line, st.scoreP, st.scoreS));
    Layer cutL = paperLayer(L_CUT, 0xFFFF6B70LL, LayerMode::Line, st.cutP, st.cutS);
    cutL.thicknessMm = st.t;
    r.layers.push_back(cutL);

    // Order by layer, so the project gets Gravieren, Markieren, Falzen and Schneiden last.
    if (!bed)
        for (int pl = 0; pl < plates; ++pl) r.parts.push_back({QStringLiteral("Bogen %1").arg(pl + 1), L_SHEET, PolySet{rectP(0, 0, W, H)}, pl, {}});
    const auto push = [&](const QString& layer, PolySet Piece::*what, const QString& suffix) {
        for (size_t i = 0; i < pieces.size(); ++i) {
            Piece pc = pieces[i];
            if ((pc.*what).empty()) continue;
            movePiece(pc, place[i].x, place[i].y);
            r.parts.push_back({pc.name + suffix, layer, pc.*what, place[i].plate, QStringLiteral("papier-%1").arg(i)});
        }
    };
    push(L_ENGRAVE, &Piece::engrave, QStringLiteral(" Gravur"));
    push(L_MARK, &Piece::mark, QStringLiteral(" Linien"));
    push(L_FOLD, &Piece::fold, QStringLiteral(" Falze"));
    push(L_CUT, &Piece::cut, QString());

    QStringList all;
    all << QStringLiteral("%1 %2 auf %3%4.").arg(pieces.size()).arg(pieces.size() == 1 ? QStringLiteral("Teil") : QStringLiteral("Teile"),
                                                 bed ? QStringLiteral("der Arbeitsfläche") : sh.name,
                                                 plates > 1 ? QStringLiteral(", %1 Bögen").arg(plates) : QString());
    all << notes;
    if (foldStyle == 0) all << QStringLiteral("Falze werden geritzt. Bergfalz durchgezogen: vom Laser weg falzen, die Rille liegt außen. Talfalz gestrichelt: zum Laser hin.");
    else if (foldStyle == 1) all << QStringLiteral("Falze werden perforiert: kurze Schnitte mit Stegen. Bergfalz gestrichelt (vom Laser weg), Talfalz strichpunktiert (zum Laser hin).");
    else all << QStringLiteral("Falze werden nur leicht markiert. Mit Lineal und Falzbein nachziehen. Bergfalz gestrichelt, Talfalz strichpunktiert.");
    if (!bed) all << QStringLiteral("Den Bogen auf die angezeigte Fläche legen und flach halten (Kreppband am Rand). Gewölbtes Papier verschiebt den Fokus.");
    r.notes = all;
    r.warnings = warnings;
    r.warnings << QStringLiteral("Laserwerte für %1 sind Vorschläge, auf dieser Maschine nicht geprüft. Erst ein Materialtest-Raster auf einem Rest desselben Papiers.").arg(st.name);
    r.warnings << QStringLiteral("Papier und Karton brennen leicht: Abluft und Luftunterstützung an, nie unbeaufsichtigt lassen.");
    return r;
}

// ---- Formular ----

QVariantMap fNum(const QString& key, const QString& label, const QString& unit, double min, double max, double step, int digits, const QString& hint) {
    return {{"type", "num"}, {"key", key}, {"label", label}, {"unit", unit}, {"min", min}, {"max", max}, {"step", step}, {"digits", digits}, {"hint", hint}};
}
QVariantMap fMm(const QString& key, const QString& label, double min, double max, double step, int digits, const QString& hint) {
    return fNum(key, label, QStringLiteral("mm"), min, max, step, digits, hint);
}
QVariantMap fSeg(const QString& key, const QString& label, const QList<std::pair<QString, QString>>& opts, const QString& hint) {
    QVariantList o;
    for (const auto& [v, l] : opts) o.push_back(QVariantMap{{"value", v}, {"label", l}});
    return {{"type", "seg"}, {"key", key}, {"label", label}, {"options", o}, {"hint", hint}};
}
QVariantMap fSelect(const QString& key, const QString& label, const QList<std::pair<QString, QString>>& opts, const QString& hint) {
    QVariantMap m = fSeg(key, label, opts, hint);
    m.insert("type", "select");
    return m;
}
QVariantMap fText(const QString& key, const QString& label, const QString& hint, const QString& placeholder) {
    return {{"type", "text"}, {"key", key}, {"label", label}, {"hint", hint}, {"placeholder", placeholder}};
}
QVariantMap fCheck(const QString& key, const QString& label) { return {{"type", "check"}, {"key", key}, {"label", label}}; }
QVariantMap fRow(const QVariantList& f) { return {{"type", "row"}, {"fields", f}}; }
QVariantMap fSection(const QString& label) { return {{"type", "section"}, {"label", label}}; }
QVariantMap fNote(const QString& t, const QString& tone) { return {{"type", "note"}, {"text", t}, {"tone", tone}}; }
QVariantMap fMotif(const QString& key, const QString& label, bool withNone) {
    QList<std::pair<QString, QString>> o;
    if (withNone) o.push_back({QStringLiteral("none"), QStringLiteral("Keins")});
    for (const QString& id : motifIds()) o.push_back({id, motifLabel(id)});
    return fSelect(key, label, o);
}
QVariantMap fEdge(const QString& key, const QString& label) {
    return fSelect(key, label, {{"gerade", "Gerade"}, {"wellen", "Wellen"}, {"boegen", "Bögen"}, {"zacken", "Zacken"}, {"spitze", "Spitze (mit Löchern)"}});
}
QVariantList commonFields(bool folds) {
    QList<std::pair<QString, QString>> st, sh;
    for (const Stock& s : stocks()) st.push_back({s.id, s.name});
    for (const Sheet& s : sheets()) sh.push_back({s.id, s.name});
    QVariantList f{fSection(QStringLiteral("Papier und Bogen")), fSelect(QStringLiteral("stock"), QStringLiteral("Papier"), st)};
    if (folds)
        f.push_back(fSeg(QStringLiteral("fold"), QStringLiteral("Falzlinien"), {{"rillen", "Rillen"}, {"perf", "Perforieren"}, {"linie", "Nur anzeichnen"}},
                         QStringLiteral("Rillen: schwach angeritzt. Perforieren: kurze Schnitte, für dicken Karton. Anzeichnen: von Hand falzen.")));
    f.push_back(fSelect(QStringLiteral("sheet"), QStringLiteral("Bogen"), sh, QStringLiteral("Passt ein Teil nicht, wird es gedreht oder kommt auf einen weiteren Bogen.")));
    return f;
}
QVariantMap commonDefaults(const QString& stock, const QString& sheet) {
    return {{"stock", stock}, {"fold", "rillen"}, {"sheet", sheet}};
}
double pd(const QVariantMap& p, const char* k) { return p.value(QLatin1String(k)).toDouble(); }
int pi(const QVariantMap& p, const char* k) { return int(std::lround(p.value(QLatin1String(k)).toDouble())); }
QString ps(const QVariantMap& p, const char* k) { return p.value(QLatin1String(k)).toString(); }
bool pb(const QVariantMap& p, const char* k) { return p.value(QLatin1String(k)).toBool(); }
double need(double v, double lo, double hi, const QString& what) {
    if (!std::isfinite(v) || v < lo - 1e-9 || v > hi + 1e-9)
        throw GenError(QStringLiteral("%1: %2 bis %3.").arg(what, Werkstatt::num(lo), Werkstatt::num(hi)));
    return v;
}
QStringList listOf(const QString& s) {
    QStringList out;
    for (const QString& part : s.split(QLatin1Char(','))) if (!part.trimmed().isEmpty()) out << part.trimmed();
    return out;
}

}  // namespace lumacut::Papier
