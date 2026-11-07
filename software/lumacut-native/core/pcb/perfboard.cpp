#include "core/pcb/perfboard.h"

#include "core/text.h"
#include <QFile>
#include <QImage>
#include <QBuffer>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPainter>
#include <QPainterPath>
#include <algorithm>
#include <cmath>
#include <map>
#include <mutex>
#include <numbers>
#include <set>

namespace lumacut::pcb {
namespace {

constexpr double kPi = std::numbers::pi;

double pathLength(const Polys& ps) {
    double s = 0;
    for (const Poly& p : ps) for (size_t i = 1; i < p.size(); ++i) s += std::hypot(p[i].x - p[i - 1].x, p[i].y - p[i - 1].y);
    return s;
}
Poly circleRing(Pt c, double r) {
    Poly p = circle(c.x, c.y, r, 0.01);
    return closed(std::move(p));
}
Poly rectRing(double x0, double y0, double x1, double y1) { return {{x0, y0}, {x1, y0}, {x1, y1}, {x0, y1}, {x0, y0}}; }

struct RotPt { double x, y; };
RotPt rotD(double x, double y, int rot) {
    switch (((rot % 4) + 4) % 4) {
    case 1: return {-y, x};
    case 2: return {-x, -y};
    case 3: return {y, -x};
    default: return {x, y};
    }
}
/** Pitch units relative to pin 1 of a placed part to board mm. */
Pt partPoint(const Placed& p, const PerfBoard& b, double x, double y) {
    const RotPt q = rotD(x, y, p.rot);
    const Pt o = b.hole(p.at);
    return {o.x + q.x * b.pitch, o.y + q.y * b.pitch};
}
/** Outline polylines of shapes, in board mm. */
void shapeLines(const std::vector<PartShape>& shapes, const Placed& p, const PerfBoard& b, Polys& out) {
    for (const PartShape& s : shapes) {
        switch (s.kind) {
        case PartShape::Rect: {
            Poly q{partPoint(p, b, s.a, s.b), partPoint(p, b, s.c, s.b), partPoint(p, b, s.c, s.d), partPoint(p, b, s.a, s.d)};
            q.push_back(q.front());
            out.push_back(std::move(q));
            break;
        }
        case PartShape::Line: out.push_back({partPoint(p, b, s.a, s.b), partPoint(p, b, s.c, s.d)}); break;
        case PartShape::Circle: out.push_back(circleRing(partPoint(p, b, s.a, s.b), s.c * b.pitch)); break;
        case PartShape::Plus: {
            const double h = s.c / 2;
            out.push_back({partPoint(p, b, s.a - h, s.b), partPoint(p, b, s.a + h, s.b)});
            out.push_back({partPoint(p, b, s.a, s.b - h), partPoint(p, b, s.a, s.b + h)});
            break;
        }
        }
    }
}

QString num(double v) { return QString::number(v, 'f', 3); }

}  // namespace

// ---- Board ----

Pt PerfBoard::hole(int c, int r) const {
    const double x0 = (width - (cols - 1) * pitch) / 2, y0 = (height - (rows - 1) * pitch) / 2;
    return {x0 + c * pitch, y0 + r * pitch};
}
std::vector<Pt> PerfBoard::mountHoles() const {
    if (mountDia <= 0) return {};
    return {{mountInset, mountInset}, {width - mountInset, mountInset}, {width - mountInset, height - mountInset}, {mountInset, height - mountInset}};
}
bool PerfBoard::blockedByMount(GridPt g) const {
    const Pt h = hole(g);
    const double reach = (isEdge(g) ? padDia * 0.8 : padDia / 2) + mountDia / 2 + 0.2;
    for (const Pt& m : mountHoles()) if (std::hypot(h.x - m.x, h.y - m.y) < reach) return true;
    return false;
}
std::optional<GridPt> PerfBoard::holeAt(Pt p) const {
    const Pt o = hole(0, 0);
    const GridPt g{int(std::lround((p.x - o.x) / pitch)), int(std::lround((p.y - o.y) / pitch))};
    if (!contains(g)) return std::nullopt;
    const Pt h = hole(g);
    if (std::abs(h.x - p.x) > pitch / 2 || std::abs(h.y - p.y) > pitch / 2) return std::nullopt;
    return g;
}
Poly PerfBoard::padShape(GridPt g, double grow) const {
    const Pt c = hole(g);
    if (!isEdge(g)) return circle(c.x, c.y, padDia / 2 + grow, 0.01);
    // Oblong bus pad, upright.
    const double r = padDia / 2 + grow, half = padDia * 0.3;
    Poly out;
    const int n = 16;
    for (int i = 0; i <= n; ++i) { const double a = kPi + kPi * i / n; out.push_back({c.x + r * std::cos(a), c.y - half + r * std::sin(a)}); }
    for (int i = 0; i <= n; ++i) { const double a = kPi * i / n; out.push_back({c.x + r * std::cos(a), c.y + half + r * std::sin(a)}); }
    return out;
}
QString PerfBoard::colName(int c) {
    return QString(QChar(u'A' + c % 26)) + QString(c / 26, QLatin1Char(0x27));
}
std::optional<GridPt> PerfBoard::parseHole(const QString& name) const {
    // Column: a letter and primes. Row: a letter and primes, or a number.
    qsizetype i = 0;
    const auto letter = [&](int& out) {
        if (i >= name.size() || !name[i].isLetter()) return false;
        out = name[i].toUpper().unicode() - u'A';
        ++i;
        while (i < name.size() && name[i] == QLatin1Char(0x27)) { out += 26; ++i; }
        return out >= 0 && out < 26 * 8;
    };
    int c = 0, r = 0;
    if (!letter(c)) return std::nullopt;
    if (rowLetters) {
        if (!letter(r) || i != name.size()) return std::nullopt;
    } else {
        bool ok = false;
        r = name.mid(i).toInt(&ok) - 1;
        if (!ok) return std::nullopt;
    }
    const GridPt g{c, r};
    if (!contains(g)) return std::nullopt;
    return g;
}
std::vector<PerfBoard> PerfBoard::templates() {
    const auto make = [](double w, double h, int c, int r) {
        PerfBoard b;
        b.name = QStringLiteral("%1 × %2").arg(w).arg(h);
        b.width = w; b.height = h; b.cols = c; b.rows = r;
        return b;
    };
    // 70 × 90: 26 × 32 holes like the owner's board in hardware/laser-interface-v2 (build_perfboard.py, there lying across).
    return {make(20, 80, 6, 28), make(30, 70, 10, 24), make(40, 60, 14, 20), make(50, 70, 18, 24), make(70, 90, 26, 32)};
}

// ---- Library ----

std::vector<PartDef> parsePartLibrary(const QByteArray& json) {
    QJsonParseError err;
    const QJsonDocument doc = QJsonDocument::fromJson(json, &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject()) throw std::runtime_error("Bauteil-Bibliothek ist kein gültiges JSON.");
    const auto shapes = [](const QJsonArray& a) {
        std::vector<PartShape> out;
        for (const QJsonValue& v : a) {
            const QJsonArray s = v.toArray();
            const QString k = s.at(0).toString();
            PartShape p;
            p.kind = k == QLatin1String("line") ? PartShape::Line : k == QLatin1String("circle") ? PartShape::Circle
                   : k == QLatin1String("plus") ? PartShape::Plus : PartShape::Rect;
            p.a = s.at(1).toDouble(); p.b = s.at(2).toDouble(); p.c = s.at(3).toDouble(); p.d = s.at(4).toDouble();
            out.push_back(p);
        }
        return out;
    };
    std::vector<PartDef> out;
    for (const QJsonValue& v : doc.object().value(QLatin1String("parts")).toArray()) {
        const QJsonObject o = v.toObject();
        PartDef d;
        d.id = o.value("id").toString();
        d.name = o.value("name").toString();
        d.category = o.value("category").toString();
        d.prefix = o.value("prefix").toString();
        d.value = o.value("value").toString();
        d.hint = o.value("hint").toString();
        d.order = o.value("order").toInt(50);
        d.polarized = o.value("polarized").toBool();
        for (const QJsonValue& run : o.value("pins").toArray()) {
            const QJsonArray r = run.toArray();
            for (int i = 0; i < r.at(4).toInt(); ++i) d.pins.push_back({r.at(0).toInt() + i * r.at(2).toInt(), r.at(1).toInt() + i * r.at(3).toInt()});
        }
        d.body = shapes(o.value("body").toArray());
        d.mark = shapes(o.value("mark").toArray());
        if (d.id.isEmpty() || d.pins.empty()) throw std::runtime_error("Bauteil ohne Kennung oder ohne Pins in der Bibliothek.");
        out.push_back(std::move(d));
    }
    return out;
}
const std::vector<PartDef>& partLibrary() {
    static const std::vector<PartDef> lib = [] {
        QFile f(QStringLiteral(":/pcb/perfboard_parts.json"));
        if (!f.open(QIODevice::ReadOnly)) throw std::runtime_error("Bauteil-Bibliothek fehlt.");
        return parsePartLibrary(f.readAll());
    }();
    return lib;
}
const PartDef* findPart(const QString& id) {
    for (const PartDef& d : partLibrary()) if (d.id == id) return &d;
    return nullptr;
}

// ---- Placement ----

GridPt rotated(GridPt d, int rot) {
    const RotPt q = rotD(d.c, d.r, rot);
    return {int(q.x), int(q.y)};
}
std::vector<GridPt> pinsOf(const Placed& p, const PartDef& def) {
    std::vector<GridPt> out;
    for (const GridPt& g : def.pins) { const GridPt q = rotated(g, p.rot); out.push_back({p.at.c + q.c, p.at.r + q.r}); }
    return out;
}
std::optional<Box> bodyBox(const Placed& p, const PartDef& def, const PerfBoard& b) {
    std::optional<Box> box;
    const auto grow = [&](Pt q) { box = box ? box->united({q.x, q.y, q.x, q.y}) : Box{q.x, q.y, q.x, q.y}; };
    for (const PartShape& s : def.body)
        if (s.kind == PartShape::Rect || s.kind == PartShape::Line) { grow(partPoint(p, b, s.a, s.b)); grow(partPoint(p, b, s.c, s.d)); }
    if (!box) for (const GridPt& g : pinsOf(p, def)) grow(b.hole(g));
    return box;
}
Polys partOutline(const Placed& p, const PartDef& def, const PerfBoard& b) {
    Polys out;
    shapeLines(def.body, p, b, out);
    shapeLines(def.mark, p, b, out);
    return out;
}
std::vector<GridPt> route(GridPt a, GridPt b, bool verticalFirst) {
    if (a == b) return {a};
    if (a.c == b.c || a.r == b.r) return {a, b};
    return {a, verticalFirst ? GridPt{a.c, b.r} : GridPt{b.c, a.r}, b};
}
QString nextRef(const PerfDesign& d, const QString& prefix) {
    int n = 0;
    for (const Placed& p : d.parts) {
        if (!p.ref.startsWith(prefix)) continue;
        bool ok = false;
        const int k = p.ref.mid(prefix.size()).toInt(&ok);
        if (ok) n = std::max(n, k);
    }
    return prefix + QString::number(n + 1);
}

// ---- Markings ----

Poly wireMarkLine(const Wire& w, const PerfBoard& b, int side) {
    // Shifted half a pitch into the channel beside the pads: horizontal runs below their row, vertical runs right of their
    // column. There the lacquer is free of pads all along, the line stays whole.
    Poly out;
    const double h = side * b.pitch / 2;
    for (size_t i = 0; i < w.pts.size(); ++i) {
        double dx = 0, dy = 0;
        const auto seg = [&](GridPt a, GridPt c) { if (a.r == c.r && a.c != c.c) dy = h; if (a.c == c.c && a.r != c.r) dx = h; };
        if (i > 0) seg(w.pts[i - 1], w.pts[i]);
        if (i + 1 < w.pts.size()) seg(w.pts[i], w.pts[i + 1]);
        const Pt p = b.hole(w.pts[i]);
        out.push_back({p.x + dx, p.y + dy});
    }
    return out;
}

Polys padKeepOut(const PerfDesign& d, double grow) {
    const PerfBoard& b = d.board;
    Polys pads;
    pads.reserve(size_t(b.cols * b.rows + 4));
    for (int r = 0; r < b.rows; ++r) for (int c = 0; c < b.cols; ++c) pads.push_back(b.padShape({c, r}, grow));
    for (const Pt& m : b.mountHoles()) pads.push_back(circle(m.x, m.y, b.mountDia / 2 + grow, 0.01));
    return unionPolys(pads);
}
Polys markRegion(const PerfDesign& d, const MarkOptions& o) {
    const double e = 0.3;
    Polys board{{{e, e}, {d.board.width - e, e}, {d.board.width - e, d.board.height - e}, {e, d.board.height - e}}};
    return subtractPolys(board, padKeepOut(d, o.padClearMm + o.beamMm / 2));
}
Polys textAt(const QString& text, Pt at, double heightMm, bool mirror) {
    if (text.trimmed().isEmpty() || heightMm <= 0) return {};
    const PolySet raw = textPaths(text, heightMm * 1.4);
    const auto b = boundsOf(raw);
    if (!b || b->height() <= 0) return {};
    const double k = heightMm / b->height();
    const double w = b->width() * k;
    Polys out;
    for (PolyView p : raw) {
        Poly q;
        for (const Pt& v : p) {
            double x = (v.x - b->minX) * k - w / 2, y = (v.y - b->minY) * k - heightMm / 2;
            if (mirror) x = -x;
            q.push_back({at.x + x, at.y + y});
        }
        out.push_back(std::move(q));
    }
    return out;
}
Polys mirrored(const Polys& polys, double width) {
    Polys out = polys;
    for (Poly& p : out) for (Pt& q : p) q = mirrorX(q, width);
    return out;
}

PerfMarks buildMarks(const PerfDesign& d, const MarkOptions& o) {
    const PerfBoard& b = d.board;
    Polys comp, solder, compText, solderText;
    for (const Placed& p : d.parts) {
        const PartDef* def = findPart(p.partId);
        if (!def) continue;
        shapeLines(def->body, p, b, comp);
        shapeLines(def->mark, p, b, comp);
        if (def->polarized) {
            // Pin 1 on the solder side: a ring in the diagonal gap next to it.
            const Pt c = partPoint(p, b, -0.5, -0.5);
            solder.push_back(circleRing(c, 0.3));
        }
        const auto box = bodyBox(p, *def, b);
        if (!box) continue;
        const Pt mid = box->center();
        const bool both = d.markRefs && d.markValues && !p.value.isEmpty();
        if (d.markRefs) for (Poly& q : textAt(p.ref, {mid.x, both ? mid.y - o.textMm * 0.7 : mid.y}, o.textMm)) compText.push_back(std::move(q));
        if (d.markValues && !p.value.isEmpty())
            for (Poly& q : textAt(p.value, {mid.x, both ? mid.y + o.textMm * 0.7 : mid.y}, o.textMm)) compText.push_back(std::move(q));
    }
    for (const Wire& w : d.wires) {
        Poly line = wireMarkLine(w, b);
        if (line.size() >= 2) (w.solder ? solder : comp).push_back(std::move(line));
        // A thick line (24 V, GND) gets a second line in the channel on the other side: there is no room for a wider one.
        if (isThick(w)) {
            Poly other = wireMarkLine(w, b, -1);
            if (other.size() >= 2) (w.solder ? solder : comp).push_back(std::move(other));
        }
    }
    for (const Label& l : d.labels)
        for (Poly& q : textAt(l.text, l.at, l.heightMm, l.solder)) (l.solder ? solderText : compText).push_back(std::move(q));
    if (d.holeNumbers) {
        const Pt first = b.hole(0, 0);
        const double top = first.y - (b.edgeRows ? b.padDia * 0.8 : b.padDia / 2);
        const double hTop = std::clamp(top - 1.0, 0.0, 1.2), hLeft = std::clamp((first.x - b.padDia / 2) * 0.55, 0.0, 1.0);
        if (hTop >= 0.6) for (int c = 0; c < b.cols; ++c)
            for (Poly& q : textAt(PerfBoard::colName(c), {b.hole(c, 0).x, top / 2}, hTop)) compText.push_back(std::move(q));
        if (hLeft >= 0.6) for (int r = 0; r < b.rows; ++r)
            for (Poly& q : textAt(QString::number(r + 1), {(first.x - b.padDia / 2) / 2, b.hole(0, r).y}, hLeft)) compText.push_back(std::move(q));
    }
    const Polys region = markRegion(d, o);
    PerfMarks m;
    m.component = clipLines(comp, region);
    m.solder = clipLines(solder, region);
    const Polys ct = clipLines(compText, region), st = clipLines(solderText, region);
    const double before = pathLength(compText) + pathLength(solderText), after = pathLength(ct) + pathLength(st);
    m.textLostShare = before > 0 ? std::max(0.0, 1 - after / before) : 0;
    m.component.insert(m.component.end(), ct.begin(), ct.end());
    m.solder.insert(m.solder.end(), st.begin(), st.end());
    return m;
}

// ---- Checks ----

namespace {
bool segmentsCross(Pt a, Pt b, Pt c, Pt d, Pt& at) {
    // Axis-parallel segments on the grid: intersection point or overlap.
    const double minAx = std::min(a.x, b.x), maxAx = std::max(a.x, b.x), minAy = std::min(a.y, b.y), maxAy = std::max(a.y, b.y);
    const double minCx = std::min(c.x, d.x), maxCx = std::max(c.x, d.x), minCy = std::min(c.y, d.y), maxCy = std::max(c.y, d.y);
    const double x0 = std::max(minAx, minCx), x1 = std::min(maxAx, maxCx), y0 = std::max(minAy, minCy), y1 = std::min(maxAy, maxCy);
    if (x0 > x1 + 1e-9 || y0 > y1 + 1e-9) return false;
    at = {(x0 + x1) / 2, (y0 + y1) / 2};
    return true;
}
std::vector<GridPt> wireHoles(const Wire& w) {
    std::vector<GridPt> out;
    for (size_t i = 0; i + 1 < w.pts.size(); ++i) {
        const GridPt a = w.pts[i], b = w.pts[i + 1];
        const int n = std::max(std::abs(b.c - a.c), std::abs(b.r - a.r));
        for (int k = 0; k < n; ++k) out.push_back({a.c + (b.c - a.c) * k / std::max(1, n), a.r + (b.r - a.r) * k / std::max(1, n)});
    }
    if (!w.pts.empty()) out.push_back(w.pts.back());
    return out;
}
}  // namespace

std::vector<PerfCheck> perfChecks(const PerfDesign& d, const MarkOptions& o, std::optional<Pt> bedCentre) {
    const PerfBoard& b = d.board;
    std::vector<PerfCheck> out;
    if (!d.note.trimmed().isEmpty()) out.push_back({"note", PerfTone::Warn, d.note.trimmed(), {}});
    out.push_back({"materialtest", PerfTone::Warn,
                   QStringLiteral("Zuerst Materialtest auf einem Reststück: Für Lötstopplack gibt es noch keine gemessenen Werte. Der Startwert ist ungeprüft."), {}});
    std::map<std::pair<int, int>, QStringList> holes;   // hole -> refs of pins on it
    std::vector<std::vector<GridPt>> pins(d.parts.size());
    for (size_t i = 0; i < d.parts.size(); ++i) {
        const Placed& p = d.parts[i];
        const PartDef* def = findPart(p.partId);
        if (!def) { out.push_back({"unknown", PerfTone::Bad, QStringLiteral("%1: Bauteil %2 fehlt in der Bibliothek.").arg(p.ref, p.partId), {p.ref}}); continue; }
        pins[i] = pinsOf(p, *def);
        bool outside = false, edge = false, mount = false;
        for (const GridPt& g : pins[i]) {
            if (!b.contains(g)) { outside = true; continue; }
            holes[{g.c, g.r}] << p.ref;
            edge |= b.isEdge(g);
            mount |= b.blockedByMount(g);
        }
        if (outside) out.push_back({"outside", PerfTone::Bad, QStringLiteral("%1 steht mit Pins außerhalb der Lochreihen.").arg(p.ref), {p.ref}});
        if (edge) out.push_back({"edge", PerfTone::Warn, QStringLiteral("%1 liegt auf der Randreihe mit Langlochpads (Busreihe).").arg(p.ref), {p.ref}});
        if (mount) out.push_back({"mount", PerfTone::Bad, QStringLiteral("%1 berührt ein Befestigungsloch.").arg(p.ref), {p.ref}});
        if (const auto box = bodyBox(p, *def, b); box && !outside && (box->minX < 0 || box->minY < 0 || box->maxX > b.width || box->maxY > b.height))
            out.push_back({"body-outside", PerfTone::Warn, QStringLiteral("Der Körper von %1 ragt über den Platinenrand.").arg(p.ref), {p.ref}});
    }
    for (const auto& [h, refs] : holes)
        if (refs.size() > 1)
            out.push_back({"double", PerfTone::Bad, QStringLiteral("Loch %1 ist doppelt belegt: %2.").arg(b.holeName({h.first, h.second}), refs.join(QStringLiteral(", "))), refs});
    // Bodies overlapping.
    for (size_t i = 0; i < d.parts.size(); ++i)
        for (size_t j = i + 1; j < d.parts.size(); ++j) {
            const PartDef* a = findPart(d.parts[i].partId);
            const PartDef* c = findPart(d.parts[j].partId);
            if (!a || !c) continue;
            const auto x = bodyBox(d.parts[i], *a, b), y = bodyBox(d.parts[j], *c, b);
            if (!x || !y) continue;
            const double w = std::min(x->maxX, y->maxX) - std::max(x->minX, y->minX), h = std::min(x->maxY, y->maxY) - std::max(x->minY, y->minY);
            if (w > 0.05 && h > 0.05)
                out.push_back({"overlap", PerfTone::Warn, QStringLiteral("Die Körper von %1 und %2 überlappen.").arg(d.parts[i].ref, d.parts[j].ref), {d.parts[i].ref, d.parts[j].ref}});
        }
    // Wires: crossing on the same side is a short; a solder bridge over a foreign pad joins it. With nets named, wires
    // of one net may meet anywhere, and a bridge may collect pads that only its own net touches.
    std::map<std::pair<int, int>, std::set<QString>> netsAt;
    for (const Wire& w : d.wires)
        if (!w.net.isEmpty()) for (const GridPt& g : wireHoles(w)) netsAt[{g.c, g.r}].insert(w.net);
    for (size_t i = 0; i < d.wires.size(); ++i) {
        const Wire& wi = d.wires[i];
        for (size_t j = i + 1; j < d.wires.size(); ++j) {
            const Wire& wj = d.wires[j];
            if (wi.solder != wj.solder) continue;
            if (!wi.net.isEmpty() && wi.net == wj.net) continue;
            bool shorted = false;
            for (size_t a = 0; a + 1 < wi.pts.size() && !shorted; ++a)
                for (size_t c = 0; c + 1 < wj.pts.size() && !shorted; ++c) {
                    Pt at;
                    if (!segmentsCross(b.hole(wi.pts[a]), b.hole(wi.pts[a + 1]), b.hole(wj.pts[c]), b.hole(wj.pts[c + 1]), at)) continue;
                    const auto ends = [&](const Wire& w) { return b.hole(w.pts.front()) == at || b.hole(w.pts.back()) == at; };
                    const auto g = b.holeAt(at);
                    const bool endpoint = g && (ends(wi) || ends(wj));
                    if (!endpoint) shorted = true;
                }
            if (shorted)
                out.push_back({"short", PerfTone::Bad, QStringLiteral("Zwei Verbindungen kreuzen sich auf der %1: Kurzschluss.").arg(wi.solder ? QStringLiteral("Lötseite") : QStringLiteral("Bestückungsseite")), {wi.id, wj.id}});
        }
        const std::vector<GridPt> through = wireHoles(wi);
        for (size_t k = 1; k + 1 < through.size(); ++k) {
            auto it = holes.find({through[k].c, through[k].r});
            if (it == holes.end()) continue;
            if (!wi.net.isEmpty()) {
                QStringList others;
                for (const QString& n : netsAt[{through[k].c, through[k].r}]) if (n != wi.net) others << n;
                if (others.isEmpty()) continue;   // the pad belongs to this net only: collected on purpose
                out.push_back({"over-pad", wi.solder ? PerfTone::Bad : PerfTone::Warn,
                               QStringLiteral("Die Verbindung %1 führt über das Pad %2 von %3, das auch an %4 hängt: Kurzschluss.")
                                   .arg(wi.net, b.holeName(through[k]), it->second.join(QStringLiteral(", ")), others.join(QStringLiteral(", "))), it->second});
                continue;
            }
            out.push_back({"over-pad", wi.solder ? PerfTone::Bad : PerfTone::Warn,
                           QStringLiteral("Eine Verbindung führt über das Pad %1 von %2.").arg(b.holeName(through[k]), it->second.join(QStringLiteral(", "))), it->second});
        }
    }
    // Text height against the beam.
    const double minH = minTextHeight(o.beamMm);
    for (const Label& l : d.labels)
        if (l.heightMm < minH)
            out.push_back({"text-small", PerfTone::Warn, QStringLiteral("Text „%1“ ist %2 mm hoch, bei %3 mm Strahl sind mindestens %4 mm lesbar.")
                           .arg(l.text, QString::number(l.heightMm, 'f', 1).replace('.', ','), QString::number(o.beamMm, 'f', 2).replace('.', ','),
                                QString::number(minH, 'f', 1).replace('.', ',')), {l.id}});
    if ((d.markRefs || d.markValues) && o.textMm < minH)
        out.push_back({"text-small", PerfTone::Warn, QStringLiteral("Referenzen sind kleiner als %1 mm und beim Strahl nicht lesbar.").arg(QString::number(minH, 'f', 1).replace('.', ',')), {}});
    // Gaps too narrow for a line between pads.
    const double halfGap = (b.pitch - b.padDia) / 2;
    if (halfGap - o.padClearMm < o.beamMm / 2)
        out.push_back({"gap", PerfTone::Warn, QStringLiteral("Zwischen den Pads ist zu wenig Lack für eine Linie: Pad-Ø, Rand oder Strahl verkleinern."), {}});
    // Pins without any connection (hint only, once wiring has begun).
    if (!d.wires.empty()) {
        std::set<std::pair<int, int>> wired;
        for (const Wire& w : d.wires) for (const GridPt& g : wireHoles(w)) wired.insert({g.c, g.r});
        QStringList loose;
        for (size_t i = 0; i < d.parts.size(); ++i) {
            int n = 0;
            for (const GridPt& g : pins[i]) if (!wired.count({g.c, g.r}) && holes[{g.c, g.r}].size() < 2) ++n;
            if (n) loose << QStringLiteral("%1 (%2)").arg(d.parts[i].ref).arg(n);
        }
        if (!loose.isEmpty())
            out.push_back({"loose", PerfTone::Info, QStringLiteral("Pins ohne Verbindung: %1.").arg(loose.join(QStringLiteral(", "))), {}});
    }
    if (bedCentre) {
        const Box box{bedCentre->x - b.width / 2, bedCentre->y - b.height / 2, bedCentre->x + b.width / 2, bedCentre->y + b.height / 2};
        if (!Work::contains(box)) out.push_back({"bed", PerfTone::Bad, QStringLiteral("Die Platine liegt so nicht ganz auf der Arbeitsfläche."), {}});
        else if (Work::touchesPark(box)) out.push_back({"bed", PerfTone::Bad, QStringLiteral("Die Platine berührt die %1.").arg(Work::parkName()), {}});
    }
    return out;
}

// ---- Lists ----

std::vector<int> assemblyOrder(const PerfDesign& d) {
    std::vector<int> idx(d.parts.size());
    for (size_t i = 0; i < idx.size(); ++i) idx[i] = int(i);
    const auto order = [&](int i) { const PartDef* p = findPart(d.parts[size_t(i)].partId); return p ? p->order : 99; };
    const auto refKey = [&](int i) {
        const QString& r = d.parts[size_t(i)].ref;
        qsizetype k = r.size();
        while (k > 0 && r[k - 1].isDigit()) --k;
        return std::pair{r.left(k), r.mid(k).toInt()};
    };
    std::stable_sort(idx.begin(), idx.end(), [&](int a, int b) {
        if (order(a) != order(b)) return order(a) < order(b);
        return refKey(a) < refKey(b);
    });
    return idx;
}
std::vector<BomRow> bom(const PerfDesign& d) {
    std::vector<BomRow> rows;
    for (int i : assemblyOrder(d)) {
        const Placed& p = d.parts[size_t(i)];
        const PartDef* def = findPart(p.partId);
        const QString name = def ? def->name : p.partId;
        auto it = std::find_if(rows.begin(), rows.end(), [&](const BomRow& r) { return r.part == name && r.value == p.value; });
        if (it == rows.end()) { rows.push_back({name, p.value, {}, 0, def ? def->order : 99}); it = rows.end() - 1; }
        it->refs << p.ref;
        it->count++;
    }
    return rows;
}
QByteArray bomCsv(const PerfDesign& d) {
    const auto cell = [](QString s) {
        if (s.contains(';') || s.contains('"') || s.contains('\n')) s = '"' + s.replace('"', QStringLiteral("\"\"")) + '"';
        return s;
    };
    QString out = QStringLiteral("Referenz;Wert;Bauteil;Anzahl\r\n");
    for (const BomRow& r : bom(d))
        out += cell(r.refs.join(QStringLiteral(", "))) + ';' + cell(r.value) + ';' + cell(r.part) + ';' + QString::number(r.count) + QStringLiteral("\r\n");
    return QByteArray("\xEF\xBB\xBF") + out.toUtf8();
}

// ---- File ----

QByteArray perfToJson(const PerfDesign& d) {
    const PerfBoard& b = d.board;
    QJsonObject board{{"name", b.name}, {"width", b.width}, {"height", b.height}, {"pitch", b.pitch}, {"cols", b.cols}, {"rows", b.rows},
                      {"padDia", b.padDia}, {"holeDia", b.holeDia}, {"mountDia", b.mountDia}, {"mountInset", b.mountInset}, {"edgeRows", b.edgeRows},
                      {"rowLetters", b.rowLetters}};
    QJsonArray parts, wires, labels;
    for (const Placed& p : d.parts)
        parts.append(QJsonObject{{"id", p.id}, {"part", p.partId}, {"ref", p.ref}, {"value", p.value}, {"col", p.at.c}, {"row", p.at.r}, {"rot", p.rot}});
    for (const Wire& w : d.wires) {
        QJsonArray pts;
        for (const GridPt& g : w.pts) pts.append(QJsonArray{g.c, g.r});
        QJsonObject o{{"id", w.id}, {"side", w.solder ? "loet" : "bestueckung"}, {"points", pts}};
        if (w.widthMm > 0) o.insert("width", w.widthMm);
        if (!w.net.isEmpty()) o.insert("net", w.net);
        wires.append(o);
    }
    for (const Label& l : d.labels)
        labels.append(QJsonObject{{"id", l.id}, {"text", l.text}, {"x", l.at.x}, {"y", l.at.y}, {"height", l.heightMm}, {"side", l.solder ? "loet" : "bestueckung"}});
    QJsonObject root{{"format", "lumaraster"}, {"version", 2}, {"title", d.title}, {"board", board}, {"parts", parts}, {"wires", wires},
                     {"labels", labels}, {"holeNumbers", d.holeNumbers}, {"markRefs", d.markRefs}, {"markValues", d.markValues}};
    if (!d.note.isEmpty()) root.insert("note", d.note);
    return QJsonDocument(root).toJson(QJsonDocument::Indented);
}
PerfDesign perfFromJson(const QByteArray& json) {
    QJsonParseError err;
    const QJsonDocument doc = QJsonDocument::fromJson(json, &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject()) throw std::runtime_error("Die Datei ist kein Lochraster-Entwurf.");
    const QJsonObject o = doc.object();
    if (o.value("format").toString() != QLatin1String("lumaraster")) throw std::runtime_error("Die Datei ist kein Lochraster-Entwurf.");
    if (o.value("version").toInt() > 2) throw std::runtime_error("Die Datei stammt aus einer neueren Version. Bitte die App aktualisieren.");
    PerfDesign d;
    d.title = o.value("title").toString(d.title);
    const QJsonObject b = o.value("board").toObject();
    PerfBoard& pb = d.board;
    pb.name = b.value("name").toString(pb.name);
    pb.width = std::clamp(b.value("width").toDouble(pb.width), 5.0, 400.0);
    pb.height = std::clamp(b.value("height").toDouble(pb.height), 5.0, 400.0);
    pb.pitch = std::clamp(b.value("pitch").toDouble(pb.pitch), 1.0, 10.0);
    pb.cols = std::clamp(b.value("cols").toInt(pb.cols), 1, 200);
    pb.rows = std::clamp(b.value("rows").toInt(pb.rows), 1, 200);
    pb.padDia = std::clamp(b.value("padDia").toDouble(pb.padDia), 0.3, 5.0);
    pb.holeDia = std::clamp(b.value("holeDia").toDouble(pb.holeDia), 0.2, 4.0);
    pb.mountDia = std::clamp(b.value("mountDia").toDouble(pb.mountDia), 0.0, 6.0);
    pb.mountInset = std::clamp(b.value("mountInset").toDouble(pb.mountInset), 0.0, 20.0);
    pb.edgeRows = b.value("edgeRows").toBool(pb.edgeRows);
    pb.rowLetters = b.value("rowLetters").toBool(false);
    for (const QJsonValue& v : o.value("parts").toArray()) {
        const QJsonObject p = v.toObject();
        d.parts.push_back({p.value("id").toString(), p.value("part").toString(), p.value("ref").toString(), p.value("value").toString(),
                           {p.value("col").toInt(), p.value("row").toInt()}, ((p.value("rot").toInt() % 4) + 4) % 4});
    }
    for (const QJsonValue& v : o.value("wires").toArray()) {
        const QJsonObject w = v.toObject();
        Wire x{w.value("id").toString(), w.value("side").toString() != QLatin1String("bestueckung"),
               std::clamp(w.value("width").toDouble(0), 0.0, 5.0), w.value("net").toString(), {}};
        for (const QJsonValue& p : w.value("points").toArray()) x.pts.push_back({p.toArray().at(0).toInt(), p.toArray().at(1).toInt()});
        if (x.pts.size() >= 2) d.wires.push_back(std::move(x));
    }
    for (const QJsonValue& v : o.value("labels").toArray()) {
        const QJsonObject l = v.toObject();
        d.labels.push_back({l.value("id").toString(), l.value("text").toString(), {l.value("x").toDouble(), l.value("y").toDouble()},
                            std::clamp(l.value("height").toDouble(1.5), 0.3, 20.0), l.value("side").toString() == QLatin1String("loet")});
    }
    d.holeNumbers = o.value("holeNumbers").toBool();
    d.markRefs = o.value("markRefs").toBool(true);
    d.markValues = o.value("markValues").toBool();
    d.note = o.value("note").toString();
    return d;
}

// ---- Assembly plan ----

namespace {
struct Prim {
    enum Kind { Fill, Stroke, Text } kind;
    Polys polys;
    QColor color;
    double width = 0;
    QString text;
    Pt at;
    double size = 0;
};
std::vector<Prim> planPrims(const PerfDesign& d, bool fromBelow) {
    const PerfBoard& b = d.board;
    std::vector<Prim> out;
    const auto mx = [&](Polys p) { return fromBelow ? mirrored(p, b.width) : p; };
    out.push_back({Prim::Fill, {rectRing(0, 0, b.width, b.height)}, QColor(0x1c, 0x7a, 0x55), 0, {}, {}, 0});
    Polys pads, holes, mounts;
    for (int r = 0; r < b.rows; ++r) for (int c = 0; c < b.cols; ++c) {
        pads.push_back(closed(b.padShape({c, r})));
        const Pt h = b.hole(c, r);
        holes.push_back(circleRing(h, b.holeDia / 2));
    }
    for (const Pt& m : b.mountHoles()) mounts.push_back(circleRing(m, b.mountDia / 2));
    out.push_back({Prim::Fill, mx(pads), QColor(0xc8, 0xc8, 0xc0), 0, {}, {}, 0});
    out.push_back({Prim::Fill, mx(holes), QColor(0x20, 0x20, 0x20), 0, {}, {}, 0});
    out.push_back({Prim::Fill, mx(mounts), QColor(0x20, 0x20, 0x20), 0, {}, {}, 0});
    for (const Wire& w : d.wires) {
        if (fromBelow && !w.solder) continue;
        Poly line;
        for (const GridPt& g : w.pts) line.push_back(b.hole(g));
        out.push_back({Prim::Stroke, mx({line}), w.solder ? QColor(0xd0, 0x40, 0x40) : QColor(0x30, 0x60, 0xd0), 0.6, {}, {}, 0});
    }
    if (!fromBelow) {
        for (const Placed& p : d.parts) {
            const PartDef* def = findPart(p.partId);
            if (!def) continue;
            Polys lines;
            shapeLines(def->body, p, b, lines);
            shapeLines(def->mark, p, b, lines);
            out.push_back({Prim::Stroke, lines, QColor(0xf4, 0xf4, 0xf0), 0.25, {}, {}, 0});
            if (const auto box = bodyBox(p, *def, b))
                out.push_back({Prim::Text, {}, QColor(0xff, 0xff, 0xff), 0, p.value.isEmpty() ? p.ref : p.ref + ' ' + p.value, box->center(), 1.3});
        }
    }
    for (const Label& l : d.labels)
        if (l.solder == fromBelow) out.push_back({Prim::Text, {}, QColor(0xff, 0xff, 0x80), 0, l.text, fromBelow ? mirrorX(l.at, b.width) : l.at, l.heightMm});
    return out;
}
QString svgColor(const QColor& c) { return c.name(QColor::HexRgb); }
}  // namespace

QByteArray assemblySvg(const PerfDesign& d, bool fromBelow) {
    const PerfBoard& b = d.board;
    QString s = QStringLiteral("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"%1mm\" height=\"%2mm\" viewBox=\"0 0 %1 %2\">\n")
                    .arg(num(b.width), num(b.height));
    for (const Prim& p : planPrims(d, fromBelow)) {
        if (p.kind == Prim::Text) {
            s += QStringLiteral("<text x=\"%1\" y=\"%2\" font-family=\"sans-serif\" font-size=\"%3\" text-anchor=\"middle\" dominant-baseline=\"middle\" fill=\"%4\">%5</text>\n")
                     .arg(num(p.at.x), num(p.at.y), num(p.size), svgColor(p.color), p.text.toHtmlEscaped());
            continue;
        }
        QString dpath;
        for (const Poly& q : p.polys) {
            for (size_t i = 0; i < q.size(); ++i) dpath += (i ? QStringLiteral("L") : QStringLiteral("M")) + num(q[i].x) + ' ' + num(q[i].y);
            if (p.kind == Prim::Fill) dpath += 'Z';
        }
        if (p.kind == Prim::Fill) s += QStringLiteral("<path d=\"%1\" fill=\"%2\" fill-rule=\"evenodd\"/>\n").arg(dpath, svgColor(p.color));
        else s += QStringLiteral("<path d=\"%1\" fill=\"none\" stroke=\"%2\" stroke-width=\"%3\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n").arg(dpath, svgColor(p.color), num(p.width));
    }
    s += QStringLiteral("</svg>\n");
    return s.toUtf8();
}

QByteArray assemblyPng(const PerfDesign& d, double pxPerMm, bool fromBelow) {
    const PerfBoard& b = d.board;
    pxPerMm = std::clamp(pxPerMm, 2.0, 40.0);
    QImage img(int(std::ceil(b.width * pxPerMm)), int(std::ceil(b.height * pxPerMm)), QImage::Format_RGB32);
    img.fill(Qt::white);
    img.setDotsPerMeterX(int(std::lround(pxPerMm * 1000)));
    img.setDotsPerMeterY(int(std::lround(pxPerMm * 1000)));
    {
        QPainter painter(&img);
        painter.setRenderHint(QPainter::Antialiasing);
        painter.setRenderHint(QPainter::TextAntialiasing);
        painter.scale(pxPerMm, pxPerMm);
        for (const Prim& p : planPrims(d, fromBelow)) {
            if (p.kind == Prim::Text) {
                QFont f(QStringLiteral("Segoe UI"));
                f.setPixelSize(std::max(1, int(std::lround(p.size * pxPerMm))));
                painter.save();
                painter.resetTransform();
                painter.setFont(f);
                painter.setPen(p.color);
                const QRectF r(p.at.x * pxPerMm - 200, p.at.y * pxPerMm - 100, 400, 200);
                painter.drawText(r, Qt::AlignCenter, p.text);
                painter.restore();
                continue;
            }
            QPainterPath path;
            path.setFillRule(Qt::OddEvenFill);
            for (const Poly& q : p.polys) {
                if (q.empty()) continue;
                path.moveTo(q[0].x, q[0].y);
                for (size_t i = 1; i < q.size(); ++i) path.lineTo(q[i].x, q[i].y);
                if (p.kind == Prim::Fill) path.closeSubpath();
            }
            if (p.kind == Prim::Fill) painter.fillPath(path, p.color);
            else painter.strokePath(path, QPen(p.color, p.width, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
        }
    }
    QByteArray out;
    QBuffer buf(&out);
    buf.open(QIODevice::WriteOnly);
    img.save(&buf, "PNG");
    return out;
}

// ---- Into the project ----

std::vector<PerfTemplate> perfTemplates() {
    return {{QStringLiteral("laser-interface-v2"), QStringLiteral("Laser-Interface V2 (7 × 9 cm)"), QStringLiteral(":/pcb/vorlagen/laser-interface-v2.lumaraster")}};
}
PerfDesign loadPerfTemplate(const QString& id) {
    for (const PerfTemplate& t : perfTemplates()) {
        if (t.id != id) continue;
        QFile f(t.file);
        if (!f.open(QIODevice::ReadOnly)) throw std::runtime_error("Vorlage fehlt.");
        return perfFromJson(f.readAll());
    }
    throw std::runtime_error("Unbekannte Vorlage.");
}

QString perfLayerName(bool solder) { return solder ? QStringLiteral("Lochraster Lötseite") : QStringLiteral("Lochraster Bestückungsseite"); }

std::vector<Element> perfElements(std::vector<Layer>& layers, const PerfMarks& m, const PerfDesign& d, int plateTop, int plateBottom,
                                  Pt centre, double powerPct, double speed) {
    const QString groupId = newId();
    std::vector<Element> out;
    for (bool solder : {false, true}) {
        const Polys& polys = solder ? m.solder : m.component;
        if (polys.empty()) continue;
        const QString name = perfLayerName(solder);
        auto it = std::find_if(layers.begin(), layers.end(), [&](const Layer& l) { return l.name == name; });
        if (it == layers.end()) { layers.push_back(newLayer(name, solder ? 0xFFFF8AD8LL : 0xFF5CE1E6LL, LayerMode::Line)); it = layers.end() - 1; }
        Layer& l = *it;
        l.mode = LayerMode::Line;            // marking only, never cutting
        l.powerPct = std::max(powerPct, Limits::MIN_RELIABLE_POWER_PCT);
        l.speed = speed;
        l.passes = 1;
        l.zStepMm = 0;
        l.output = true;
        l.visible = true;
        l.extra.insert(QStringLiteral("process"), QStringLiteral("Markieren"));
        Element e = newElement(l.id, QStringLiteral("Lochraster"));
        e.groupId = groupId;
        e.plate = solder ? plateBottom : plateTop;
        e.transform.x = centre.x - d.board.width / 2;
        e.transform.y = centre.y - d.board.height / 2;
        for (const Poly& p : solder ? mirrored(polys, d.board.width) : polys) e.paths.add(p);
        out.push_back(std::move(e));
    }
    return out;
}

}  // namespace lumacut::pcb
