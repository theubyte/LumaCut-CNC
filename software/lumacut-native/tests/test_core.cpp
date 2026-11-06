/**
 * Was der Kotlin-Vergleich nicht abdeckt: Rundreise Projekt-JSON mit unbekannten Feldern, Raster-Reihenfolge
 * gegen lineare Suche, parallele gegen serielle Rasterzeilen, Vektorisieren und Kurven gegen TypeScript-Golden,
 * boolesche Operationen über Flächensummen.
 */
#include "core/boolean.h"
#include "core/contour.h"
#include "core/curves.h"
#include "core/gcode.h"
#include "core/geometry.h"
#include "core/image.h"
#include "core/material.h"
#include "core/parts.h"
#include "core/toolpath.h"
#include "core/vectorize.h"

#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QThreadPool>
#include <QtTest>
#include <cmath>
#include <random>

using namespace lumacut;

namespace {
QByteArray readFile(const QString& rel) {
    QFile f(QStringLiteral(LUMACUT_GOLDEN_DIR "/") + rel);
    if (!f.open(QIODevice::ReadOnly)) qFatal("Datei fehlt: %s", qPrintable(rel));
    return f.readAll();
}
double totalArea(const PolySet& s) {
    double a = 0;
    for (PolyView p : s) a += polyArea(p);
    return a;
}
Poly square(double x, double y, double w, double h) { return {{x, y}, {x + w, y}, {x + w, y + h}, {x, y + h}, {x, y}}; }
PolySet one(const Poly& p) { PolySet s; s.add(p); return s; }
Poly polyOf(const QJsonValue& v) {
    Poly out;
    for (const QJsonValue& q : v.toArray()) out.push_back({q[0].toDouble(), q[1].toDouble()});
    return out;
}
void compareTs(const PolySet& got, const QJsonValue& want, const char* what) {
    const QJsonArray w = want.toArray();
    QVERIFY2(qsizetype(got.size()) == w.size(), qPrintable(QStringLiteral("%1: %2 Pfade statt %3").arg(what).arg(got.size()).arg(w.size())));
    for (size_t i = 0; i < got.size(); ++i) {
        const Poly q = polyOf(w[qsizetype(i)]);
        QVERIFY2(got[i].size() == q.size(), what);
        for (size_t k = 0; k < q.size(); ++k)
            QVERIFY2(std::fabs(got[i][k].x - q[k].x) <= 1e-9 && std::fabs(got[i][k].y - q[k].y) <= 1e-9, what);
    }
}
}  // namespace

class TestCore : public QObject {
    Q_OBJECT
private slots:
    void init() { Bed::configure(370, 360, 78, 35); }

    void fmtWieJava() {
        QCOMPARE(fmt3(1.0005), QByteArray("1.001"));
        QCOMPARE(fmt3(0.0005), QByteArray("0.001"));
        QCOMPARE(fmt3(0.0004999), QByteArray("0.000"));
        QCOMPARE(fmt3(100.1235), QByteArray("100.124"));
        QCOMPARE(fmt3(999.9995), QByteArray("1000.000"));
        QCOMPARE(fmt3(9.9999), QByteArray("10.000"));
        QCOMPARE(fmt3(-0.0), QByteArray("-0.000"));
        QCOMPARE(fmt3(-0.0001), QByteArray("-0.000"));
        QCOMPARE(fmt3(370), QByteArray("370.000"));
        QCOMPARE(fmtFixed(7500.5, 0, ','), QByteArray("7501"));
        QCOMPARE(fmtFixed(2.5, 2, ','), QByteArray("2,50"));
        QCOMPARE(fmtFixed(0.5, 0), QByteArray("1"));
        QCOMPARE(fmtFixed(1e-7, 3), QByteArray("0.000"));
    }

    void hypotWieFdlibm() {
        QCOMPARE(hypotJ(3, 4), 5.0);
        QCOMPARE(hypotJ(0, -2), 2.0);
        QCOMPARE(hypotJ(1e-20, 1), 1.0);
    }

