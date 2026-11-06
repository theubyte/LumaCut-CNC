/**
 * Messung großer Dateien: Importzeit und Speicher. Jede Prüfung einzeln starten, sonst misst der Höchststand die davor mit:
 *   test_import_big svg100k
 * Zeilen beginnen mit MESSUNG. Die Grenzen hier sind grob und fangen nur Einbrüche, sie sind kein Tempoversprechen.
 */
#include "core/export.h"
#include "core/import/import.h"
#include "core/import/vector.h"
#include "core/import/xml.h"

#include <QBuffer>
#include <QElapsedTimer>
#include <QImage>
#include <QThreadPool>
#include <QtTest>

#ifdef Q_OS_WIN
#include <windows.h>
#include <psapi.h>
#endif

using namespace lumacut;
using namespace lumacut::import;

namespace {

struct Memory {
    double currentMb = 0, peakMb = 0;
};
Memory memory() {
    Memory m;
#ifdef Q_OS_WIN
    PROCESS_MEMORY_COUNTERS_EX pmc{};
    if (K32GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&pmc), sizeof pmc)) {
        m.currentMb = double(pmc.WorkingSetSize) / (1024 * 1024);
        m.peakMb = double(pmc.PeakWorkingSetSize) / (1024 * 1024);
    }
#endif
    return m;
}

ImportContext ctx() { return importContextFor(Document{}); }

/** 100.000 einzelne Pfade im Raster auf der Fläche, mit `L` oder mit Kurven. */
QByteArray bigSvg(int n, bool curves) {
    QByteArray s = R"(<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="360mm" height="340mm" viewBox="0 0 3600 3400"><g id="ebene">)" "\n";
    s.reserve(qsizetype(n) * 90);
    const int cols = 400;
    for (int i = 0; i < n; ++i) {
        const int x = (i % cols) * 9, y = (i / cols) * 9 % 3390;
        s += "<path stroke=\"#000\" fill=\"none\" d=\"M";
        s += QByteArray::number(x);
        s += ' ';
        s += QByteArray::number(y);
        if (curves) s += "c2 0 4 2 4 4s-2 4-4 4a2 2 0 0 1-2-2z";
        else s += "l5 0l0 5z";
        s += "\"/>\n";
    }
    s += "</g></svg>\n";
    return s;
}
QByteArray bigDxf(int n) {
    QByteArray s = "0\nSECTION\n2\nHEADER\n9\n$INSUNITS\n70\n4\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n";
    s.reserve(qsizetype(n) * 64);
    for (int i = 0; i < n; ++i) {
        const double x = (i % 1000) * 0.3, y = (i / 1000) * 3.0;
        s += "0\nLINE\n8\n0\n10\n";
        s += QByteArray::number(x, 'f', 3);
        s += "\n20\n";
        s += QByteArray::number(y, 'f', 3);
        s += "\n11\n";
        s += QByteArray::number(x + 0.2, 'f', 3);
        s += "\n21\n";
        s += QByteArray::number(y + 2, 'f', 3);
        s += '\n';
    }
    s += "0\nENDSEC\n0\nEOF\n";
    return s;
}

void report(const char* what, const QByteArray& file, const ImportResult& r, qint64 ms) {
    size_t points = 0, paths = 0;
    for (const Element& e : r.elements) { points += e.paths.pointCount(); paths += e.paths.size(); }
    const Memory m = memory();
    qInfo("MESSUNG %s: %.1f MB Datei, %lld ms, %zu Elemente, %zu Pfade, %zu Punkte, Speicher jetzt %.0f MB, Höchststand %.0f MB, %d Threads",
          what, double(file.size()) / (1024 * 1024), qlonglong(ms), r.elements.size(), paths, points, m.currentMb, m.peakMb, QThreadPool::globalInstance()->maxThreadCount());
}

ImportResult timed(const char* what, const QString& name, const QByteArray& file, const ImportContext& c) {
    QElapsedTimer t;
    t.start();
    ImportResult r = importFile(name, file, c);
    const qint64 ms = t.elapsed();
    if (!r.ok()) qWarning("%s: %s", what, qPrintable(r.error));
    report(what, file, r, ms);
    return r;
}

}  // namespace

