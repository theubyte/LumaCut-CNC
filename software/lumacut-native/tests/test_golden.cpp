/**
 * Bis aufs Zeichen gegen den echten Kotlin-Code. tests/golden/in sind die Eingaben, tests/golden/out hat
 * GoldenGen.kt daraus erzeugt (Weg: tests/golden/README). Dieser Test braucht weder Node noch Kotlin.
 * Zahlen aus Winkelfunktionen dürfen in den Geometrie-Tabellen um 1e-6 abweichen (Sinus der JVM und der CRT),
 * Struktur und Text gar nicht. G-Code und Prüfsummen sind hart.
 */
#include "core/contour.h"
#include "core/create.h"
#include "core/darkness.h"
#include "core/extras.h"
#include "core/frame.h"
#include "core/gcode.h"
#include "core/geometry.h"
#include "core/parallel.h"
#include "core/parts.h"
#include "core/toolpath.h"
#include "core/tools.h"

#include <atomic>
#include <bit>
#include <mutex>
#include <QCryptographicHash>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QtTest>

using namespace lumacut;

namespace {
QByteArray readFile(const QString& rel) {
    QFile f(QStringLiteral(LUMACUT_GOLDEN_DIR "/") + rel);
    if (!f.open(QIODevice::ReadOnly)) qFatal("Datei fehlt: %s", qPrintable(rel));
    QByteArray t = f.readAll();
    t.replace("\r\n", "\n");
    return t;
}
QJsonDocument readJson(const QString& rel) {
    QJsonParseError err{};
    const QJsonDocument d = QJsonDocument::fromJson(readFile(rel), &err);
    if (err.error != QJsonParseError::NoError) qFatal("JSON kaputt: %s", qPrintable(rel));
    return d;
}
QString sha(QByteArrayView s) {
    return QString::fromLatin1(QCryptographicHash::hash(s, QCryptographicHash::Sha256).toHex());
}
QJsonValue num(double d) { return std::isfinite(d) ? QJsonValue(d) : QJsonValue(); }
QJsonArray pt(Pt p) { return QJsonArray{num(p.x), num(p.y)}; }
QJsonArray poly(PolyView p) {
    QJsonArray a;
    for (const Pt q : p) a.append(pt(q));
    return a;
}
QJsonArray polys(const PolySet& l) {
    QJsonArray a;
    for (PolyView p : l) a.append(poly(p));
    return a;
}
QJsonArray ptsN(const std::vector<std::optional<Pt>>& l) {
    QJsonArray a;
    for (const auto& p : l) a.append(p ? QJsonValue(pt(*p)) : QJsonValue());
    return a;
}
QJsonArray ptsO(const std::vector<Pt>& l) { return poly(l); }
QJsonValue boxJ(const std::optional<Box>& b) {
    if (!b) return QJsonValue();
    return QJsonArray{num(b->minX), num(b->minY), num(b->maxX), num(b->maxY)};
}
QJsonObject parts(const Parts& p) {
    QJsonArray labels;
    for (const auto& [q, s] : p.labels) labels.append(QJsonArray{pt(q), s});
    return {{"engrave", polys(p.engrave)}, {"cut", polys(p.cut)}, {"marks", polys(p.marks)}, {"labels", labels}};
}
Poly readPoly(const QJsonValue& v) {
    Poly out;
    for (const QJsonValue& q : v.toArray()) out.push_back({q[QStringLiteral("x")].toDouble(), q[QStringLiteral("y")].toDouble()});
    return out;
}
PolySet readPolys(const QJsonValue& v) {
    PolySet out;
    for (const QJsonValue& p : v.toArray()) out.add(readPoly(p));
    return out;
}
Box readBox(const QJsonValue& v) {
    return {v[QStringLiteral("minX")].toDouble(), v[QStringLiteral("minY")].toDouble(), v[QStringLiteral("maxX")].toDouble(), v[QStringLiteral("maxY")].toDouble()};
}

QJsonObject stats(const QByteArray& gcode) {
    const Toolpath tp = parseToolpath(gcode);
    QByteArray seg;
    seg.reserve(qsizetype(tp.count()) * 60);
    for (size_t i = 0; i < tp.count(); ++i) {
        const float* s = tp.xy.data() + i * 4;
        for (int k = 0; k < 4; ++k) seg += QByteArray::number(std::bit_cast<qint32>(s[k])) + ' ';
        seg += QByteArray::number(tp.power[i]);
        seg += tp.power[i] > 0 ? " true " : " false ";
        seg += QByteArray::number(tp.line[i]);
        seg += '\n';
    }
    const std::vector<Pt> cuts = cutPoints(tp);
    QJsonArray warnings;
    for (const QString& w : tp.stats.warnings) warnings.append(w);
    return {{"cutMm", num(tp.stats.cutMm)}, {"travelMm", num(tp.stats.travelMm)}, {"seconds", num(tp.stats.seconds)}, {"maxPower", tp.stats.maxPower},
            {"warnings", warnings}, {"bounds", boxJ(tp.bounds)}, {"lineCount", tp.lineCount}, {"count", qint64(tp.count())}, {"segments", sha(seg)},
            {"remaining", num(tp.remainingSeconds(tp.lineCount / 3))}, {"duration", formatDuration(tp.stats.seconds)},
            {"frameBox", cuts.empty() ? QString() : sha(frameProgram(cuts, FrameMode::Box))},
            {"frameHull", cuts.empty() ? QString() : sha(frameProgram(cuts, FrameMode::Hull, 5000))}};
}

QByteArray runCase(const QJsonObject& c, QByteArray* json = nullptr) {
    const QByteArray text = QJsonDocument(c[QStringLiteral("doc")].toObject()).toJson(QJsonDocument::Compact);
    const Document doc = Document::fromJson(text);
    if (json) *json = doc.toJson();
    WriteOptions opt;
    opt.appVersion = "golden";
    const QJsonValue m = c[QStringLiteral("motion")];
    if (m.isObject()) opt.motion = Motion{m[QStringLiteral("accel")].toDouble(), m[QStringLiteral("speed")].toDouble()};
    const QJsonArray bed = c[QStringLiteral("bed")].toArray();
    if (bed.size() == 4) Bed::configure(bed[0].toDouble(), bed[1].toDouble(), bed[2].toDouble(), bed[3].toDouble());
    else Bed::configure(370, 360, 78, 35);
    try {
        return writeMarlin(doc, opt);
    } catch (const JobBuildError& e) {
        return "FEHLER: " + e.message().toUtf8();
    }
}

/** Zeigt die erste abweichende Zeile. */
QString firstDiff(const QByteArray& got, const QByteArray& want) {
    const auto a = got.split('\n'), b = want.split('\n');
    for (qsizetype i = 0; i < std::min(a.size(), b.size()); ++i)
        if (a[i] != b[i]) return QStringLiteral("Zeile %1: %2 != %3").arg(i + 1).arg(QString::fromUtf8(a[i]), QString::fromUtf8(b[i]));
    return QStringLiteral("Längen %1 != %2").arg(got.size()).arg(want.size());
}
bool near(const QJsonValue& a, const QJsonValue& b, const QString& path, double eps, QString& why) {
    if (a.isDouble() && b.isDouble()) {
        if (std::fabs(a.toDouble() - b.toDouble()) > eps) { why = QStringLiteral("%1: %2 != %3").arg(path).arg(a.toDouble(), 0, 'g', 17).arg(b.toDouble(), 0, 'g', 17); return false; }
        return true;
    }
    if (a.isArray() && b.isArray()) {
        const QJsonArray x = a.toArray(), y = b.toArray();
        if (x.size() != y.size()) { why = QStringLiteral("%1: Länge %2 != %3").arg(path).arg(x.size()).arg(y.size()); return false; }
        for (qsizetype i = 0; i < x.size(); ++i) if (!near(x[i], y[i], QStringLiteral("%1[%2]").arg(path).arg(i), eps, why)) return false;
        return true;
    }
    if (a.isObject() && b.isObject()) {
        const QJsonObject y = b.toObject(), x = a.toObject();
        for (auto it = y.begin(); it != y.end(); ++it) if (!near(x[it.key()], it.value(), path + "." + it.key(), eps, why)) return false;
        return true;
    }
    if (a != b) { why = QStringLiteral("%1: %2 != %3").arg(path, QJsonDocument(QJsonArray{a}).toJson(QJsonDocument::Compact), QJsonDocument(QJsonArray{b}).toJson(QJsonDocument::Compact)); return false; }
    return true;
}
bool sameStats(const QJsonObject& a, const QJsonObject& b, QString& why) {
    // Exakt: Doubles aus derselben Rechenfolge wie Kotlin, Prüfsummen über die Float-Bits.
    for (auto it = b.begin(); it != b.end(); ++it) {
        if (a[it.key()] != it.value()) {
            why = QStringLiteral("%1: %2 != %3").arg(it.key(), QJsonDocument(QJsonArray{a[it.key()]}).toJson(QJsonDocument::Compact), QJsonDocument(QJsonArray{it.value()}).toJson(QJsonDocument::Compact));
            return false;
        }
    }
    return true;
}
}  // namespace

