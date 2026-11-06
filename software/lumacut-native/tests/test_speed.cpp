/**
 * Tempo-Messung, kein Grenzwert: Foto 2000 × 2000 bis G-Code und Werkzeugweg, Zeit je Stufe in ms.
 * Vergleich aus der TypeScript-Fassung: 2,2 Mio. Zeilen, 1,8 s G-Code plus 2,3 s Werkzeugweg.
 */
#include "core/gcode.h"
#include "core/geometry.h"
#include "core/image.h"
#include "core/toolpath.h"

#include <QElapsedTimer>
#include <QThread>
#include <QtTest>
#include <cmath>
#include <random>

using namespace lumacut;

namespace {
struct Gpu { float x0, y0, x1, y1, power; };

/** Reproduzierbares "Foto": Verlauf, weiche Flecken, Körnung. Ergibt beim Dithern viele kurze Stücke. */
std::vector<uint8_t> photo(int w, int h) {
    std::vector<uint8_t> g(size_t(w) * h);
    std::mt19937 rng(20261106);
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x) {
            const double fx = double(x) / w, fy = double(y) / h;
            double v = 0.15 + 0.5 * fx + 0.25 * std::sin(fx * 13) * std::cos(fy * 9);
            v += 0.35 * std::exp(-((fx - 0.4) * (fx - 0.4) + (fy - 0.6) * (fy - 0.6)) * 18);
            v += double(rng() % 41) / 255.0 - 0.08;
            g[size_t(y) * w + x] = uint8_t(std::clamp(v, 0.0, 1.0) * 255);
        }
    return g;
}
double ms(QElapsedTimer& t) { return double(t.nsecsElapsed()) / 1e6; }
}  // namespace

class TestSpeed : public QObject {
    Q_OBJECT
private slots:
    void init() { Bed::configure(370, 360, 78, 35); }

    void photoToToolpath_data() {
        QTest::addColumn<int>("modeValue");
        QTest::newRow("Floyd") << int(ImageMode::Dither);
        QTest::newRow("Jarvis") << int(ImageMode::DitherJarvis);
        QTest::newRow("Graustufen") << int(ImageMode::Grayscale);
    }
    void photoToToolpath() {
        QFETCH(int, modeValue);
        const int W = 2000, H = 2000;
        qInfo("Kerne: %d", QThread::idealThreadCount());
        const std::vector<uint8_t> gray = photo(W, H);

        QElapsedTimer t;
        t.start();
        const QByteArray b64 = encodeBase64(gray);
        const double tEnc = ms(t);

        Layer layer = newLayer(QStringLiteral("Gravieren"), 0xFF4FD8B4LL, LayerMode::Fill);
        layer.powerPct = 40;
        layer.speed = 6000;
        layer.intervalMm = 0.1;
        Element e = newElement(layer.id, QStringLiteral("Bild"));
        e.transform.x = 20;
        e.transform.y = 50;
        e.raster = Raster::fromBase64(W, H, b64);
        e.imageWidthMm = 200;
        e.imageHeightMm = 200;
        e.imageMode = ImageMode(modeValue);
        Document doc;
        doc.title = QStringLiteral("Tempo");
        doc.layers = {layer};
        doc.elements.push_back(e);

        t.restart();
        const std::vector<uint8_t>& decoded = e.raster.gray();
        const double tDec = ms(t);
        QCOMPARE(decoded.size(), gray.size());

        t.restart();
        const Gray levels = jobLevels(e.raster, W, H, e.adjust, e.imageMode);
        const double tLevels = ms(t);
        QCOMPARE(levels.size(), gray.size());

        WriteOptions opt;
        opt.appVersion = "tempo";
        t.restart();
        const QByteArray g = writeMarlin(doc, opt);
        const double tGcode = ms(t);
        const qint64 lines = g.count('\n');

        t.restart();
        const Toolpath tp = parseToolpath(g);
        const double tTool = ms(t);
        QVERIFY(tp.count() > 0);

        t.restart();
        const std::vector<Gpu> gpu = toGpuSegments<Gpu>(tp);
        const double tGpu = ms(t);
        QCOMPARE(gpu.size(), tp.count());

        t.restart();
        const QByteArray json = doc.toJson();
        const double tSave = ms(t);
        t.restart();
        const Document again = Document::fromJson(json);
        const double tLoad = ms(t);
        QCOMPARE(again.elements.size(), doc.elements.size());

        qInfo("Foto %d x %d, %lld Zeilen, %.1f MB G-Code, %lld Segmente",
              W, H, lines, double(g.size()) / 1e6, qint64(tp.count()));
        qInfo("  Base64 kodieren      %8.1f ms", tEnc);
        qInfo("  Base64 dekodieren    %8.1f ms", tDec);
        qInfo("  Abtasten + Dither    %8.1f ms (im G-Code enthalten)", tLevels);
        qInfo("  G-Code gesamt        %8.1f ms  (TS: 1800 ms)", tGcode);
        qInfo("  Werkzeugweg          %8.1f ms  (TS: 2300 ms)", tTool);
        qInfo("  GPU-Segmente         %8.1f ms", tGpu);
        qInfo("  Projekt speichern    %8.1f ms (%.1f MB)", tSave, double(json.size()) / 1e6);
        qInfo("  Projekt laden        %8.1f ms", tLoad);
    }

    /** Viele Vektorpfade: Reihenfolge und Ausgabe ohne quadratisches Verhalten. */
    void manyPaths() {
        std::mt19937 rng(7);
        std::uniform_real_distribution<double> u(0.0, 1.0);
        PolySet paths;
        const int N = 100000;
        for (int i = 0; i < N; ++i) {
            const double x = 10 + u(rng) * 340, y = 40 + u(rng) * 300;
            paths.add({Pt{x, y}, Pt{x + u(rng), y + u(rng)}, Pt{x + 1, y + 1}});
        }
        QElapsedTimer t;
        t.start();
        const auto order = orderPathsIndexed(paths, {0, 0});
        const double tOrder = ms(t);
        QCOMPARE(order.size(), size_t(N));

        Layer layer = newLayer(QStringLiteral("Linie"), 1, LayerMode::Line);
        Element e = newElement(layer.id, QStringLiteral("Viele"));
        e.paths = paths;
        Document doc;
        doc.layers = {layer};
        doc.elements.push_back(e);
        t.restart();
        const QByteArray g = writeMarlin(doc);
        const double tGcode = ms(t);
        t.restart();
        const QByteArray json = doc.toJson();
        const double tSave = ms(t);
        t.restart();
        const Document again = Document::fromJson(json);
        const double tLoad = ms(t);
        QCOMPARE(again.elements[0].paths.pointCount(), paths.pointCount());
        qInfo("%d Pfade: Reihenfolge %.1f ms, G-Code %.1f ms (%.1f MB), Speichern %.1f ms, Laden %.1f ms (%.1f MB)",
              N, tOrder, tGcode, double(g.size()) / 1e6, tSave, tLoad, double(json.size()) / 1e6);
    }
};

QTEST_GUILESS_MAIN(TestSpeed)
#include "test_speed.moc"