    void unbekannteFelderBleiben() {
        const QByteArray in = "{\"zukunft\":{\"a\":[1,2,{\"b\":null}]},\"title\":\"Täst \\\"x\\\"\",\"layers\":[{\"id\":\"L\",\"name\":\"A\",\"color\":4283356340,\"mode\":\"FILL\",\"process\":\"Markieren\",\"darkness\":{\"points\":[{\"power\":20,\"speed\":3000,\"tone\":0.1,\"neu\":true}],\"neu2\":\"x\"}}],"
                              "\"elements\":[{\"layerId\":\"L\",\"kind\":\"Pfad\",\"paths\":[[{\"x\":0,\"y\":0},{\"y\":5,\"x\":10,\"z\":9}]],\"curves\":[{\"closed\":false,\"nodes\":[{\"x\":0,\"y\":0},{\"x\":10,\"y\":5,\"hx1\":2,\"hy1\":2}]}],\"neuElement\":[1],\"adjust\":{\"brightness\":5,\"gamma\":2}}],\"plateCount\":0,\"activePlate\":7}";
        const Document d = Document::fromJson(in);
        QCOMPARE(d.title, QStringLiteral("Täst \"x\""));
        QCOMPARE(d.plateCount, 1);
        QCOMPARE(d.activePlate, 0);
        QCOMPARE(d.layers[0].extra[QStringLiteral("process")].toString(), QStringLiteral("Markieren"));
        QCOMPARE(d.elements[0].paths[0][1].y, 5.0);
        QVERIFY(!d.elements[0].id.isEmpty());
        QVERIFY(d.elements[0].curves.has_value());
        QVERIFY((*d.elements[0].curves)[0].nodes[1].hasIn());
        QVERIFY(!(*d.elements[0].curves)[0].nodes[1].hasOut());

        const QByteArray out = d.toJson();
        const Document again = Document::fromJson(out);
        QCOMPARE(again.toJson(), out);
        const QJsonObject o = QJsonDocument::fromJson(out).object();
        QCOMPARE(o[QStringLiteral("zukunft")][QStringLiteral("a")][2][QStringLiteral("b")].isNull(), true);
        QCOMPARE(o[QStringLiteral("layers")][0][QStringLiteral("process")].toString(), QStringLiteral("Markieren"));
        QCOMPARE(o[QStringLiteral("layers")][0][QStringLiteral("darkness")][QStringLiteral("neu2")].toString(), QStringLiteral("x"));
        QCOMPARE(o[QStringLiteral("layers")][0][QStringLiteral("darkness")][QStringLiteral("points")][0][QStringLiteral("neu")].toBool(), true);
        QCOMPARE(o[QStringLiteral("elements")][0][QStringLiteral("neuElement")][0].toInt(), 1);
        QCOMPARE(o[QStringLiteral("elements")][0][QStringLiteral("adjust")][QStringLiteral("gamma")].toInt(), 2);
    }

    void androidDateiLesen() {
        const QByteArray text = readFile(QStringLiteral("in/android-doc.json"));
        const Document d = Document::fromJson(text);
        QVERIFY(!d.elements.empty());
        QCOMPARE(d.toJson(), text.trimmed());
        WriteOptions o;
        o.appVersion = "x";
        QVERIFY(writeMarlin(d.plateView(0), o).contains("G1 "));
    }

    void kaputteDateien() {
        for (const QByteArray& bad : {QByteArray("{"), QByteArray("[]"), QByteArray("{\"layers\":[{\"mode\":\"NEU\"}]}"), QByteArray("{\"title\":\"x\"} y"), QByteArray("{\"title\":\"x")}) {
            bool thrown = false;
            try { Document::fromJson(bad); } catch (const JsonError&) { thrown = true; }
            QVERIFY2(thrown, bad.constData());
        }
        const Document empty = Document::fromJson("{}");
        QCOMPARE(empty.layers.size(), size_t(3));
        QCOMPARE(empty.title, QStringLiteral("Neues Projekt"));
    }

    void rasterTeiltEinmal() {
        std::vector<uint8_t> g(12 * 9);
        for (size_t i = 0; i < g.size(); ++i) g[i] = uint8_t(i * 7);
        const Raster r = Raster::ofGray(12, 9, g);
        const Raster copy = r;
        QCOMPARE(copy.gray().data(), r.gray().data());
        const Raster fromB = Raster::fromBase64(12, 9, r.grayBase64());
        QVERIFY(fromB.gray() == g);
        QCOMPARE(encodeBase64(g), r.grayBase64());
        bool thrown = false;
        try { decodeBase64("A!!A"); } catch (const std::invalid_argument&) { thrown = true; }
        QVERIFY(thrown);
        for (const int n : {1, 2, 3, 4, 5, 300000, 300001, 300002}) {
            std::vector<uint8_t> b(static_cast<size_t>(n));
            for (int i = 0; i < n; ++i) b[size_t(i)] = uint8_t(i * 31);
            QVERIFY(decodeBase64(encodeBase64(b)) == b);
            const QByteArray qt = QByteArray(reinterpret_cast<const char*>(b.data()), n).toBase64();
            QCOMPARE(encodeBase64(b), qt);
        }
        QVERIFY_THROWS_EXCEPTION(std::invalid_argument, Raster::ofGray(2, 2, {1, 2, 3}));
    }

