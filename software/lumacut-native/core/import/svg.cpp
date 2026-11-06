/**
 * SVG wie SvgImport.kt: sichtbare Geometrie in mm, Ursprung oben links. Jedes Zeichenobjekt ein Teil, <g> werden Gruppen,
 * Farben werden Ebenen, eingebettete Bilder kommen mit. Der Baum wird seriell abgelaufen (Vererbung, Gruppen), Pfade
 * lesen und abflachen läuft mehrkernig, die Reihenfolge bleibt die der Datei.
 */
#include "core/fastnum.h"
#include "core/geometry.h"
#include "core/import/vector.h"
#include "core/import/xml.h"
#include "core/parallel.h"
#include "core/parts.h"

#include <QHash>
#include <algorithm>
#include <cctype>
#include <climits>
#include <cmath>
#include <cstring>

namespace lumacut::import {
namespace {

constexpr double CURVE_MM = 0.2;
constexpr double PX_MM = 25.4 / 96.0;
constexpr double PI = 3.14159265358979323846;

QString tooComplex() { return QStringLiteral("SVG zu komplex"); }
QString badPath() { return QStringLiteral("Ungültige Pfaddaten"); }

inline bool isCommand(char c) {
    switch (c) {
    case 'M': case 'm': case 'L': case 'l': case 'H': case 'h': case 'V': case 'v': case 'C': case 'c':
    case 'S': case 's': case 'Q': case 'q': case 'T': case 't': case 'A': case 'a': case 'Z': case 'z':
        return true;
    default:
        return false;
    }
}
inline bool startsNumber(char c) { return (c >= '0' && c <= '9') || c == '-' || c == '+' || c == '.'; }

std::vector<double> numbers(QByteArrayView s) {
    std::vector<double> out;
    const char* p = s.data();
    const char* end = p + s.size();
    while (p < end) {
        double v = 0;
        const char* q = startsNumber(*p) ? detail::parseDouble(p, end, v) : nullptr;
        if (!q) { ++p; continue; }
        if (std::isfinite(v)) out.push_back(v);
        p = q;
    }
    return out;
}

/** Sehne etwa `seg`, Viertelstück einer kubischen Kurve wie Androids cubic(). */
template <class To>
void cubicTo(Pt p0, Pt c1, Pt c2, Pt p1, double seg, To&& to) {
    const double approx = dist(p0, c1) + dist(c1, c2) + dist(c2, p1);
    const int n = clampSteps(approx / seg, 2, 400);
    for (int k = 1; k <= n; ++k) {
        const double t = double(k) / n, u = 1 - t;
        to(Pt{u * u * u * p0.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * p1.x,
              u * u * u * p0.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * p1.y});
    }
}

/** Endpunkt- zu Mittelpunkt-Darstellung (SVG F.6.5). */
template <class To>
void arcTo(Pt p0, double rxIn, double ryIn, double rotDeg, bool large, bool sweep, Pt p1, double seg, To&& to) {
    if (dist(p0, p1) < 1e-9) return;
    double rx = std::fabs(rxIn), ry = std::fabs(ryIn);
    if (rx < 1e-9 || ry < 1e-9) { to(p1); return; }
    const double phi = rotDeg * PI / 180, cp = std::cos(phi), sp = std::sin(phi);
    const double dx = (p0.x - p1.x) / 2, dy = (p0.y - p1.y) / 2;
    const double x1 = cp * dx + sp * dy, y1 = -sp * dx + cp * dy;
    const double lambda = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry);
    if (lambda > 1) { const double q = std::sqrt(lambda); rx *= q; ry *= q; }
    const double numer = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1;
    const double den = rx * rx * y1 * y1 + ry * ry * x1 * x1;
    const double coef = (large == sweep ? -1 : 1) * std::sqrt(std::max(0.0, numer / den));
    const double cx1 = coef * rx * y1 / ry, cy1 = -coef * ry * x1 / rx;
    const double cx = cp * cx1 - sp * cy1 + (p0.x + p1.x) / 2, cy = sp * cx1 + cp * cy1 + (p0.y + p1.y) / 2;
    const auto angle = [](double ux, double uy, double vx, double vy) {
        const double dot = ux * vx + uy * vy, len = std::sqrt((ux * ux + uy * uy) * (vx * vx + vy * vy));
        const double a = std::acos(std::clamp(dot / len, -1.0, 1.0));
        return ux * vy - uy * vx < 0 ? -a : a;
    };
    const double t1 = angle(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry);
    double dt = angle((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry);
    if (!sweep && dt > 0) dt -= 2 * PI;
    else if (sweep && dt < 0) dt += 2 * PI;
    const int n = clampSteps(std::fabs(dt) * std::max(rx, ry) / seg, 2, 720);
    for (int k = 1; k <= n; ++k) {
        if (k == n) { to(p1); break; }
        const double t = t1 + dt * k / n;
        to(Pt{cx + rx * std::cos(t) * cp - ry * std::sin(t) * sp, cy + rx * std::cos(t) * sp + ry * std::sin(t) * cp});
    }
}

// ---- CSS ----

/** Nur was das Lesen braucht; Werte als Sichten oder eigene Kopien. */
struct Props {
    QByteArray fill, stroke, strokeWidth, display, visibility;
    bool hasFill = false, hasStroke = false, hasStrokeWidth = false, hasDisplay = false, hasVisibility = false;
    void set(QByteArrayView key, QByteArray value) {
        if (key == "fill") { fill = std::move(value); hasFill = true; }
        else if (key == "stroke") { stroke = std::move(value); hasStroke = true; }
        else if (key == "stroke-width") { strokeWidth = std::move(value); hasStrokeWidth = true; }
        else if (key == "display") { display = std::move(value); hasDisplay = true; }
        else if (key == "visibility") { visibility = std::move(value); hasVisibility = true; }
    }
    void merge(const Props& o) {
        if (o.hasFill) { fill = o.fill; hasFill = true; }
        if (o.hasStroke) { stroke = o.stroke; hasStroke = true; }
        if (o.hasStrokeWidth) { strokeWidth = o.strokeWidth; hasStrokeWidth = true; }
        if (o.hasDisplay) { display = o.display; hasDisplay = true; }
        if (o.hasVisibility) { visibility = o.visibility; hasVisibility = true; }
    }
};

QByteArray rawCopy(QByteArrayView v) { return QByteArray::fromRawData(v.data(), v.size()); }

void declarations(QByteArrayView s, Props& out) {
    while (!s.isEmpty()) {
        const qsizetype semi = s.indexOf(';');
        const QByteArrayView d = semi >= 0 ? s.first(semi) : s;
        s = semi >= 0 ? s.sliced(semi + 1) : QByteArrayView();
        const qsizetype colon = d.indexOf(':');
        if (colon < 0) continue;
        QByteArrayView key = trimmedView(d.first(colon));
        if (key.isEmpty() || key.size() > 16) continue;
        char lower[16];
        for (qsizetype i = 0; i < key.size(); ++i) lower[i] = char(std::tolower(uint8_t(key[i])));
        QByteArrayView value = trimmedView(d.sliced(colon + 1));
        const qsizetype bang = value.indexOf('!');
        if (bang >= 0) value = trimmedView(value.first(bang));   // "!important"
        out.set(QByteArrayView(lower, key.size()), rawCopy(value));
    }
}

/** Regeln der <style>-Blöcke nach Selektor (".name" oder Tag); Illustrator schreibt seine Farben so. */
QHash<QByteArray, Props> cssRules(const XmlDoc& doc, std::vector<QByteArray>& keepAlive) {
    QHash<QByteArray, Props> rules;
    for (const int block : doc.allByLocalName("style")) {
        QByteArray text = doc.text(block);
        // Kommentare stören die Selektoren.
        for (qsizetype a = text.indexOf("/*"); a >= 0; a = text.indexOf("/*", a)) {
            const qsizetype b = text.indexOf("*/", a + 2);
            text.remove(a, (b < 0 ? text.size() : b + 2) - a);
        }
        text.detach();
        keepAlive.push_back(text);
        const QByteArrayView s = keepAlive.back();
        qsizetype selStart = 0;
        while (selStart < s.size()) {
            const qsizetype open = s.indexOf('{', selStart);
            if (open < 0) break;
            const qsizetype next = [&] {
                for (qsizetype i = open + 1; i < s.size(); ++i) if (s[i] == '{' || s[i] == '}') return i;
                return qsizetype(-1);
            }();
            if (next < 0) break;
            if (s[next] == '{') { selStart = open + 1; continue; }      // geschachtelt (@media): nur das Innere zählt
            Props props;
            declarations(s.sliced(open + 1, next - open - 1), props);
            QByteArrayView sels = s.sliced(selStart, open - selStart);
            while (!sels.isEmpty()) {
                const qsizetype comma = sels.indexOf(',');
                const QByteArrayView sel = trimmedView(comma >= 0 ? sels.first(comma) : sels);
                sels = comma >= 0 ? sels.sliced(comma + 1) : QByteArrayView();
                rules[sel.toByteArray()].merge(props);
            }
            selStart = next + 1;
        }
    }
    return rules;
}

// ---- Einheiten und Wurzel ----

/** mm aus "10cm", "96", "1in"; leer bei allem anderen, auch bei %. */
std::optional<double> length(QByteArrayView raw) {
    const QByteArrayView v = trimmedView(raw);
    if (v.isEmpty()) return std::nullopt;
    double n = 0;
    const char* end = v.data() + v.size();
    const char* q = detail::parseDouble(v.data(), end, n);
    if (!q || !std::isfinite(n)) return std::nullopt;
    const QByteArray unit = trimmedView(QByteArrayView(q, end - q)).toByteArray().toLower();
    if (unit == "mm") return n;
    if (unit == "cm") return n * 10;
    if (unit == "in") return n * 25.4;
    if (unit == "pt") return n * 25.4 / 72;
    if (unit == "pc") return n * 25.4 / 6;
    if (unit.isEmpty() || unit == "px") return n * PX_MM;
    return std::nullopt;
}

Matrix rootMatrix(const XmlDoc& doc, int svg) {
    const std::vector<double> vb = numbers(doc.rawAttr(svg, "viewBox"));
    std::optional<double> w = length(doc.rawAttr(svg, "width")), h = length(doc.rawAttr(svg, "height"));
    if (w && *w <= 0) w.reset();
    if (h && *h <= 0) h.reset();
    if (vb.size() == 4 && vb[2] > 0 && vb[3] > 0) {
        const double sx = w.value_or(vb[2] * PX_MM) / vb[2], sy = h.value_or(vb[3] * PX_MM) / vb[3];
        const double k = w && h ? std::min(sx, sy) : w ? sx : h ? sy : PX_MM;
        return {k, 0, 0, k, -vb[0] * k, -vb[1] * k};
    }
    return {PX_MM, 0, 0, PX_MM, 0, 0};
}

double num(const XmlDoc& doc, int node, QByteArrayView name) { return parseFloatOr(doc.rawAttr(node, name), 0); }

// ---- Baum ablaufen ----

bool skipped(QByteArrayView t) {
    return t == "defs" || t == "clipPath" || t == "mask" || t == "symbol" || t == "marker" || t == "pattern" || t == "title" || t == "desc" ||
           t == "metadata" || t == "style" || t == "script" || t == "text" || t == "linearGradient" || t == "radialGradient" || t == "filter";
}
bool isShape(QByteArrayView t) {
    return t == "path" || t == "rect" || t == "circle" || t == "ellipse" || t == "line" || t == "polyline" || t == "polygon";
}

struct Task {
    int node;
    Matrix m;
    int fill, stroke;
    bool noWidth;
    QStringList groups;
    std::optional<QString> name;
};
struct Done {
    std::vector<PolySet> parts;
    int colour = COLOUR_OTHER;
    bool filled = false;
};

struct Walker {
    const XmlDoc& doc;
    const QHash<QByteArray, Props>& css;
    std::vector<Task> tasks;
    std::vector<EmbeddedImage> images;
    int texts = 0, linkedImages = 0, clones = 0, ids = 0;

