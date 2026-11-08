#include "core/papier/papier_net.h"
#include "core/boolean.h"
#include "core/extras.h"
#include "core/geometry.h"
#include "core/model.h"
#include <QDate>
#include <QLocale>
#include <algorithm>
#include <array>
#include <random>

namespace lumacut::Papier {
namespace {

using Opts = QList<std::pair<QString, QString>>;
using TS = TextShaper;

QVariantMap with(QVariantMap a, const QVariantMap& b) {
    for (auto it = b.begin(); it != b.end(); ++it) a.insert(it.key(), it.value());
    return a;
}
QVariantList plus(QVariantList a, const QVariantList& b) { a.append(b); return a; }
const Opts FLAPS = {{"gerade", "Gerade"}, {"rund", "Rund"}, {"spitz", "Spitz"}, {"wellen", "Wellen"}, {"boegen", "Bögen"}, {"zacken", "Zacken"}};
bool none(const QString& s) { return s.isEmpty() || s == QLatin1String("none"); }

/** Lasche oder Klappe links von a→b in einer Form; Falz auf a-b. */
void flap(Net& n, Pt a, Pt b, double depth, const QString& style, bool mountain = true) {
    const double L = plen(psub(b, a));
    const Pt nrm = leftN(a, b);
    if (style == QLatin1String("rund")) {
        n.solid(bulge(a, b, std::min(depth, L / 2)));
        n.fold(a, b, mountain);
    } else if (style == QLatin1String("spitz")) {
        n.solid({a, padd(plerp(a, b, 0.5), pmul(nrm, depth)), b});
        n.fold(a, b, mountain);
    } else if (style == QLatin1String("gerade") || style.isEmpty()) {
        n.tab(a, b, depth, 72, 72, mountain);
    } else {
        const double dd = depth * 0.78;
        const Pt a2 = padd(a, pmul(nrm, dd)), b2 = padd(b, pmul(nrm, dd));
        const EdgeLine el = decoratedEdge(a2, b2, edgeFromId(style), std::max(6.0, L / 9));
        Poly p{a};
        p.insert(p.end(), el.line.begin(), el.line.end());
        p.push_back(b);
        n.solid(p);
        for (const Poly& h : el.holes) n.hole(h);
        n.fold(a, b, mountain);
    }
}
/** Rechteck im Uhrzeigersinn; Kante 0 oben, 1 rechts, 2 unten, 3 links mit eigenem Rand. */
void decoRect(Net& n, double x, double y, double w, double h, const std::array<Edge, 4>& e, double size) {
    const Pt c[4] = {{x, y}, {x + w, y}, {x + w, y + h}, {x, y + h}};
    Poly p;
    for (int s = 0; s < 4; ++s) {
        const EdgeLine el = decoratedEdge(c[s], c[(s + 1) % 4], e[s], size);
        p.insert(p.end(), el.line.begin(), el.line.end() - 1);
        for (const Poly& h : el.holes) n.hole(h);
    }
    n.solid(p);
}
/** Schale: Boden w × d an (h, h), Wände h hoch, Ecklaschen an den Längswänden. rim: Rand der Wandoberkanten. */
void tray(Net& n, double w, double d, double h, Edge rim = Edge::Straight, double rimSize = 8) {
    n.rect(h, h, w, d);
    const Edge S = Edge::Straight;
    decoRect(n, h, 0, w, h, {rim, S, S, S}, rimSize);
    decoRect(n, h + w, h, h, d, {S, rim, S, S}, rimSize);
    decoRect(n, h, h + d, w, h, {S, S, rim, S}, rimSize);
    decoRect(n, 0, h, h, d, {S, S, S, rim}, rimSize);
    n.fold({h, h}, {h + w, h});
    n.fold({h + w, h}, {h + w, h + d});
    n.fold({h, h + d}, {h + w, h + d});
    n.fold({h, h}, {h, h + d});
    const double t = std::min({12.0, h * 0.85, d * 0.45});
    n.tab({h, h}, {h, 0}, t, 40, 45);
    n.tab({h + w, 0}, {h + w, h}, t, 45, 40);
    n.tab({h, 2 * h + d}, {h, h + d}, t, 45, 40);
    n.tab({h + w, h + d}, {h + w, 2 * h + d}, t, 40, 45);
}
/** Vieleck-Schale um c: Boden aus n Seiten der Länge a, Wände h hoch, eine Lasche je Wand. Liefert die Ecken. */
std::vector<Pt> polyTray(Net& n, int sides, double a, double h, Pt c) {
    const std::vector<Pt> v = regular(sides, a, c);
    n.solid(Poly(v.begin(), v.end()));
    const double ext = 360.0 / sides;
    for (int k = 0; k < sides; ++k) {
        const Pt p = v[k], q = v[(k + 1) % sides];
        const Pt nrm = leftN(p, q);
        n.solid({p, q, padd(q, pmul(nrm, h)), padd(p, pmul(nrm, h))});
        n.fold(p, q);
        n.tab(padd(q, pmul(nrm, h)), q, std::min({10.0, h * 0.4, a * 0.4}), 45, std::min(45.0, ext * 0.7));
    }
    return v;
}
/** Scheibe mit Zähnen zum Einkleben in einen Mantel. Falz am Fuß jedes Zahns. */
void toothedDisc(Net& n, Pt c, double dia, bool mountain = true) {
    const double R = dia / 2;
    const int count = std::clamp(int(std::lround(PI * dia / 9)), 8, 48);
    const double tooth = std::min(8.0, dia * 0.14);
    const double pitch = 2 * PI / count, span = pitch * 0.72, taper = span * 0.18;
    Poly p;
    for (int k = 0; k < count; ++k) {
        const double a0 = k * pitch;
        p.push_back(polar(c, R, a0));
        p.push_back(polar(c, R + tooth, a0 + taper));
        p.push_back(polar(c, R + tooth, a0 + span - taper));
        p.push_back(polar(c, R, a0 + span));
        const Poly arc = arcP(c, R, a0 + span, a0 + pitch, 0.6);
        p.insert(p.end(), arc.begin() + 1, arc.end() - 1);
        n.foldPath(arcP(c, R, a0, a0 + span, 0.6), mountain);
    }
    n.solid(p);
}
/** Fenstergröße: runde Motive quadratisch, sonst im Verhältnis des Feldes. */
std::pair<double, double> winSize(const QString& m, double w, double h, double pct) {
    const double k = pct / 100;
    static const QStringList square = {"kreis", "herz", "stern", "stern6", "blume", "flocke", "sechseck", "raute", "schmetterling", "krone", "wolke", "mond"};
    if (square.contains(m)) { const double s = std::min(w, h) * k; return {s, s}; }
    if (m == QLatin1String("ei") || m == QLatin1String("ballon") || m == QLatin1String("tropfen") || m == QLatin1String("tanne")) {
        const double s = std::min(w * 0.8, h) * k; return {s * 0.78, s};
    }
    return {w * k, h * k};
}
/** Breite eines Motivs bei Höhe h, im Verhältnis wie winSize. */
double aspectW(const QString& m, double h) {
    const auto [w0, h0] = winSize(m, 100, 100, 100);
    return h * w0 / h0;
}
/** Sheet size from the parameters (bed: the work area). */
std::pair<double, double> sheetSize(const QVariantMap& p) {
    const Sheet& s = sheetById(ps(p, "sheet"));
    if (s.w <= 0) return {Work::width(), Work::height()};
    return {s.w, s.h};
}

// ---- Verpackung ----

GenResult faltschachtel(const QVariantMap& p, const TS& sh) {
    const double w = need(pd(p, "w"), 15, 250, "Breite"), d = need(pd(p, "d"), 10, 150, "Tiefe"), h = need(pd(p, "h"), 15, 300, "Höhe");
    const double t = thickness(p);
    Net n{QStringLiteral("Faltschachtel")};
    const double g = std::clamp(d * 0.6, 8.0, 15.0), x1 = w, x2 = w + d, x3 = 2 * w + d, x4 = 2 * w + 2 * d;
    n.rect(0, 0, x4, h);
    n.fold({x1, 0}, {x1, h}); n.fold({x2, 0}, {x2, h}); n.fold({x3, 0}, {x3, h});
    n.tab({x4, 0}, {x4, h}, g, 45, 45);
    const double tuck = std::clamp(d * 0.6, 8.0, 25.0), c = t + 0.5, r = std::min(tuck * 0.6, (w - 2 * c) * 0.3);
    const double fl = std::min(d * 0.8, w * 0.45);
    // Oben: Deckel an der Rückwand, Staublaschen an den Seiten.
    n.rect(x2, -d, w, d); n.fold({x2, 0}, {x3, 0});
    n.rect(x2 + c, -d - tuck, w - 2 * c, tuck + r, r); n.fold({x2 + c, -d}, {x3 - c, -d});
    n.tab({x1, 0}, {x2, 0}, fl, 40, 80);
    n.tab({x3, 0}, {x4, 0}, fl, 80, 40);
    // Unten: Deckel an der Vorderseite.
    n.rect(0, h, w, d); n.fold({0, h}, {w, h});
    n.rect(c, h + d - r, w - 2 * c, tuck + r, r); n.fold({c, h + d}, {w - c, h + d});
    n.tab({x2, h}, {x1, h}, fl, 40, 80);
    n.tab({x4, h}, {x3, h}, fl, 40, 40);
    const QString m = ps(p, "window");
    const auto [ww, wh] = winSize(m, w * 0.8, h * 0.6, pd(p, "winSize"));
    const bool win = !none(m);
    n.window(m, {w / 2, win ? h * 0.42 : h / 2}, ww, wh);
    n.text(sh, ps(p, "text"), pd(p, "textH"), {w / 2, win ? std::min(h - 8, h * 0.42 + wh / 2 + 10) : h / 2}, w * 0.85);
    return finish({n}, p, {QStringLiteral("Innenmaß etwa %1 × %2 × %3 mm, Steckverschluss oben und unten.").arg(Werkstatt::num(w), Werkstatt::num(d), Werkstatt::num(h))});
}

GenResult deckelschachtel(const QVariantMap& p, const TS& sh) {
    const double w = need(pd(p, "w"), 20, 250, "Breite"), d = need(pd(p, "d"), 20, 250, "Tiefe"), h = need(pd(p, "h"), 8, 150, "Höhe");
    const double lh = need(pd(p, "lidH"), 5, h, "Deckelhöhe");
    const double t = thickness(p), cl = 2 * t + 0.8;
    Net base{QStringLiteral("Unterteil")};
    tray(base, w, d, h);
    Net lid{QStringLiteral("Deckel")};
    const double W = w + cl, D = d + cl;
    tray(lid, W, D, lh, edgeFromId(ps(p, "rim")), 8);
    if (pb(p, "grip")) {
        const double r = std::min({9.0, W * 0.12, lh * 0.7});
        lid.hole(circleP({lh + W / 2, 0}, 2 * r));
        lid.hole(circleP({lh + W / 2, 2 * lh + D}, 2 * r));
    }
    const QString m = ps(p, "window");
    const auto [ww, wh] = winSize(m, W * 0.8, D * 0.8, pd(p, "winSize"));
    lid.window(m, {lh + W / 2, lh + D / 2}, ww, wh);
    lid.text(sh, ps(p, "text"), pd(p, "textH"), {lh + W / 2, none(m) ? lh + D / 2 : lh + D / 2 + wh / 2 + 7}, W * 0.85);
    return finish({base, lid}, p, {QStringLiteral("Der Deckel ist um %1 mm größer als das Unterteil (zweimal die Papierstärke und Spiel).").arg(Werkstatt::num(cl))});
}

GenResult vieleck(const QVariantMap& p, const TS& sh) {
    const int sides = int(need(pi(p, "sides"), 3, 12, "Ecken"));
    const double a = need(pd(p, "a"), 10, 150, "Seitenlänge"), h = need(pd(p, "h"), 5, 200, "Höhe"), lh = need(pd(p, "lidH"), 0, h, "Deckelhöhe");
    const double c = thickness(p) + 0.4;
    Net base{QStringLiteral("Unterteil")};
    polyTray(base, sides, a, h, {});
    std::vector<Net> nets{base};
    if (lh > 0) {
        Net lid{QStringLiteral("Deckel")};
        const double a2 = a + 2 * c * std::tan(PI / sides);
        polyTray(lid, sides, a2, lh, {});
        const double rin = a2 / (2 * std::tan(PI / sides));
        const QString m = ps(p, "window");
        const auto [ww, wh] = winSize(m, rin * 1.3, rin * 1.3, pd(p, "winSize"));
        lid.window(m, {0, 0}, ww, wh);
        lid.text(sh, ps(p, "text"), pd(p, "textH"), {0, none(m) ? 0.0 : wh / 2 + 6}, rin * 1.4);
        nets.push_back(lid);
    }
    return finish(nets, p, {QStringLiteral("%1-eckige Schachtel, Seitenlänge %2 mm.").arg(sides).arg(Werkstatt::num(a))});
}

GenResult pyramide(const QVariantMap& p, const TS&) {
    const int sides = int(need(pi(p, "sides"), 3, 8, "Ecken"));
    const double a = need(pd(p, "a"), 15, 200, "Seitenlänge"), H = need(pd(p, "H"), 10, 300, "Höhe");
    Net n{QStringLiteral("Pyramidenschachtel")};
    const std::vector<Pt> v = regular(sides, a, {});
    n.solid(Poly(v.begin(), v.end()));
    const double ra = a / (2 * std::tan(PI / sides)), slant = std::sqrt(H * H + ra * ra);
    const QString m = ps(p, "motif");
    for (int k = 0; k < sides; ++k) {
        const Pt q0 = v[k], q1 = v[(k + 1) % sides], nrm = leftN(q0, q1), mid = plerp(q0, q1, 0.5);
        const Pt apex = padd(mid, pmul(nrm, slant));
        n.solid({q0, apex, q1});
        n.fold(q0, q1);
        if (pb(p, "ribbon")) n.hole(circleP(padd(apex, pmul(nrm, -std::min(12.0, slant * 0.15))), 4));
        if (!none(m)) {
            const double s = std::min(a * 0.32, slant * 0.28);
            const Pt cc = padd(mid, pmul(nrm, slant * 0.38));
            n.hole(rotatedP(movedP(motif(m, s, s), cc.x - s / 2, cc.y - s / 2), std::atan2(nrm.y, nrm.x) + PI / 2, cc));
        }
    }
    return finish({n}, p, {QStringLiteral("Die Spitzen mit einem Band durch die Löcher zusammenbinden.")});
}

GenResult kissen(const QVariantMap& p, const TS& sh) {
    const double w = need(pd(p, "w"), 30, 200, "Breite"), h = need(pd(p, "h"), 40, 280, "Länge");
    const double k = need(pd(p, "k"), 5, w * 0.45, "Wölbung");
    Net n{QStringLiteral("Kissenschachtel")};
    n.rect(0, 0, 2 * w, h);
    n.fold({w, 0}, {w, h});
    n.tab({0, h}, {0, 0}, 12, 45, 45);
    for (double x0 : {0.0, w}) {
        n.solid(bulge({x0, 0}, {x0 + w, 0}, k));
        n.foldPath(bulge({x0, 0}, {x0 + w, 0}, -k), false);
        n.solid(bulge({x0 + w, h}, {x0, h}, k));
        n.foldPath(bulge({x0 + w, h}, {x0, h}, -k), false);
    }
    n.text(sh, ps(p, "text"), pd(p, "textH"), {w / 2, h / 2}, w * 0.8);
    return finish({n}, p, {QStringLiteral("Die Bogenfalze sanft vorbiegen, dann schließen sich die Enden von selbst.")});
}

GenResult prisma(const QVariantMap& p, const TS& sh) {
    const double a = need(pd(p, "a"), 15, 120, "Seitenlänge"), L = need(pd(p, "L"), 30, 280, "Länge");
    Net n{QStringLiteral("Dreieckschachtel")};
    n.rect(0, 0, 3 * a, L);
    n.fold({a, 0}, {a, L}); n.fold({2 * a, 0}, {2 * a, L});
    n.tab({3 * a, 0}, {3 * a, L}, std::min(12.0, a * 0.4));
    const double th = a * std::sqrt(3.0) / 2, td = std::min(10.0, a * 0.25);
    const Pt top{1.5 * a, -th}, bot{1.5 * a, L + th};
    n.solid({{a, 0}, top, {2 * a, 0}}); n.fold({a, 0}, {2 * a, 0});
    n.tab({a, 0}, top, td); n.tab(top, {2 * a, 0}, td);
    n.solid({{2 * a, L}, bot, {a, L}}); n.fold({a, L}, {2 * a, L});
    n.tab({2 * a, L}, bot, td); n.tab(bot, {a, L}, td);
    n.text(sh, ps(p, "text"), std::min(pd(p, "textH"), a * 0.5), {1.5 * a, L / 2}, L * 0.85, -90);
    return finish({n}, p);
}

GenResult schiebeschachtel(const QVariantMap& p, const TS& sh) {
    const double w = need(pd(p, "w"), 20, 200, "Breite"), L = need(pd(p, "L"), 20, 250, "Länge"), h = need(pd(p, "h"), 8, 100, "Höhe");
    const double t = thickness(p);
    Net drawer{QStringLiteral("Schublade")};
    tray(drawer, w, L, h);
    if (pb(p, "grip")) drawer.hole(circleP({h + w / 2, 0}, std::min({16.0, w * 0.4, h * 1.4})));
    Net sleeve{QStringLiteral("Hülle")};
    const double W = w + 2 * t + 0.8, H = h + 2 * t + 0.8;
    const double xs[] = {0, W, W + H, 2 * W + H, 2 * W + 2 * H};
    sleeve.rect(0, 0, xs[4], L);
    for (int k = 1; k < 4; ++k) sleeve.fold({xs[k], 0}, {xs[k], L});
    sleeve.tab({xs[4], 0}, {xs[4], L}, std::min(12.0, H * 0.8));
    const QString txt = ps(p, "text");
    sleeve.text(sh, txt, pd(p, "textH"), {W / 2, L / 2}, (L > W ? L : W) * 0.85, L > W * 1.4 ? -90 : 0);
    return finish({drawer, sleeve}, p, {QStringLiteral("Die Hülle ist um %1 mm weiter als die Schublade.").arg(Werkstatt::num(2 * t + 0.8))});
}

GenResult tuete(const QVariantMap& p, const TS& sh) {
    const double w = need(pd(p, "w"), 30, 250, "Breite"), g = need(pd(p, "g"), 10, w, "Seitenfalte"), h = need(pd(p, "h"), 40, 300, "Höhe");
    Net n{QStringLiteral("Tüte")};
    const double X = 2 * w + 2 * g, bh = g / 2 + 12, top = pb(p, "hem") ? -20.0 : 0.0;
    if (top < 0) { n.rect(0, top, X, -top); n.fold({0, 0}, {X, 0}); }
    n.rect(0, 0, X, h + bh);
    for (double x : {w, w + g, 2 * w + g}) n.fold({x, top}, {x, h + bh});
    for (double x : {w + g / 2, 2 * w + 1.5 * g}) n.fold({x, top}, {x, h}, false);
    n.fold({0, h}, {X, h});
    n.fold({0, h + g / 2}, {X, h + g / 2});
    for (double xs : {w, 2 * w + g}) {
        n.fold({xs, h}, {xs + g / 2, h + g / 2}, false);
        n.fold({xs + g, h}, {xs + g / 2, h + g / 2}, false);
    }
    n.tab({X, top}, {X, h + bh}, 15, 45, 45);
    if (pb(p, "holes"))
        for (double x0 : {0.0, w + g})
            for (double fx : {0.3, 0.7}) {
                n.hole(circleP({x0 + w * fx, 10}, 5));
                if (top < 0) n.hole(circleP({x0 + w * fx, -10}, 5));
            }
    const QString m = ps(p, "window");
    const auto [ww, wh] = winSize(m, w * 0.7, h * 0.5, pd(p, "winSize"));
    n.window(m, {w / 2, h * 0.45}, ww, wh);
    n.text(sh, ps(p, "text"), pd(p, "textH"), {w / 2, none(m) ? h * 0.45 : h * 0.45 + wh / 2 + 9}, w * 0.85);
    return finish({n}, p, {QStringLiteral("Seitenfalten nach innen drücken, Boden falten und kleben.")});
}

GenResult henkelbox(const QVariantMap& p, const TS& sh) {
    const double w = need(pd(p, "w"), 30, 200, "Breite"), d = need(pd(p, "d"), 20, 150, "Tiefe"), h = need(pd(p, "h"), 20, 250, "Höhe");
    const double hh = need(pd(p, "handle"), 15, 100, "Griffhöhe");
    Net n{QStringLiteral("Henkelbox")};
    const double r = d / 2, X = 2 * w + 2 * d, x2 = w + d;
    n.rect(0, -r, X, h + r);
    n.rect(0, -r - hh, w, hh);
    n.rect(x2, -r - hh, w, hh);
    for (double x : {w, w + d, 2 * w + d}) n.fold({x, -r}, {x, h});
    n.fold({0, 0}, {X, 0});
    n.fold({0, -r}, {w, -r});
    n.fold({x2, -r}, {x2 + w, -r});
    for (double xs : {w, 2 * w + d}) {
        n.fold({xs, 0}, {xs + d / 2, -r}, false);
        n.fold({xs + d, 0}, {xs + d / 2, -r}, false);
    }
    for (double x0 : {0.0, x2}) n.hole(rectP(x0 + w * 0.27, -r - hh * 0.62, w * 0.46, std::min(14.0, hh * 0.32), 6));
    n.tab({w, h}, {0, h}, d * 0.55, 40, 40);
    n.tab({x2 + w, h}, {x2, h}, d * 0.55, 40, 40);
    n.tab({x2, h}, {w, h}, d * 0.45, 40, 40);
    n.tab({X, h}, {x2 + w, h}, d * 0.45, 40, 40);
    n.tab({X, 0}, {X, h}, 12);
    n.text(sh, ps(p, "text"), pd(p, "textH"), {w / 2, h / 2}, w * 0.85);
    return finish({n}, p, {QStringLiteral("Die Dreiecke an den Seiten nach innen falten, die Griffteile aufeinanderlegen.")});
}

GenResult runddose(const QVariantMap& p, const TS& sh) {
    const double D = need(pd(p, "D"), 20, 200, "Durchmesser"), h = need(pd(p, "h"), 10, 250, "Höhe"), lh = need(pd(p, "lidH"), 0, h, "Deckelhöhe");
    const double t = thickness(p);
    std::vector<Net> nets;
    Net bottom{QStringLiteral("Boden")};
    toothedDisc(bottom, {}, D);
    nets.push_back(bottom);
    Net wall{QStringLiteral("Mantel")};
    const double U = PI * (D + t);
    wall.rect(0, 0, U, h);
    wall.tab({U, 0}, {U, h}, 10);
    nets.push_back(wall);
    Net inner{QStringLiteral("Bodenscheibe")};
    inner.solid(circleP({}, D - 1));
    nets.push_back(inner);
    if (lh > 0) {
        const double D2 = D + 2 * t + 0.8;
        Net lid{QStringLiteral("Deckel")};
        toothedDisc(lid, {}, D2);
        lid.text(sh, ps(p, "text"), pd(p, "textH"), {}, D2 * 0.75);
        const QString m = ps(p, "motif");
        if (!none(m)) { const double s = D2 * 0.35; lid.engraveShape(movedP(motif(m, s, s), -s / 2, -s / 2 - (ps(p, "text").isEmpty() ? 0 : s * 0.7))); }
        nets.push_back(lid);
        Net rim{QStringLiteral("Deckelrand")};
        const double U2 = PI * (D2 + t);
        rim.rect(0, 0, U2, lh);
        rim.tab({U2, 0}, {U2, lh}, 10);
        nets.push_back(rim);
    }
    return finish(nets, p, {QStringLiteral("Den Mantel um den Boden legen, die Zähne innen ankleben, dann die Bodenscheibe darüber.")});
}

GenResult steckhuelle(const QVariantMap& p, const TS& sh) {
    const QString f = ps(p, "format");
    double W = pd(p, "w"), H = pd(p, "h");
    if (f == QLatin1String("cd")) { W = 125; H = 125; }
    else if (f == QLatin1String("foto")) { W = 102; H = 152; }
    else if (f == QLatin1String("gutschein")) { W = 150; H = 75; }
    else if (f == QLatin1String("a6")) { W = 105; H = 148; }
    need(W, 20, 250, "Breite"); need(H, 20, 250, "Höhe");
    const double t = thickness(p), Wc = W + 2 * t + 2, Hc = H + 2 * t + 2, front = Hc * 0.62;
    Net n{QStringLiteral("Steckhülle")};
    n.rect(0, 0, Wc, Hc);
    n.rect(0, Hc, Wc, front);
    n.fold({0, Hc}, {Wc, Hc});
    n.tab({0, Hc}, {0, 0}, 12, 40, 40);
    n.tab({Wc, 0}, {Wc, Hc}, 12, 40, 40);
    flap(n, {0, 0}, {Wc, 0}, Hc * 0.3, ps(p, "flap"));
    if (pb(p, "thumb")) n.hole(circleP({Wc / 2, Hc + front}, std::min(30.0, Wc * 0.22)));
    const QString m = ps(p, "window");
    const auto [ww, wh] = winSize(m, Wc * 0.7, Hc * 0.6, pd(p, "winSize"));
    n.window(m, {Wc / 2, Hc * 0.45}, ww, wh);
    n.text(sh, ps(p, "text"), pd(p, "textH"), {Wc / 2, none(m) ? Hc * 0.5 : std::min(Hc - 8, Hc * 0.45 + wh / 2 + 9)}, Wc * 0.85);
    return finish({n}, p, {QStringLiteral("Für Inhalt bis %1 × %2 mm. Die gelaserte Seite ist vorn, die Tasche liegt hinten.").arg(Werkstatt::num(W), Werkstatt::num(H))});
}

GenResult koerbchen(const QVariantMap& p, const TS&) {
    const double w = need(pd(p, "w"), 20, 250, "Breite"), d = need(pd(p, "d"), 20, 250, "Tiefe"), h = need(pd(p, "h"), 8, 120, "Höhe");
    Net n{QStringLiteral("Körbchen")};
    tray(n, w, d, h, edgeFromId(ps(p, "rim")), std::max(6.0, std::min(w, d) / 8));
    std::vector<Net> nets{n};
    if (pb(p, "handle")) {
        Net hd{QStringLiteral("Henkel")};
        hd.rect(0, 0, 15, d + 2 * h + 30, 3);
        nets.push_back(hd);
    }
    return finish(nets, p, {QStringLiteral("Den Henkel innen an die Längswände kleben.")});
}

// ---- Umschlag ----

std::pair<double, double> envFormat(const QVariantMap& p) {
    static const QHash<QString, std::pair<double, double>> f = {
        {"q120", {120, 120}}, {"q155", {155, 155}}, {"c7", {114, 81}}, {"c6", {162, 114}}, {"b6", {176, 125}}, {"dl", {220, 110}}, {"c5", {229, 162}}, {"geld", {170, 90}}};
    const QString id = ps(p, "format");
    if (f.contains(id)) return f.value(id);
    return {need(pd(p, "w"), 30, 300, "Breite"), need(pd(p, "h"), 30, 300, "Höhe")};
}
const Opts ENV = {{"q120", "Quadrat 120 (Karten bis 115)"}, {"q155", "Quadrat 155"}, {"c7", "C7 (114 × 81)"}, {"c6", "C6 (162 × 114)"}, {"b6", "B6 (176 × 125)"},
                  {"dl", "DIN lang (220 × 110)"}, {"c5", "C5 (229 × 162)"}, {"geld", "Geldkuvert (170 × 90)"}, {"frei", "Eigene Maße"}};

GenResult umschlag(const QVariantMap& p, const TS& sh) {
    const auto [W, H] = envFormat(p);
    Net n{QStringLiteral("Umschlag")};
    n.rect(0, 0, W, H);
    // Side flaps narrow by 30 % of the height at each end, the bottom flap by 28 % of the width.
    const double s = std::clamp(W * 0.12, 10.0, 35.0), sa = std::atan2(s, H * 0.3) * 180 / PI;
    const double bf = H * 0.55, ba = std::atan2(bf, W * 0.28) * 180 / PI;
    n.tab({0, H}, {0, 0}, s, sa, sa);
    n.tab({W, 0}, {W, H}, s, sa, sa);
    n.tab({W, H}, {0, H}, bf, ba, ba);
    const double tf = H * 0.42;
    const QString style = ps(p, "flap");
    flap(n, {0, 0}, {W, 0}, tf, style);
    const QString m = ps(p, "deco");
    if (!none(m)) { const double sz = tf * 0.36; n.window(m, {W / 2, -tf * (style == QLatin1String("spitz") ? 0.38 : 0.5)}, sz, sz); }
    if (pb(p, "addrWin")) n.hole(rectP(20, H - 15 - 45, std::min(90.0, W - 40), std::min(45.0, H - 30), 3));
    n.text(sh, ps(p, "text"), pd(p, "textH"), {W * 0.3, H * 0.25}, W * 0.5);
    std::vector<Net> nets{n};
    if (pb(p, "liner")) {
        Net body{QStringLiteral("x")};
        body.rect(0, 0, W, H);
        flap(body, {0, 0}, {W, 0}, tf, style);
        std::vector<PolySet> sets;
        for (const Poly& q : body.solids) { PolySet ps1; ps1.add(q); sets.push_back(ps1); }
        const PolySet inset = offsetPolys(booleanShapes(BooleanOp::Union, sets), -3, JoinKind::Round);
        Net liner{QStringLiteral("Futter")};
        for (PolyView v : inset) liner.solid(Poly(v.begin(), v.end()));
        liner.fold({3, 0}, {W - 3, 0});
        nets.push_back(liner);
    }
    return finish(nets, p, {QStringLiteral("Innenmaß %1 × %2 mm. Gelaserte Seite ist die Vorderseite, alle Klappen gehen nach hinten.").arg(Werkstatt::num(W), Werkstatt::num(H)),
                            QStringLiteral("Seitenklappen zuerst, dann die untere Klappe darauf kleben.")});
}

GenResult pochette(const QVariantMap& p, const TS& sh) {
    static const QHash<QString, std::pair<double, double>> f = {{"a6", {105, 148}}, {"a7", {74, 105}}, {"q140", {140, 140}}, {"dl", {99, 210}}};
    const QString id = ps(p, "format");
    const auto [W, H] = f.contains(id) ? f.value(id) : std::make_pair(need(pd(p, "w"), 30, 250, "Breite"), need(pd(p, "h"), 30, 250, "Höhe"));
    const double Wc = W + 3, Hc = H + 3, ph = Hc * 0.42, fd = Hc * 0.4;
    Net n{QStringLiteral("Pochette")};
    n.rect(0, 0, Wc, Hc);
    n.rect(0, Hc, Wc, ph);
    n.fold({0, Hc}, {Wc, Hc});
    n.tab({0, Hc + ph}, {0, Hc}, 10, 40, 40);
    n.tab({Wc, Hc}, {Wc, Hc + ph}, 10, 40, 40);
    flap(n, {0, 0}, {Wc, 0}, fd, ps(p, "flap"));
    const QString m = ps(p, "deco");
    if (!none(m)) { const double sz = fd * 0.4; n.window(m, {Wc / 2, -fd * 0.45}, sz, sz); }
    n.text(sh, ps(p, "text"), pd(p, "textH"), {Wc / 2, Hc + ph / 2}, Wc * 0.85, 180);
    return finish({n}, p, {QStringLiteral("Für Karten %1 × %2 mm. Die Tasche nach hinten klappen, ihre Seitenlaschen ankleben; die Klappe schließt darüber.").arg(Werkstatt::num(W), Werkstatt::num(H))});
}

GenResult samentuete(const QVariantMap& p, const TS& sh) {
    const double W = need(pd(p, "w"), 30, 200, "Breite"), H = need(pd(p, "h"), 30, 200, "Höhe");
    Net n{QStringLiteral("Tütchen")};
    n.rect(0, 0, W, 2 * H);
    n.fold({0, H}, {W, H});
    n.tab({0, H}, {0, 0}, 11, 35, 35);
    n.tab({W, 0}, {W, H}, 11, 35, 35);
    flap(n, {W, 2 * H}, {0, 2 * H}, std::min(28.0, H * 0.3), ps(p, "flap"));
    const QString m = ps(p, "motif");
    double y = H * 0.18;
    if (!none(m)) { const double s = std::min(W, H) * 0.3; n.engraveShape(movedP(motif(m, s, s), W / 2 - s / 2, y)); y += s + 4; }
    const QString title = ps(p, "title");
    if (!title.trimmed().isEmpty()) { n.text(sh, title, pd(p, "textH"), {W / 2, y + pd(p, "textH") / 2}, W * 0.85, 0, true); y += pd(p, "textH") + 6; }
    if (pb(p, "lines")) {
        const QStringList labels = {QStringLiteral("Gesät am"), QStringLiteral("Ernte")};
        for (const QString& l : labels) {
            if (y + 8 > H - 4) break;
            n.text(sh, l, 3, {W * 0.25, y + 3}, W * 0.4);
            n.markLine({W * 0.46, y + 5}, {W - 6, y + 5});
            y += 9;
        }
    }
    return finish({n}, p, {QStringLiteral("Die Rückseite liegt unten: nach hinten falten, Seitenlaschen ankleben, mit der Klappe schließen.")});
}

GenResult briefbogen(const QVariantMap& p, const TS& sh) {
    static const QHash<QString, std::pair<double, double>> f = {{"a5", {148, 210}}, {"a4", {210, 297}}, {"a6", {105, 148}}};
    const QString id = ps(p, "format");
    const auto [W, H] = f.contains(id) ? f.value(id) : std::make_pair(need(pd(p, "w"), 50, 300, "Breite"), need(pd(p, "h"), 50, 300, "Höhe"));
    const Edge e = edgeFromId(ps(p, "edge"));
    const double size = need(pd(p, "edgeSize"), 4, 30, "Randgröße");
    Net n{QStringLiteral("Briefbogen")};
    const double in = e == Edge::Straight ? 0 : size * 0.46;
    const QString where = ps(p, "edgeWhere");
    const Edge top = e, side = where == QLatin1String("alle") ? e : Edge::Straight;
    decoRect(n, in, in, W - 2 * in, H - 2 * in, {top, side, top, side}, size);
    if (e == Edge::Straight) n.solids = {rectP(0, 0, W, H)};
    const double ml = 18, mr = 14;
    double y0 = 22;
    const QString head = ps(p, "title");
    if (!head.trimmed().isEmpty()) { n.text(sh, head, pd(p, "textH"), {W / 2, 16 + in}, W - ml - mr); y0 = 16 + in + pd(p, "textH") + 8; }
    const QString m = ps(p, "corner");
    if (!none(m)) {
        const double s = std::min(W, H) * 0.08;
        for (Pt c : {Pt{ml / 2 + s / 2 + in, ml / 2 + s / 2 + in}, Pt{W - mr / 2 - s / 2 - in, ml / 2 + s / 2 + in}, Pt{ml / 2 + s / 2 + in, H - ml / 2 - s / 2 - in},
                     Pt{W - mr / 2 - s / 2 - in, H - ml / 2 - s / 2 - in}})
            n.engraveShape(movedP(motif(m, s, s), c.x - s / 2, c.y - s / 2));
    }
    const QString lines = ps(p, "lines");
    if (lines != QLatin1String("keine")) {
        const double step = lines == QLatin1String("eng") ? 6 : 8.5;
        for (double y = y0 + step; y < H - 18 - in; y += step) n.markLine({ml + in, y}, {W - mr - in, y});
    }
    const auto [sw, shh] = sheetSize(p);
    if (e == Edge::Straight && std::abs(W - sw) < 0.5 && std::abs(H - shh) < 0.5) {
        // The sheet itself is the letter: no cut along its edge, only the lines and the engraving.
        n.outputOutline = false;
        return finish({n}, p, {QStringLiteral("Bogen und Briefbogen sind gleich groß: nichts wird ausgeschnitten.")});
    }
    return finish({n}, p);
}

GenResult faltbrief(const QVariantMap& p, const TS& sh) {
    const double W = 210, H = 297;
    Net n{QStringLiteral("Faltbrief")};
    n.rect(0, 0, W, H);
    n.fold({0, H / 3}, {W, H / 3});
    n.fold({0, 2 * H / 3}, {W, 2 * H / 3});
    if (pb(p, "ribbon"))
        for (double x : {W / 2 - 10, W / 2 + 10}) for (double y : {H / 6, H / 2, 5 * H / 6}) n.hole(circleP({x, y}, 4));
    const double y0 = H / 3;
    if (pb(p, "address")) {
        n.markPoly(closedP(rectP(W - 15 - 25, y0 + 8, 25, 30)));
        for (int k = 0; k < 4; ++k) n.markLine({W * 0.48, y0 + 52 + k * 10}, {W - 15, y0 + 52 + k * 10});
        n.markLine({15, y0 + 14}, {W * 0.45, y0 + 14});
        n.text(sh, QStringLiteral("Absender"), 2.6, {35, y0 + 18}, 40);
    }
    n.text(sh, ps(p, "text"), pd(p, "textH"), {W / 2, y0 + H / 6 + 30}, W * 0.5);
    // On an A4 sheet the sheet is the letter: its edges stay uncut, only folds, holes and lines.
    const auto [sw, shh] = sheetSize(p);
    n.outputOutline = !(std::abs(sw - W) < 0.5 && std::abs(shh - H) < 0.5);
    return finish({n}, p, {QStringLiteral("Ein A4-Bogen, in Dritteln nach hinten gefaltet; die gelaserte Mitte ist die Adressseite."),
                             QStringLiteral("Mit einem Band durch die Löcher verschließen.")});
}

// ---- Karte ----

std::pair<double, double> cardFormat(const QVariantMap& p) {
    static const QHash<QString, std::pair<double, double>> f = {{"a6", {105, 148}}, {"a6q", {148, 105}}, {"q145", {145, 145}}, {"q120", {120, 120}},
                                                                {"dl", {99, 210}}, {"a5", {148, 210}}, {"mini", {70, 100}}};
    const QString id = ps(p, "format");
    if (f.contains(id)) return f.value(id);
    return {need(pd(p, "w"), 30, 280, "Breite"), need(pd(p, "h"), 30, 280, "Höhe")};
}
const Opts CARD = {{"a6", "A6 hoch (105 × 148)"}, {"a6q", "A6 quer (148 × 105)"}, {"q145", "Quadrat 145"}, {"q120", "Quadrat 120"},
                   {"dl", "DIN lang (99 × 210)"}, {"a5", "A5 (148 × 210)"}, {"mini", "Mini (70 × 100)"}, {"frei", "Eigene Maße"}};

GenResult klappkarte(const QVariantMap& p, const TS& sh) {
    const auto [W, H] = cardFormat(p);
    const bool left = ps(p, "spine") != QLatin1String("oben");
    const Edge e = edgeFromId(ps(p, "edge"));
    const double es = std::max(6.0, std::min(W, H) / 12);
    const Edge S = Edge::Straight;
    Net n{QStringLiteral("Klappkarte")};
    Pt fc;   // front centre
    if (left) {
        n.rect(0, 0, W, H);
        decoRect(n, W, 0, W, H, {S, e, S, S}, es);
        n.fold({W, 0}, {W, H});
        fc = {1.5 * W, H / 2};
    } else {
        n.rect(0, 0, W, H);
        decoRect(n, 0, H, W, H, {S, S, e, S}, es);
        n.fold({0, H}, {W, H});
        fc = {W / 2, 1.5 * H};
    }
    const QString m = ps(p, "window");
    const auto [ww, wh] = winSize(m, W * 0.8, H * 0.6, pd(p, "winSize"));
    const bool win = !none(m);
    n.window(m, {fc.x, fc.y - H * 0.08}, ww, wh);
    const QString em = ps(p, "engr");
    if (!none(em)) { const double s = std::min(W, H) * 0.3; n.engraveShape(movedP(motif(em, s, s), fc.x - s / 2, fc.y - H * 0.08 - s / 2)); }
    const double ty = (win || !none(em)) ? std::min(fc.y + H / 2 - 10, fc.y - H * 0.08 + std::max(wh, std::min(W, H) * 0.3) / 2 + 12) : fc.y;
    n.text(sh, ps(p, "text"), pd(p, "textH"), {fc.x, ty}, W * 0.85);
    std::vector<Net> nets{n};
    if (pb(p, "insert")) {
        Net ins{QStringLiteral("Einleger")};
        if (left) { ins.rect(0, 0, 2 * W - 8, H - 6); ins.fold({W - 4, 0}, {W - 4, H - 6}, false); }
        else { ins.rect(0, 0, W - 6, 2 * H - 8); ins.fold({0, H - 4}, {W - 6, H - 4}, false); }
        nets.push_back(ins);
    }
    return finish(nets, p, {QStringLiteral("Gelaserte Seite ist außen; die Vorderseite liegt %1.").arg(left ? QStringLiteral("rechts") : QStringLiteral("unten"))});
}

GenResult faltkarte(const QVariantMap& p, const TS& sh) {
    const double W = need(pd(p, "w"), 30, 250, "Breite"), H = need(pd(p, "h"), 30, 280, "Höhe");
    const QString art = ps(p, "art");
    int panels = int(need(pi(p, "panels"), 2, 8, "Felder"));
    std::vector<double> widths;
    if (art == QLatin1String("altar")) widths = {W / 2, W, W / 2};
    else if (art == QLatin1String("wickel")) for (int k = 0; k < panels; ++k) widths.push_back(W - 2.0 * std::max(0, k - 1));
    else for (int k = 0; k < panels; ++k) widths.push_back(W);
    Net n{QStringLiteral("Faltkarte")};
    const Edge e = edgeFromId(ps(p, "edge"));
    const Edge S = Edge::Straight;
    double x = 0;
    for (size_t k = 0; k < widths.size(); ++k) {
        const bool last = k + 1 == widths.size();
        decoRect(n, x, 0, widths[k], H, {S, last ? e : S, S, S}, std::max(6.0, H / 12));
        if (k > 0) n.fold({x, 0}, {x, H}, art == QLatin1String("lepo") ? k % 2 == 1 : true);
        x += widths[k];
    }
    n.text(sh, ps(p, "text"), pd(p, "textH"), {art == QLatin1String("altar") ? W : widths[0] / 2, H / 2}, W * 0.8);
    static const QHash<QString, QString> names = {{"lepo", "Leporello: abwechselnd Berg- und Talfalz."},
                                                  {"wickel", "Wickelfalz: die Felder werden zum Ende 2 mm schmaler, damit sie innen Platz haben."},
                                                  {"altar", "Altarfalz: die halben Flügel schließen sich zur Mitte."}};
    return finish({n}, p, {names.value(art)});
}

struct Step { double x1, x2, d; };
/** Pop-up-Einleger W × 2H mit Mittelfalz und Stufen; Talfalz der Karte außerhalb der Stufen. */
void popupBase(Net& n, double W, double H, const std::vector<Step>& steps) {
    n.rect(0, 0, W, 2 * H);
    std::vector<Step> s = steps;
    std::sort(s.begin(), s.end(), [](const Step& a, const Step& b) { return a.x1 < b.x1; });
    double x = 0;
    for (const Step& st : s) {
        if (st.x1 > x) n.fold({x, H}, {st.x1, H}, false);
        x = st.x2;
    }
    if (x < W) n.fold({x, H}, {W, H}, false);
}
Net coverCard(double W, double H, const TS& sh, const QString& text, double th) {
    Net c{QStringLiteral("Umschlagkarte")};
    c.rect(0, 0, W + 4, 2 * H + 4);
    c.fold({0, H + 2}, {W + 4, H + 2});
    c.text(sh, text, th, {W / 2 + 2, 1.5 * H + 2}, W * 0.85);
    return c;
}

GenResult popupStufen(const QVariantMap& p, const TS& sh) {
    const double W = need(pd(p, "w"), 60, 280, "Breite"), H = need(pd(p, "h"), 40, 200, "Höhe einer Hälfte");
    const int n = int(need(pi(p, "steps"), 1, 7, "Stufen"));
    const double sw = need(pd(p, "stepW"), 5, 100, "Stufenbreite"), gap = need(pd(p, "gap"), 2, 60, "Abstand");
    const double total = n * sw + (n - 1) * gap;
    if (total > W - 16) throw GenError(QStringLiteral("Die Stufen sind zusammen %1 mm breit, die Karte nur %2 mm. Weniger oder schmalere Stufen.").arg(Werkstatt::num(total), Werkstatt::num(W)));
    const QString pat = ps(p, "pattern");
    std::vector<Step> steps;
    for (int k = 0; k < n; ++k) {
        double f = 0.3;
        if (pat == QLatin1String("treppe")) f = 0.14 + 0.3 * (n == 1 ? 1 : double(k) / (n - 1));
        else if (pat == QLatin1String("pyramide")) f = 0.14 + 0.3 * (1 - std::abs(k - (n - 1) / 2.0) / std::max(1.0, (n - 1) / 2.0));
        const double x1 = (W - total) / 2 + k * (sw + gap);
        steps.push_back({x1, x1 + sw, H * f});
    }
    Net in{QStringLiteral("Pop-up-Einleger")};
    popupBase(in, W, H, steps);
    for (const Step& s : steps) {
        in.cut({{s.x1, H - s.d}, {s.x1, H + s.d}});
        in.cut({{s.x2, H - s.d}, {s.x2, H + s.d}});
        in.fold({s.x1, H}, {s.x2, H});
        in.fold({s.x1, H - s.d}, {s.x2, H - s.d}, false);
        in.fold({s.x1, H + s.d}, {s.x2, H + s.d}, false);
    }
    std::vector<Net> nets{in};
    if (pb(p, "cover")) nets.push_back(coverCard(W, H, sh, ps(p, "text"), pd(p, "textH")));
    return finish(nets, p, {QStringLiteral("Einleger zur Hälfte falten, die Stufen nach vorn drücken und in die Umschlagkarte kleben (nur die Ränder).")});
}

GenResult popupMotiv(const QVariantMap& p, const TS& sh) {
    const double W = need(pd(p, "w"), 60, 280, "Breite"), H = need(pd(p, "h"), 40, 200, "Höhe einer Hälfte");
    const int count = int(need(pi(p, "count"), 1, 3, "Anzahl"));
    const double m = need(pd(p, "size"), 15, 180, "Motivgröße"), d = need(pd(p, "depth"), 6, H - 8, "Abstand vom Falz");
    const QString mid = ps(p, "motif");
    const double mw = aspectW(mid, m);
    Net in{QStringLiteral("Pop-up-Einleger")};
    std::vector<Step> steps;
    std::vector<Poly> motifs;
    const double gapM = 8, total = count * mw + (count - 1) * gapM;
    if (total > W - 12) throw GenError(QStringLiteral("Die Motive passen nicht nebeneinander auf die Karte. Kleiner oder weniger."));
    for (int k = 0; k < count; ++k) {
        const double cx = (W - total) / 2 + mw / 2 + k * (mw + gapM);
        const double bottom = H + d * 0.6, topY = bottom - m;
        if (topY < 3) throw GenError(QStringLiteral("Das Motiv ragt oben aus der Karte. Kleiner machen oder näher an den Falz."));
        const Poly M = closedP(movedP(motif(mid, mw, m), cx - mw / 2, topY));
        double xl = 1e9, xr = -1e9;
        for (size_t i = 0; i + 1 < M.size(); ++i) {
            const Pt a = M[i], b = M[i + 1];
            if ((a.y - H) * (b.y - H) <= 0 && a.y != b.y) { const double x = a.x + (b.x - a.x) * (H - a.y) / (b.y - a.y); xl = std::min(xl, x); xr = std::max(xr, x); }
        }
        if (xl > xr) { xl = cx - mw / 4; xr = cx + mw / 4; }
        steps.push_back({xl - 3, xr + 3, d});
        motifs.push_back(M);
    }
    popupBase(in, W, H, steps);
    for (size_t k = 0; k < steps.size(); ++k) {
        const Step& s = steps[k];
        const Poly& M = motifs[k];
        for (const Poly& part : aboveY(M, H)) in.cut(part);
        for (double x : {s.x1, s.x2}) for (const auto& [a, b] : outsideOf({x, H - s.d}, {x, H + s.d}, M)) in.cut({a, b});
        for (const auto& [a, b] : outsideOf({s.x1, H}, {s.x2, H}, M)) in.fold(a, b);
        for (const auto& [a, b] : outsideOf({s.x1, H - s.d}, {s.x2, H - s.d}, M)) in.fold(a, b, false);
        in.fold({s.x1, H + s.d}, {s.x2, H + s.d}, false);
    }
    std::vector<Net> nets{in};
    if (pb(p, "cover")) nets.push_back(coverCard(W, H, sh, ps(p, "text"), pd(p, "textH")));
    return finish(nets, p, {QStringLiteral("Das Motiv steht beim Öffnen vor der Karte. Die Lücke dahinter verdeckt die Umschlagkarte.")});
}

GenResult schuettelkarte(const QVariantMap& p, const TS& sh) {
    const auto [W, H] = cardFormat(p);
    const QString m = ps(p, "window");
    if (none(m)) throw GenError(QStringLiteral("Die Schüttelkarte braucht ein Fenster. Ein Motiv wählen."));
    const auto [ww, wh] = winSize(m, W * 0.85, H * 0.7, pd(p, "winSize"));
    const Pt c{W / 2, H * 0.45};
    std::vector<Net> nets;
    Net front{QStringLiteral("Vorderseite")};
    front.rect(0, 0, W, H, 3);
    front.window(m, c, ww, wh);
    front.text(sh, ps(p, "text"), pd(p, "textH"), {W / 2, std::min(H - 8, c.y + wh / 2 + 10)}, W * 0.85);
    nets.push_back(front);
    PolySet win;
    win.add(movedP(motif(m, ww, wh), c.x - ww / 2, c.y - wh / 2));
    const PolySet big = offsetPolys(win, 3, JoinKind::Round);
    for (int k = 0; k < int(need(pi(p, "spacers"), 1, 6, "Abstandsrahmen")); ++k) {
        Net s{QStringLiteral("Abstandsrahmen %1").arg(k + 1)};
        s.rect(0, 0, W, H, 3);
        for (PolyView v : big) s.hole(Poly(v.begin(), v.end()));
        nets.push_back(s);
    }
    Net back{QStringLiteral("Rückseite")};
    back.rect(0, 0, W, H, 3);
    nets.push_back(back);
    return finish(nets, p, {QStringLiteral("Folie hinter die Vorderseite kleben, Abstandsrahmen darauf, Konfetti hinein, Rückseite zu.")});
}

GenResult tischkarte(const QVariantMap& p, const TS& sh) {
    const double W = need(pd(p, "w"), 40, 200, "Breite"), H = need(pd(p, "h"), 25, 120, "Höhe");
    QStringList names = listOf(ps(p, "names"));
    if (names.isEmpty()) names = {QString()};
    if (names.size() > 60) throw GenError(QStringLiteral("Höchstens 60 Namen auf einmal."));
    const QString mid = ps(p, "motif");
    const double ms = need(pd(p, "size"), 8, H * 1.4, "Motivgröße");
    const QString pos = ps(p, "pos");
    std::vector<Net> nets;
    for (const QString& name : names) {
        Net n{name.isEmpty() ? QStringLiteral("Tischkarte") : name};
        n.rect(0, 0, W, 2 * H);
        double tx = W / 2, tw = W * 0.88, ty = 1.5 * H;
        if (!none(mid)) {
            const double mw = aspectW(mid, ms);
            const double cx = pos == QLatin1String("links") ? 6 + mw / 2 : pos == QLatin1String("rechts") ? W - 6 - mw / 2 : W / 2;
            const double top = H + ms * 0.35 - ms;
            if (top < 1) throw GenError(QStringLiteral("Das Motiv ist zu groß für die Karte."));
            const Poly M = closedP(movedP(motif(mid, mw, ms), cx - mw / 2, top));
            for (const Poly& part : aboveY(M, H)) n.cut(part);
            for (const auto& [a, b] : outsideOf({0, H}, {W, H}, M)) n.fold(a, b);
            if (pos == QLatin1String("mitte")) ty = (H + ms * 0.35 + 2 * H) / 2;
            else { tw = W - mw - 16; tx = pos == QLatin1String("links") ? mw + 10 + tw / 2 : W - mw - 10 - tw / 2; }
        } else {
            n.fold({0, H}, {W, H});
        }
        n.text(sh, name, pd(p, "textH"), {tx, ty}, tw);
        if (pb(p, "both")) n.text(sh, name, pd(p, "textH"), {W - tx, 2 * H - ty}, tw, 180);
        nets.push_back(n);
    }
    return finish(nets, p, {QStringLiteral("%1 Tischkarte(n). Das Motiv ragt nach dem Falten über die Kante.").arg(names.size())});
}

GenResult postkarte(const QVariantMap& p, const TS& sh) {
    const double W = need(pd(p, "w"), 60, 250, "Breite"), H = need(pd(p, "h"), 40, 200, "Höhe"), r = need(pd(p, "r"), 0, 20, "Eckenradius");
    const int count = int(need(pi(p, "count"), 1, 40, "Stück"));
    std::vector<Net> nets;
    for (int k = 0; k < count; ++k) {
        Net n{QStringLiteral("Postkarte %1").arg(k + 1)};
        n.rect(0, 0, W, H, r);
        if (pb(p, "back")) {
            n.markLine({W / 2, 10}, {W / 2, H - 10});
            for (int i = 0; i < 4; ++i) n.markLine({W / 2 + 6, H * 0.45 + i * 10}, {W - 8, H * 0.45 + i * 10});
            n.markPoly(closedP(rectP(W - 8 - 22, 8, 22, 26)));
        }
        n.text(sh, ps(p, "text"), pd(p, "textH"), {pb(p, "back") ? W / 4 : W / 2, H / 2}, pb(p, "back") ? W / 2 - 14 : W * 0.85);
        nets.push_back(n);
    }
    return finish(nets, p);
}

GenResult kaertchen(const QVariantMap& p, const TS& sh) {
    static const QHash<QString, std::pair<double, double>> f = {{"visit", {85, 55}}, {"spiel", {63, 88}}, {"memory", {50, 50}}, {"etikett", {70, 37}}, {"mini", {40, 25}}};
    const QString id = ps(p, "preset");
    const auto [W, H] = f.contains(id) ? f.value(id) : std::make_pair(need(pd(p, "w"), 15, 200, "Breite"), need(pd(p, "h"), 15, 200, "Höhe"));
    const int count = int(need(pi(p, "count"), 1, 200, "Stück"));
    const double r = need(pd(p, "r"), 0, std::min(W, H) / 2, "Eckenradius");
    const QStringList lines = {ps(p, "l1"), ps(p, "l2"), ps(p, "l3")};
    const QString m = ps(p, "motif");
    std::vector<Net> nets;
    for (int k = 0; k < count; ++k) {
        Net n{QStringLiteral("Kärtchen %1").arg(k + 1)};
        n.rect(0, 0, W, H, r);
        double x0 = 0, tw = W;
        if (!none(m)) {
            const double s = H * 0.5;
            n.engraveShape(movedP(motif(m, s, s), H * 0.18, H / 2 - s / 2));
            x0 = s + H * 0.3; tw = W - x0;
        }
        const double hs[3] = {H * 0.16, H * 0.1, H * 0.1};
        int used = 0;
        for (const QString& l : lines) if (!l.trimmed().isEmpty()) ++used;
        double y = H / 2 - (used > 1 ? H * 0.14 * (used - 1) / 2 : 0);
        for (int i = 0; i < 3; ++i) {
            if (lines[i].trimmed().isEmpty()) continue;
            n.text(sh, lines[i], hs[i], {x0 + tw / 2, y}, tw * 0.88, 0, i == 0);
            y += H * 0.15;
        }
        nets.push_back(n);
    }
    return finish(nets, p, {QStringLiteral("%1 Kärtchen %2 × %3 mm.").arg(count).arg(Werkstatt::num(W), Werkstatt::num(H))});
}

GenResult drehscheibe(const QVariantMap& p, const TS& sh) {
    const double D = need(pd(p, "D"), 50, 300, "Durchmesser");
    QStringList labels = listOf(ps(p, "labels"));
    const int n = int(need(labels.isEmpty() ? pi(p, "segments") : labels.size(), 2, 16, "Felder"));
    const double R = D / 2, seg = 2 * PI / n;
    Net base{QStringLiteral("Unterscheibe")};
    base.solid(circleP({}, D));
    base.hole(circleP({}, 3.5));
    for (int k = 0; k < n; ++k) {
        const double a = -PI / 2 + k * seg + seg / 2;
        base.markLine(polar({}, R * 0.14, a), polar({}, R * 0.94, a));
        if (k < labels.size()) {
            const double ac = -PI / 2 + k * seg;
            base.text(sh, labels[k], std::min(pd(p, "textH"), R * 0.14), polar({}, R * 0.62, ac), std::min(R * 0.5, 2 * R * 0.62 * std::sin(seg / 2) * 1.6), ac * 180 / PI + 90);
        }
    }
    Net top{QStringLiteral("Oberscheibe")};
    top.solid(circleP({}, D));
    top.hole(circleP({}, 3.5));
    if (ps(p, "win") == QLatin1String("rund")) top.hole(circleP({0, -R * 0.62}, std::min(R * 0.5, 2 * R * 0.62 * std::sin(seg / 2) * 1.6)));
    else {
        const double a0 = -PI / 2 - seg * 0.42, a1 = -PI / 2 + seg * 0.42;
        Poly w = arcP({}, R * 0.88, a0, a1);
        Poly inner = arcP({}, R * 0.36, a1, a0);
        w.insert(w.end(), inner.begin(), inner.end());
        top.hole(w);
    }
    top.text(sh, ps(p, "title"), pd(p, "textH"), {0, R * 0.42}, R * 1.2);
    for (int k = 0; k < 3; ++k) top.solid(circleP(polar({}, R, PI / 2 + (k - 1) * 0.5), 14));
    return finish({base, top}, p, {QStringLiteral("Beide Scheiben mit einer Musterbeutelklammer durch die Mitte verbinden. Die Nasen am Rand helfen beim Drehen.")});
}

GenResult schieber(const QVariantMap& p, const TS& sh) {
    const double W = need(pd(p, "w"), 60, 250, "Breite"), H = need(pd(p, "h"), 50, 200, "Höhe");
    const double Ls = need(pd(p, "slot"), 20, W - 30, "Weg"), y0 = H * need(pd(p, "slotY"), 20, 80, "Höhe des Schlitzes") / 100;
    const double x0 = (W - Ls) / 2;
    std::vector<Net> nets;
    Net front{QStringLiteral("Vorderkarte")};
    front.rect(0, 0, W, H, 3);
    front.hole(rectP(x0 - 1.5, y0 - 1.5, Ls + 3, 3, 1.5));
    front.text(sh, ps(p, "text"), pd(p, "textH"), {W / 2, y0 < H / 2 ? H * 0.75 : H * 0.25}, W * 0.85);
    nets.push_back(front);
    Net back{QStringLiteral("Rückkarte")};
    back.rect(0, 0, W, H, 3);
    nets.push_back(back);
    Net strip{QStringLiteral("Schieber")};
    strip.rect(0, 0, W + 20 - x0, 14, 4);
    nets.push_back(strip);
    if (y0 - 9 > 8) { Net g{QStringLiteral("Führung oben")}; g.rect(0, 0, W, y0 - 9); nets.push_back(g); }
    if (H - y0 - 9 > 8) { Net g{QStringLiteral("Führung unten")}; g.rect(0, 0, W, H - y0 - 9); nets.push_back(g); }
    const QString m = ps(p, "motif");
    const double s = need(pd(p, "size"), 10, H * 0.8, "Motivgröße");
    Net mo{QStringLiteral("Motiv")};
    mo.solid(motif(none(m) ? QStringLiteral("stern") : m, s, s));
    nets.push_back(mo);
    Net steg{QStringLiteral("Steg")};
    steg.rect(0, 0, 2.5, 18);
    nets.push_back(steg);
    return finish(nets, p, {QStringLiteral("Führungen auf die Rückkarte kleben, Schieber dazwischen, Vorderkarte darauf. Den Steg durch den Schlitz stecken und Motiv und Schieber daran kleben.")});
}

// ---- Deko ----

/** Anhänger-Form mit Loch. */
void tagShape(Net& n, const QString& form, double W, double H, double holeD) {
    double hx = W / 2, hy = holeD + 2;
    if (form == QLatin1String("etikett")) {
        const double c = W * 0.28;
        n.solid({{c, 0}, {W - c, 0}, {W, c}, {W, H}, {0, H}, {0, c}});
        hy = c * 0.85;
    } else if (form == QLatin1String("rund")) { n.solid(circleP({W / 2, W / 2}, W)); hy = W * 0.13; }
    else if (form == QLatin1String("kugel")) {
        n.solid(circleP({W / 2, W * 0.2 + W / 2}, W));
        n.rect(W * 0.36, 0, W * 0.28, W * 0.24, 1);
        hy = W * 0.11;
        holeD = std::min(holeD, W * 0.28 - 3);
    } else if (form == QLatin1String("abgerundet")) { n.rect(0, 0, W, H, std::min(W, H) * 0.12); }
    else {
        n.solid(motif(form, W, H));
        if (form == QLatin1String("herz")) { hx = W * 0.3; hy = H * 0.24; }
        else if (form == QLatin1String("stern") || form == QLatin1String("stern6")) hy = H * 0.2;
        else hy = H * 0.13;
    }
    if (holeD > 0.5) n.hole(circleP({hx, hy}, holeD));
}

GenResult anhaenger(const QVariantMap& p, const TS& sh) {
    const QString form = ps(p, "form");
    double W = need(pd(p, "w"), 15, 200, "Breite"), H = need(pd(p, "h"), 15, 250, "Höhe");
    if (form == QLatin1String("rund") || form == QLatin1String("kugel")) H = W * (form == QLatin1String("kugel") ? 1.2 : 1);
    QStringList texts = listOf(ps(p, "names"));
    const int count = texts.isEmpty() ? int(need(pi(p, "count"), 1, 200, "Stück")) : int(texts.size());
    if (count > 200) throw GenError(QStringLiteral("Höchstens 200 Anhänger auf einmal."));
    const QString m = ps(p, "motif");
    std::vector<Net> nets;
    for (int k = 0; k < count; ++k) {
        const QString t = texts.isEmpty() ? ps(p, "text") : texts[k];
        Net n{t.isEmpty() ? QStringLiteral("Anhänger %1").arg(k + 1) : t};
        double cy = H * 0.6;
        if (form == QLatin1String("klapp")) {
            n.rect(0, 0, W, 2 * H, std::min(W, H) * 0.1);
            n.fold({0, H}, {W, H});
            const double hd = pd(p, "hole");
            if (hd > 0.5) { n.hole(circleP({W / 2, H - 6}, hd)); n.hole(circleP({W / 2, H + 6}, hd)); }
            cy = H * 1.6;
        } else {
            tagShape(n, form, W, H, pd(p, "hole"));
        }
        if (!none(m)) { const double s = W * 0.34; n.engraveShape(movedP(motif(m, s, s), W / 2 - s / 2, cy - s - 2)); }
        n.text(sh, t, pd(p, "textH"), {W / 2, none(m) ? cy : cy + pd(p, "textH") / 2}, W * 0.78);
        nets.push_back(n);
    }
    return finish(nets, p, {QStringLiteral("%1 Anhänger.").arg(count)});
}

GenResult lesezeichen(const QVariantMap& p, const TS& sh) {
    if (ps(p, "art") == QLatin1String("ecke")) {
        const double s = need(pd(p, "corner"), 30, 120, "Größe");
        Net n{QStringLiteral("Eckenlesezeichen")};
        n.solid({{0, 0}, {s, 0}, {0, s}});
        n.solid({{0, 0}, {0, -s}, {s, 0}});
        n.fold({0, 0}, {s, 0});
        n.tab({0, 0}, {0, -s}, 10, 45, 45);
        if (pb(p, "monster")) {
            // Zähne an der offenen Kante, zwei Augen.
            n.solids.erase(n.solids.begin());
            const EdgeLine el = decoratedEdge({s, 0}, {0, s}, Edge::Zigzag, s / 7);
            Poly front{{0, 0}};
            front.insert(front.end(), el.line.begin(), el.line.end());
            n.solid(front);
            n.hole(circleP({s * 0.2, s * 0.32}, s * 0.12));
            n.hole(circleP({s * 0.38, s * 0.14}, s * 0.1));
        }
        n.text(sh, ps(p, "text"), pd(p, "textH"), {s * 0.3, s * 0.42}, s * 0.45, 0);
        return finish({n}, p, {QStringLiteral("Die hintere Hälfte nach hinten klappen und die Lasche umkleben: die offene Kante kommt über die Seitenecke.")});
    }
    const double W = need(pd(p, "w"), 15, 100, "Breite"), H = need(pd(p, "h"), 50, 280, "Länge");
    const QString end = ps(p, "end");
    const double e = end == QLatin1String("gerade") ? 0 : W * 0.5;
    const double r = W * 0.15;
    Net n{QStringLiteral("Lesezeichen")};
    Poly b{{0, H - e}};
    Poly a1 = arcP({r, r}, r, PI, 1.5 * PI);
    b.insert(b.end(), a1.begin(), a1.end());
    Poly a2 = arcP({W - r, r}, r, 1.5 * PI, 2 * PI);
    b.insert(b.end(), a2.begin(), a2.end());
    b.push_back({W, H - e});
    if (end == QLatin1String("spitz")) b.push_back({W / 2, H});
    else if (end == QLatin1String("rund")) { const Poly arc = bulge({W, H - e}, {0, H - e}, e); b.insert(b.end(), arc.begin() + 1, arc.end() - 1); }
    else if (end == QLatin1String("schwalbe")) { b.push_back({W, H}); b.push_back({W / 2, H - e}); b.push_back({0, H}); }
    n.solid(b);
    if (pb(p, "hole")) n.hole(circleP({W / 2, W * 0.24}, 5));
    const QString m = ps(p, "pattern");
    const QString txt = ps(p, "text");
    const double yTop = W * 0.48, yBot = (txt.trimmed().isEmpty() ? H - e - W * 0.25 : H * 0.55);
    if (!none(m)) {
        const int cols = W < 38 ? 1 : 2;
        const double s = W * (cols == 1 ? 0.42 : 0.26), step = s * 1.55;
        const int rows = std::max(1, int((yBot - yTop) / step));
        for (int rI = 0; rI < rows; ++rI)
            for (int c = 0; c < cols; ++c) {
                const double cx = cols == 1 ? W / 2 : W * (rI % 2 ? (c ? 0.72 : 0.28) : (c ? 0.66 : 0.34));
                const double cy = yTop + step * (rI + 0.5);
                n.hole(movedP(motif(m, s, s), cx - s / 2, cy - s / 2));
            }
    }
    n.text(sh, txt, std::min(pd(p, "textH"), W * 0.5), {W / 2, (yBot + H - e) / 2}, (H - e - yBot) * 0.92, -90);
    return finish({n}, p);
}

GenResult girlande(const QVariantMap& p, const TS& sh) {
    const QString form = ps(p, "form");
    const double W = need(pd(p, "w"), 20, 250, "Breite"), H = need(pd(p, "h"), 20, 280, "Höhe");
    QString text = ps(p, "text");
    const int count = text.trimmed().isEmpty() ? int(need(pi(p, "count"), 1, 60, "Stück")) : int(text.size());
    if (count > 60) throw GenError(QStringLiteral("Höchstens 60 Wimpel auf einmal."));
    const bool strip = ps(p, "hang") == QLatin1String("lasche");
    const QString m = ps(p, "motif");
    std::vector<Net> nets;
    for (int k = 0; k < count; ++k) {
        const QString ch = text.trimmed().isEmpty() ? QString() : QString(text[k]);
        Net n{ch.trimmed().isEmpty() ? QStringLiteral("Wimpel %1").arg(k + 1) : QStringLiteral("Wimpel %1").arg(ch)};
        double cy = H * 0.42;
        if (form == QLatin1String("dreieck")) { n.solid({{0, 0}, {W, 0}, {W / 2, H}}); cy = H * 0.33; }
        else if (form == QLatin1String("schwalbe")) n.solid({{0, 0}, {W, 0}, {W, H}, {W / 2, H * 0.72}, {0, H}});
        else if (form == QLatin1String("rund")) {
            Poly q{{0, 0}, {W, 0}, {W, H - W / 2}};
            const Poly arc = bulge({W, H - W / 2}, {0, H - W / 2}, W / 2);
            q.insert(q.end(), arc.begin() + 1, arc.end());
            n.solid(q);
        } else if (form == QLatin1String("rechteck")) n.rect(0, 0, W, H);
        else { n.solid(motif(form, W, H)); cy = H * 0.5; }
        if (strip) { n.rect(0, -14, W, 14); n.fold({0, 0}, {W, 0}); }
        else { n.hole(circleP({W * 0.14, 6}, 4)); n.hole(circleP({W * 0.86, 6}, 4)); }
        if (!ch.trimmed().isEmpty()) n.text(sh, ch, pd(p, "textH"), {W / 2, cy}, W * 0.7, 0, true);
        else if (!none(m)) { const double s = W * 0.4; n.engraveShape(movedP(motif(m, s, s), W / 2 - s / 2, cy - s / 2)); }
        nets.push_back(n);
    }
    return finish(nets, p, {strip ? QStringLiteral("Die Lasche über die Schnur falten und festkleben.") : QStringLiteral("Die Schnur durch die zwei Löcher fädeln.")});
}

GenResult stern3d(const QVariantMap& p, const TS&) {
    const int pts = int(need(pi(p, "points"), 4, 10, "Zacken"));
    const double D = need(pd(p, "D"), 30, 280, "Durchmesser"), ratio = need(pd(p, "ratio"), 25, 75, "Innenradius") / 100;
    const double R = D / 2, r = R * ratio;
    std::vector<Net> nets;
    for (int k = 0; k < 2; ++k) {
        Net n{k == 0 ? QStringLiteral("Stern vorn") : QStringLiteral("Stern hinten")};
        Poly s;
        for (int i = 0; i < 2 * pts; ++i) s.push_back(polar({}, i % 2 ? r : R, -PI / 2 + i * PI / pts));
        n.solid(s);
        for (int i = 0; i < 2 * pts; ++i) n.fold({0, 0}, s[i], i % 2 == 0);
        if (k == 0 && pb(p, "hole")) n.hole(circleP({0, -R * 0.78}, std::max(2.0, R * 0.05)));
        nets.push_back(n);
    }
    return finish(nets, p, {QStringLiteral("Beide Sterne falten (Grate zum Laser hin) und Rücken an Rücken an den Kanten zusammenkleben.")});
}

GenResult schneeflocke(const QVariantMap& p, const TS&) {
    const double D = need(pd(p, "D"), 20, 280, "Durchmesser");
    const int count = int(need(pi(p, "count"), 1, 60, "Stück")), seed = pi(p, "seed"), arms = pi(p, "arms") == 8 ? 8 : 6;
    const double minW = std::max(0.8, thickness(p) * 3);
    std::vector<Net> nets;
    for (int k = 0; k < count; ++k) {
        PolySet f = snowflake(D, seed + k, arms, minW);
        if (pb(p, "hole")) {
            PolySet ring;
            ring.add(circleP({0, -D / 2 - 2}, 8));
            f = booleanOp(BooleanOp::Union, f, ring);
            PolySet h;
            h.add(circleP({0, -D / 2 - 2}, 3.5));
            f = booleanOp(BooleanOp::Subtract, f, h);
        }
        Net n{QStringLiteral("Schneeflocke %1").arg(seed + k)};
        n.cuts = f;
        nets.push_back(n);
    }
    return finish(nets, p, {QStringLiteral("Jede Flocke hat ihr eigenes Muster aus der Zahl %1 aufwärts. Andere Zahl, andere Flocken.").arg(seed)});
}

GenResult mandala(const QVariantMap& p, const TS&) {
    const double D = need(pd(p, "D"), 40, 280, "Durchmesser");
    const int sym = int(need(pi(p, "sym"), 4, 32, "Symmetrie")), rings = int(need(pi(p, "rings"), 1, 6, "Ringe")), seed = pi(p, "seed");
    const double R = D / 2;
    std::mt19937 rng(uint32_t(seed) * 2246822519u + 3u);
    Net n{QStringLiteral("Spitzendeckchen")};
    const Edge e = edgeFromId(ps(p, "edge"));
    const int chords = sym * 2;
    Poly outline;
    for (int k = 0; k < chords; ++k) {
        const Pt a = polar({}, R * 0.94, 2 * PI * k / chords), b = polar({}, R * 0.94, 2 * PI * (k + 1) / chords);
        const EdgeLine el = decoratedEdge(a, b, e == Edge::Straight ? Edge::Straight : e, plen(psub(b, a)));
        outline.insert(outline.end(), el.line.begin(), el.line.end() - 1);
        for (const Poly& h : el.holes) n.hole(h);
    }
    if (e == Edge::Straight) outline = circleP({}, D);
    n.solid(outline);
    static const QStringList kinds = {"kreis", "tropfen", "herz", "raute", "blume", "stern", "ei"};
    const double band = R * 0.66 / rings;
    for (int i = 0; i < rings; ++i) {
        const double rc = R * 0.2 + band * (i + 0.5);
        const QString kind = kinds[rng() % kinds.size()];
        const int cnt = sym * (rc * 2 * PI / sym > band * 2.2 ? 2 : 1);
        const double s = std::min(band * 0.72, 2 * PI * rc / cnt * 0.62);
        const double off = (i % 2) * PI / cnt;
        for (int k = 0; k < cnt; ++k) {
            const double a = 2 * PI * k / cnt + off;
            const Pt c = polar({}, rc, a);
            n.hole(rotatedP(movedP(motif(kind, s * (kind == "tropfen" || kind == "ei" ? 0.62 : 1), s), c.x - s * (kind == "tropfen" || kind == "ei" ? 0.31 : 0.5), c.y - s / 2), a + PI / 2, c));
        }
    }
    n.hole(movedP(motif(sym % 6 == 0 ? QStringLiteral("stern6") : QStringLiteral("blume"), R * 0.24, R * 0.24), -R * 0.12, -R * 0.12));
    return finish({n}, p, {QStringLiteral("Feine Stege: dünnes Papier und kleine Leistung, damit nichts verbrennt.")});
}

GenResult laterne(const QVariantMap& p, const TS&) {
    const double U = need(pd(p, "U"), 60, 400, "Umfang"), H = need(pd(p, "h"), 40, 280, "Höhe");
    const QString art = ps(p, "art");
    const Edge e = edgeFromId(ps(p, "edge"));
    const Edge S = Edge::Straight;
    Net n{QStringLiteral("Laterne")};
    decoRect(n, 0, 0, U, H, {e, S, e, S}, std::max(6.0, U / 24));
    n.tab({U, 0}, {U, H}, 12, 45, 45);
    const QString m = ps(p, "motif");
    if (art == QLatin1String("schlitze")) {
        for (double x = 10; x < U - 6; x += 12) n.cut({{x, 25}, {x, H - 25}});
        n.fold({0, H / 2}, {U, H / 2}, false);
    } else if (art == QLatin1String("muster")) {
        const double s = need(pd(p, "size"), 6, 60, "Motivgröße"), step = s * 1.7;
        const int cols = std::max(1, int((U - 8) / step)), rows = std::max(1, int((H - 30) / step));
        const double ox = (U - cols * step) / 2, oy = (H - rows * step) / 2;
        for (int r = 0; r < rows; ++r)
            for (int c = 0; c < cols; ++c) {
                const double cx = ox + step * (c + 0.5 + (r % 2 ? 0.25 : -0.25)), cy = oy + step * (r + 0.5);
                if (cx - s / 2 < 4 || cx + s / 2 > U - 4) continue;
                n.window(none(m) ? QStringLiteral("stern") : m, {cx, cy}, s, s);
            }
    } else {
        const int panels = int(need(pi(p, "panels"), 3, 12, "Seiten"));
        const double pw = U / panels;
        for (int k = 1; k < panels; ++k) n.fold({k * pw, 0}, {k * pw, H});
        const auto [ww, wh] = winSize(none(m) ? QStringLiteral("bogen") : m, pw * 0.75, H * 0.7, 85);
        for (int k = 0; k < panels; ++k) n.window(none(m) ? QStringLiteral("bogen") : m, {pw * (k + 0.5), H / 2}, ww, wh);
    }
    std::vector<Net> nets{n};
    if (pb(p, "handle")) { Net hd{QStringLiteral("Henkel")}; hd.rect(0, 0, 12, U / PI + 70, 3); nets.push_back(hd); }
    return finish(nets, p, {}, {QStringLiteral("Nur mit LED-Teelicht verwenden, nie mit einer Kerze.")});
}

GenResult steckfigur(const QVariantMap& p, const TS&) {
    const QString m = ps(p, "motif");
    const double H = need(pd(p, "h"), 30, 280, "Höhe");
    const double W = aspectW(m, H);
    const double sw = thickness(p) + 0.3;
    const int sets = int(need(pi(p, "count"), 1, 20, "Stück"));
    std::vector<Net> nets;
    for (int k = 0; k < sets; ++k) {
        Net a{QStringLiteral("Figur %1 A").arg(k + 1)}, b{QStringLiteral("Figur %1 B").arg(k + 1)};
        a.solid(motif(m, W, H));
        b.solid(motif(m, W, H));
        a.hole(rectP(W / 2 - sw / 2, -1, sw, H / 2 + 1));
        b.hole(rectP(W / 2 - sw / 2, H / 2, sw, H / 2 + 1));
        nets.push_back(a);
        nets.push_back(b);
    }
    return finish(nets, p, {QStringLiteral("Schlitze %1 mm breit (Papierstärke plus 0,3). Teil A von oben auf Teil B stecken.").arg(Werkstatt::num(sw, 2))});
}

GenResult passepartout(const QVariantMap& p, const TS& sh) {
    const double W = need(pd(p, "w"), 40, 300, "Breite"), H = need(pd(p, "h"), 40, 300, "Höhe");
    const int cols = int(need(pi(p, "cols"), 1, 6, "Spalten")), rows = int(need(pi(p, "rows"), 1, 6, "Zeilen"));
    const double fw = need(pd(p, "fw"), 10, W - 10, "Fensterbreite"), fh = need(pd(p, "fh"), 10, H - 10, "Fensterhöhe");
    const double gap = 8, tw = cols * fw + (cols - 1) * gap, th = rows * fh + (rows - 1) * gap;
    if (tw > W - 10 || th > H - 10) throw GenError(QStringLiteral("Die Fenster passen nicht in den Rahmen. Kleiner oder weniger Fenster."));
    const QString shape = ps(p, "shape");
    Net n{QStringLiteral("Passepartout")};
    n.rect(0, 0, W, H);
    const QString txt = ps(p, "text");
    const double cyAll = txt.trimmed().isEmpty() ? H * 0.47 : H * 0.44;
    for (int r = 0; r < rows; ++r)
        for (int c = 0; c < cols; ++c) {
            const double cx = (W - tw) / 2 + fw / 2 + c * (fw + gap), cy = cyAll - th / 2 + fh / 2 + r * (fh + gap);
            if (shape == QLatin1String("rechteck")) n.hole(rectP(cx - fw / 2, cy - fh / 2, fw, fh));
            else n.window(shape, {cx, cy}, fw, fh);
        }
    n.text(sh, txt, pd(p, "textH"), {W / 2, std::min(H - 6, cyAll + th / 2 + (H - cyAll - th / 2) / 2)}, W * 0.85);
    std::vector<Net> nets{n};
    if (pb(p, "back")) { Net b{QStringLiteral("Rückwand")}; b.rect(0, 0, W - 1, H - 1); nets.push_back(b); }
    if (pb(p, "stand")) {
        Net s{QStringLiteral("Aufsteller")};
        s.solid({{0, 0}, {40, 0}, {40, H * 0.7}, {0, H * 0.7 - 8}});
        s.fold({0, 25}, {40, 25});
        nets.push_back(s);
    }
    return finish(nets, p, {QStringLiteral("Fotos hinter die Fenster kleben, Rückwand dahinter. Den Aufsteller am oberen Teil ankleben.")});
}

GenResult stanzformen(const QVariantMap& p, const TS&) {
    const double s = need(pd(p, "size"), 5, 150, "Größe"), gap = need(pd(p, "gap"), 1, 30, "Abstand");
    const bool fill = pb(p, "fill");
    const int want = fill ? 100000 : int(need(pi(p, "count"), 1, 500, "Stück"));
    const auto [SW, SH] = sheetSize(p);
    const double aw = SW - 12, ah = SH - 12;
    const int cols = std::max(1, int((aw + gap) / (s + gap))), rows = std::max(1, int((ah + gap) / (s + gap)));
    std::mt19937 rng(uint32_t(pi(p, "seed")) * 747796405u + 1u);
    std::uniform_real_distribution<double> U(0.55, 1.0);
    static const QStringList mix = {"herz", "stern", "kreis", "blume", "mond", "wolke", "schmetterling", "tanne", "ballon", "krone"};
    const QString m = ps(p, "motif");
    const bool mixed = pb(p, "mixMotifs"), sizes = pb(p, "mixSizes");
    Net n{QStringLiteral("Streuteile")};
    int made = 0;
    for (int r = 0; r < rows && made < want; ++r)
        for (int c = 0; c < cols && made < want; ++c) {
            const QString kind = mixed ? mix[(r * cols + c + pi(p, "seed")) % mix.size()] : m;
            const double k = sizes ? U(rng) : 1.0, sz = s * k;
            const double cx = c * (s + gap) + s / 2, cy = r * (s + gap) + s / 2;
            const auto [ww, wh] = winSize(kind, sz, sz, 100);
            n.solid(movedP(motif(kind, ww, wh), cx - ww / 2, cy - wh / 2));
            ++made;
        }
    if (!fill && made < want) {
        // More than one sheet: the rest as further pieces.
        std::vector<Net> nets{n};
        int left = want - made, part = 2;
        while (left > 0) {
            Net more{QStringLiteral("Streuteile %1").arg(part++)};
            int k2 = 0;
            for (int r = 0; r < rows && k2 < left; ++r)
                for (int c = 0; c < cols && k2 < left; ++c, ++k2) {
                    const QString kind = mixed ? mix[(r * cols + c + k2) % mix.size()] : m;
                    const double sz = s * (sizes ? U(rng) : 1.0);
                    const auto [ww, wh] = winSize(kind, sz, sz, 100);
                    more.solid(movedP(motif(kind, ww, wh), c * (s + gap) + s / 2 - ww / 2, r * (s + gap) + s / 2 - wh / 2));
                }
            left -= k2;
            nets.push_back(more);
        }
        return finish(nets, p, {QStringLiteral("%1 Teile.").arg(want)});
    }
    return finish({n}, p, {QStringLiteral("%1 Teile.").arg(made)});
}

GenResult rosette(const QVariantMap& p, const TS& sh) {
    const double pitch = need(pd(p, "pitch"), 5, 40, "Faltbreite"), w = need(pd(p, "w"), 15, 150, "Breite");
    const int folds = int(need(pi(p, "folds"), 8, 120, "Falten"));
    const auto [SW, SH] = sheetSize(p);
    const double maxLen = std::max(SW, SH) - 12;
    const int perStrip = std::max(2, int((maxLen - pitch) / pitch) / 2 * 2);
    const Edge e = edgeFromId(ps(p, "edge"));
    const Edge S = Edge::Straight;
    std::vector<Net> nets;
    int done = 0, idx = 1;
    while (done < folds) {
        const int k = std::min(perStrip, folds - done);
        const bool more = done + k < folds;
        const double len = k * pitch + (more ? pitch : 0);
        Net n{QStringLiteral("Streifen %1").arg(idx++)};
        decoRect(n, 0, 0, len, w, {e, S, S, S}, pitch);
        for (int i = 1; i * pitch < len - 0.1; ++i) n.fold({i * pitch, 0}, {i * pitch, w}, (done + i) % 2 == 1);
        nets.push_back(n);
        done += k;
    }
    const double cd = need(pd(p, "center"), 20, 150, "Mitte");
    Net front{QStringLiteral("Mitte vorn")};
    front.solid(circleP({}, cd));
    front.text(sh, ps(p, "text"), pd(p, "textH"), {}, cd * 0.75);
    Net back{QStringLiteral("Mitte hinten")};
    back.solid(circleP({}, cd));
    nets.push_back(front);
    nets.push_back(back);
    return finish(nets, p, {QStringLiteral("Streifen im Zickzack falten, aneinanderkleben (je ein Feld überlappt), zum Kreis legen und die Mitten vorn und hinten aufkleben.")});
}

GenResult kalender(const QVariantMap& p, const TS& sh) {
    const int month = int(need(pi(p, "month"), 1, 12, "Monat")), year = int(need(pi(p, "year"), 1900, 2200, "Jahr"));
    const double W = need(pd(p, "w"), 80, 300, "Breite"), H = need(pd(p, "h"), 80, 300, "Höhe");
    Net n{QStringLiteral("Kalenderblatt")};
    n.rect(0, 0, W, H);
    if (pb(p, "hole")) n.hole(circleP({W / 2, 6}, 5));
    double y = 14;
    if (pb(p, "photo")) { n.markPoly(closedP(rectP(10, 12, W - 20, H * 0.42))); y = 12 + H * 0.42 + 6; }
    const QLocale de(QLocale::German);
    const double th = need(pd(p, "textH"), 3, 30, "Schrifthöhe");
    n.text(sh, de.standaloneMonthName(month) + QStringLiteral(" ") + QString::number(year), th, {W / 2, y + th / 2}, W - 20, 0, true);
    y += th + 6;
    const QDate first(year, month, 1);
    const int lead = first.dayOfWeek() - 1, days = first.daysInMonth();
    const int weeks = (lead + days + 6) / 7;
    const double x0 = 8, cw = (W - 16) / 7, hh = std::min(5.0, cw * 0.32);
    static const char* wd[] = {"Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"};
    for (int c = 0; c < 7; ++c) n.text(sh, QString::fromLatin1(wd[c]), hh * 0.8, {x0 + cw * (c + 0.5), y + hh / 2}, cw * 0.9);
    y += hh + 3;
    const double ch = (H - 8 - y) / weeks, nh = std::min({ch * 0.3, cw * 0.35, 6.0});
    for (int d = 1; d <= days; ++d) {
        const int cell = lead + d - 1, r = cell / 7, c = cell % 7;
        n.text(sh, QString::number(d), nh, {x0 + cw * (c + 0.5), y + ch * r + nh / 2 + 1.5}, cw * 0.9, 0, c == 6);
    }
    if (pb(p, "grid")) {
        for (int r = 0; r <= weeks; ++r) n.markLine({x0, y + r * ch - 0.5}, {W - 8, y + r * ch - 0.5});
        for (int c = 0; c <= 7; ++c) n.markLine({x0 + c * cw, y - 0.5}, {x0 + c * cw, y + weeks * ch - 0.5});
    }
    return finish({n}, p, {QStringLiteral("%1 %2: %3 Tage, beginnt am %4.").arg(de.standaloneMonthName(month)).arg(year).arg(days).arg(de.dayName(first.dayOfWeek()))});
}

// ---- Körper ----

GenResult wuerfel(const QVariantMap& p, const TS& sh) {
    const double w = need(pd(p, "w"), 10, 200, "Breite"), d = need(pd(p, "d"), 10, 200, "Tiefe"), h = need(pd(p, "h"), 10, 200, "Höhe");
    Net n{QStringLiteral("Quader")};
    const std::vector<std::vector<Pt>> faces = {
        {{0, d}, {d, d}, {d, d + h}, {0, d + h}},                                     // links
        {{d, d}, {d + w, d}, {d + w, d + h}, {d, d + h}},                             // vorn
        {{d + w, d}, {2 * d + w, d}, {2 * d + w, d + h}, {d + w, d + h}},             // rechts
        {{2 * d + w, d}, {2 * d + 2 * w, d}, {2 * d + 2 * w, d + h}, {2 * d + w, d + h}},   // hinten
        {{d, 0}, {d + w, 0}, {d + w, d}, {d, d}},                                     // oben
        {{d, d + h}, {d + w, d + h}, {d + w, 2 * d + h}, {d, 2 * d + h}},             // unten
    };
    facesNet(n, faces, std::min({10.0, w * 0.3, d * 0.3, h * 0.3}), true);
    if (pb(p, "pips")) {
        const int value[6] = {3, 1, 4, 6, 2, 5};
        static const std::vector<std::vector<std::pair<double, double>>> layout = {
            {}, {{0.5, 0.5}}, {{0.25, 0.25}, {0.75, 0.75}}, {{0.25, 0.25}, {0.5, 0.5}, {0.75, 0.75}},
            {{0.25, 0.25}, {0.75, 0.25}, {0.25, 0.75}, {0.75, 0.75}}, {{0.25, 0.25}, {0.75, 0.25}, {0.5, 0.5}, {0.25, 0.75}, {0.75, 0.75}},
            {{0.25, 0.25}, {0.75, 0.25}, {0.25, 0.5}, {0.75, 0.5}, {0.25, 0.75}, {0.75, 0.75}}};
        for (int f = 0; f < 6; ++f) {
            const auto& q = faces[f];
            const double fx = q[0].x, fy = q[0].y, fw = q[1].x - q[0].x, fh = q[2].y - q[1].y;
            const double dot = std::min(fw, fh) * 0.17;
            for (auto [u, v] : layout[value[f]]) n.engraveShape(circleP({fx + fw * u, fy + fh * v}, dot));
        }
    } else {
        n.text(sh, ps(p, "text"), pd(p, "textH"), {d + w / 2, d + h / 2}, w * 0.85);
    }
    return finish({n}, p, {QStringLiteral("Laschen sitzen an jeder zweiten Außenkante: jede Kante wird genau einmal geklebt.")});
}

/** Netze der Körper als Flächen. */
std::vector<std::vector<Pt>> solidNet(const QString& kind, double a, int n) {
    std::vector<std::vector<Pt>> f;
    const double h = a * std::sqrt(3.0) / 2;
    if (kind == QLatin1String("tetra")) {
        const Pt A{0, 2 * h}, B{2 * a, 2 * h}, C{a, 0}, AB{a, 2 * h}, BC{1.5 * a, h}, CA{0.5 * a, h};
        f = {{A, AB, CA}, {AB, B, BC}, {CA, BC, C}, {AB, BC, CA}};
    } else if (kind == QLatin1String("okta")) {
        std::vector<Pt> P;
        for (int k = 0; k <= 4; ++k) P.push_back(polar({}, a, rad(-120 + k * 60)));
        for (int k = 0; k < 4; ++k) {
            f.push_back({Pt{0, 0}, P[k], P[k + 1]});
            f.push_back({P[k], padd(P[k], P[k + 1]), P[k + 1]});
        }
    } else if (kind == QLatin1String("ikosa")) {
        for (int k = 0; k < 5; ++k) {
            const Pt T0{k * a, h}, T1{(k + 1) * a, h}, B0{k * a + a / 2, 2 * h}, B1{(k + 1) * a + a / 2, 2 * h};
            f.push_back({T0, T1, B0});
            f.push_back({B0, T1, B1});
            f.push_back({T0, Pt{k * a + a / 2, 0}, T1});
            f.push_back({B0, B1, Pt{(k + 1) * a, 3 * h}});
        }
    } else if (kind == QLatin1String("dodeka")) {
        const std::vector<Pt> c = regular(5, a, {});
        std::vector<std::vector<Pt>> ros{c};
        const auto reflect = [](const std::vector<Pt>& poly, Pt p, Pt q) {
            std::vector<Pt> out;
            const Pt u = punit(psub(q, p));
            for (const Pt& v : poly) {
                const Pt w = psub(v, p);
                const double t = w.x * u.x + w.y * u.y;
                const Pt foot = padd(p, pmul(u, t));
                out.push_back(psub(pmul(foot, 2), v));
            }
            return out;
        };
        for (int k = 0; k < 5; ++k) ros.push_back(reflect(c, c[k], c[(k + 1) % 5]));
        // Second rosette: turned by 180 degrees about the middle of an outer edge of an outer pentagon.
        const std::vector<Pt>& q = ros[1];
        Pt m{};
        double best = -1;
        for (int k = 0; k < 5; ++k) {
            const Pt mid = plerp(q[k], q[(k + 1) % 5], 0.5);
            if (plen(mid) > best) { best = plen(mid); m = mid; }
        }
        f = ros;
        for (const auto& poly : ros) {
            std::vector<Pt> r;
            for (const Pt& v : poly) r.push_back(psub(pmul(m, 2), v));
            f.push_back(r);
        }
    } else if (kind == QLatin1String("prisma")) {
        const double H = a * 1.6;
        for (int k = 0; k < n; ++k) f.push_back({{k * a, 0}, {(k + 1) * a, 0}, {(k + 1) * a, H}, {k * a, H}});
        // regular() has its first edge horizontal at the top: put that edge on the first panel's top and bottom edge.
        const std::vector<Pt> base = regular(n, a, {});
        const Pt v0 = base[0];
        std::vector<Pt> up, down;
        for (const Pt& v : base) {
            up.push_back({v.x - v0.x, -(v.y - v0.y)});
            down.push_back({v.x - v0.x, v.y - v0.y + H});
        }
        f.push_back(up);
        f.push_back(down);
    } else if (kind == QLatin1String("pyramide")) {
        const std::vector<Pt> v = regular(n, a, {});
        f.push_back(v);
        const double ra = a / (2 * std::tan(PI / n)), slant = std::sqrt(a * a * 1.2 + ra * ra);
        for (int k = 0; k < n; ++k) {
            const Pt q0 = v[k], q1 = v[(k + 1) % n], apex = padd(plerp(q0, q1, 0.5), pmul(leftN(q0, q1), slant));
            f.push_back({q0, apex, q1});
        }
    }
    return f;
}

GenResult polyeder(const QVariantMap& p, const TS&) {
    const QString kind = ps(p, "kind");
    const double a = need(pd(p, "a"), 8, 150, "Kantenlänge");
    const int sides = int(need(pi(p, "sides"), 3, 12, "Ecken"));
    const auto faces = solidNet(kind, a, sides);
    if (faces.empty()) throw GenError(QStringLiteral("Unbekannter Körper."));
    Net n{QStringLiteral("Körper")};
    const int tabs = facesNet(n, faces, std::min(9.0, a * 0.3), pb(p, "tabs"));
    const QString m = ps(p, "motif");
    if (!none(m)) {
        const bool cut = ps(p, "motifArt") == QLatin1String("loch");
        for (const auto& f : faces) {
            Pt c{};
            for (const Pt& v : f) c = padd(c, v);
            c = pmul(c, 1.0 / f.size());
            double rin = 1e9;
            for (size_t i = 0; i < f.size(); ++i) {
                const Pt q0 = f[i], q1 = f[(i + 1) % f.size()], u = punit(psub(q1, q0));
                const Pt w = psub(c, q0);
                rin = std::min(rin, std::abs(w.x * u.y - w.y * u.x));
            }
            const double s = rin * 1.1;
            const Poly mp = movedP(motif(m, s, s), c.x - s / 2, c.y - s / 2);
            if (cut) n.hole(mp); else n.engraveShape(mp);
        }
    }
    static const QHash<QString, QString> names = {{"tetra", "Tetraeder (4 Dreiecke)"}, {"okta", "Oktaeder (8 Dreiecke)"}, {"ikosa", "Ikosaeder (20 Dreiecke)"},
                                                  {"dodeka", "Dodekaeder (12 Fünfecke)"}, {"prisma", "Prisma"}, {"pyramide", "Pyramide"}};
    QStringList notes{QStringLiteral("%1, Kante %2 mm, %3 Flächen.").arg(names.value(kind)).arg(Werkstatt::num(a)).arg(faces.size())};
    if (pb(p, "tabs")) notes << QStringLiteral("%1 Laschen: jede Kante wird genau einmal geklebt.").arg(tabs);
    return finish({n}, p, notes, ps(p, "motifArt") == QLatin1String("loch") && !none(m) ? QStringList{QStringLiteral("Als Leuchte nur mit LED.")} : QStringList{});
}

GenResult haus(const QVariantMap& p, const TS& sh) {
    const double w = need(pd(p, "w"), 20, 200, "Breite"), d = need(pd(p, "d"), 20, 200, "Tiefe"), h = need(pd(p, "h"), 15, 200, "Wandhöhe");
    const double rh = need(pd(p, "rh"), 5, 150, "Dachhöhe"), o = need(pd(p, "over"), 0, 30, "Dachüberstand");
    Net n{QStringLiteral("Haus")};
    const double X = 2 * w + 2 * d;
    n.rect(0, 0, X, h);
    for (double x : {w, w + d, 2 * w + d}) n.fold({x, 0}, {x, h});
    n.tab({X, 0}, {X, h}, 10);
    for (double xs : {w, 2 * w + d}) {
        const Pt apex{xs + d / 2, -rh};
        n.solid({{xs, 0}, apex, {xs + d, 0}});
        n.tab({xs, 0}, apex, 7, 45, 45);
        n.tab(apex, {xs + d, 0}, 7, 45, 45);
    }
    if (pb(p, "floor")) {
        n.rect(0, h, w, d);
        n.fold({0, h}, {w, h});
        n.tab({0, h + d}, {0, h}, 8, 40, 40);
        n.tab({w, h}, {w, h + d}, 8, 40, 40);
        n.tab({w, h + d}, {0, h + d}, 8, 40, 40);
    }
    const QString win = ps(p, "windows");
    const auto window = [&](double cx, double cy, double ww, double wh) {
        if (win == QLatin1String("loch")) {
            const double bar = std::max(1.2, ww * 0.1);
            const double pw = (ww - bar) / 2, ph = (wh - bar) / 2;
            for (int i = 0; i < 2; ++i) for (int j = 0; j < 2; ++j) n.hole(rectP(cx - ww / 2 + i * (pw + bar), cy - wh / 2 + j * (ph + bar), pw, ph));
        } else if (win == QLatin1String("graviert")) {
            n.markPoly(closedP(rectP(cx - ww / 2, cy - wh / 2, ww, wh)));
            n.markLine({cx, cy - wh / 2}, {cx, cy + wh / 2});
            n.markLine({cx - ww / 2, cy}, {cx + ww / 2, cy});
        }
    };
    const double ww = std::min(w, d) * 0.22, wh = h * 0.28;
    if (pb(p, "door")) {
        const double dw = w * 0.22, dh = h * 0.5;
        if (win == QLatin1String("graviert") || win == QLatin1String("keine")) n.markPoly(closedP(rectP(w / 2 - dw / 2, h - dh - 2, dw, dh, dw * 0.2)));
        else {
            n.cut({{w / 2 - dw / 2, h - dh - 2}, {w / 2 + dw / 2, h - dh - 2}, {w / 2 + dw / 2, h - 2}, {w / 2 - dw / 2, h - 2}});
            n.fold({w / 2 - dw / 2, h - dh - 2}, {w / 2 - dw / 2, h - 2}, false);
        }
        window(w * 0.18, h * 0.35, ww, wh);
        window(w * 0.82, h * 0.35, ww, wh);
    } else {
        window(w * 0.3, h * 0.45, ww, wh);
        window(w * 0.7, h * 0.45, ww, wh);
    }
    window(w + d / 2, h * 0.45, ww, wh);
    window(w + d + w * 0.3, h * 0.45, ww, wh);
    window(w + d + w * 0.7, h * 0.45, ww, wh);
    window(2 * w + d + d / 2, h * 0.45, ww, wh);
    n.text(sh, ps(p, "text"), pd(p, "textH"), {w / 2, h * 0.14}, w * 0.6);
    Net roof{QStringLiteral("Dach")};
    const double sl = std::sqrt(d * d / 4 + rh * rh) + o;
    roof.rect(0, 0, w + 2 * o, 2 * sl);
    roof.fold({0, sl}, {w + 2 * o, sl});
    return finish({n, roof}, p, {QStringLiteral("Das Dach auf die Laschen der Giebel kleben. Die Tür ist an einer Seite angeschnitten und lässt sich öffnen.")});
}

GenResult kegel(const QVariantMap& p, const TS&) {
    const double D = need(pd(p, "D"), 20, 300, "Durchmesser oben"), H = need(pd(p, "H"), 10, 300, "Höhe");
    const bool stumpf = ps(p, "art") == QLatin1String("stumpf");
    const double d2 = stumpf ? need(pd(p, "d2"), 5, D - 2, "Durchmesser unten") : 0;
    const double slantF = std::sqrt(H * H + (D - d2) * (D - d2) / 4);
    const double s = slantF * D / (D - d2), s2 = s - slantF;
    const double phi = 2 * PI * (D / 2) / s;
    if (phi > 2 * PI - 0.05) throw GenError(QStringLiteral("So flach geht es nicht: der Mantel wäre ein ganzer Kreis. Höher oder schmaler machen."));
    const double a0 = -PI / 2 - phi / 2, a1 = a0 + phi;
    Net n{stumpf ? QStringLiteral("Kegelstumpf") : QStringLiteral("Kegel")};
    const Edge e = edgeFromId(ps(p, "edge"));
    Poly outline;
    const int chords = std::max(8, int(phi * s / 8));
    for (int k = 0; k < chords; ++k) {
        const Pt a = polar({}, s, a0 + phi * k / chords), b = polar({}, s, a0 + phi * (k + 1) / chords);
        if (e == Edge::Straight) { const Poly arc = arcP({}, s, a0 + phi * k / chords, a0 + phi * (k + 1) / chords); outline.insert(outline.end(), arc.begin(), arc.end() - 1); }
        else { const EdgeLine el = decoratedEdge(a, b, e, plen(psub(b, a))); outline.insert(outline.end(), el.line.begin(), el.line.end() - 1); for (const Poly& h : el.holes) n.hole(h); }
    }
    outline.push_back(polar({}, s, a1));
    if (stumpf) { const Poly in = arcP({}, s2, a1, a0); outline.insert(outline.end(), in.begin(), in.end()); }
    else outline.push_back({0, 0});
    n.solid(outline);
    n.tab(stumpf ? polar({}, s2, a0) : Pt{0, 0}, polar({}, s, a0), 12, stumpf ? 45 : std::min(45.0, (360 - phi * 180 / PI) * 0.4), 45);
    const QString m = ps(p, "motif");
    if (!none(m)) {
        const double sz = need(pd(p, "size"), 5, 60, "Motivgröße"), step = sz * 1.8;
        for (double rr = s2 + step * 0.7; rr < s - step * 0.5; rr += step) {
            const double arcLen = rr * phi;
            const int cnt = int(arcLen / step);
            for (int k = 0; k < cnt; ++k) {
                const double a = a0 + phi * (k + 0.5) / cnt;
                if ((a - a0) * rr < sz || (a1 - a) * rr < sz) continue;
                const Pt c = polar({}, rr, a);
                n.hole(rotatedP(movedP(motif(m, sz, sz), c.x - sz / 2, c.y - sz / 2), a + PI / 2, c));
            }
        }
    }
    std::vector<Net> nets{n};
    if (stumpf && pb(p, "bottom")) { Net b{QStringLiteral("Boden")}; toothedDisc(b, {}, d2); nets.push_back(b); }
    return finish(nets, p, {QStringLiteral("Mantelwinkel %1°.").arg(Werkstatt::num(phi * 180 / PI, 0))},
                  none(m) ? QStringList{} : QStringList{QStringLiteral("Als Lampenschirm nur mit LED.")});
}

// ---- Liste ----

Template T(const char* id, const char* group, const char* title, const char* blurb, const char* icon, QVariantMap defaults,
           std::function<QVariantList(const QVariantMap&)> fields, std::function<GenResult(const QVariantMap&, const TS&)> run,
           const QString& stock = QStringLiteral("karton300"), const QString& sheet = QStringLiteral("a4"), bool folds = true) {
    Template t;
    t.id = QString::fromLatin1(id);
    t.group = QString::fromUtf8(group);
    t.title = QString::fromUtf8(title);
    t.blurb = QString::fromUtf8(blurb);
    t.icon = QString::fromLatin1(icon);
    const QVariantMap base = with(commonDefaults(stock, sheet), defaults);
    t.defaults = [base] { return base; };
    t.fields = [fields, folds](const QVariantMap& p) { return plus(fields(p), commonFields(folds)); };
    t.run = std::move(run);
    return t;
}
QVariantList textFields(const QString& label = QStringLiteral("Text"), const QString& ph = {}) {
    return {fRow({fText("text", label, {}, ph), fMm("textH", "Schrifthöhe", 2, 60, 0.5)})};
}
QVariantList windowFields() {
    return {fRow({fMotif("window", "Fenster"), fNum("winSize", "Größe", "%", 10, 95, 5, 0)})};
}

std::vector<Template> build() {
    std::vector<Template> v;
    const char* V = "Verpackung";
    v.push_back(T("faltschachtel", V, "Faltschachtel", "Steckverschluss oben und unten, mit Fenster", "package",
        {{"w", 50}, {"d", 35}, {"h", 80}, {"window", "none"}, {"winSize", 50}, {"text", ""}, {"textH", 7}},
        [](const QVariantMap&) { return plus({fSection("Innenmaße"), fRow({fMm("w", "Breite", 15, 250), fMm("d", "Tiefe", 10, 150), fMm("h", "Höhe", 15, 300)}), fSection("Gestaltung")},
                                             plus(windowFields(), textFields())); }, faltschachtel));
    v.push_back(T("deckelschachtel", V, "Schachtel mit Deckel", "Stülpdeckel, Griffmulden, Zierrand", "box",
        {{"w", 80}, {"d", 60}, {"h", 40}, {"lidH", 20}, {"rim", "gerade"}, {"grip", true}, {"window", "none"}, {"winSize", 50}, {"text", ""}, {"textH", 8}},
        [](const QVariantMap&) { return plus({fSection("Innenmaße"), fRow({fMm("w", "Breite", 20, 250), fMm("d", "Tiefe", 20, 250), fMm("h", "Höhe", 8, 150)}),
                                              fMm("lidH", "Deckelhöhe", 5, 150), fSection("Deckel"), fEdge("rim", "Rand"), fCheck("grip", "Griffmulden")},
                                             plus(windowFields(), textFields())); }, deckelschachtel));
    v.push_back(T("vieleck", V, "Vieleck-Dose", "3 bis 12 Ecken, mit Deckel", "shapes",
        {{"sides", 6}, {"a", 40}, {"h", 40}, {"lidH", 15}, {"window", "none"}, {"winSize", 60}, {"text", ""}, {"textH", 7}},
        [](const QVariantMap&) { return plus({fRow({fNum("sides", "Ecken", "", 3, 12, 1, 0), fMm("a", "Seitenlänge", 10, 150), fMm("h", "Höhe", 5, 200)}),
                                              fMm("lidH", "Deckelhöhe", 0, 200, 1, 1, "0 = ohne Deckel")}, plus(windowFields(), textFields())); }, vieleck));
    v.push_back(T("pyramide", V, "Pyramidenschachtel", "Spitzen mit Band geschlossen", "shapes",
        {{"sides", 4}, {"a", 50}, {"H", 60}, {"ribbon", true}, {"motif", "none"}},
        [](const QVariantMap&) { return QVariantList{fRow({fNum("sides", "Ecken", "", 3, 8, 1, 0), fMm("a", "Seitenlänge", 15, 200), fMm("H", "Höhe", 10, 300)}),
                                                     fCheck("ribbon", "Löcher für das Band"), fMotif("motif", "Muster auf den Flächen")}; }, pyramide));
    v.push_back(T("kissen", V, "Kissenschachtel", "Gewölbte Enden, ohne Kleber zu schließen", "package",
        {{"w", 80}, {"h", 120}, {"k", 18}, {"text", ""}, {"textH", 7}},
        [](const QVariantMap&) { return plus({fRow({fMm("w", "Breite", 30, 200), fMm("h", "Länge", 40, 280), fMm("k", "Wölbung", 5, 90)})}, textFields()); }, kissen));
    v.push_back(T("prisma", V, "Dreieckschachtel", "Prisma, etwa für Schokolade", "package",
        {{"a", 45}, {"L", 150}, {"text", ""}, {"textH", 8}},
        [](const QVariantMap&) { return plus({fRow({fMm("a", "Seitenlänge", 15, 120), fMm("L", "Länge", 30, 280)})}, textFields()); }, prisma));
    v.push_back(T("schiebeschachtel", V, "Schiebeschachtel", "Hülle und Schublade, wie eine Streichholzschachtel", "package",
        {{"w", 50}, {"L", 80}, {"h", 20}, {"grip", true}, {"text", ""}, {"textH", 7}},
        [](const QVariantMap&) { return plus({fSection("Schublade innen"), fRow({fMm("w", "Breite", 20, 200), fMm("L", "Länge", 20, 250), fMm("h", "Höhe", 8, 100)}),
                                              fCheck("grip", "Griffloch an der Schublade")}, textFields()); }, schiebeschachtel));
    v.push_back(T("tuete", V, "Papiertüte", "Mit Seitenfalten, Boden und Henkellöchern", "package",
        {{"w", 80}, {"g", 40}, {"h", 120}, {"hem", true}, {"holes", true}, {"window", "none"}, {"winSize", 50}, {"text", ""}, {"textH", 8}},
        [](const QVariantMap&) { return plus({fRow({fMm("w", "Breite", 30, 250), fMm("g", "Seitenfalte", 10, 150), fMm("h", "Höhe", 40, 300)}),
                                              fCheck("hem", "Umschlag oben"), fCheck("holes", "Löcher für Kordel")}, plus(windowFields(), textFields())); },
        tuete, QStringLiteral("karton160")));
    v.push_back(T("henkelbox", V, "Henkelbox", "Giebelschachtel mit Tragegriff", "package",
        {{"w", 60}, {"d", 40}, {"h", 70}, {"handle", 30}, {"text", ""}, {"textH", 8}},
        [](const QVariantMap&) { return plus({fRow({fMm("w", "Breite", 30, 200), fMm("d", "Tiefe", 20, 150), fMm("h", "Höhe", 20, 250)}),
                                              fMm("handle", "Griffhöhe", 15, 100)}, textFields()); }, henkelbox));
    v.push_back(T("runddose", V, "Runde Dose", "Zylinder mit Zahnboden und Deckel", "circle",
        {{"D", 50}, {"h", 50}, {"lidH", 18}, {"motif", "none"}, {"text", ""}, {"textH", 7}},
        [](const QVariantMap&) { return plus({fRow({fMm("D", "Durchmesser", 20, 200), fMm("h", "Höhe", 10, 250), fMm("lidH", "Deckelrand", 0, 250)}),
                                              fMotif("motif", "Motiv auf dem Deckel")}, textFields()); }, runddose));
    v.push_back(T("steckhuelle", V, "Steckhülle", "Für CD, Fotos, Gutscheine, Karten", "square",
        {{"format", "cd"}, {"w", 100}, {"h", 70}, {"flap", "rund"}, {"thumb", true}, {"window", "none"}, {"winSize", 50}, {"text", ""}, {"textH", 8}},
        [](const QVariantMap& p) {
            QVariantList f{fSelect("format", "Inhalt", {{"cd", "CD (125 × 125)"}, {"foto", "Foto 10 × 15"}, {"gutschein", "Gutschein (150 × 75)"}, {"a6", "Karte A6"}, {"frei", "Eigene Maße"}})};
            if (ps(p, "format") == QLatin1String("frei")) f.push_back(fRow({fMm("w", "Breite", 20, 250), fMm("h", "Höhe", 20, 250)}));
            f.push_back(fSelect("flap", "Verschlussklappe", FLAPS));
            f.push_back(fCheck("thumb", "Griffausschnitt"));
            return plus(f, plus(windowFields(), textFields()));
        }, steckhuelle));
    v.push_back(T("koerbchen", V, "Körbchen", "Schale mit Zierrand und Henkel", "package",
        {{"w", 80}, {"d", 60}, {"h", 35}, {"rim", "wellen"}, {"handle", true}},
        [](const QVariantMap&) { return QVariantList{fRow({fMm("w", "Breite", 20, 250), fMm("d", "Tiefe", 20, 250), fMm("h", "Höhe", 8, 120)}), fEdge("rim", "Rand"),
                                                     fCheck("handle", "Henkel")}; }, koerbchen));

    const char* U = "Umschlag";
    v.push_back(T("umschlag", U, "Briefumschlag", "Alle Formate, Klappen, Zierloch, Futter", "send-to-back",
        {{"format", "q120"}, {"w", 150}, {"h", 100}, {"flap", "spitz"}, {"deco", "none"}, {"addrWin", false}, {"liner", false}, {"text", ""}, {"textH", 6}},
        [](const QVariantMap& p) {
            QVariantList f{fSelect("format", "Format", ENV)};
            if (ps(p, "format") == QLatin1String("frei")) f.push_back(fRow({fMm("w", "Breite", 30, 300), fMm("h", "Höhe", 30, 300)}));
            f << fSelect("flap", "Klappe", FLAPS) << fMotif("deco", "Zierloch in der Klappe") << fCheck("addrWin", "Adressfenster (DIN, 90 × 45)")
              << fCheck("liner", "Futter aus zweitem Papier");
            return plus(f, textFields("Text vorn (Absender, Gruß)"));
        }, umschlag, QStringLiteral("papier120")));
    v.push_back(T("pochette", U, "Pochette", "Karte in Tasche mit Klappe", "send-to-back",
        {{"format", "a6"}, {"w", 100}, {"h", 140}, {"flap", "rund"}, {"deco", "herz"}, {"text", ""}, {"textH", 7}},
        [](const QVariantMap& p) {
            QVariantList f{fSelect("format", "Karte", {{"a6", "A6 (105 × 148)"}, {"a7", "A7 (74 × 105)"}, {"q140", "Quadrat 140"}, {"dl", "DIN lang (99 × 210)"}, {"frei", "Eigene Maße"}})};
            if (ps(p, "format") == QLatin1String("frei")) f.push_back(fRow({fMm("w", "Breite", 30, 250), fMm("h", "Höhe", 30, 250)}));
            f << fSelect("flap", "Klappe", FLAPS) << fMotif("deco", "Zierloch in der Klappe");
            return plus(f, textFields("Text auf der Tasche"));
        }, pochette, QStringLiteral("karton220")));
    v.push_back(T("samentuete", U, "Tütchen", "Für Samen, Tee, kleine Geschenke, beschriftet", "send-to-back",
        {{"w", 70}, {"h", 100}, {"flap", "rund"}, {"motif", "blume"}, {"title", "Ringelblume"}, {"textH", 6}, {"lines", true}},
        [](const QVariantMap&) { return QVariantList{fRow({fMm("w", "Breite", 30, 200), fMm("h", "Höhe", 30, 200)}), fSelect("flap", "Klappe", FLAPS),
                                                     fMotif("motif", "Motiv (graviert)"), fRow({fText("title", "Titel"), fMm("textH", "Schrifthöhe", 2, 30, 0.5)}),
                                                     fCheck("lines", "Zeilen „Gesät am“ und „Ernte“")}; }, samentuete, QStringLiteral("papier120")));
    v.push_back(T("briefbogen", U, "Briefbogen", "Zierrand, Kopfzeile, Linien, Eckmotive", "pen-line",
        {{"format", "a5"}, {"w", 148}, {"h", 210}, {"edge", "boegen"}, {"edgeSize", 10}, {"edgeWhere", "oben"}, {"title", ""}, {"textH", 7}, {"lines", "linien"}, {"corner", "none"}},
        [](const QVariantMap& p) {
            QVariantList f{fSelect("format", "Format", {{"a6", "A6"}, {"a5", "A5"}, {"a4", "A4"}, {"frei", "Eigene Maße"}})};
            if (ps(p, "format") == QLatin1String("frei")) f.push_back(fRow({fMm("w", "Breite", 50, 300), fMm("h", "Höhe", 50, 300)}));
            f << fRow({fEdge("edge", "Rand"), fMm("edgeSize", "Größe", 4, 30)}) << fSeg("edgeWhere", "Rand an", {{"oben", "Oben und unten"}, {"alle", "Allen Seiten"}})
              << fRow({fText("title", "Kopfzeile"), fMm("textH", "Schrifthöhe", 2, 30, 0.5)}) << fSeg("lines", "Linien", {{"keine", "Keine"}, {"linien", "8,5 mm"}, {"eng", "6 mm"}})
              << fMotif("corner", "Eckmotive (graviert)");
            return f;
        }, briefbogen, QStringLiteral("papier120"), QStringLiteral("a4"), false));
    v.push_back(T("faltbrief", U, "Faltbrief", "A4, gefaltet zum Verschicken, mit Adressfeld", "send-to-back",
        {{"address", true}, {"ribbon", true}, {"text", ""}, {"textH", 8}},
        [](const QVariantMap&) { return plus({fCheck("address", "Adressfeld, Absender, Markenfeld"), fCheck("ribbon", "Löcher für einen Bandverschluss")}, textFields("Text auf der Adressseite")); },
        faltbrief, QStringLiteral("papier80")));

    const char* K = "Karte";
    v.push_back(T("klappkarte", K, "Klappkarte", "Fenster, Zierkante, Gravur, Einleger", "image",
        {{"format", "a6"}, {"w", 105}, {"h", 148}, {"spine", "links"}, {"edge", "gerade"}, {"window", "herz"}, {"winSize", 45}, {"engr", "none"}, {"text", "Alles Gute"}, {"textH", 8}, {"insert", false}},
        [](const QVariantMap& p) {
            QVariantList f{fSelect("format", "Format (je Seite)", CARD)};
            if (ps(p, "format") == QLatin1String("frei")) f.push_back(fRow({fMm("w", "Breite", 30, 280), fMm("h", "Höhe", 30, 280)}));
            f << fSeg("spine", "Falz", {{"links", "Links"}, {"oben", "Oben"}}) << fEdge("edge", "Zierkante vorn");
            f.append(windowFields());
            f << fMotif("engr", "Motiv graviert");
            f.append(textFields("Text vorn"));
            f << fCheck("insert", "Einleger zum Beschreiben");
            return f;
        }, klappkarte));
    v.push_back(T("faltkarte", K, "Faltkarte mehrteilig", "Leporello, Wickelfalz, Altarfalz", "layout-grid",
        {{"art", "lepo"}, {"panels", 3}, {"w", 90}, {"h", 120}, {"edge", "gerade"}, {"text", ""}, {"textH", 8}},
        [](const QVariantMap& p) {
            QVariantList f{fSeg("art", "Art", {{"lepo", "Leporello"}, {"wickel", "Wickelfalz"}, {"altar", "Altarfalz"}})};
            if (ps(p, "art") != QLatin1String("altar")) f.push_back(fNum("panels", "Felder", "", 2, 8, 1, 0));
            f << fRow({fMm("w", "Feldbreite", 30, 250), fMm("h", "Höhe", 30, 280)}) << fEdge("edge", "Zierkante am Ende");
            return plus(f, textFields("Text auf dem ersten Feld"));
        }, faltkarte));
    v.push_back(T("popupstufen", K, "Pop-up-Karte Stufen", "Stufen springen beim Öffnen heraus", "layout-grid",
        {{"w", 120}, {"h", 85}, {"steps", 3}, {"stepW", 22}, {"gap", 8}, {"pattern", "treppe"}, {"cover", true}, {"text", ""}, {"textH", 8}},
        [](const QVariantMap&) { return plus({fRow({fMm("w", "Breite", 60, 280), fMm("h", "Höhe je Hälfte", 40, 200)}),
                                              fRow({fNum("steps", "Stufen", "", 1, 7, 1, 0), fMm("stepW", "Stufenbreite", 5, 100), fMm("gap", "Abstand", 2, 60)}),
                                              fSeg("pattern", "Tiefe", {{"gleich", "Gleich"}, {"treppe", "Treppe"}, {"pyramide", "Pyramide"}}),
                                              fCheck("cover", "Umschlagkarte dazu")}, textFields("Text auf der Umschlagkarte")); },
        popupStufen, QStringLiteral("karton220"), QStringLiteral("a4q")));
    v.push_back(T("popupmotiv", K, "Pop-up-Karte Motiv", "Herz, Stern, Tanne … steht beim Öffnen auf", "image",
        {{"w", 120}, {"h", 85}, {"motif", "herz"}, {"count", 1}, {"size", 50}, {"depth", 22}, {"cover", true}, {"text", ""}, {"textH", 8}},
        [](const QVariantMap&) { return plus({fRow({fMm("w", "Breite", 60, 280), fMm("h", "Höhe je Hälfte", 40, 200)}), fMotif("motif", "Motiv", false),
                                              fRow({fNum("count", "Anzahl", "", 1, 3, 1, 0), fMm("size", "Größe", 15, 180), fMm("depth", "Abstand", 6, 150)}),
                                              fCheck("cover", "Umschlagkarte dazu")}, textFields("Text auf der Umschlagkarte")); },
        popupMotiv, QStringLiteral("karton220"), QStringLiteral("a4q")));
    v.push_back(T("schuettelkarte", K, "Schüttelkarte", "Fenster, Abstandsrahmen, Rückseite", "image",
        {{"format", "mini"}, {"w", 90}, {"h", 120}, {"window", "herz"}, {"winSize", 60}, {"spacers", 2}, {"text", ""}, {"textH", 7}},
        [](const QVariantMap& p) {
            QVariantList f{fSelect("format", "Format", CARD)};
            if (ps(p, "format") == QLatin1String("frei")) f.push_back(fRow({fMm("w", "Breite", 30, 280), fMm("h", "Höhe", 30, 280)}));
            f.append(windowFields());
            f << fNum("spacers", "Abstandsrahmen", "", 1, 6, 1, 0);
            return plus(f, textFields());
        }, schuettelkarte));
    v.push_back(T("tischkarte", K, "Tischkarten", "Ein Name je Karte, Motiv ragt über die Kante", "type",
        {{"names", "Anna, Ben, Clara"}, {"w", 90}, {"h", 50}, {"motif", "herz"}, {"size", 22}, {"pos", "mitte"}, {"both", false}, {"textH", 9}},
        [](const QVariantMap&) { return QVariantList{fText("names", "Namen", "Mit Komma getrennt; jeder Name eine Karte."), fRow({fMm("w", "Breite", 40, 200), fMm("h", "Höhe", 25, 120), fMm("textH", "Schrift", 2, 40, 0.5)}),
                                                     fRow({fMotif("motif", "Motiv"), fMm("size", "Größe", 8, 160)}), fSeg("pos", "Motiv", {{"links", "Links"}, {"mitte", "Mitte"}, {"rechts", "Rechts"}}),
                                                     fCheck("both", "Name auch auf der Rückseite")}; }, tischkarte));
    v.push_back(T("postkarte", K, "Postkarte", "Mit Adressfeld und Markenfeld", "image",
        {{"w", 148}, {"h", 105}, {"r", 3}, {"count", 2}, {"back", true}, {"text", ""}, {"textH", 6}},
        [](const QVariantMap&) { return plus({fRow({fMm("w", "Breite", 60, 250), fMm("h", "Höhe", 40, 200), fMm("r", "Ecken", 0, 20)}), fNum("count", "Stück", "", 1, 40, 1, 0),
                                              fCheck("back", "Adressseite markieren")}, textFields("Gruß links")); }, postkarte));
    v.push_back(T("kaertchen", K, "Kärtchen im Nutzen", "Visitenkarten, Spielkarten, Memory, Etiketten", "layout-grid",
        {{"preset", "visit"}, {"w", 85}, {"h", 55}, {"count", 8}, {"r", 3}, {"motif", "none"}, {"l1", "Vorname Nachname"}, {"l2", "Werkstatt"}, {"l3", ""}},
        [](const QVariantMap& p) {
            QVariantList f{fSelect("preset", "Art", {{"visit", "Visitenkarte 85 × 55"}, {"spiel", "Spielkarte 63 × 88"}, {"memory", "Memory 50 × 50"}, {"etikett", "Etikett 70 × 37"},
                                                    {"mini", "Mini 40 × 25"}, {"frei", "Eigene Maße"}})};
            if (ps(p, "preset") == QLatin1String("frei")) f.push_back(fRow({fMm("w", "Breite", 15, 200), fMm("h", "Höhe", 15, 200)}));
            f << fRow({fNum("count", "Stück", "", 1, 200, 1, 0), fMm("r", "Ecken", 0, 30)}) << fMotif("motif", "Motiv links (graviert)")
              << fText("l1", "Zeile 1 (fett)") << fText("l2", "Zeile 2") << fText("l3", "Zeile 3");
            return f;
        }, kaertchen, QStringLiteral("karton300"), QStringLiteral("a4"), false));
    v.push_back(T("drehscheibe", K, "Drehscheibe", "Zwei Scheiben, Fenster zeigt ein Feld", "rotate-cw",
        {{"D", 120}, {"labels", "Ja, Nein, Vielleicht, Morgen, Heute, Nie"}, {"segments", 6}, {"win", "keil"}, {"title", ""}, {"textH", 7}},
        [](const QVariantMap&) { return QVariantList{fMm("D", "Durchmesser", 50, 300), fText("labels", "Felder", "Mit Komma getrennt. Leer: nur Linien."),
                                                     fNum("segments", "Felder ohne Text", "", 2, 16, 1, 0), fSeg("win", "Fenster", {{"keil", "Keil"}, {"rund", "Rund"}}),
                                                     fRow({fText("title", "Text oben"), fMm("textH", "Schrifthöhe", 2, 30, 0.5)})}; }, drehscheibe, QStringLiteral("karton300"), QStringLiteral("a4"), false));
    v.push_back(T("schieber", K, "Ziehkarte", "Motiv gleitet im Schlitz", "move",
        {{"w", 148}, {"h", 105}, {"slot", 80}, {"slotY", 60}, {"motif", "stern"}, {"size", 30}, {"text", ""}, {"textH", 8}},
        [](const QVariantMap&) { return plus({fRow({fMm("w", "Breite", 60, 250), fMm("h", "Höhe", 50, 200)}), fRow({fMm("slot", "Weg", 20, 220), fNum("slotY", "Höhe", "%", 20, 80, 5, 0)}),
                                              fRow({fMotif("motif", "Motiv", false), fMm("size", "Größe", 10, 160)})}, textFields()); },
        schieber, QStringLiteral("karton300"), QStringLiteral("a4"), false));

    const char* D = "Deko";
    v.push_back(T("anhaenger", D, "Geschenkanhänger", "Viele Formen, ein Name je Anhänger", "stamp",
        {{"form", "etikett"}, {"w", 45}, {"h", 70}, {"hole", 5}, {"names", ""}, {"count", 6}, {"text", "Für dich"}, {"textH", 6}, {"motif", "none"}},
        [](const QVariantMap&) { return QVariantList{fSelect("form", "Form", {{"etikett", "Etikett"}, {"rund", "Rund"}, {"abgerundet", "Abgerundet"}, {"oval", "Oval"}, {"herz", "Herz"},
                                                                             {"stern", "Stern"}, {"kugel", "Christbaumkugel"}, {"ei", "Ei"}, {"wolke", "Wolke"}, {"sechseck", "Sechseck"},
                                                                             {"blume", "Blume"}, {"klapp", "Klappanhänger"}}),
                                                     fRow({fMm("w", "Breite", 15, 200), fMm("h", "Höhe", 15, 250), fMm("hole", "Loch", 0, 15, 0.5)}),
                                                     fText("names", "Namen", "Mit Komma getrennt: ein Anhänger je Name. Leer: Stückzahl und Text unten."),
                                                     fRow({fNum("count", "Stück", "", 1, 200, 1, 0), fText("text", "Text"), fMm("textH", "Schrift", 2, 40, 0.5)}),
                                                     fMotif("motif", "Motiv (graviert)")}; }, anhaenger, QStringLiteral("karton300"), QStringLiteral("a4"), false));
    v.push_back(T("lesezeichen", D, "Lesezeichen", "Streifen mit Muster oder Ecke als Monster", "pen-tool",
        {{"art", "streifen"}, {"w", 45}, {"h", 160}, {"end", "schwalbe"}, {"hole", true}, {"pattern", "herz"}, {"text", ""}, {"textH", 9}, {"corner", 60}, {"monster", true}},
        [](const QVariantMap& p) {
            if (ps(p, "art") == QLatin1String("ecke"))
                return plus({fSeg("art", "Art", {{"streifen", "Streifen"}, {"ecke", "Ecke"}}), fMm("corner", "Größe", 30, 120), fCheck("monster", "Monster mit Zähnen und Augen")}, textFields());
            return plus({fSeg("art", "Art", {{"streifen", "Streifen"}, {"ecke", "Ecke"}}), fRow({fMm("w", "Breite", 15, 100), fMm("h", "Länge", 50, 280)}),
                         fSeg("end", "Ende", {{"gerade", "Gerade"}, {"spitz", "Spitz"}, {"rund", "Rund"}, {"schwalbe", "Schwalbe"}}), fCheck("hole", "Loch für eine Quaste"),
                         fMotif("pattern", "Lochmuster")}, textFields("Text (längs)"));
        }, lesezeichen, QStringLiteral("karton300"), QStringLiteral("a4"), true));
    v.push_back(T("girlande", D, "Wimpelkette", "Ein Buchstabe je Wimpel, viele Formen", "spline",
        {{"form", "dreieck"}, {"w", 90}, {"h", 120}, {"text", "HAPPY"}, {"count", 6}, {"textH", 50}, {"hang", "loecher"}, {"motif", "none"}},
        [](const QVariantMap&) { return QVariantList{fSelect("form", "Form", {{"dreieck", "Dreieck"}, {"schwalbe", "Schwalbenschwanz"}, {"rund", "Rund"}, {"rechteck", "Rechteck"},
                                                                             {"herz", "Herz"}, {"stern", "Stern"}, {"kreis", "Kreis"}, {"wolke", "Wolke"}}),
                                                     fRow({fMm("w", "Breite", 20, 250), fMm("h", "Höhe", 20, 280)}),
                                                     fRow({fText("text", "Buchstaben", "Jeder Buchstabe ein Wimpel, Leerzeichen gibt einen leeren."), fMm("textH", "Größe", 5, 200)}),
                                                     fNum("count", "Stück ohne Text", "", 1, 60, 1, 0), fSeg("hang", "Aufhängen", {{"loecher", "Zwei Löcher"}, {"lasche", "Lasche"}}),
                                                     fMotif("motif", "Motiv ohne Text")}; }, girlande, QStringLiteral("karton220")));
    v.push_back(T("stern3d", D, "Faltstern 3D", "Zwei gefaltete Sterne Rücken an Rücken", "wand-2",
        {{"points", 5}, {"D", 140}, {"ratio", 45}, {"hole", true}},
        [](const QVariantMap&) { return QVariantList{fRow({fNum("points", "Zacken", "", 4, 10, 1, 0), fMm("D", "Durchmesser", 30, 280), fNum("ratio", "Innen", "%", 25, 75, 5, 0)}),
                                                     fCheck("hole", "Loch zum Aufhängen")}; }, stern3d, QStringLiteral("karton220")));
    v.push_back(T("schneeflocke", D, "Schneeflocken", "Jede anders, aus einer Startzahl", "wand-2",
        {{"D", 90}, {"count", 4}, {"seed", 1}, {"arms", 6}, {"hole", true}},
        [](const QVariantMap&) { return QVariantList{fRow({fMm("D", "Durchmesser", 20, 280), fNum("count", "Stück", "", 1, 60, 1, 0)}),
                                                     fRow({fNum("seed", "Startzahl", "", 1, 99999, 1, 0), fSeg("arms", "Arme", {{"6", "6"}, {"8", "8"}})}),
                                                     fCheck("hole", "Öse zum Aufhängen")}; }, schneeflocke, QStringLiteral("papier120"), QStringLiteral("a4"), false));
    v.push_back(T("mandala", D, "Spitzendeckchen", "Mandala mit Ringen und Zierrand", "wand-2",
        {{"D", 160}, {"sym", 12}, {"rings", 3}, {"seed", 1}, {"edge", "boegen"}},
        [](const QVariantMap&) { return QVariantList{fMm("D", "Durchmesser", 40, 280), fRow({fNum("sym", "Symmetrie", "", 4, 32, 1, 0), fNum("rings", "Ringe", "", 1, 6, 1, 0),
                                                                                         fNum("seed", "Startzahl", "", 1, 99999, 1, 0)}), fEdge("edge", "Rand")}; },
        mandala, QStringLiteral("papier120"), QStringLiteral("a4"), false));
    v.push_back(T("laterne", D, "Laterne und Windlicht", "Schlitze, Muster oder Fensterseiten", "lightbulb",
        {{"art", "muster"}, {"U", 180}, {"h", 140}, {"motif", "stern"}, {"size", 16}, {"panels", 6}, {"edge", "boegen"}, {"handle", false}},
        [](const QVariantMap& p) {
            QVariantList f{fSeg("art", "Art", {{"schlitze", "Schlitze"}, {"muster", "Muster"}, {"fenster", "Fensterseiten"}}),
                           fRow({fMm("U", "Umfang", 60, 400), fMm("h", "Höhe", 40, 280)}), fEdge("edge", "Rand oben und unten")};
            if (ps(p, "art") == QLatin1String("muster")) f << fRow({fMotif("motif", "Motiv", false), fMm("size", "Größe", 6, 60)});
            if (ps(p, "art") == QLatin1String("fenster")) f << fRow({fNum("panels", "Seiten", "", 3, 12, 1, 0), fMotif("motif", "Fenster")});
            f << fCheck("handle", "Henkel");
            return f;
        }, laterne, QStringLiteral("karton220")));
    v.push_back(T("steckfigur", D, "Steckfigur 3D", "Zwei Teile gesteckt: Tanne, Stern, Herz …", "squares-intersect",
        {{"motif", "tanne"}, {"h", 120}, {"count", 1}},
        [](const QVariantMap&) { return QVariantList{fMotif("motif", "Form", false), fRow({fMm("h", "Höhe", 30, 280), fNum("count", "Stück", "", 1, 20, 1, 0)}),
                                                     fNote("Am besten aus Graupappe. Die Schlitzbreite folgt der Papierstärke.")}; },
        steckfigur, QStringLiteral("graupappe"), QStringLiteral("a4"), false));
    v.push_back(T("passepartout", D, "Passepartout und Rahmen", "Fenster, Collage, Aufsteller", "crop",
        {{"w", 180}, {"h", 130}, {"shape", "rechteck"}, {"fw", 120}, {"fh", 80}, {"cols", 1}, {"rows", 1}, {"back", true}, {"stand", true}, {"text", ""}, {"textH", 6}},
        [](const QVariantMap&) { return plus({fRow({fMm("w", "Breite", 40, 300), fMm("h", "Höhe", 40, 300)}),
                                              fSelect("shape", "Fenster", {{"rechteck", "Rechteck"}, {"abgerundet", "Abgerundet"}, {"oval", "Oval"}, {"kreis", "Kreis"},
                                                                           {"herz", "Herz"}, {"bogen", "Rundbogen"}, {"sechseck", "Sechseck"}, {"stern", "Stern"}}),
                                              fRow({fMm("fw", "Fensterbreite", 10, 290), fMm("fh", "Fensterhöhe", 10, 290)}),
                                              fRow({fNum("cols", "Spalten", "", 1, 6, 1, 0), fNum("rows", "Zeilen", "", 1, 6, 1, 0)}), fCheck("back", "Rückwand"), fCheck("stand", "Aufsteller")},
                                             textFields("Text unter dem Fenster")); }, passepartout));
    v.push_back(T("stanzformen", D, "Streudeko und Stanzteile", "Bogen voller Formen, gemischt", "shapes",
        {{"motif", "herz"}, {"size", 25}, {"gap", 3}, {"fill", true}, {"count", 30}, {"mixSizes", true}, {"mixMotifs", false}, {"seed", 1}},
        [](const QVariantMap& p) {
            QVariantList f{fMotif("motif", "Form", false), fRow({fMm("size", "Größe", 5, 150), fMm("gap", "Abstand", 1, 30)}), fCheck("fill", "Ganzen Bogen füllen")};
            if (!pb(p, "fill")) f << fNum("count", "Stück", "", 1, 500, 1, 0);
            f << fCheck("mixSizes", "Verschiedene Größen") << fCheck("mixMotifs", "Verschiedene Formen") << fNum("seed", "Startzahl", "", 1, 99999, 1, 0);
            return f;
        }, stanzformen, QStringLiteral("karton160"), QStringLiteral("a4"), false));
    v.push_back(T("rosette", D, "Papierrosette", "Zickzack-Fächer mit beschrifteter Mitte", "wand-2",
        {{"pitch", 12}, {"folds", 48}, {"w", 50}, {"edge", "zacken"}, {"center", 60}, {"text", "1"}, {"textH", 20}},
        [](const QVariantMap&) { return plus({fRow({fMm("pitch", "Faltbreite", 5, 40), fNum("folds", "Falten", "", 8, 120, 2, 0), fMm("w", "Breite", 15, 150)}),
                                              fEdge("edge", "Außenkante"), fMm("center", "Mitte Durchmesser", 20, 150)}, textFields("Text in der Mitte")); },
        rosette, QStringLiteral("papier120")));
    v.push_back(T("kalender", D, "Kalenderblatt", "Monat mit Wochentagen, Bildfeld, Linien", "clock",
        {{"month", QDate::currentDate().addMonths(1).month()}, {"year", QDate::currentDate().addMonths(1).year()}, {"w", 148}, {"h", 210}, {"photo", true}, {"grid", true}, {"hole", true}, {"textH", 9}},
        [](const QVariantMap&) { return QVariantList{fRow({fNum("month", "Monat", "", 1, 12, 1, 0), fNum("year", "Jahr", "", 1900, 2200, 1, 0)}),
                                                     fRow({fMm("w", "Breite", 80, 300), fMm("h", "Höhe", 80, 300), fMm("textH", "Titel", 3, 30, 0.5)}),
                                                     fCheck("photo", "Bildfeld oben"), fCheck("grid", "Linien"), fCheck("hole", "Aufhängeloch")}; },
        kalender, QStringLiteral("karton300"), QStringLiteral("a4"), false));

    const char* B = "Körper";
    v.push_back(T("wuerfel", B, "Würfel und Quader", "Mit Laschen, auf Wunsch mit Augen", "box",
        {{"w", 45}, {"d", 45}, {"h", 45}, {"pips", true}, {"text", ""}, {"textH", 8}},
        [](const QVariantMap&) { return plus({fRow({fMm("w", "Breite", 10, 200), fMm("d", "Tiefe", 10, 200), fMm("h", "Höhe", 10, 200)}), fCheck("pips", "Würfelaugen (graviert)")},
                                             textFields("Text vorn (ohne Augen)")); }, wuerfel));
    v.push_back(T("polyeder", B, "Platonische Körper", "Tetraeder bis Ikosaeder, Prisma, Pyramide", "shapes",
        {{"kind", "ikosa"}, {"a", 35}, {"sides", 6}, {"tabs", true}, {"motif", "none"}, {"motifArt", "graviert"}},
        [](const QVariantMap& p) {
            QVariantList f{fSelect("kind", "Körper", {{"tetra", "Tetraeder"}, {"okta", "Oktaeder"}, {"ikosa", "Ikosaeder"}, {"dodeka", "Dodekaeder"}, {"prisma", "Prisma"}, {"pyramide", "Pyramide"}}),
                           fMm("a", "Kantenlänge", 8, 150)};
            if (ps(p, "kind") == QLatin1String("prisma") || ps(p, "kind") == QLatin1String("pyramide")) f << fNum("sides", "Ecken", "", 3, 12, 1, 0);
            f << fCheck("tabs", "Klebelaschen") << fMotif("motif", "Motiv auf jeder Fläche") << fSeg("motifArt", "Motiv", {{"graviert", "Graviert"}, {"loch", "Ausgeschnitten"}});
            return f;
        }, polyeder));
    v.push_back(T("haus", B, "Papierhaus", "Fenster, Tür, Dach, Boden", "home",
        {{"w", 70}, {"d", 50}, {"h", 50}, {"rh", 30}, {"over", 5}, {"windows", "loch"}, {"door", true}, {"floor", true}, {"text", ""}, {"textH", 5}},
        [](const QVariantMap&) { return plus({fRow({fMm("w", "Breite", 20, 200), fMm("d", "Tiefe", 20, 200), fMm("h", "Wandhöhe", 15, 200)}),
                                              fRow({fMm("rh", "Dachhöhe", 5, 150), fMm("over", "Überstand", 0, 30)}),
                                              fSeg("windows", "Fenster", {{"loch", "Ausgeschnitten"}, {"graviert", "Gezeichnet"}, {"keine", "Keine"}}),
                                              fCheck("door", "Tür zum Öffnen"), fCheck("floor", "Boden")}, textFields("Hausnummer oder Name")); }, haus));
    v.push_back(T("kegel", B, "Kegel und Tüte", "Spitztüte, Kegelstumpf, Lampenschirm", "shapes",
        {{"art", "kegel"}, {"D", 90}, {"d2", 40}, {"H", 100}, {"bottom", true}, {"edge", "gerade"}, {"motif", "none"}, {"size", 12}},
        [](const QVariantMap& p) {
            QVariantList f{fSeg("art", "Art", {{"kegel", "Kegel"}, {"stumpf", "Kegelstumpf"}}), fRow({fMm("D", "Durchmesser oben", 20, 300), fMm("H", "Höhe", 10, 300)})};
            if (ps(p, "art") == QLatin1String("stumpf")) f << fMm("d2", "Durchmesser unten", 5, 298) << fCheck("bottom", "Boden");
            f << fEdge("edge", "Oberkante") << fRow({fMotif("motif", "Lochmuster"), fMm("size", "Größe", 5, 60)});
            return f;
        }, kegel));
    return v;
}

}  // namespace

std::vector<std::vector<Pt>> solidFaces(const QString& kind, double a, int sides) { return solidNet(kind, a, sides); }

const std::vector<Template>& templates() {
    static const std::vector<Template> list = build();
    return list;
}
const Template* findTemplate(const QString& id) {
    for (const Template& t : templates()) if (t.id == id) return &t;
    return nullptr;
}
QStringList groupNames() {
    return {QStringLiteral("Verpackung"), QStringLiteral("Umschlag"), QStringLiteral("Karte"), QStringLiteral("Deko"), QStringLiteral("Körper")};
}

}  // namespace lumacut::Papier