    /** Das Raster sucht anders, das Ergebnis muss gleich bleiben, auch bei vielen Gleichständen. */
    void rasterReihenfolgeWieLinear() {
        std::mt19937 rng(11);
        for (const int mode : {0, 1, 2}) {
            PolySet paths;
            std::uniform_int_distribution<int> grid(0, 60);
            std::uniform_real_distribution<double> real(0.0, 300.0);
            for (int i = 0; i < 2500; ++i) {
                // Modus 0: ganz zufällig, 1: Raster mit vielen gleichen Abständen, 2: Häufung plus geschlossene Pfade.
                const double x = mode == 0 ? real(rng) : grid(rng) * 2.0, y = mode == 0 ? real(rng) : grid(rng) * 2.0;
                if (mode == 2 && i % 3 == 0) paths.add(square(x, y, 1, 1));
                else paths.add({Pt{x, y}, Pt{x + (mode == 0 ? real(rng) / 50 : 2.0), y}});
            }
            const auto viaGrid = orderPathsIndexed(paths, {3, 3});
            // Dieselbe Eingabe linear: Teilmengen unter der Grenze laufen linear, darum hier von Hand nachgerechnet.
            std::vector<uint8_t> used(paths.size(), 0);
            Pt at{3, 3};
            for (size_t step = 0; step < viaGrid.size(); ++step) {
                size_t best = 0;
                double bestD = std::numeric_limits<double>::max();
                bool rev = false;
                for (size_t i = 0; i < paths.size(); ++i) {
                    if (used[i]) continue;
                    const double d0 = dist(at, paths[i].front());
                    if (d0 < bestD) { bestD = d0; best = i; rev = false; }
                    if (!isClosed(paths[i])) {
                        const double d1 = dist(at, paths[i].back());
                        if (d1 < bestD) { bestD = d1; best = i; rev = true; }
                    }
                }
                QVERIFY2(viaGrid[step].index == best && viaGrid[step].reversed == rev, qPrintable(QStringLiteral("Schritt %1 Modus %2").arg(step).arg(mode)));
                used[best] = 1;
                at = rev ? paths[best].front() : paths[best].back();
            }
        }
    }

    /** Mehrere Kerne dürfen nichts ändern: gleicher G-Code mit einem Thread und mit allen. */
    void parallelGleichSeriell() {
        std::vector<uint8_t> g(300 * 200);
        std::mt19937 rng(5);
        for (uint8_t& v : g) v = uint8_t(rng());
        Layer layer = newLayer(QStringLiteral("G"), 1, LayerMode::Fill);
        layer.powerPct = 50; layer.speed = 3000; layer.intervalMm = 0.1; layer.passes = 2;
        Document doc;
        doc.layers = {layer};
        for (int i = 0; i < 3; ++i) {
            Element e = newElement(layer.id, QStringLiteral("Bild"));
            e.transform.x = 20 + i * 60;
            e.transform.y = 50;
            e.raster = Raster::ofGray(300, 200, g);
            e.imageWidthMm = 50;
            e.imageHeightMm = 40;
            e.imageMode = i == 0 ? ImageMode::Dither : i == 1 ? ImageMode::Grayscale : ImageMode::DitherStucki;
            if (i == 1) { e.adjust.sharpen = 40; e.adjust.contrast = 15; }
            doc.elements.push_back(e);
        }
        const QByteArray many = writeMarlin(doc);
        const QByteArray parsedText = many;
        const Toolpath a = parseToolpath(parsedText);
        const int before = QThreadPool::globalInstance()->maxThreadCount();
        QThreadPool::globalInstance()->setMaxThreadCount(1);
        const QByteArray single = writeMarlin(doc);
        const Toolpath b = parseToolpath(parsedText);
        QThreadPool::globalInstance()->setMaxThreadCount(before);
        QVERIFY(many == single);
        QVERIFY(a.xy == b.xy && a.power == b.power && a.line == b.line);
        QCOMPARE(a.stats.seconds, b.stats.seconds);
    }