class TestImportBig : public QObject {
    Q_OBJECT
private slots:
    void svg100k() {
        const QByteArray f = bigSvg(100000, false);
        QVERIFY(timed("SVG 100.000 Pfade, zusammengefasst", QStringLiteral("a.svg"), f, ctx()).ok());
    }
    void svg100kEinzeln() {
        const QByteArray f = bigSvg(100000, false);
        ImportContext c = ctx();
        c.maxElements = 0;
        const ImportResult r = timed("SVG 100.000 Pfade, je Element", QStringLiteral("a.svg"), f, c);
        QCOMPARE(r.elements.size(), size_t(100000));
    }
    void svg100kKurven() {
        const QByteArray f = bigSvg(100000, true);
        QVERIFY(timed("SVG 100.000 Pfade mit Kurven, zusammengefasst", QStringLiteral("a.svg"), f, ctx()).ok());
    }
    void svg100kEinThread() {
        const QByteArray f = bigSvg(100000, false);
        QThreadPool::globalInstance()->setMaxThreadCount(1);
        QVERIFY(timed("SVG 100.000 Pfade, ein Thread", QStringLiteral("a.svg"), f, ctx()).ok());
        QThreadPool::globalInstance()->setMaxThreadCount(QThread::idealThreadCount());
    }
    void teileSvg() {
        const QByteArray f = bigSvg(100000, false);
        QElapsedTimer t;
        t.start();
        const FileKind kind = detectKind(f);
        qInfo("MESSUNG Teil: Typ erkennen %lld ms", qlonglong(t.restart()));
        QCOMPARE(kind, FileKind::Svg);
        { const XmlDoc doc(f); qInfo("MESSUNG Teil: XML %lld ms, %zu Knoten", qlonglong(t.restart()), doc.nodeCount()); }
        VectorImport r = parseSvg(f);
        qInfo("MESSUNG Teil: SVG gesamt %lld ms", qlonglong(t.restart()));
        const Units units = unitsOf(r);
        qInfo("MESSUNG Teil: Einheiten %lld ms", qlonglong(t.restart()));
        const Layout l = arrange(r, units);
        qInfo("MESSUNG Teil: Anordnen %lld ms", qlonglong(t.restart()));
        QVERIFY(l.kind == FitKind::AsIs);
        const ImportResult full = importFile(QStringLiteral("a.svg"), f, ctx());
        qInfo("MESSUNG Teil: alles zusammen %lld ms", qlonglong(t.restart()));
        QVERIFY(full.ok());
    }
    void svg1M() {
        const QByteArray f = bigSvg(1000000, false);
        const ImportResult r = timed("SVG 1.000.000 Pfade, zusammengefasst", QStringLiteral("a.svg"), f, ctx());
        QVERIFY2(r.ok(), qPrintable(r.error));
    }
    void dxf100k() {
        const QByteArray f = bigDxf(100000);
        const ImportResult r = timed("DXF 100.000 Linien", QStringLiteral("a.dxf"), f, ctx());
        QVERIFY(r.ok());
        size_t paths = 0;
        for (const Element& e : r.elements) paths += e.paths.size();
        QCOMPARE(paths, size_t(100000));
    }
    void dxf1M() {
        const QByteArray f = bigDxf(1000000);
        QVERIFY(timed("DXF 1.000.000 Linien", QStringLiteral("a.dxf"), f, ctx()).ok());
    }
    void dxf100kEinThread() {
        const QByteArray f = bigDxf(100000);
        QThreadPool::globalInstance()->setMaxThreadCount(1);
        QVERIFY(timed("DXF 100.000 Linien, ein Thread", QStringLiteral("a.dxf"), f, ctx()).ok());
        QThreadPool::globalInstance()->setMaxThreadCount(QThread::idealThreadCount());
    }
    void exportUndRueckimport100k() {
        const Document start;
        // Auf "Schneiden": Linien, die das PNG wirklich zeichnen muss.
        const ImportResult r = importFile(QStringLiteral("a.dxf"), bigDxf(100000), importContextFor(start, start.layers[2].id));
        QVERIFY(r.ok());
        const Document d = applyImport(start, r);
        QElapsedTimer t;
        t.start();
        const QByteArray svg = exportSvg(d);
        qInfo("MESSUNG Export SVG 100.000 Linien: %.1f MB, %lld ms", double(svg.size()) / (1024 * 1024), qlonglong(t.restart()));
        const QByteArray dxf = exportDxf(d);
        qInfo("MESSUNG Export DXF 100.000 Linien: %.1f MB, %lld ms", double(dxf.size()) / (1024 * 1024), qlonglong(t.restart()));
        const QByteArray png = exportPng(d, std::nullopt, 10);
        qInfo("MESSUNG Export PNG 3700 x 3600: %.1f MB, %lld ms", double(png.size()) / (1024 * 1024), qlonglong(t.restart()));
        const ImportResult back = timed("Rückimport SVG 100.000 Linien", QStringLiteral("b.svg"), svg, ctx());
        QVERIFY(back.ok());
        const ImportResult backDxf = timed("Rückimport DXF 100.000 Linien", QStringLiteral("b.dxf"), dxf, ctx());
        QVERIFY(backDxf.ok());
        const Box a = *d.elements[0].worldBounds();
        const Box b = *backDxf.elements[0].worldBounds();
        QVERIFY(std::fabs(a.width() - b.width()) < 0.01);
        QVERIFY(std::fabs(a.height() - b.height()) < 0.01);
    }
    void bild20MP() {
        QImage img(5000, 4000, QImage::Format_RGB32);
        for (int y = 0; y < img.height(); ++y) {
            QRgb* row = reinterpret_cast<QRgb*>(img.scanLine(y));
            for (int x = 0; x < img.width(); ++x) row[x] = qRgb(x & 255, y & 255, (x ^ y) & 255);
        }
        QByteArray jpeg;
        {
            QBuffer buf(&jpeg);
            buf.open(QIODevice::WriteOnly);
            img.save(&buf, "JPG", 85);
        }
        img = QImage();
        const ImportResult r = timed("JPEG 20 Megapixel", QStringLiteral("a.jpg"), jpeg, ctx());
        QVERIFY(r.ok());
        QCOMPARE(r.elements[0].raster.width(), MAX_RASTER_SIDE);
    }
};

QTEST_GUILESS_MAIN(TestImportBig)
#include "test_import_big.moc"