class TestGolden : public QObject {
    Q_OBJECT
private slots:
    void init() { Bed::configure(370, 360, 78, 35); }

    void named_data() {
        QTest::addColumn<QJsonObject>("c");
        for (const QJsonValue& v : readJson(QStringLiteral("in/named.json")).array()) {
            const QJsonObject o = v.toObject();
            QTest::newRow(qPrintable(o[QStringLiteral("name")].toString())) << o;
        }
    }
    void named() {
        QFETCH(QJsonObject, c);
        const QString name = c[QStringLiteral("name")].toString();
        QByteArray json;
        const QByteArray got = runCase(c, &json);
        const QByteArray want = readFile(QStringLiteral("out/gcode/%1.gcode").arg(name));
        if (got != want) QFAIL(qPrintable(firstDiff(got, want)));
        static const QJsonObject expected = readJson(QStringLiteral("out/stats.json")).object();
        if (!got.startsWith("FEHLER")) {
            QString why;
            if (!sameStats(stats(got), expected[name].toObject(), why)) QFAIL(qPrintable(why));
        }
        const QByteArray wantJson = readFile(QStringLiteral("out/roundtrip/%1.json").arg(name));
        if (json != wantJson) QFAIL(qPrintable(QStringLiteral("JSON weicht ab: %1").arg(firstDiff(json.replace(",\"", ",\n\""), QByteArray(wantJson).replace(",\"", ",\n\"")))));
    }