    void gpuLayout() {
        struct Gpu { float x0, y0, x1, y1, power; };
        const Toolpath tp = parseToolpath("M3 I\nG0 X10 Y10\nG1 X20 Y10 F600 S255\nG1 X20 Y20 S51\n");
        const auto v = toGpuSegments<Gpu>(tp);
        QCOMPARE(v.size(), size_t(3));
        QCOMPARE(v[0].power, 0.0f);
        QCOMPARE(v[1].power, 1.0f);
        QCOMPARE(v[1].x1, 20.0f);
        QCOMPARE(v[2].power, 0.2f);
    }

    void bildUndVorschau() {
        std::vector<uint8_t> g(40 * 30, 200);
        const Raster r = Raster::ofGray(40, 30, g);
        PreviewOptions o;
        o.mode = ImageMode::Threshold;
        PreviewImage p = previewRgba(r, o);
        QCOMPARE(p.width, 40);
        QCOMPARE(int(p.rgba[0]), 255);
        QCOMPARE(int(p.rgba[3]), 255);
        o.transparentWhite = true;
        p = previewRgba(r, o);
        QCOMPARE(int(p.rgba[3]), 0);
        o.maxPixels = 300;
        p = previewRgba(r, o);
        QVERIFY(qint64(p.width) * p.height <= 300);
        const std::vector<uint8_t> rgba{10, 20, 30, 255, 0, 0, 0, 0};
        const Gray gr = grayFromRgba(rgba, 2, 1);
        QCOMPARE(int(gr[1]), 255);
        QCOMPARE(int(gr[0]), 19);
    }

    void boolesch() {
        const PolySet a = one(square(0, 0, 10, 10)), b = one(square(5, 5, 10, 10));
        QCOMPARE(std::fabs(totalArea(booleanOp(BooleanOp::Union, a, b))), 175.0);
        QCOMPARE(std::fabs(totalArea(booleanOp(BooleanOp::Intersect, a, b))), 25.0);
        QCOMPARE(std::fabs(totalArea(booleanOp(BooleanOp::Subtract, a, b))), 75.0);
        QCOMPARE(booleanOp(BooleanOp::Xor, a, b).size(), size_t(2));
        for (PolyView p : booleanOp(BooleanOp::Union, a, b)) QVERIFY(isClosed(p));

        // Ring: Außenkontur vor Loch, Fläche als Summe mit Vorzeichen.
        PolySet ring;
        ring.add(square(0, 0, 20, 20));
        ring.add(square(5, 5, 10, 10));
        const PolySet u = booleanOp(BooleanOp::Union, ring, {});
        QCOMPARE(u.size(), size_t(2));
        QVERIFY(std::fabs(polyArea(u[0])) > std::fabs(polyArea(u[1])));
        QCOMPARE(std::fabs(polyArea(u[0])) - std::fabs(polyArea(u[1])), 300.0);
        QVERIFY(booleanShapes(BooleanOp::Subtract, {a, b, one(square(100, 100, 1, 1))}).size() == 1);
        QCOMPARE(std::fabs(totalArea(booleanShapes(BooleanOp::Union, {a, b}))), 175.0);
        QVERIFY(booleanOp(BooleanOp::Subtract, {}, a).empty());

        const PolySet off = offsetPolys(one(square(0, 0, 10, 10)), 1, JoinKind::Miter);
        QCOMPARE(off.size(), size_t(1));
        QVERIFY(std::fabs(std::fabs(polyArea(off[0])) - 144.0) < 1e-3);
        const PolySet round = offsetPolys(one(square(0, 0, 10, 10)), 1);
        QVERIFY(std::fabs(std::fabs(polyArea(round[0])) - (100 + 40 + M_PI)) < 0.05);
        const PolySet in = offsetPolys(one(square(0, 0, 10, 10)), -1, JoinKind::Miter);
        QVERIFY(std::fabs(std::fabs(polyArea(in[0])) - 64.0) < 1e-3);
        QVERIFY(offsetPolys(one(square(0, 0, 10, 10)), -6).empty());
    }

