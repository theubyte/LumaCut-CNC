/**
 * Lochraster core: hole positions, library, rotation, pads kept free of markings, mirroring for the solder side,
 * checks (short, double use, text size, bed), parts list, file round trip, assembly plan.
 */
#include "core/pcb/perfboard.h"

#include <QImage>
#include <QtTest>
#include <cmath>

using namespace lumacut;
using namespace lumacut::pcb;

#define NEAR(a, b, tol) QVERIFY2(std::abs(double(a) - double(b)) <= (tol), qPrintable(QStringLiteral("%1 statt %2").arg(double(a), 0, 'g', 10).arg(double(b), 0, 'g', 10)))

namespace {
PerfBoard board5070() {
    for (const PerfBoard& b : PerfBoard::templates()) if (b.width == 50 && b.height == 70) return b;
    qFatal("Vorlage 50 x 70 fehlt");
}
Placed part(const QString& id, const QString& ref, int c, int r, int rot = 0) { return {ref, id, ref, findPart(id)->value, {c, r}, rot}; }
Wire wire(const QString& id, bool solder, std::vector<GridPt> pts) { return {id, solder, std::move(pts)}; }
bool hasCheck(const std::vector<PerfCheck>& cs, const char* id, PerfTone tone) {
    for (const PerfCheck& c : cs) if (c.id == QLatin1String(id) && c.tone == tone) return true;
    return false;
}
Polys strokeAll(const Polys& lines, double w) {
    Polys out;
    for (const Poly& l : lines) for (Poly& p : strokePolyline(l, w)) out.push_back(std::move(p));
    return unionPolys(out);
}
Polys allPads(const PerfDesign& d) {
    Polys p;
    for (int r = 0; r < d.board.rows; ++r) for (int c = 0; c < d.board.cols; ++c) p.push_back(d.board.padShape({c, r}));
    return unionPolys(p);
}
}  // namespace