    Props properties(int node, QByteArrayView tag, QByteArray& styleKeep) const {
        Props p;
        const auto attr = [&](QByteArrayView k) {
            const QByteArrayView v = doc.rawAttr(node, k);
            if (!trimmedView(v).isEmpty()) p.set(k, XmlDoc::decodeEntities(v));
        };
        attr("fill"); attr("stroke"); attr("stroke-width"); attr("display"); attr("visibility");
        if (!css.isEmpty()) {
            const auto byTag = css.constFind(rawCopy(tag));
            if (byTag != css.constEnd()) p.merge(*byTag);
            QByteArrayView cls = doc.rawAttr(node, "class");
            while (!cls.isEmpty()) {
                qsizetype i = 0;
                while (i < cls.size() && !std::isspace(uint8_t(cls[i]))) ++i;
                if (i > 0) {
                    QByteArray key;
                    key.reserve(i + 1);
                    key += '.';
                    key.append(cls.data(), i);
                    const auto byClass = css.constFind(key);
                    if (byClass != css.constEnd()) p.merge(*byClass);
                }
                cls = i < cls.size() ? cls.sliced(i + 1) : QByteArrayView();
            }
        }
        const QByteArrayView style = doc.rawAttr(node, "style");
        if (!style.isEmpty()) {
            styleKeep = XmlDoc::decodeEntities(style);
            declarations(styleKeep, p);
        }
        return p;
    }