    void fuzz() {
        const QJsonArray cases = readJson(QStringLiteral("in/fuzz.json")).array();
        const QJsonObject want = readJson(QStringLiteral("out/fuzz.json")).object();
        QVERIFY(cases.size() >= 400);
        QStringList bad;
        std::atomic_int ok{0}, errors{0};
        std::mutex mutex;
        // Nebeneinander: spart Zeit und prüft zugleich, dass geschachtelte Rasterzeilen nichts durcheinanderbringen.
        // Alle Zufallsdokumente nutzen dieselbe Maschine, Bed::configure bleibt also gleich.
        parallelFor(cases.size(), [&](std::ptrdiff_t i) {
            const QJsonObject c = cases[qsizetype(i)].toObject();
            const QString name = c[QStringLiteral("name")].toString();
            const QJsonObject w = want[name].toObject();
            const QByteArray got = runCase(c);
            if (got.startsWith("FEHLER")) ++errors; else ++ok;
            if (sha(got) != w[QStringLiteral("sha")].toString()) {
                const std::lock_guard lock(mutex);
                bad << QStringLiteral("%1: %2 / Kotlin %3").arg(name, got.startsWith("FEHLER") ? QString::fromUtf8(got) : QStringLiteral("G-Code weicht ab"),
                                                               w[QStringLiteral("error")].toString(QStringLiteral("G-Code")));
                return;
            }
            const QJsonObject ws = w[QStringLiteral("stats")].toObject();
            if (!ws.isEmpty()) {
                QString why;
                if (!sameStats(stats(got), ws, why)) {
                    const std::lock_guard lock(mutex);
                    bad << name + ": Werkzeugweg " + why;
                }
            }
        });
        qInfo("Zufallsdokumente: %d G-Code, %d Fehlertexte, %lld abweichend", ok.load(), errors.load(), qint64(bad.size()));
        if (!bad.isEmpty()) QFAIL(qPrintable(bad.mid(0, 12).join(QLatin1Char('\n'))));
        QVERIFY(ok > 100);
        QVERIFY(errors > 20);
    }