    /** tests/golden/ts/extra.json: dieselben Eingaben durch die geprüfte TypeScript-Fassung. */
    void vektorUndKurvenWieTs() {
        const QJsonObject ts = QJsonDocument::fromJson(readFile(QStringLiteral("ts/extra.json"))).object();
        const int w = 64, h = 48;
        Gray g(size_t(w) * h, 255);
        for (int y = 0; y < h; ++y)
            for (int x = 0; x < w; ++x) {
                const int d = (x - 20) * (x - 20) + (y - 22) * (y - 22);
                if ((d < 200 && d > 40) || (x > 40 && x < 58 && y > 8 && y < 18) || (x == 45 && y == 30) || (x + y) % 37 == 0 || (x == 50 && y == 40) || (x == 51 && y == 41)) g[size_t(y) * w + x] = 10;
            }
        compareTs(vectorize(g, w, h), ts[QStringLiteral("vecPlain")], "vecPlain");
        VectorizeOptions o;
        o.widthMm = 32;
        o.heightMm = 24;
        o.smooth = true;
        compareTs(vectorize(g, w, h, o), ts[QStringLiteral("vecSmooth")], "vecSmooth");
        VectorizeOptions o2;
        o2.outerOnly = true;
        o2.invert = true;
        o2.threshold = 100;
        o2.minAreaMm2 = 1;
        o2.toleranceMm = 0.1;
        compareTs(vectorize(g, w, h, o2), ts[QStringLiteral("vecOuter")], "vecOuter");

        const CurvePath e = ellipseCurve(40, 20);
        compareTs(one(flattenCurve(e)), ts[QStringLiteral("ellipse")], "ellipse");
        compareTs(one(flattenCurve(insertNode(e, 1, 0.3), 0.005)), ts[QStringLiteral("insert")], "insert");
        compareTs(one(flattenCurve(moveHandle(e, 0, true, {25, 3}))), ts[QStringLiteral("handle")], "handle");
        compareTs(one(flattenCurve(moveNode(e, 2, {30, 25}))), ts[QStringLiteral("node")], "node");
        compareTs(one(flattenCurve(toggleSmooth(rectCurve(10, 10), 1))), ts[QStringLiteral("toggle")], "toggle");
        compareTs(one(flattenCurve(toggleSmooth(toggleSmooth(rectCurve(10, 10), 1), 1))), ts[QStringLiteral("toggleBack")], "toggleBack");
        const auto hit = nearestOnCurve(rectCurve(10, 10), {11, 5});
        QVERIFY(hit && hit->span == 1);
        QCOMPARE(hit->dist, 1.0);
        QVERIFY(!deleteNode(rectCurve(1, 1), 0)->nodes.empty());
        const auto paths = curvesFromPaths(one(square(0, 0, 4, 4)));
        QVERIFY(paths[0].closed);
        QCOMPARE(paths[0].nodes.size(), size_t(4));
        QCOMPARE(flattenCurves(paths).pointCount(), size_t(5));
    }

    void teilen() {
        Element e = newElement(QStringLiteral("L"), QStringLiteral("Form"));
        e.transform.x = 10;
        e.paths.add(square(0, 0, 20, 20));
        e.paths.add(square(5, 5, 5, 5));
        e.paths.add(square(40, 0, 10, 10));
        e.curves = std::vector<CurvePath>{rectCurve(1, 1)};
        const auto parts = splitParts(e);
        QCOMPARE(parts.size(), size_t(2));
        QCOMPARE(parts[0].paths.size(), size_t(2));
        QCOMPARE(parts[0].transform.x, 10.0);
        QCOMPARE(parts[1].transform.x, 50.0);
        QVERIFY(!parts[0].curves.has_value());
        QVERIFY(parts[0].id != e.id);
        Element t = e;
        t.text = QStringLiteral("Wort");
        QCOMPARE(splitParts(t).size(), size_t(1));
    }

    void material() {
        const auto list = Material::defaults();
        QCOMPARE(list.size(), size_t(7));
        QCOMPARE(list[0].effectivePasses(), 2);
        Layer l = newLayer(QStringLiteral("Schneiden"), 1, LayerMode::Line);
        const Layer a = list[0].applyTo(l);
        QCOMPARE(a.passes, 2);
        QCOMPARE(a.zStepMm, 0.5);
        QCOMPARE(*a.materialName, QStringLiteral("Pappelsperrholz"));
        Material deep = list[0];
        deep.thicknessMm = 20;
        deep.zStepMm = 2;
        const Layer b = deep.applyTo(l);
        QVERIFY(b.focusDropMm() <= Limits::MAX_FOCUS_DROP_MM + 1e-9);
    }