    void image(int node, const Matrix& m) {
        QByteArray hrefOwned = doc.attr(node, "href");
        if (trimmedView(hrefOwned).isEmpty()) hrefOwned = doc.attr(node, "xlink:href");
        const QByteArrayView href = trimmedView(hrefOwned);
        const QByteArray bytes = href.startsWith("data:image") ? decodeBase64Loose(href) : QByteArray();
        const double w = num(doc, node, "width"), h = num(doc, node, "height");
        if (bytes.isEmpty() || w <= 0 || h <= 0) { ++linkedImages; return; }
        const double x = num(doc, node, "x"), y = num(doc, node, "y");
        const Pt a = m.apply({x, y}), b = m.apply({x + w, y + h});
        images.push_back({bytes, Box{std::min(a.x, b.x), std::min(a.y, b.y), std::max(a.x, b.x), std::max(a.y, b.y)}});
    }

    void walk(int node, const Matrix& parent, int fill0, int stroke0, const QStringList& parentGroups) {
        const QByteArrayView tag = XmlDoc::localName(doc.node(node).tag);
        if (tag == "text") ++texts;
        if (skipped(tag)) return;
        QByteArray styleKeep;
        const Props props = properties(node, tag, styleKeep);
        if ((props.hasDisplay && trimmedView(props.display) == "none") || (props.hasVisibility && trimmedView(props.visibility) == "hidden")) return;
        const QByteArrayView tf = doc.rawAttr(node, "transform");
        const Matrix m = tf.isEmpty() ? parent : parent * svgTransform(tf);
        if (tag == "image") { image(node, m); return; }
        if (tag == "use") { ++clones; return; }
        const int fill = props.hasFill ? parseColour(props.fill, fill0) : fill0;
        const int stroke = props.hasStroke ? parseColour(props.stroke, stroke0) : stroke0;
        if (isShape(tag)) {
            bool noWidth = false;
            if (props.hasStrokeWidth) {
                double v = 1;
                const QByteArrayView sw = trimmedView(props.strokeWidth);
                const char* end = sw.data() + sw.size();
                if (!sw.isEmpty() && detail::parseDouble(sw.data(), end, v) && v == 0) noWidth = true;
            }
            std::optional<QString> name;
            QByteArray label = doc.attr(node, "inkscape:label");
            if (trimmedView(label).isEmpty()) label = doc.attr(node, "data-name");
            if (!trimmedView(label).isEmpty()) name = QString::fromUtf8(label);
            tasks.push_back({node, m, fill, stroke, noWidth, parentGroups, std::move(name)});
        }
        const int first = doc.node(node).firstChild;
        if (first < 0) return;
        if (tag == "g") {
            QStringList groups = parentGroups;
            groups.push_back(QStringLiteral("g%1").arg(ids++));
            for (int c = first; c >= 0; c = doc.node(c).nextSibling) walk(c, m, fill, stroke, groups);
        } else {
            for (int c = first; c >= 0; c = doc.node(c).nextSibling) walk(c, m, fill, stroke, parentGroups);
        }
    }
};

PolySet shapeOf(const XmlDoc& doc, int node, QByteArrayView tag, double seg, PointBudget& budget) {
    PolySet out;
    const auto addMoved = [&](const Poly& p, double dx, double dy) {
        if (p.size() < 2) return;
        std::span<Pt> o = out.addUninitialized(p.size());
        for (size_t i = 0; i < p.size(); ++i) o[i] = {p[i].x + dx, p[i].y + dy};
    };
    if (tag == "path") {
        const QByteArrayView raw = doc.rawAttr(node, "d");
        if (raw.indexOf('&') >= 0) { const QByteArray d = XmlDoc::decodeEntities(raw); return pathData(d, seg, &budget); }
        return pathData(raw, seg, &budget);
    }
    if (tag == "rect") {
        const double w = num(doc, node, "width"), h = num(doc, node, "height");
        if (w > 0 && h > 0) addMoved(Shapes::rect(w, h, std::max(num(doc, node, "rx"), num(doc, node, "ry"))), num(doc, node, "x"), num(doc, node, "y"));
    } else if (tag == "circle") {
        const double r = num(doc, node, "r");
        if (r > 0) addMoved(safeEllipse(2 * r, 2 * r, seg), num(doc, node, "cx") - r, num(doc, node, "cy") - r);
    } else if (tag == "ellipse") {
        const double rx = num(doc, node, "rx"), ry = num(doc, node, "ry");
        if (rx > 0 && ry > 0) addMoved(safeEllipse(2 * rx, 2 * ry, seg), num(doc, node, "cx") - rx, num(doc, node, "cy") - ry);
    } else if (tag == "line") {
        const Pt p[2] = {{num(doc, node, "x1"), num(doc, node, "y1")}, {num(doc, node, "x2"), num(doc, node, "y2")}};
        out.add(PolyView(p, 2));
    } else if (tag == "polyline" || tag == "polygon") {
        const std::vector<double> n = numbers(doc.rawAttr(node, "points"));
        const size_t count = n.size() / 2;
        if (count >= 2) {
            const bool polygon = tag == "polygon";
            std::span<Pt> o = out.addUninitialized(count + (polygon ? 1 : 0));
            for (size_t i = 0; i < count; ++i) o[i] = {n[2 * i], n[2 * i + 1]};
            if (polygon) o[count] = o[0];
        }
    }
    budget.take(qint64(out.pointCount()));
    return out;
}

}  // namespace

double Matrix::scale() const { return std::sqrt(std::fabs(a * d - b * c)); }

int clampSteps(double v, int lo, int hi) {
    if (!(v > lo)) return lo;
    if (v >= hi) return hi;
    return int(std::ceil(v));
}

Poly safeEllipse(double w, double h, double segment) {
    if (!std::isfinite(w) || !std::isfinite(h)) return {};
    const double around = PI * (std::fabs(w) + std::fabs(h)) / 2;
    return Shapes::ellipse(w, h, std::max(segment, around / 20000));
}

double parseFloatOr(QByteArrayView s, double fallback) {
    const QByteArrayView v = trimmedView(s);
    if (v.isEmpty()) return fallback;
    double out = 0;
    const char* q = detail::parseDouble(v.data(), v.data() + v.size(), out);
    return q && std::isfinite(out) ? out : fallback;
}

QByteArray decodeBase64Loose(QByteArrayView text) {
    const qsizetype i = text.indexOf("base64,");
    const QByteArrayView body = i >= 0 ? text.sliced(i + 7) : text;
    QByteArray decoded = QByteArray::fromBase64(rawCopy(body));
    return decoded.size() > 8 ? decoded : QByteArray();
}

Matrix svgTransform(QByteArrayView s) {
    Matrix m;
    qsizetype i = 0;
    while (i < s.size()) {
        const qsizetype open = s.indexOf('(', i);
        if (open < 0) break;
        const qsizetype close = s.indexOf(')', open + 1);
        if (close < 0) break;
        // Der Name steht unmittelbar vor der Klammer.
        qsizetype e = open;
        while (e > i && std::isspace(uint8_t(s[e - 1]))) --e;
        qsizetype b = e;
        while (b > i && std::isalpha(uint8_t(s[b - 1]))) --b;
        const QByteArrayView name = s.sliced(b, e - b);
        const std::vector<double> v = numbers(s.sliced(open + 1, close - open - 1));
        const auto at = [&](size_t k, double d) { return k < v.size() ? v[k] : d; };
        const auto rad = [](double deg) { return deg * PI / 180; };
        if (name == "matrix") { if (v.size() == 6) m = m * Matrix{v[0], v[1], v[2], v[3], v[4], v[5]}; }
        else if (name == "translate") m = m * Matrix{1, 0, 0, 1, at(0, 0), at(1, 0)};
        else if (name == "scale") m = m * Matrix{at(0, 1), 0, 0, at(1, at(0, 1)), 0, 0};
        else if (name == "rotate") {
            const double r = rad(at(0, 0)), cx = at(1, 0), cy = at(2, 0), co = std::cos(r), si = std::sin(r);
            m = m * Matrix{1, 0, 0, 1, cx, cy} * Matrix{co, si, -si, co, 0, 0} * Matrix{1, 0, 0, 1, -cx, -cy};
        }
        else if (name == "skewX") m = m * Matrix{1, 0, std::tan(rad(at(0, 0))), 1, 0, 0};
        else if (name == "skewY") m = m * Matrix{1, std::tan(rad(at(0, 0))), 0, 1, 0, 0};
        i = close + 1;
    }
    return m;
}

PolySet pathData(QByteArrayView d, double segment, PointBudget* budget) {
    PolySet out;
    Poly cur;
    Pt pos, start;
    std::optional<Pt> lastCtrl;
    char lastCmd = ' ', cmd = ' ';
    const char* p = d.data();
    const char* end = p + d.size();

    // Wie ein Tokenizer: alles, was weder Befehl noch Zahl ist, wird übersprungen.
    const auto skip = [&] {
        while (p < end && !isCommand(*p)) {
            if (startsNumber(*p)) {
                double probe;
                if (detail::parseDouble(p, end, probe)) return;
            }
            ++p;
        }
    };
    const auto n = [&]() -> double {
        skip();
        if (p >= end || isCommand(*p)) throw ImportError(badPath());
        double v = 0;
        p = detail::parseDouble(p, end, v);
        if (!std::isfinite(v)) throw ImportError(badPath());
        return v;
    };
    /** "a1 1 0 01 2 2": Flags sind einstellig und dürfen an der nächsten Zahl kleben. */
    const auto flag = [&]() -> bool {
        skip();
        if (p >= end || (*p != '0' && *p != '1')) throw ImportError(badPath());
        return *p++ == '1';
    };
    const auto flush = [&] {
        if (cur.size() >= 2) {
            if (budget) budget->take(qint64(cur.size()));
            out.add(PolyView(cur));
        }
        cur.clear();
    };
    const auto to = [&](Pt q) {
        if (cur.empty()) cur.push_back(pos);
        cur.push_back(q);
        pos = q;
        if (cur.size() > size_t(MAX_POINTS)) throw ImportError(tooComplex());
    };

    for (;;) {
        skip();
        if (p >= end) break;
        if (isCommand(*p)) cmd = *p++;
        else if (cmd == ' ') throw ImportError(badPath());
        const bool rel = cmd >= 'a';
        const auto pt = [&]() -> Pt {
            const double x = n(), y = n();
            return rel ? Pt{pos.x + x, pos.y + y} : Pt{x, y};
        };
        const char up = rel ? char(cmd - 32) : cmd;
        switch (up) {
        case 'M':
            flush();
            pos = pt();
            start = pos;
            cur.push_back(pos);
            cmd = rel ? 'l' : 'L';
            lastCtrl.reset();
            break;
        case 'L': to(pt()); lastCtrl.reset(); break;
        case 'H': { const double x = n(); to({rel ? pos.x + x : x, pos.y}); lastCtrl.reset(); break; }
        case 'V': { const double y = n(); to({pos.x, rel ? pos.y + y : y}); lastCtrl.reset(); break; }
        case 'C': case 'S': {
            const char was = lastCmd >= 'a' ? char(lastCmd - 32) : lastCmd;
            const Pt c1 = up == 'C' ? pt() : (lastCtrl && (was == 'C' || was == 'S')) ? Pt{2 * pos.x - lastCtrl->x, 2 * pos.y - lastCtrl->y} : pos;
            const Pt c2 = pt(), q = pt();
            cubicTo(pos, c1, c2, q, segment, to);
            lastCtrl = c2;
            break;
        }
        case 'Q': case 'T': {
            const char was = lastCmd >= 'a' ? char(lastCmd - 32) : lastCmd;
            const Pt c = up == 'Q' ? pt() : (lastCtrl && (was == 'Q' || was == 'T')) ? Pt{2 * pos.x - lastCtrl->x, 2 * pos.y - lastCtrl->y} : pos;
            const Pt q = pt();
            const Pt c1{pos.x + (c.x - pos.x) * 2 / 3, pos.y + (c.y - pos.y) * 2 / 3}, c2{q.x + (c.x - q.x) * 2 / 3, q.y + (c.y - q.y) * 2 / 3};
            cubicTo(pos, c1, c2, q, segment, to);
            lastCtrl = c;
            break;
        }
        case 'A': {
            const double rx = n(), ry = n(), rot = n();
            const bool large = flag(), sweep = flag();
            const Pt q = pt();
            arcTo(pos, rx, ry, rot, large, sweep, q, segment, to);
            lastCtrl.reset();
            break;
        }
        case 'Z':
            if (!cur.empty()) { to(start); flush(); }
            pos = start;
            lastCtrl.reset();
            break;
        default:
            throw ImportError(badPath());
        }
        lastCmd = cmd;
        if (up == 'Z') {
            skip();
            if (p < end && !isCommand(*p)) throw ImportError(badPath());
        }
    }
    flush();
    return out;
}

// ---- Farben ----

int parseColour(QByteArrayView value, int inherited) {
    const QByteArrayView trimmed = trimmedView(value);
    // Fast immer kurz: ohne Speicheranforderung kleinschreiben, das läuft für jedes Element.
    char lower[64];
    if (trimmed.size() >= qsizetype(sizeof lower)) return COLOUR_OTHER;
    for (qsizetype i = 0; i < trimmed.size(); ++i) {
        const char c = trimmed[i];
        lower[i] = c >= 'A' && c <= 'Z' ? char(c + 32) : c;
    }
    const QByteArrayView v(lower, trimmed.size());
    if (v == "none" || v == "transparent") return COLOUR_NONE;
    if (v == "inherit") return inherited;
    static const struct { const char* name; int rgb; } names[] = {
        {"black", 0x000000}, {"white", 0xffffff}, {"red", 0xff0000}, {"green", 0x008000}, {"lime", 0x00ff00}, {"blue", 0x0000ff},
        {"yellow", 0xffff00}, {"orange", 0xffa500}, {"purple", 0x800080}, {"magenta", 0xff00ff}, {"fuchsia", 0xff00ff}, {"cyan", 0x00ffff},
        {"aqua", 0x00ffff}, {"gray", 0x808080}, {"grey", 0x808080}, {"silver", 0xc0c0c0}, {"brown", 0xa52a2a}, {"pink", 0xffc0cb},
        {"navy", 0x000080}, {"maroon", 0x800000}, {"teal", 0x008080}};
    if (v.startsWith('#')) {
        const auto hex = [](char c) { return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : -1; };
        int out = 0;
        if (v.size() == 7) {
            for (int i = 1; i < 7; ++i) { const int h = hex(v[i]); if (h < 0) return COLOUR_OTHER; out = out * 16 + h; }
            return out;
        }
        if (v.size() == 4) {
            for (int i = 1; i < 4; ++i) { const int h = hex(v[i]); if (h < 0) return COLOUR_OTHER; out = out * 256 + h * 17; }
            return out;
        }
        return COLOUR_OTHER;
    }
    if (v.startsWith("rgb") && v.endsWith(')')) {
        const qsizetype open = v.indexOf('(');
        if (open != 3 && open != 4) return COLOUR_OTHER;
        if (open == 4 && v[3] != 'a') return COLOUR_OTHER;
        // Teile durch Leerraum, Komma oder Schrägstrich getrennt; ein Prozentzeichen zählt zum Teil davor.
        const QByteArrayView body = v.sliced(open + 1, v.size() - open - 2);
        std::vector<QByteArrayView> parts;
        qsizetype i = 0;
        while (i < body.size()) {
            while (i < body.size() && (std::isspace(uint8_t(body[i])) || body[i] == ',' || body[i] == '/')) ++i;
            const qsizetype a = i;
            while (i < body.size() && !(std::isspace(uint8_t(body[i])) || body[i] == ',' || body[i] == '/')) ++i;
            if (i > a) parts.push_back(body.sliced(a, i - a));
        }
        if (parts.size() < 3) return COLOUR_OTHER;
        int out = 0;
        for (size_t k = 0; k < 3; ++k) {
            double x = 0;
            if (!detail::parseDouble(parts[k].data(), parts[k].data() + parts[k].size(), x) || !std::isfinite(x)) return COLOUR_OTHER;
            const double scaled = parts[k].endsWith('%') ? x * 2.55 : x;
            const int c = int(std::clamp(std::trunc(scaled), 0.0, 255.0));
            out = out * 256 + c;
        }
        return out;
    }
    for (const auto& n : names) if (v == n.name) return n.rgb;
    return COLOUR_OTHER;
}

QString colourKey(int rgb) { return QStringLiteral("#%1").arg(rgb, 6, 16, QLatin1Char('0')); }

QString colourName(int rgb) {
    static const struct { const char* name; int rgb; } names[] = {
        {"Schwarz", 0x000000}, {"Weiß", 0xffffff}, {"Grau", 0x808080}, {"Rot", 0xff0000}, {"Grün", 0x00a000}, {"Blau", 0x0000ff},
        {"Gelb", 0xffff00}, {"Orange", 0xff8000}, {"Violett", 0x8000c0}, {"Rosa", 0xff80c0}, {"Türkis", 0x00c0c0}, {"Braun", 0x804000}};
    const char* best = names[0].name;
    int bestD = INT_MAX;
    const int r = rgb >> 16 & 255, g = rgb >> 8 & 255, b = rgb & 255;
    for (const auto& n : names) {
        const int dr = (n.rgb >> 16 & 255) - r, dg = (n.rgb >> 8 & 255) - g, db = (n.rgb & 255) - b;
        const int d = dr * dr + dg * dg + db * db;
        if (d < bestD) { bestD = d; best = n.name; }
    }
    return QString::fromUtf8(best);
}

void finishDrawables(std::vector<RawDrawable>& raw, VectorImport& out) {
    // Gruppe um alles sagt nichts und entfällt.
    qsizetype drop = 0;
    while (!raw.empty()) {
        bool same = true;
        const QStringList& g0 = raw[0].groups;
        if (g0.size() <= drop) break;
        const QString& first = g0[drop];
        for (const RawDrawable& r : raw) if (r.groups.size() <= drop || r.groups[drop] != first) { same = false; break; }
        if (!same) break;
        ++drop;
    }
    bool anyGroup = false;
    for (RawDrawable& r : raw) {
        if (drop) r.groups = r.groups.mid(drop);
        anyGroup = anyGroup || !r.groups.isEmpty();
    }
    if (raw.size() > 1 && !anyGroup) {
        const QStringList star{QStringLiteral("*")};
        for (RawDrawable& r : raw) r.groups = star;
    }
    // Mindestens zwei Sorten (Farbe, Füllung) werden Ebenen; eine Farbe bleibt auf der gewählten Ebene.
    std::vector<int> colours;
    bool two = false;
    int firstColour = COLOUR_OTHER;
    bool firstFill = false, seen = false;
    for (const RawDrawable& r : raw) {
        if (r.colour < 0) continue;
        if (!seen) { firstColour = r.colour; firstFill = r.fill; seen = true; }
        else if (r.colour != firstColour || r.fill != firstFill) two = true;
    }
    QHash<int, QString> keys;
    if (two) {
        for (const RawDrawable& r : raw) {
            if (r.colour >= 0 && !keys.contains(r.colour)) {
                keys.insert(r.colour, colourKey(r.colour));
                colours.push_back(r.colour);
            }
        }
        QHash<QString, int> nameCount;
        for (const int c : colours) ++nameCount[colourName(c)];
        int order = 0;
        for (const int c : colours) {
            const QString name = colourName(c);
            out.layers.push_back({keys[c], nameCount[name] > 1 ? name + QLatin1Char(' ') + keys[c] : name, order++, c != 0xffffff});
        }
    }
    out.items.resize(raw.size());
    for (size_t i = 0; i < raw.size(); ++i) {
        RawDrawable& r = raw[i];
        ImportItem& it = out.items[i];
        it.polys = std::move(r.polys);
        if (r.colour >= 0 && two) it.layerKey = keys.value(r.colour);
        it.fill = r.fill;
        it.groups = std::move(r.groups);
        it.name = std::move(r.name);
    }
}

VectorImport parseSvg(const QByteArray& bytes) {
    const QByteArray text = decodeText(bytes);
    std::optional<XmlDoc> doc;
    try {
        doc.emplace(text);
    } catch (const XmlError&) {
        throw ImportError(QStringLiteral("SVG konnte nicht gelesen werden"));
    }
    const int root = doc->root();
    if (XmlDoc::localName(doc->node(root).tag) != "svg") throw ImportError(QStringLiteral("Keine SVG-Datei"));
    std::vector<QByteArray> cssKeep;
    const QHash<QByteArray, Props> css = cssRules(*doc, cssKeep);
    Walker w{*doc, css};
    w.tasks.reserve(doc->nodeCount());
    w.walk(root, rootMatrix(*doc, root), 0x000000, COLOUR_NONE, {});

    PointBudget budget(tooComplex());
    std::vector<Done> done(w.tasks.size());
    parallelBlocks(std::ptrdiff_t(w.tasks.size()), 64, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
        for (std::ptrdiff_t i = a; i < b; ++i) {
            const Task& t = w.tasks[size_t(i)];
            // Nie gröber als die Vorlage, aber auch bei hochskalierten Dateien (viewBox 0 0 1 1) rund: 0,2 mm auf der Fläche.
            const double k = t.m.scale();
            const double seg = k > 1 ? CURVE_MM / k : CURVE_MM;
            PolySet world = shapeOf(*doc, t.node, XmlDoc::localName(doc->node(t.node).tag), seg, budget);
            if (world.empty()) continue;
            for (Pt& q : world.allPoints()) q = t.m.apply(q);
            bool allClosed = true;
            for (PolyView poly : world) if (poly.size() < 4 || !isClosed(poly)) { allClosed = false; break; }
            // Ein Strich macht es zur Linie in der Strichfarbe, sonst ist eine geschlossene Form eine Fläche. Buchstaben behalten ihre Löcher.
            const bool stroked = t.stroke != COLOUR_NONE && !t.noWidth;
            const bool filled = !stroked && t.fill != COLOUR_NONE && allClosed;
            Done& out = done[size_t(i)];
            out.colour = stroked ? t.stroke : filled ? t.fill : COLOUR_OTHER;
            out.filled = filled;
            if (world.size() == 1) {
                if (world[0].size() >= 2) out.parts.push_back(std::move(world));
            } else {
                out.parts = PartSplitter::split(world).parts;
            }
        }
    });

    VectorImport r;
    r.images = std::move(w.images);
    std::vector<RawDrawable> raw;
    raw.reserve(done.size());
    int partGroup = 0;
    for (size_t i = 0; i < done.size(); ++i) {
        Done& d = done[i];
        const Task& t = w.tasks[i];
        QStringList own = t.groups;
        if (d.parts.size() > 1) own.push_back(QStringLiteral("p%1").arg(partGroup++));
        for (PolySet& part : d.parts) raw.push_back({std::move(part), d.colour, d.filled, own, t.name});
    }
    if (raw.empty() && r.images.empty()) throw ImportError(QStringLiteral("Keine Vektoren gefunden (Text vorher in Pfade umwandeln)"));
    if (w.texts > 0) r.skipped.push_back(QStringLiteral("Text (%1)").arg(w.texts));
    if (w.linkedImages > 0) r.skipped.push_back(QStringLiteral("verlinkte Bilder (%1)").arg(w.linkedImages));
    if (w.clones > 0) r.skipped.push_back(QStringLiteral("Klone (%1)").arg(w.clones));
    finishDrawables(raw, r);
    return r;
}

}  // namespace lumacut::import