    void toolpaths() {
        const QJsonObject want = readJson(QStringLiteral("out/toolpaths.json")).object();
        for (const QJsonValue& v : readJson(QStringLiteral("in/toolpaths.json")).array()) {
            const QJsonObject c = v.toObject();
            const QJsonArray bed = c[QStringLiteral("bed")].toArray();
            if (bed.size() == 4) Bed::configure(bed[0].toDouble(), bed[1].toDouble(), bed[2].toDouble(), bed[3].toDouble());
            else Bed::configure(370, 360, 78, 35);
            QString why;
            const QString name = c[QStringLiteral("name")].toString();
            if (!sameStats(stats(c[QStringLiteral("gcode")].toString().toUtf8()), want[name].toObject(), why)) QFAIL(qPrintable(name + ": " + why));
        }
    }

    void work() {
        const std::vector<Box> boxes{{10, 40, 20, 50}, {300, 0, 310, 10}, {0, 34.9, 400, 40}, {0, 35, 370, 360}, {-1, 0, 5, 5}, {10, 10, 700, 700}};
        const std::vector<Box> sb{{0, 0, 200, 20}, {0, 0, 100, 20}, {0, 0, 300, 40}, {5, 5, 60, 100}, {0, 0, 200, 20}, {0, 0, 360, 200}};
        const double beds[8][4] = {{370, 360, 78, 35}, {370, 360, 370, 35}, {400, 300, 60, 30}, {400, 300, 600, 50}, {370, 360, 601, 201}, {99, 601, -1, -1}, {100, 600, 0, 0}, {600, 100, 200, 200}};
        const QJsonArray want = readJson(QStringLiteral("out/work.json")).array();
        for (int i = 0; i < 8; ++i) {
            Bed::configure(370, 360, 78, 35);
            Bed::configure(beds[i][0], beds[i][1], beds[i][2], beds[i][3]);
            QJsonArray touches, contains, bedTouches;
            for (const Box& b : boxes) { touches.append(Work::touchesPark(b)); contains.append(Work::contains(b)); bedTouches.append(Bed::touchesPark(b)); }
            QJsonArray inWork;
            for (const Pt p : {Pt{5, 5}, Pt{100, 5}, Pt{100, 100}, Pt{-1, 50}, Pt{50, 500}}) inWork.append(Bed::inWorkArea(p.x, p.y));
            QJsonArray cross;
            const double segs[5][4] = {{0, 10, 200, 10}, {78, 0, 78, 30}, {100, 5, 100, 30}, {10, 50, 10, 10}, {5, 5, 5, 5}};
            for (const auto& s : segs) cross.append(Bed::segmentInPark(s[0], s[1], s[2], s[3]));
            QJsonArray nest;
            for (const auto& p : Nest::place(sb)) nest.append(p ? QJsonValue(QJsonArray{p->plate, pt(p->offset)}) : QJsonValue());
            const QJsonObject got{{"bed", QJsonArray{Bed::width(), Bed::height(), Bed::parkX(), Bed::parkY()}}, {"size", Work::sizeLabel()}, {"park", boxJ(Work::park())},
                                  {"blocked", Work::bandBlocked()}, {"name", Work::parkName()}, {"usable", Work::usableHeight()}, {"center", pt(Work::center())},
                                  {"machine", pt(Work::toMachine({12.5, 7}))}, {"from", pt(Work::fromMachine({12.5, 7}))}, {"touches", touches}, {"contains", contains},
                                  {"bedTouches", bedTouches}, {"inWork", inWork}, {"cross", cross}, {"shelf", ptsN(shelf(sb, Work::width(), Work::height()))}, {"nest", nest}};
            QString why;
            if (!near(got, want[i], QStringLiteral("bed%1").arg(i), 0, why)) QFAIL(qPrintable(why));
        }
    }

