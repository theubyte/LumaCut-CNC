#include "core/werkstatt/generators.h"
#include "core/boolean.h"
#include "core/create.h"
#include "core/extras.h"
#include "core/frame.h"
#include "core/geometry.h"
#include "core/tools.h"
#include "core/werkstatt/qr.h"
#include <QHash>
#include <QRegularExpression>
#include <algorithm>
#include <cmath>
#include <numbers>

namespace lumacut::Werkstatt {

namespace {
const QString GRAVIEREN = QStringLiteral("Gravieren"), LINIE = QStringLiteral("Linie"), SCHNEIDEN = QStringLiteral("Schneiden");

void moveBy(PolySet& s, double dx, double dy) { for (Pt& p : s.allPoints()) p = {p.x + dx, p.y + dy}; }
PolySet moved(PolySet s, double dx, double dy) { moveBy(s, dx, dy); return s; }
Poly movedPoly(Poly p, double dx, double dy) { for (Pt& q : p) q = {q.x + dx, q.y + dy}; return p; }
Poly circleAt(double cx, double cy, double d) { return movedPoly(Shapes::ellipse(d, d), cx - d / 2, cy - d / 2); }
PolySet one(const Poly& p) { PolySet s; s.add(p); return s; }

/** The text with its middle at x = cx and its top at `top`. */
PolySet centeredText(const TextShaper& shape, const QString& text, double h, double cx, double top, bool bold = false) {
    PolySet polys = shape(text, h, bold);
    const auto b = boundsOf(polys);
    if (!b) return {};
    moveBy(polys, cx - b->center().x, top - b->minY);
    return polys;
}
/** Largest height up to h at which the text is at most maxW wide. */
double fitText(const TextShaper& shape, const QString& text, double h, double maxW, bool bold = false) {
    const auto b = boundsOf(shape(text, h, bold));
    if (!b || b->width() <= maxW) return h;
    return h * maxW / b->width();
}
bool finite(double v) { return std::isfinite(v); }
}  // namespace

QString num(double v, int digits) {
    QString s = QString::number(v, 'f', digits);
    if (s.contains(QLatin1Char('.'))) {
        while (s.endsWith(QLatin1Char('0'))) s.chop(1);
        if (s.endsWith(QLatin1Char('.'))) s.chop(1);
    }
    if (s == QLatin1String("-0")) s = QStringLiteral("0");
    return s.replace(QLatin1Char('.'), QLatin1Char(','));
}

// ---- Result to elements ----

std::optional<Box> partsBounds(const GenResult& r, std::optional<int> plate) {
    std::optional<Box> out;
    for (const GenPart& p : r.parts) {
        if (plate && p.plate != *plate) continue;
        const auto b = boundsOf(p.paths);
        if (!b) continue;
        out = out ? out->united(*b) : *b;
    }
    return out;
}
int plateCount(const GenResult& r) {
    int n = 0;
    for (const GenPart& p : r.parts) n = std::max(n, p.plate + 1);
    return n;
}
Pt plateOffset(const GenResult& r, int plate) {
    if (!r.center) return {};
    const auto b = partsBounds(r, plate);
    if (!b) return {};
    const Pt c = Work::center();
    return {c.x - b->center().x, c.y - b->center().y};
}
std::vector<Element> toElements(const GenResult& r, const std::function<QString(const QString&)>& layerId) {
    std::vector<Element> out;
    QHash<QString, QString> groups;
    QHash<int, Pt> offsets;
    for (const GenPart& p : r.parts) {
        const auto b = boundsOf(p.paths);
        if (!b) continue;
        if (!offsets.contains(p.plate)) offsets.insert(p.plate, plateOffset(r, p.plate));
        const Pt o = offsets.value(p.plate);
        Element e = newElement(layerId(p.layer), p.name);
        e.transform.x = b->minX + o.x;
        e.transform.y = b->minY + o.y;
        e.paths = moved(p.paths, -b->minX, -b->minY);
        e.plate = p.plate;
        if (!p.group.isEmpty()) {
            const QString key = QString::number(p.plate) + QLatin1Char('|') + p.group;
            if (!groups.contains(key)) groups.insert(key, newId());
            e.groupId = groups.value(key);
        }
        out.push_back(std::move(e));
    }
    return out;
}

// ---- Material test ----

GenResult matGrid(const MatGridSpec& s, const TextShaper& shape) {
    if (!(s.powerSteps >= 1 && s.powerSteps <= 10 && s.speedSteps >= 1 && s.speedSteps <= 10)) throw GenError(QStringLiteral("Höchstens 10 × 10 Felder."));
    if (std::min(s.powerFrom, s.powerTo) < Limits::MIN_RELIABLE_POWER_PCT)
        throw GenError(QStringLiteral("Unter %1 % zündet der Laser nicht sicher. Untere Leistung anheben.").arg(Limits::MIN_RELIABLE_POWER_PCT));
    if (std::max(s.powerFrom, s.powerTo) > 100) throw GenError(QStringLiteral("Leistung höchstens 100 %."));
    if (!(s.cellMm >= 2 && s.cellMm <= 50 && s.gapMm >= 0.5 && s.gapMm <= 30)) throw GenError(QStringLiteral("Feldgröße 2 bis 50 mm, Abstand 0,5 bis 30 mm."));
    if (!(s.intervalMm >= 0.03 && s.intervalMm <= 2)) throw GenError(QStringLiteral("Zeilenabstand 0,03 bis 2 mm."));
    MaterialTestSpec m;
    m.powerFrom = s.powerFrom; m.powerTo = s.powerTo; m.powerSteps = s.powerSteps;
    m.speedFrom = s.speedFrom; m.speedTo = s.speedTo; m.speedSteps = s.speedSteps;
    m.mode = s.fill ? LayerMode::Fill : LayerMode::Line;
    m.cellMm = s.cellMm; m.gapMm = s.gapMm; m.passes = std::clamp(s.passes, Limits::PASSES_MIN, Limits::PASSES_MAX);
    m.intervalMm = s.intervalMm; m.originX = 0; m.originY = 0;
    Document d;
    try {
        d = buildMaterialTest(m, [&](const QString& t, double h) { return shape(t, h, false); });
    } catch (const std::invalid_argument& e) {
        throw GenError(QString::fromUtf8(e.what()) + QLatin1Char('.'));
    }
    GenResult r;
    r.freshPlate = true;
    r.layers = d.layers;
    for (const Element& e : d.elements) {
        const Layer* l = d.layer(e.layerId);
        r.parts.push_back({e.kind, l ? l->name : GRAVIEREN, moved(e.paths, e.transform.x, e.transform.y), 0, QStringLiteral("test")});
    }
    const auto b = partsBounds(r);
    r.notes << QStringLiteral("%1 Felder, zusammen %2 × %3 mm. Jedes Feld hat eine eigene Ebene mit seiner Leistung und seinem Tempo, die Beschriftung wird markiert.")
                   .arg(s.powerSteps * s.speedSteps).arg(std::ceil(b ? b->width() : 0)).arg(std::ceil(b ? b->height() : 0));
    r.warnings << QStringLiteral("Nur auf Material, das sich sicher lasern lässt. Kunststoff zuerst prüfen: PVC und Vinyl gar nicht.");
    return r;
}

// ---- Box ----

Size3 boxOuter(const BoxGenSpec& s) {
    if (!s.inner) return {s.w, s.d, s.h};
    return {s.w + 2 * s.t, s.d + 2 * s.t, s.h + (s.lid == BoxLid::Joined ? 2 : 1) * s.t};
}
std::vector<std::pair<QString, Poly>> boxPanels(const BoxGenSpec& s) {
    const Size3 o = boxOuter(s);
    if (!(s.t > 0 && s.finger > 0 && std::min({o.w, o.d, o.h}) > 4 * s.t)) throw GenError(QStringLiteral("Die Box ist zu klein für diese Materialstärke."));
    BoxSpec b;
    b.w = o.w; b.d = o.d; b.h = o.h; b.t = s.t; b.finger = s.finger; b.closed = s.lid == BoxLid::Joined;
    auto list = BoxMaker::panels(b);
    if (s.lid == BoxLid::Loose) {
        list.push_back({QStringLiteral("Deckel"), Shapes::rect(o.w, o.d)});
        list.push_back({QStringLiteral("Deckel-Einsatz"), Shapes::rect(o.w - 2 * s.t - 0.6, o.d - 2 * s.t - 0.6)});
    }
    return list;
}
GenResult box(const BoxGenSpec& s) {
    if (!(s.kerf >= 0 && s.kerf <= 1)) throw GenError(QStringLiteral("Schnittbreite 0 bis 1 mm."));
    if (s.finger < 2 * s.t) throw GenError(QStringLiteral("Die Zinken müssen mindestens doppelt so breit sein wie das Material."));
    struct Panel { QString name; PolySet polys; Box box; };
    std::vector<Panel> panels;
    for (auto& [name, poly] : boxPanels(s)) {
        PolySet polys = s.kerf > 0 ? offsetPolys(one(poly), s.kerf / 2, JoinKind::Miter) : one(poly);
        const Box b = *boundsOf(polys);
        panels.push_back({name, std::move(polys), b});
    }
    GenResult r;
    r.center = false;
    r.freshPlate = true;
    std::vector<size_t> rest(panels.size());
    for (size_t i = 0; i < rest.size(); ++i) rest[i] = i;
    int plate = 0;
    while (!rest.empty() && plate < 20) {
        std::vector<Box> boxes;
        for (size_t i : rest) boxes.push_back(panels[i].box);
        const auto packed = shelf(boxes, Work::width(), Work::height(), 5);
        std::vector<size_t> next;
        for (size_t k = 0; k < rest.size(); ++k) {
            const auto& o = packed[k];
            if (!o) { next.push_back(rest[k]); continue; }
            const Panel& p = panels[rest[k]];
            r.parts.push_back({p.name, SCHNEIDEN, moved(p.polys, o->x, o->y), plate, QStringLiteral("box")});
        }
        if (next.size() == rest.size()) throw GenError(QStringLiteral("Das Teil „%1“ ist größer als eine Platte.").arg(panels[next[0]].name));
        rest = std::move(next);
        ++plate;
    }
    const Size3 o = boxOuter(s);
    r.notes << QStringLiteral("Außenmaße %1 × %2 × %3 mm, %4 Teile%5.").arg(num(o.w), num(o.d), num(o.h)).arg(r.parts.size())
                   .arg(plate > 1 ? QStringLiteral(" auf %1 Platten").arg(plate) : QString());
    r.notes << QStringLiteral("Zinken je Kante: Breite %1, Tiefe %2, Höhe %3. Materialstärke genau messen: davon hängt die Passung ab.")
                   .arg(BoxMaker::segments(o.w, s.finger)).arg(BoxMaker::segments(o.d, s.finger)).arg(BoxMaker::segments(o.h, s.finger));
    return r;
}

// ---- Gear ----

GearDims gearDims(const GearSpec& s) {
    const double pitch = s.module * s.teeth;
    return {pitch, pitch + 2 * s.module, pitch - 2.5 * s.module, pitch * std::cos(s.pressureDeg * std::numbers::pi / 180)};
}
Poly gearOutline(const GearSpec& s) {
    const int z = s.teeth;
    const double a = s.pressureDeg * std::numbers::pi / 180;
    const GearDims d = gearDims(s);
    const double ra = d.outer / 2, rf = d.root / 2, rb = d.base / 2;
    const auto inv = [](double x) { return std::tan(x) - x; };
    const auto halfAt = [&](double r) { return std::numbers::pi / (2 * z) + inv(a) - inv(std::acos(std::min(1.0, rb / r))); };
    const auto polar = [&](double r, double t) { return Pt{ra + r * std::cos(t), ra + r * std::sin(t)}; };
    const double startR = std::max(rb, rf);
    constexpr int FLANK = 10;
    std::vector<double> rs;
    for (int i = 0; i <= FLANK; ++i) rs.push_back(startR + (ra - startR) * i / FLANK);
    Poly pts;
    for (int k = 0; k < z; ++k) {
        const double c = 2 * std::numbers::pi * k / z - std::numbers::pi / 2, atBase = halfAt(startR), tip = halfAt(ra);
        pts.push_back(polar(rf, c - atBase));
        for (double r : rs) pts.push_back(polar(r, c - halfAt(r)));
        for (int i = 1; i < 4; ++i) pts.push_back(polar(ra, c - tip + 2 * tip * i / 4));
        for (auto it = rs.rbegin(); it != rs.rend(); ++it) pts.push_back(polar(*it, c + halfAt(*it)));
        pts.push_back(polar(rf, c + atBase));
        const double next = c + 2 * std::numbers::pi / z - atBase;
        for (int i = 1; i < 4; ++i) pts.push_back(polar(rf, c + atBase + (next - c - atBase) * i / 4));
    }
    pts.push_back(pts.front());
    Poly out;
    for (size_t i = 0; i < pts.size(); ++i) if (i == 0 || dist(pts[i], pts[i - 1]) > 1e-6) out.push_back(pts[i]);
    return out;
}
GenResult gear(const GearSpec& s) {
    if (!(s.teeth >= 6 && s.teeth <= 200)) throw GenError(QStringLiteral("Zähne: 6 bis 200."));
    if (!(s.module >= 0.5 && s.module <= 20)) throw GenError(QStringLiteral("Modul: 0,5 bis 20 mm."));
    if (!(s.pressureDeg >= 14 && s.pressureDeg <= 25)) throw GenError(QStringLiteral("Eingriffswinkel: 14 bis 25 Grad."));
    const GearDims d = gearDims(s);
    if (d.root <= 0) throw GenError(QStringLiteral("Für dieses Modul sind es zu wenige Zähne."));
    if (s.boreMm >= d.root - 2) throw GenError(QStringLiteral("Die Bohrung ist größer als der Zahnfuß."));
    if (d.outer > std::min(Work::width(), Work::height())) throw GenError(QStringLiteral("Das Zahnrad ist größer als die Arbeitsfläche."));
    const Poly outline = gearOutline(s);
    PolySet paths = s.kerf > 0 ? offsetPolys(one(outline), s.kerf / 2, JoinKind::Round) : one(outline);
    if (s.boreMm > 0) {
        const double b = std::max(0.2, s.boreMm - s.kerf);
        paths.add(circleAt(d.outer / 2, d.outer / 2, b));
    }
    GenResult r;
    r.parts.push_back({QStringLiteral("Zahnrad"), SCHNEIDEN, std::move(paths), 0, {}});
    r.notes << QStringLiteral("%1 Zähne, Teilkreis %2 mm, außen %3 mm, Fuß %4 mm.").arg(s.teeth).arg(num(d.pitch, 2), num(d.outer, 2), num(d.root, 2));
    r.notes << QStringLiteral("Achsabstand zu einem Rad mit z Zähnen: %1 × (%2 + z) ÷ 2. Beide Räder brauchen dasselbe Modul.").arg(num(s.module, 2)).arg(s.teeth);
    if (s.teeth < 17) r.warnings << QStringLiteral("Unter 17 Zähnen fehlt der Unterschnitt-Ausgleich, die Räder können leicht klemmen. Etwas mehr Achsabstand einplanen.");
    return r;
}

// ---- Ruler and scale bar ----

GenResult ruler(const RulerSpec& s, const TextShaper& shape) {
    if (!(s.lengthMm >= 30 && s.lengthMm <= 340)) throw GenError(QStringLiteral("Messlänge: 30 bis 340 mm."));
    if (!(s.widthMm >= 15 && s.widthMm <= 80)) throw GenError(QStringLiteral("Breite: 15 bis 80 mm."));
    if (!(s.holeMm >= 0 && s.holeMm <= 15)) throw GenError(QStringLiteral("Loch: 0 bis 15 mm."));
    const int len = int(std::lround(s.lengthMm));
    const Parts p = Personalize::ruler(len, s.widthMm, s.holeMm > 0 ? std::optional<double>(s.holeMm) : std::nullopt);
    const double numH = std::min(4.0, s.widthMm * 0.16);
    PolySet numbers;
    for (const auto& [pos, text] : p.labels) numbers.append(centeredText(shape, text, numH, pos.x, pos.y));
    GenResult r;
    r.parts.push_back({QStringLiteral("Lineal Umriss"), SCHNEIDEN, p.cut, 0, QStringLiteral("lineal")});
    r.parts.push_back({QStringLiteral("Lineal Striche"), LINIE, p.marks, 0, QStringLiteral("lineal")});
    r.parts.push_back({QStringLiteral("Lineal Zahlen"), GRAVIEREN, numbers, 0, QStringLiteral("lineal")});
    const QString title = s.title.trimmed();
    if (!title.isEmpty()) {
        const double h = fitText(shape, title, std::min(5.0, s.widthMm * 0.2), len - 4);
        r.parts.push_back({QStringLiteral("Lineal Text"), GRAVIEREN, centeredText(shape, title, h, 5 + len / 2.0, s.widthMm - h - 2), 0, QStringLiteral("lineal")});
    }
    const auto b = boundsOf(p.cut);
    r.notes << QStringLiteral("Gesamtlänge %1 mm. Striche werden markiert, Zahlen graviert, der Umriss geschnitten.").arg(num(b ? b->width() : 0));
    return r;
}

GenResult scaleBar(const ScaleBarSpec& s, const TextShaper& shape) {
    if (!(s.scale >= 1 && s.scale <= 100000)) throw GenError(QStringLiteral("Maßstab: 1 bis 100 000."));
    if (!(s.segments >= 1 && s.segments <= 20)) throw GenError(QStringLiteral("Felder: 1 bis 20."));
    if (!(s.heightMm >= 1 && s.heightMm <= 20)) throw GenError(QStringLiteral("Balkenhöhe: 1 bis 20 mm."));
    const double lengthMm = s.realLengthM * 1000 / s.scale;
    if (!(lengthMm >= 5 && lengthMm <= 340))
        throw GenError(QStringLiteral("Der Balken wäre %1 mm lang: Länge oder Maßstab ändern (5 bis 340 mm).").arg(std::lround(lengthMm)));
    const double seg = lengthMm / s.segments, h = s.heightMm, numH = std::clamp(h, 2.2, 4.0), top = numH + 1.5;
    PolySet fields, labels;
    for (int i = 0; i < s.segments; i += 2) fields.add(movedPoly(Shapes::rect(seg, h), i * seg, top));
    for (int i = 0; i <= s.segments; ++i) {
        const double v = s.realLengthM * i / s.segments;
        labels.append(centeredText(shape, i == s.segments ? num(v, 2) + QStringLiteral(" m") : num(v, 2), numH, i * seg, 0));
    }
    GenResult r;
    r.parts.push_back({QStringLiteral("Maßstab Felder"), GRAVIEREN, fields, 0, QStringLiteral("massstab")});
    r.parts.push_back({QStringLiteral("Maßstab Rahmen"), LINIE, one(movedPoly(Shapes::rect(lengthMm, h), 0, top)), 0, QStringLiteral("massstab")});
    r.parts.push_back({QStringLiteral("Maßstab Zahlen"), GRAVIEREN, labels, 0, QStringLiteral("massstab")});
    r.parts.push_back({QStringLiteral("Maßstab Text"), GRAVIEREN,
                       centeredText(shape, QStringLiteral("1:%1").arg(qint64(s.scale)), numH, lengthMm / 2, top + h + 1.5), 0, QStringLiteral("massstab")});
    r.notes << QStringLiteral("%1 m im Maßstab 1:%2 sind %3 mm auf dem Material.").arg(num(s.realLengthM, 2)).arg(qint64(s.scale)).arg(num(lengthMm, 2));
    return r;
}

// ---- Frame ----

GenResult frame(const FrameGenSpec& s) {
    if (!s.around && !(s.widthMm >= 5 && s.heightMm >= 5)) throw GenError(QStringLiteral("Rahmen: mindestens 5 × 5 mm."));
    if (!(s.marginMm >= 0 && s.marginMm <= 100)) throw GenError(QStringLiteral("Abstand: 0 bis 100 mm."));
    const Box b0 = s.around.value_or(Box{0, 0, s.widthMm, s.heightMm});
    const FrameStyle style = static_cast<FrameStyle>(std::clamp(s.style, 0, 4));
    PolySet paths = Personalize::frame(b0, style, s.around ? s.marginMm : 0);
    GenResult r;
    r.center = !s.around;
    r.parts.push_back({QStringLiteral("Rahmen"), s.cut ? SCHNEIDEN : LINIE, paths, 0, {}});
    const auto b = boundsOf(paths);
    r.notes << QStringLiteral("Rahmen außen %1 × %2 mm.").arg(num(b->width()), num(b->height()));
    if (s.around && !Work::contains(*b)) r.warnings << QStringLiteral("Der Rahmen ragt über die Arbeitsfläche. Abstand verkleinern oder das Motiv verschieben.");
    return r;
}

// ---- Serial numbers ----

SerialTemplate parseTemplate(const QString& t) {
    static const QRegularExpression re(QStringLiteral("\\{(\\d{1,9})\\}"));
    const auto m = re.match(t);
    if (!m.hasMatch()) throw GenError(QStringLiteral("Die Vorlage braucht einen Platzhalter wie {0001}."));
    return {t.left(m.capturedStart()), t.mid(m.capturedEnd()), m.captured(1).toLongLong(), int(m.capturedLength(1))};
}
QString serialText(const SerialTemplate& t, int i, int step) {
    return t.before + QStringLiteral("%1").arg(t.start + qint64(i) * step, t.width, 10, QLatin1Char('0')) + t.after;
}
GenResult serials(const SerialSpec& s, const TextShaper& shape, double plateW, double plateH) {
    const SerialTemplate tpl = parseTemplate(s.templ);
    if (!(s.count >= 1 && s.count <= MAX_SERIALS)) throw GenError(QStringLiteral("Anzahl: 1 bis %1.").arg(MAX_SERIALS));
    if (!(s.step >= 1)) throw GenError(QStringLiteral("Schrittweite mindestens 1."));
    if (!(s.textHeightMm >= 1 && s.textHeightMm <= 50)) throw GenError(QStringLiteral("Schrifthöhe: 1 bis 50 mm."));
    const bool tagged = s.tagWidthMm > 0 && s.tagHeightMm > 0;
    struct Piece { PolySet text, cut; Box box; QString name; };
    std::vector<Piece> pieces;
    for (int i = 0; i < s.count; ++i) {
        const QString label = serialText(tpl, i, s.step);
        if (!tagged) {
            PolySet text = shape(label, s.textHeightMm, false);
            const auto b = boundsOf(text);
            if (!b) throw GenError(QStringLiteral("Die Vorlage ergibt keinen Text."));
            pieces.push_back({std::move(text), {}, *b, label});
            continue;
        }
        const double holeSpace = s.holeMm > 0 ? s.holeMm + 3 : 0;
        if (s.tagWidthMm - holeSpace < 8) throw GenError(QStringLiteral("Das Schild ist zu schmal für Loch und Text."));
        const double h = std::min(fitText(shape, label, s.textHeightMm, s.tagWidthMm - holeSpace - 4), s.tagHeightMm - 3);
        PolySet text = shape(label, h, false);
        const auto b = boundsOf(text);
        if (!b) throw GenError(QStringLiteral("Die Vorlage ergibt keinen Text."));
        moveBy(text, holeSpace + (s.tagWidthMm - holeSpace) / 2 - b->center().x, s.tagHeightMm / 2 - b->center().y);
        PolySet cut;
        cut.add(Shapes::rect(s.tagWidthMm, s.tagHeightMm, std::min(s.tagWidthMm, s.tagHeightMm) * 0.15));
        if (s.holeMm > 0) cut.add(circleAt(2.5 + s.holeMm / 2, s.tagHeightMm / 2, s.holeMm));
        pieces.push_back({std::move(text), std::move(cut), Box{0, 0, s.tagWidthMm, s.tagHeightMm}, label});
    }
    GenResult r;
    r.center = false;
    r.freshPlate = true;
    std::vector<size_t> rest(pieces.size());
    for (size_t i = 0; i < rest.size(); ++i) rest[i] = i;
    int plate = 0;
    while (!rest.empty() && plate < 50) {
        std::vector<Box> boxes;
        for (size_t i : rest) boxes.push_back(pieces[i].box);
        const auto packed = shelf(boxes, plateW, plateH, s.gapMm);
        std::vector<size_t> next;
        for (size_t k = 0; k < rest.size(); ++k) {
            const auto& o = packed[k];
            if (!o) { next.push_back(rest[k]); continue; }
            const Piece& p = pieces[rest[k]];
            const QString group = p.cut.empty() ? QString() : QStringLiteral("s%1").arg(rest[k]);
            r.parts.push_back({p.name, GRAVIEREN, moved(p.text, o->x, o->y), plate, group});
            if (!p.cut.empty()) r.parts.push_back({p.name + QStringLiteral(" Umriss"), SCHNEIDEN, moved(p.cut, o->x, o->y), plate, group});
        }
        if (next.size() == rest.size()) throw GenError(QStringLiteral("Ein Stück ist größer als eine Platte."));
        rest = std::move(next);
        ++plate;
    }
    if (!rest.empty()) throw GenError(QStringLiteral("Zu viele Stücke: mehr als 50 Platten."));
    r.notes << QStringLiteral("%1 bis %2: %3 Stück %4. Die %5 bleibt frei.")
                   .arg(serialText(tpl, 0, s.step), serialText(tpl, s.count - 1, s.step)).arg(s.count)
                   .arg(plate > 1 ? QStringLiteral("auf %1 Platten").arg(plate) : QStringLiteral("auf einer Platte"), Work::parkName());
    return r;
}

// ---- Stamp ----

GenResult stamp(const StampSpec& s, const TextShaper& shape) {
    if (!(s.widthMm >= 10 && s.widthMm <= 300 && (s.round || (s.heightMm >= 10 && s.heightMm <= 300)))) throw GenError(QStringLiteral("Größe: 10 bis 300 mm."));
    if (!(s.borderMm >= 0 && s.borderMm <= 5)) throw GenError(QStringLiteral("Rahmenstärke: 0 bis 5 mm."));
    QStringList lines;
    for (const QString& l : s.lines) if (!l.trimmed().isEmpty()) lines << l.trimmed();
    if (lines.isEmpty() && s.motif == StampMotif::None) throw GenError(QStringLiteral("Text oder Motiv fehlt."));
    const double W = s.widthMm, H = s.round ? s.widthMm : s.heightMm;
    const Poly outline = s.round ? Shapes::ellipse(W, W) : Shapes::rect(W, H, 1.5);
    const auto inset = [&](double d) {
        return s.round ? movedPoly(Shapes::ellipse(W - 2 * d, W - 2 * d), d, d) : movedPoly(Shapes::rect(W - 2 * d, H - 2 * d, std::max(0.0, 1.5 - d / 2)), d, d);
    };
    const auto motifPoly = [&](double m) -> Poly {
        switch (s.motif) {
        case StampMotif::Star: return ShapeLib::star(5, m, m);
        case StampMotif::Heart: return ShapeLib::heart(m, m * 0.92);
        case StampMotif::Drop: return makeShape(ShapeKind::Drop, m * 0.75, m);
        default: return {};
        }
    };
    const double pad = 2 + s.borderMm + (s.borderMm > 0 ? 1.5 : 0);
    PolySet ink;
    if (s.borderMm > 0) { ink.add(inset(1.5)); ink.add(inset(1.5 + s.borderMm)); }
    // In a circle the corners of the text block must stay inside: use the middle part only.
    const double areaW = (W - 2 * pad) * (s.round ? 0.8 : 1), areaH = (H - 2 * pad) * (s.round ? 0.72 : 1), areaTop = (H - areaH) / 2;
    double textX = W / 2, textW = areaW, textTop = areaTop, textH = areaH;
    if (s.motif != StampMotif::None) {
        const bool beside = !lines.isEmpty() && !s.round && areaW > areaH * 1.3;
        if (beside) {
            const double m = std::min(areaH * 0.8, areaW * 0.3);
            ink.add(movedPoly(motifPoly(m), pad, H / 2 - m / 2));
            textX = pad + m + 2 + (areaW - m - 2) / 2;
            textW = areaW - m - 2;
        } else {
            const double m = !lines.isEmpty() ? areaH * 0.42 : std::min(areaH, areaW) * 0.8;
            const double pw = s.motif == StampMotif::Drop ? m * 0.75 : m;
            ink.add(movedPoly(motifPoly(m), W / 2 - pw / 2, !lines.isEmpty() ? areaTop : H / 2 - m / 2));
            textTop = areaTop + m + 1.5;
            textH = areaH - m - 1.5;
        }
    }
    if (!lines.isEmpty()) {
        const double gap = 0.35;
        double h = textH / (lines.size() + (lines.size() - 1) * gap);
        for (const QString& l : lines) h = std::min(h, fitText(shape, l, h, textW, s.bold));
        const double block = h * lines.size() + h * gap * (lines.size() - 1);
        const double start = textTop + (textH - block) / 2;
        for (int i = 0; i < lines.size(); ++i) ink.append(centeredText(shape, lines[i], h, textX, start + i * h * (1 + gap), s.bold));
    }
    PolySet engrave;
    if (s.inverted) engrave.add(outline);
    engrave.append(ink);
    PolySet cut = one(outline);
    if (s.mirrored) {
        for (Pt& p : engrave.allPoints()) p.x = W - p.x;
        for (Pt& p : cut.allPoints()) p.x = W - p.x;
    }
    GenResult r;
    r.parts.push_back({QStringLiteral("Stempel"), GRAVIEREN, std::move(engrave), 0, QStringLiteral("stempel")});
    r.parts.push_back({QStringLiteral("Stempel Umriss"), SCHNEIDEN, std::move(cut), 0, QStringLiteral("stempel")});
    r.notes << QStringLiteral("Stempelplatte %1 × %2 mm.%3").arg(num(W), num(H), s.mirrored ? QStringLiteral(" Gespiegelt, damit der Abdruck richtig lesbar ist.") : QString());
    r.warnings << QStringLiteral("Nur laserfähigen Stempelgummi verwenden, ohne PVC und ohne Chlor. Andere Gummis geben giftige Dämpfe ab.");
    if (!s.inverted) r.warnings << QStringLiteral("Nicht invertiert: die Schrift wird vertieft. Das ergibt eine Gravur, keinen Stempel.");
    if (!s.mirrored) r.warnings << QStringLiteral("Nicht gespiegelt: als Stempel läse sich der Abdruck verkehrt.");
    return r;
}

// ---- QR ----

GenResult qr(const QrSpec& s) {
    if (!(s.moduleMm >= 0.2 && s.moduleMm <= 10)) throw GenError(QStringLiteral("Punktgröße: 0,2 bis 10 mm."));
    Qr::Code q;
    try {
        q = Qr::encode(s.text);
    } catch (const std::invalid_argument& e) {
        throw GenError(QString::fromUtf8(e.what()));
    }
    const double size = q.size * s.moduleMm, quiet = 4 * s.moduleMm;
    GenResult r;
    r.parts.push_back({QStringLiteral("QR-Code"), GRAVIEREN, Qr::polys(q, s.moduleMm), 0, s.plate ? QStringLiteral("qr") : QString()});
    r.notes << QStringLiteral("Version %1, %2 × %2 Punkte = %3 × %3 mm. Graviert werden die dunklen Punkte.").arg(q.version).arg(q.size).arg(num(size));
    if (s.plate) {
        const double t = size + 2 * quiet;
        r.parts.push_back({QStringLiteral("QR Umriss"), SCHNEIDEN, one(movedPoly(Shapes::rect(t, t), -quiet, -quiet)), 0, QStringLiteral("qr")});
        r.notes << QStringLiteral("Der Umriss lässt rundum vier Punkte hellen Rand.");
    } else {
        r.notes << QStringLiteral("Beim Gravieren rundum einen hellen Rand von mindestens vier Punkten lassen.");
    }
    if (s.moduleMm < Qr::MIN_MODULE_MM) r.warnings << QStringLiteral("Punkte unter %1 mm lassen sich oft nicht mehr lesen. Größer wählen.").arg(num(Qr::MIN_MODULE_MM));
    return r;
}

}  // namespace lumacut::Werkstatt