class TestPerfboard : public QObject {
    Q_OBJECT
private slots:
    void holes50x70() {
        const PerfBoard b = board5070();
        QCOMPARE(b.cols, 18);
        QCOMPARE(b.rows, 24);
        NEAR(b.hole(0, 0).x, 3.41, 1e-9);
        NEAR(b.hole(0, 0).y, 5.79, 1e-9);
        NEAR(b.hole(17, 23).x, 46.59, 1e-9);
        NEAR(b.hole(17, 23).y, 64.21, 1e-9);
        NEAR(b.hole(1, 0).x - b.hole(0, 0).x, 2.54, 1e-12);
        QCOMPARE(PerfBoard::colName(0), QStringLiteral("A"));
        QCOMPARE(PerfBoard::colName(25), QStringLiteral("Z"));
        QCOMPARE(PerfBoard::colName(26), QStringLiteral("AA"));
        QCOMPARE(b.holeName({2, 4}), QStringLiteral("C5"));
        QCOMPARE(*b.holeAt({3.41 + 2.54 * 2 + 0.8, 5.79 + 2.54 * 4 - 0.8}), (GridPt{2, 4}));
        QVERIFY(!b.holeAt({0.5, 0.5}));
        QVERIFY(b.isEdge({4, 0}) && b.isEdge({4, 23}) && !b.isEdge({4, 1}));
    }
    void templates() {
        const auto t = PerfBoard::templates();
        QCOMPARE(t.size(), size_t(5));
        const int want[5][4] = {{20, 80, 6, 28}, {30, 70, 10, 24}, {40, 60, 14, 20}, {50, 70, 18, 24}, {70, 90, 24, 32}};
        for (size_t i = 0; i < t.size(); ++i) {
            const PerfBoard& b = t[i];
            QCOMPARE(int(b.width), want[i][0]); QCOMPARE(int(b.height), want[i][1]);
            QCOMPARE(b.cols, want[i][2]); QCOMPARE(b.rows, want[i][3]);
            // The grid is centred and leaves the pad inside the board; no pad touches a mounting hole.
            NEAR(b.hole(0, 0).x, b.width - b.hole(b.cols - 1, 0).x, 1e-9);
            QVERIFY(b.hole(0, 0).x - b.padDia / 2 > 1);
            for (int r = 0; r < b.rows; ++r) for (int c = 0; c < b.cols; ++c) QVERIFY(!b.blockedByMount({c, r}));
        }
    }
    void library() {
        const auto& lib = partLibrary();
        QVERIFY(lib.size() >= 30);
        for (const char* id : {"res-762", "res-1016", "res-127", "diode", "led-3", "led-5", "cap-254", "elko-508", "to92", "to220",
                               "dip8", "dip14", "dip16", "dip28", "hdr-2x5", "sock-1x8", "term-2", "tact-6x6", "poti", "jumper-2", "nano", "esp32"})
            QVERIFY2(findPart(QString::fromLatin1(id)), id);
        QCOMPARE(findPart("res-1016")->pins.back(), (GridPt{4, 0}));
        QCOMPARE(findPart("dip8")->pins.size(), size_t(8));
        QCOMPARE(findPart("nano")->pins.size(), size_t(30));
        QCOMPARE(findPart("nano")->pins[15], (GridPt{6, 0}));   // 15.24 mm between the rows
        QCOMPARE(findPart("esp32")->pins[15], (GridPt{10, 0}));
        QVERIFY(findPart("elko-254")->polarized && !findPart("res-762")->polarized);
    }
    void rotateDip8() {
        const PartDef& dip = *findPart("dip8");
        Placed p = part("dip8", "U1", 5, 5, 0);
        auto pins = pinsOf(p, dip);
        QCOMPARE(pins[0], (GridPt{5, 5}));
        QCOMPARE(pins[3], (GridPt{5, 8}));
        QCOMPARE(pins[4], (GridPt{8, 8}));
        QCOMPARE(pins[7], (GridPt{8, 5}));
        p.rot = 1;   // a quarter turn clockwise: the pin row goes from downward to leftward
        pins = pinsOf(p, dip);
        QCOMPARE(pins[0], (GridPt{5, 5}));
        QCOMPARE(pins[3], (GridPt{2, 5}));
        QCOMPARE(pins[4], (GridPt{2, 8}));
        QCOMPARE(pins[7], (GridPt{5, 8}));
        p.rot = 2;
        QCOMPARE(pinsOf(p, dip)[4], (GridPt{2, 2}));
        const Box box = *bodyBox(p, dip, board5070());
        NEAR(box.width(), 2 * 2.54, 1e-9);
        NEAR(box.height(), 4 * 2.54, 1e-9);
        QCOMPARE(rotated({1, 0}, 1), (GridPt{0, 1}));
        QCOMPARE(rotated({1, 0}, 4), (GridPt{1, 0}));
    }
    void routeAndRefs() {
        QCOMPARE(route({0, 0}, {3, 2}).size(), size_t(3));
        QCOMPARE(route({0, 0}, {3, 2})[1], (GridPt{3, 0}));
        QCOMPARE(route({0, 0}, {3, 2}, true)[1], (GridPt{0, 2}));
        QCOMPARE(route({0, 0}, {0, 5}).size(), size_t(2));
        PerfDesign d;
        QCOMPARE(nextRef(d, "R"), QStringLiteral("R1"));
        d.parts = {part("res-762", "R1", 1, 2), part("res-762", "R7", 1, 4), part("led-3", "LED1", 1, 6)};
        QCOMPARE(nextRef(d, "R"), QStringLiteral("R8"));
        QCOMPARE(nextRef(d, "LED"), QStringLiteral("LED2"));
    }
    void padsKeptFree() {
        PerfDesign d;
        d.board = board5070();
        d.parts = {part("res-762", "R1", 2, 3), part("dip8", "U1", 8, 6), part("led-5", "LED1", 3, 12), part("elko-254", "C1", 10, 15)};
        d.wires = {wire("w1", true, route({2, 3}, {8, 6})), wire("w2", false, route({5, 3}, {10, 15}))};
        d.labels = {{"t1", "TEST", d.board.hole(8, 18), 2.0, false}};
        d.holeNumbers = true;
        const MarkOptions o;
        // Without clipping the strokes lie on pads.
        Polys raw;
        for (const Wire& w : d.wires) { Poly l; for (const GridPt& g : w.pts) l.push_back(d.board.hole(g)); raw.push_back(l); }
        const double before = polysArea(intersectPolys(strokeAll(raw, o.beamMm), allPads(d)));
        QVERIFY2(before > 1, qPrintable(QString::number(before)));
        // After: every marking with its beam width stays off the pads, with a margin.
        const PerfMarks m = buildMarks(d, o);
        QVERIFY(!m.component.empty() && !m.solder.empty());
        NEAR(polysArea(intersectPolys(strokeAll(m.component, o.beamMm), allPads(d))), 0, 1e-6);
        NEAR(polysArea(intersectPolys(strokeAll(m.solder, o.beamMm), allPads(d))), 0, 1e-6);
        Polys grown;
        for (int r = 0; r < d.board.rows; ++r) for (int c = 0; c < d.board.cols; ++c) grown.push_back(d.board.padShape({c, r}, o.padClearMm - 0.01));
        NEAR(polysArea(intersectPolys(strokeAll(m.solder, o.beamMm), unionPolys(grown))), 0, 1e-6);
        // A bridge along a row from C4 to I4 is marked whole in the channel half a pitch below the row: 6 × 2.54 mm.
        PerfDesign one;
        one.board = d.board;
        one.wires = {wire("w", true, {{2, 3}, {8, 3}})};
        const PerfMarks lm = buildMarks(one, o);
        QCOMPARE(lm.solder.size(), size_t(1));
        NEAR(lm.solder[0].front().y, d.board.hole(2, 3).y + 1.27, 1e-6);
        NEAR(std::abs(lm.solder[0].back().x - lm.solder[0].front().x), 6 * 2.54, 0.01);
        // Clipped hard against the pads instead, the same line would leave only 0.19 mm dashes.
        NEAR(polysArea(intersectPolys(strokeAll(clipLines({{d.board.hole(2, 3), d.board.hole(8, 3)}}, markRegion(one, o)), o.beamMm), allPads(d))), 0, 1e-6);
        // Text over the pad field is mostly lost and that is measured.
        QVERIFY(m.textLostShare > 0 && m.textLostShare < 1);
    }
    void mirrorSolderSide() {
        QCOMPARE(mirrorX({3, 5}, 50), (Pt{47, 5}));
        PerfDesign d;
        d.board = board5070();
        d.parts = {part("cap-254", "C1", 2, 5)};   // not polarized: no pin-1 ring on the solder side
        d.wires = {wire("w", true, {{2, 10}, {5, 10}})};
        const PerfMarks m = buildMarks(d, MarkOptions{});
        std::vector<Layer> layers = Document::defaultLayers();
        const auto els = perfElements(layers, m, d, 0, 1, {185, 197.5}, 10, 3000);
        QCOMPARE(els.size(), size_t(2));
        QCOMPARE(layers.size(), size_t(5));
        for (const Layer& l : layers)
            if (l.name.startsWith(QLatin1String("Lochraster"))) {
                QCOMPARE(l.mode, LayerMode::Line);
                QCOMPARE(l.extra.value("process").toString(), QStringLiteral("Markieren"));
                QVERIFY(l.powerPct >= Limits::MIN_RELIABLE_POWER_PCT);
            }
        const Element& top = els[0];
        const Element& bottom = els[1];
        QCOMPARE(top.plate, 0);
        QCOMPARE(bottom.plate, 1);
        NEAR(top.transform.x, 160, 1e-9);
        NEAR(top.transform.y, 162.5, 1e-9);
        // The solder wire runs from C11 to F11 (x 8.49..16.11); turned about the vertical axis it lies at 50 - x.
        const auto bb = boundsOf(bottom.paths);
        QVERIFY(bb->minX > 50 - d.board.hole(5, 10).x - 0.01 && bb->maxX < 50 - d.board.hole(2, 10).x + 0.01);
        NEAR(bb->minY, d.board.hole(2, 10).y + 1.27, 1e-6);
        // Pin-1 ring of the LED on the solder side, mirrored as well.
        Polys solderOnly = buildMarks(PerfDesign{d.title, d.board, {part("led-3", "LED1", 2, 5)}, {}, {}, false, false, false}, MarkOptions{}).solder;
        QVERIFY(!solderOnly.empty());
        const Box ring = *boundsOfPolys(solderOnly);
        NEAR((ring.minX + ring.maxX) / 2, d.board.hole(2, 5).x - 1.27, 0.01);
    }
    void checksFindProblems() {
        PerfDesign d;
        d.board = board5070();
        const MarkOptions o;
        d.parts = {part("res-762", "R1", 2, 3), part("res-762", "R2", 5, 3)};   // R1 pin 2 and R2 pin 1 on F4
        auto cs = perfChecks(d, o);
        QVERIFY(hasCheck(cs, "double", PerfTone::Bad));
        QVERIFY(hasCheck(cs, "materialtest", PerfTone::Warn));
        d.parts = {part("res-762", "R1", 2, 3), part("res-762", "R2", 2, 5)};
        d.wires = {wire("a", true, {{0, 8}, {6, 8}}), wire("b", true, {{3, 6}, {3, 11}})};
        cs = perfChecks(d, o);
        QVERIFY(!hasCheck(cs, "double", PerfTone::Bad));
        QVERIFY(hasCheck(cs, "short", PerfTone::Bad));
        d.wires[1].solder = false;   // different sides: no short
        QVERIFY(!hasCheck(perfChecks(d, o), "short", PerfTone::Bad));
        d.wires = {wire("a", true, {{0, 8}, {6, 8}}), wire("b", true, {{3, 8}, {3, 11}})};   // T at an end: a junction
        QVERIFY(!hasCheck(perfChecks(d, o), "short", PerfTone::Bad));
        d.wires = {wire("a", true, {{0, 3}, {4, 3}})};   // over pin 1 of R1 (C4) without ending there
        QVERIFY(hasCheck(perfChecks(d, o), "over-pad", PerfTone::Bad));
        d.wires = {};
        d.parts = {part("res-762", "R1", 16, 3)};        // pin 2 at column 19 of 18
        QVERIFY(hasCheck(perfChecks(d, o), "outside", PerfTone::Bad));
        d.parts = {part("res-762", "R1", 2, 0)};
        QVERIFY(hasCheck(perfChecks(d, o), "edge", PerfTone::Warn));
        d.parts = {part("elko-508", "C1", 2, 4), part("res-762", "R1", 3, 5)};
        QVERIFY(hasCheck(perfChecks(d, o), "overlap", PerfTone::Warn));
        d.parts = {};
        d.labels = {{"t", "klein", {25, 35}, 0.5, false}};
        QVERIFY(hasCheck(perfChecks(d, o), "text-small", PerfTone::Warn));
        NEAR(minTextHeight(0.15), 1.2, 1e-9);
        d.labels = {};
        QVERIFY(!hasCheck(perfChecks(d, o, Pt{185, 197.5}), "bed", PerfTone::Bad));
        QVERIFY(hasCheck(perfChecks(d, o, Pt{9999, 0}), "bed", PerfTone::Bad));
        d.parts = {part("res-762", "R1", 2, 3), part("led-3", "LED1", 2, 8)};
        d.wires = {wire("a", true, {{5, 3}, {5, 6}})};
        bool loose = false;
        for (const PerfCheck& c : perfChecks(d, o)) if (c.id == "loose") { loose = true; QVERIFY2(c.text.contains("R1 (1)") && c.text.contains("LED1 (2)"), qPrintable(c.text)); }
        QVERIFY(loose);
    }
    void partsList() {
        PerfDesign d;
        d.board = board5070();
        d.parts = {part("led-3", "LED1", 2, 10), part("res-762", "R2", 2, 5), part("res-762", "R1", 2, 3), part("dip8", "U1", 8, 4)};
        d.parts[3].value = "NE555";
        const auto rows = bom(d);
        QCOMPARE(rows.size(), size_t(3));
        QCOMPARE(rows[0].part, QStringLiteral("Widerstand 7,62 mm"));
        QCOMPARE(rows[0].refs, (QStringList{"R1", "R2"}));
        QCOMPARE(rows[0].count, 2);
        QCOMPARE(rows[2].refs, QStringList{"LED1"});
        const QByteArray raw = bomCsv(d);
        QVERIFY(raw.startsWith(QByteArray::fromHex("EFBBBF")));
        const QString csv = QString::fromUtf8(raw.mid(3));
        QVERIFY(csv.startsWith("Referenz;Wert;Bauteil;Anzahl\r\n"));
        QVERIFY(csv.contains("\"R1, R2\";10k;Widerstand 7,62 mm;2\r\n") || csv.contains("R1, R2;10k;Widerstand 7,62 mm;2\r\n"));
        const auto order = assemblyOrder(d);
        QCOMPARE(d.parts[size_t(order[0])].ref, QStringLiteral("R1"));
        QCOMPARE(d.parts[size_t(order.back())].ref, QStringLiteral("LED1"));
    }
    void fileRoundTrip() {
        PerfDesign d;
        d.title = "Blinker";
        d.board = PerfBoard::templates()[4];
        d.board.padDia = 1.7;
        d.parts = {part("dip8", "U1", 4, 4, 3), part("led-5", "LED1", 10, 12, 1)};
        d.parts[1].value = "grün";
        d.wires = {wire("w1", true, route({4, 4}, {10, 12})), wire("w2", false, {{1, 1}, {1, 9}})};
        d.labels = {{"t1", "+5 V", {12.5, 7.25}, 1.8, true}};
        d.holeNumbers = true;
        d.markValues = true;
        const PerfDesign e = perfFromJson(perfToJson(d));
        QCOMPARE(e.title, d.title);
        QCOMPARE(e.board.cols, 24); QCOMPARE(e.board.rows, 32);
        NEAR(e.board.padDia, 1.7, 1e-12);
        QCOMPARE(e.parts.size(), size_t(2));
        QCOMPARE(e.parts[0].rot, 3);
        QCOMPARE(e.parts[1].value, QStringLiteral("grün"));
        QCOMPARE(e.parts[1].at, (GridPt{10, 12}));
        QCOMPARE(e.wires.size(), size_t(2));
        QVERIFY(e.wires[0].solder && !e.wires[1].solder);
        QCOMPARE(e.wires[0].pts, d.wires[0].pts);
        QCOMPARE(e.labels[0].text, QStringLiteral("+5 V"));
        QVERIFY(e.labels[0].solder);
        QVERIFY(e.holeNumbers && e.markValues && e.markRefs);
        QCOMPARE(perfToJson(e), perfToJson(d));
        QVERIFY_THROWS_EXCEPTION(std::runtime_error, perfFromJson("{\"format\":\"lumaraster\",\"version\":9}"));
        QVERIFY_THROWS_EXCEPTION(std::runtime_error, perfFromJson("kein json"));
        QVERIFY_THROWS_EXCEPTION(std::runtime_error, perfFromJson("{\"title\":\"Projekt\"}"));
    }
    void assemblyPlan() {
        PerfDesign d;
        d.board = board5070();
        d.parts = {part("dip8", "U1", 6, 6)};
        d.wires = {wire("w", true, {{6, 6}, {6, 12}})};
        const QByteArray svg = assemblySvg(d);
        QVERIFY(svg.contains("width=\"50.000mm\" height=\"70.000mm\""));
        QVERIFY(svg.contains(">U1 NE555</text>"));
        const QImage png = QImage::fromData(assemblyPng(d, 10));
        QCOMPARE(png.width(), 500);
        QCOMPARE(png.height(), 700);
        QVERIFY(!assemblySvg(d, true).contains("U1"));
    }
};

QTEST_MAIN(TestPerfboard)
#include "test_perfboard.moc"