    void geometry() {
        const QJsonObject g = readJson(QStringLiteral("in/geo.json")).object();
        const QJsonObject want = readJson(QStringLiteral("out/geometry.json")).object();
        const PolySet nested = readPolys(g[QStringLiteral("nested")]), ring = readPolys(g[QStringLiteral("ring")]), open = readPolys(g[QStringLiteral("open")]), text = readPolys(g[QStringLiteral("text")]);
        const Poly dense = readPoly(g[QStringLiteral("dense")]), points = readPoly(g[QStringLiteral("points")]);
        std::vector<Box> boxes;
        for (const QJsonValue& v : g[QStringLiteral("boxes")].toArray()) boxes.push_back(readBox(v));

        std::vector<uint32_t> argb(60 * 40);
        for (int y = 0; y < 40; ++y)
            for (int x = 0; x < 60; ++x) {
                const int d = (x - 20) * (x - 20) + (y - 20) * (y - 20);
                const bool on = (d < 144 && d > 25) || (x > 40 && x < 55 && y > 10 && y < 30) || (x == 50 && y == 36);
                argb[size_t(y) * 60 + x] = x < 3 && y < 3 ? 0u : on ? 0xFF102030u : 0xFFF0F0E8u;
            }
        const Mask m = Mask::fromArgb(argb, 60, 40, 30, 20);
        PolySet nestedOpen = nested;
        nestedOpen.append(open);
        PolySet ringOpen = ring;
        ringOpen.append(open);
        const auto first4 = PolyView(points).subspan(0, 4);

        QJsonObject got;
        got["hatch"] = polys(hatch(nested, 0.5));
        got["hatchRing"] = polys(hatch(ring, 1.3));
        got["orderPaths"] = polys(orderPaths(open, {5, 5}));
        got["orderForCutting"] = polys(orderForCutting(nestedOpen, {0, 0}));
        got["simplify"] = poly(simplify(dense, 0.3));
        got["rect"] = poly(Shapes::rect(30, 20));
        got["rectR"] = poly(Shapes::rect(30, 20, 4));
        got["ellipse"] = poly(Shapes::ellipse(30, 20));
        got["polygon"] = poly(Shapes::polygon(7, 30, 20));
        got["contourOut"] = polys(Contour::fromPolys(nested, 2));
        got["contourIn"] = polys(Contour::fromPolys(nested, -0.5));
        got["contourOuter"] = polys(Contour::fromPolys(ring, 1, 8, true));
        got["maskCount"] = m.count();
        got["maskFilled"] = m.filled().count();
        got["maskSpecks"] = m.withoutSpecks(0.5).count();
        got["sticker"] = polys(Contour::sticker(m, 2));
        got["stickerJoin"] = polys(Contour::sticker(m, 1, true));
        got["edge"] = polys(Contour::edge(m, 0.2));
        {
            QJsonArray a;
            for (const PolySet& p : PartSplitter::split(nestedOpen).parts) a.append(polys(p));
            got["split"] = a;
        }
        const std::pair<const char*, AlignMode> aligns[] = {{"LEFT", AlignMode::Left}, {"CENTER_X", AlignMode::CenterX}, {"RIGHT", AlignMode::Right}, {"TOP", AlignMode::Top}, {"CENTER_Y", AlignMode::CenterY}, {"BOTTOM", AlignMode::Bottom}};
        for (const auto& [n, mode] : aligns) got[QStringLiteral("align") + QLatin1String(n)] = ptsO(Align::offsets(boxes, mode, boxes[1]));
        got["distH"] = ptsO(Align::distribute(boxes, true));
        got["distV"] = ptsO(Align::distribute(boxes, false));
        PolySet bar;
        {
            Poly r = Shapes::rect(20, 50);
            for (Pt& p : r) p = {p.x + 10, p.y - 5};
            bar.add(r);
        }
        got["boolUNION"] = polys(Booleans::apply({ring, bar}, RasterBooleanOp::Union));
        got["boolSUBTRACT"] = polys(Booleans::apply({ring, bar}, RasterBooleanOp::Subtract));
        got["boolINTERSECT"] = polys(Booleans::apply({ring, bar}, RasterBooleanOp::Intersect));
        got["tabs"] = polys(Tabs::apply(ringOpen, 3, 1.5));
        got["shelf"] = ptsN(shelf(boxes, 370, 360));
        {
            QJsonArray a;
            for (const auto& p : Nest::place(boxes)) a.append(p ? QJsonValue(QJsonArray{p->plate, pt(p->offset)}) : QJsonValue());
            got["nest"] = a;
        }
        for (const bool closed : {false, true}) {
            QJsonArray a;
            for (const auto& [n, p] : BoxMaker::panels({60, 40, 30, 3, 8, closed})) a.append(QJsonArray{n, poly(p)});
            got[closed ? "boxClosed" : "boxOpen"] = a;
        }
        got["arcUp"] = polys(ArcText::bend(text, 30));
        got["arcDown"] = polys(ArcText::bend(text, -30));
        got["grid"] = ptsO(Arrange::gridOffsets(boxes[0], 3, 4, 2, 5));
        got["gridInside"] = ptsO(Arrange::inside(boxes[4], Arrange::gridOffsets(boxes[0], 3, 4, 20, 5)));
        got["heart"] = poly(ShapeLib::heart(30, 25));
        got["star"] = poly(ShapeLib::star(6, 30, 25, 0.5));
        got["pendant"] = polys(ShapeLib::pendant(30, 25));
        const std::pair<const char*, ShapeKind> kinds[] = {{"STAR", ShapeKind::Star}, {"HEART", ShapeKind::Heart}, {"ARROW", ShapeKind::Arrow}, {"BUBBLE", ShapeKind::Bubble}, {"CROSS", ShapeKind::Cross}, {"DROP", ShapeKind::Drop}};
        for (const auto& [n, k] : kinds) got[QStringLiteral("make") + QLatin1String(n)] = poly(makeShape(k, 30, 25));
        got["curveOpen"] = poly(Curves::catmullRom(first4, false));
        got["curveClosed"] = poly(Curves::catmullRom(first4, true, 5));
        const std::pair<const char*, TagStyle> tags[] = {{"KEYCHAIN", TagStyle::Keychain}, {"PLATE", TagStyle::Plate}, {"HEART", TagStyle::Heart}, {"ROUND", TagStyle::Round}};
        for (const auto& [n, s] : tags) {
            got[QStringLiteral("tag") + QLatin1String(n)] = parts(Personalize::tag(text, s, 4.0));
            got[QStringLiteral("tagNo") + QLatin1String(n)] = parts(Personalize::tag(text, s, std::nullopt));
        }
        got["emblem"] = parts(Personalize::emblem(text, text, text, 60));
        got["emblemPlain"] = parts(Personalize::emblem(text, std::nullopt, std::nullopt, 40));
        const std::pair<const char*, FrameStyle> frames[] = {{"SIMPLE", FrameStyle::Simple}, {"ROUNDED", FrameStyle::Rounded}, {"DOUBLE", FrameStyle::Double}, {"OVAL", FrameStyle::Oval}, {"DASHED", FrameStyle::Dashed}};
        for (const auto& [n, s] : frames) got[QStringLiteral("frame") + QLatin1String(n)] = polys(Personalize::frame(boxes[0], s, 3));
        got["dashes"] = polys(Personalize::dashes(ring[0], 4, 2.5));
        got["ruler"] = parts(Personalize::ruler(50, 20, 4.0));
        got["puzzle7"] = polys(Personalize::puzzle(60, 40, 3, 2));
        got["puzzle2"] = polys(Personalize::puzzle(60, 40, 2, 3, 123456));
        got["puzzle3"] = polys(Personalize::puzzle(60, 40, 2, 2, -5));
        got["hull"] = poly(convexHull(points));
        got["frameBox"] = QString::fromLatin1(frameProgram(points, FrameMode::Box));
        got["frameHull"] = QString::fromLatin1(frameProgram(points, FrameMode::Hull, 12000));
        got["toolpath"] = stats(g[QStringLiteral("toolpath")].toString().toUtf8());
        {
            MaterialTestSpec spec;
            spec.powerSteps = 3;
            spec.speedSteps = 2;
            const Document mt = buildMaterialTest(spec, [](const QString& t, double h) { PolySet s; s.add(Shapes::rect(t.size() * h, h)); return s; });
            QJsonArray layers, elements;
            for (const Layer& l : mt.layers) layers.append(QJsonArray{l.name, l.color, l.powerPct, l.speed, l.mode == LayerMode::Line ? "LINE" : "FILL"});
            for (const Element& e : mt.elements) elements.append(QJsonArray{e.kind, pt({e.transform.x, e.transform.y}), polys(e.paths), e.text ? QJsonValue(*e.text) : QJsonValue()});
            got["materialTest"] = QJsonObject{{"title", mt.title}, {"layers", layers}, {"elements", elements}};
        }
        {
            DarknessCurve curve;
            const double ps[4] = {20, 40, 60, 90}, ts[4] = {0.1, 0.3, 0.25, 0.8};
            for (int i = 0; i < 4; ++i) { DarknessPoint p; p.power = ps[i]; p.speed = 3000; p.tone = ts[i]; curve.points.push_back(p); }
            Layer lay = newLayer(QStringLiteral("G"), 1, LayerMode::Fill);
            lay.powerPct = 30; lay.speed = 3000; lay.intervalMm = 0.1; lay.darkness = curve;
            Layer plain = newLayer(QStringLiteral("L"), 1, LayerMode::Line);
            plain.powerPct = 30; plain.speed = 1500;
            const auto res = [](const Darkness::Result& r) { return QJsonArray{r.layer.speed, r.layer.powerPct, r.limit ? QJsonValue(*r.limit) : QJsonValue()}; };
            Layer curved = lay;
            curved.toneCurve = {0.0, 0.2, 0.9};
            const auto r1 = Darkness::speedRange(lay, 9000), r2 = Darkness::speedRange(plain, 9000);
            QJsonArray a{r1.first, r1.second, r2.first, r2.second,
                         res(Darkness::atSpeed(lay, 500, 9000)), res(Darkness::atSpeed(lay, 8000, 9000)), res(Darkness::atSpeed(plain, 100, 9000)), res(Darkness::atSpeed(plain, 2000, 9000)),
                         Darkness::speedPosition(lay, 9000), Darkness::speedAt(lay, 0.7, 9000), Darkness::tone(lay).value_or(-1), Darkness::tone(plain).value_or(-1),
                         res(Darkness::atTone(lay, 0.5, 9000)), res(Darkness::atTone(lay, 0.05, 9000)), res(Darkness::atTone(lay, 0.95, 9000)), res(Darkness::atTone(lay, 0.11, 1000)), res(Darkness::atTone(plain, 0.5, 9000)),
                         curved.powerShare(0.3), lay.powerShare(1.5)};
            got["dark"] = a;
        }

        for (auto it = want.begin(); it != want.end(); ++it) QVERIFY2(got.contains(it.key()), qPrintable(QStringLiteral("Vergleich fehlt: ") + it.key()));
        QStringList bad;
        for (auto it = want.begin(); it != want.end(); ++it) {
            QString why;
            if (!near(got[it.key()], it.value(), it.key(), 1e-6, why)) bad << why;
        }
        qInfo("Geometrie: %lld Tabellen, %lld abweichend", qint64(want.size()), qint64(bad.size()));
        if (!bad.isEmpty()) QFAIL(qPrintable(bad.join(QLatin1Char('\n'))));
    }
};

QTEST_GUILESS_MAIN(TestGolden)
#include "test_golden.moc"