    /** Für die Gegenprobe: LUMACUT_COMPAT_OUT schreibt Datei und G-Code, die der Kotlin-Code nachprüft. */
    void gegenprobeSchreiben() {
        const QByteArray dir = qgetenv("LUMACUT_COMPAT_OUT");
        if (dir.isEmpty()) QSKIP("nur auf Anforderung");
        Document d;
        d.title = QStringLiteral("Kompatibel Ä");
        d.extra.insert(QStringLiteral("zukunft"), 1);
        Element a = newElement(d.layers[2].id, QStringLiteral("Rechteck"));
        a.paths.add(square(0, 0, 40, 30));
        a.transform = Transform{30, 60, 1, 1, 15};
        Element b = newElement(d.layers[1].id, QStringLiteral("Pfad"));
        b.paths.add({Pt{0, 0}, Pt{10, 5}});
        b.transform = Transform{100, 100, 2, 1, 0};
        CurvePath c = rectCurve(5, 5);
        b.curves = std::vector<CurvePath>{c};
        b.extra.insert(QStringLiteral("neu"), QStringLiteral("x"));
        Element e = newElement(d.layers[0].id, QStringLiteral("Text"));
        e.text = QStringLiteral("Ä\"\n");
        e.paths.add(square(0, 0, 40, 30));
        e.transform.x = 100;
        e.transform.y = 150;
        Element img = newElement(d.layers[0].id, QStringLiteral("Bild"));
        std::vector<uint8_t> g(64 * 48);
        for (size_t i = 0; i < g.size(); ++i) g[i] = uint8_t(i * 13 % 256);
        img.raster = Raster::ofGray(64, 48, g);
        img.imageWidthMm = 20;
        img.imageHeightMm = 15;
        img.imageMode = ImageMode::DitherStucki;
        img.adjust.contrast = 10;
        img.transform.x = 200;
        img.transform.y = 200;
        Element other = img;
        other.plate = 1;
        d.elements = {a, b, e, img, other};
        d.layers[0].darkness = DarknessCurve{};
        DarknessPoint pt;
        pt.power = 20; pt.speed = 3000; pt.tone = 0.5;
        d.layers[0].darkness->points.push_back(pt);
        d.layers[1].extra.insert(QStringLiteral("process"), QStringLiteral("Markieren"));
        d.plateCount = 2;
        QFile fj(QString::fromLocal8Bit(dir) + QStringLiteral("/from-cpp.json")), fg(QString::fromLocal8Bit(dir) + QStringLiteral("/from-cpp.gcode"));
        QVERIFY(fj.open(QIODevice::WriteOnly) && fg.open(QIODevice::WriteOnly));
        fj.write(d.toJson());
        WriteOptions o;
        o.appVersion = "x";
        fg.write(writeMarlin(d.plateView(0), o));
    }

    void platten() {
        Document d;
        Element a = newElement(d.layers[0].id, QStringLiteral("A")), b = newElement(d.layers[1].id, QStringLiteral("B"));
        b.plate = 1;
        d.elements = {a, b};
        d = d.normalized();
        QCOMPARE(d.plateCount, 2);
        QCOMPARE(d.plateView(1).elements.size(), size_t(1));
        const Document more = d.addPlate();
        QCOMPARE(more.activePlate, 2);
        const Document less = d.removePlate(0);
        QCOMPARE(less.plateCount, 1);
        QCOMPARE(less.elements[0].plate, 0);
        QCOMPARE(d.moveToPlate({a.id}, 1).plateSize(1), 2);
        const Layer extra = newLayer(QStringLiteral("Extra"), 1, LayerMode::Line);
        Document withExtra = d;
        withExtra.layers.push_back(extra);
        QCOMPARE(withExtra.withoutEmptyLayers().layers.size(), size_t(3));
        QCOMPARE(withExtra.withoutEmptyLayers({extra.id}).layers.size(), size_t(4));
        QCOMPARE(d.shownLayers().size(), size_t(2));
        const std::vector<QString> shown{d.layers[0].id, d.layers[1].id};
        QCOMPARE(d.movingLayer(d.layers[1].id, true, shown).layers[0].id, d.layers[1].id);
        QCOMPARE(Document::passesFor(3, 1.5), 2);
        QCOMPARE(Document::passesFor(0, 1.5), 1);
    }
};

QTEST_GUILESS_MAIN(TestCore)
#include "test_core.moc"
