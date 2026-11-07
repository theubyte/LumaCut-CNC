/**
 * Platine core: Gerber, Excellon, layer detection, board, clearance, plan (raster, isolation, film), mirroring,
 * fiducials, document. Same cases as the Tauri pcb.test.ts, plus the files in tests/pcb.
 */
#include "core/pcb/board.h"
#include "core/pcb/job.h"

#include <QElapsedTimer>
#include <QFile>
#include <QtTest>
#include <cmath>
#include <numbers>
#include <set>

using namespace lumacut;
using namespace lumacut::pcb;

namespace {
constexpr double PI = std::numbers::pi;

#define NEAR(a, b, tol) QVERIFY2(std::abs(double(a) - double(b)) <= (tol), qPrintable(QStringLiteral("%1 statt %2").arg(double(a), 0, 'g', 10).arg(double(b), 0, 'g', 10)))

GerberResult G(const std::string& body, const std::string& fs = "%FSLAX46Y46*%\n%MOMM*%\n") {
    const std::string t = fs + body + "\nM02*\n";
    return parseGerber(t);
}
QByteArray fileBody(const std::string& body) { return QByteArray::fromStdString("%FSLAX46Y46*%\n%MOMM*%\n" + body + "\nM02*\n"); }
QByteArray fixture(const QString& name) {
    QFile f(QStringLiteral(LUMACUT_PCB_DIR "/") + name);
    if (!f.open(QIODevice::ReadOnly)) qFatal("Datei fehlt: %s", qPrintable(name));
    return f.readAll();
}
Box box(const std::optional<Box>& b) {
    if (!b) throw std::runtime_error("keine Grenzen");
    return *b;
}
std::string pad(int x, int y) { return "X" + std::to_string(x) + "000000Y" + std::to_string(y) + "000000D03*"; }
const PlanLayer* layerOf(const Plan&& p, ProcessKey k, bool rest = false) = delete;
const PlanLayer* layerOf(const Plan& p, ProcessKey k, bool rest = false) {
    for (const PlanLayer& l : p.layers) if (l.key == k && l.name.endsWith(QLatin1String(" Rest")) == rest) return &l;
    return nullptr;
}
double maxX(const Polys& ps) { double m = -1e300; for (const Poly& p : ps) for (const Pt& q : p) m = std::max(m, q.x); return m; }
double minX(const Polys& ps) { double m = 1e300; for (const Poly& p : ps) for (const Pt& q : p) m = std::min(m, q.x); return m; }
Board twoPads() {
    std::vector<PcbFile> files = {readPcbFile("c.GTL", fixture("zwei_pads.GTL")), readPcbFile("c.GKO", fixture("zwei_pads.GKO")),
                                  readPcbFile("c.DRL", fixture("zwei_pads.DRL"))};
    return *buildBoard(files);
}
JobSettings S() {
    JobSettings s = defaultSettings();
    s.beamMm = 0.2;
    s.overlapPct = 50;
    s.fiducials = 0;
    return s;
}
std::vector<PcbFile> example() {
    std::vector<PcbFile> out;
    for (const auto& [n, t] : exampleBoardFiles()) out.push_back(readPcbFile(n, t));
    return out;
}
}  // namespace

class TestPcb : public QObject {
    Q_OBJECT
private slots:
    // ---- Gerber: formats and units ----
    void formatMm46() {
        const auto g = G("%ADD10C,1*%\nD10*\nX10000000Y-5000000D03*");
        NEAR(box(g.bounds).minX, 9.5, 1e-3);
        NEAR(box(g.bounds).maxY, -4.5, 1e-3);
    }
    void inchConverted() {
        const auto g = parseGerber("%FSLAX24Y24*%\n%MOIN*%\n%ADD10C,0.1*%\nD10*\nX10000Y0D03*\nM02*\n");
        QVERIFY(g.inch);
        NEAR(box(g.bounds).minX, 25.4 - 1.27, 2e-3);
        NEAR(g.area, PI * 1.27 * 1.27, 0.02);
    }
    void trailingAndIncremental() {
        const auto t = parseGerber("%FSTAX24Y24*%\n%MOMM*%\n%ADD10R,2X2*%\nD10*\nX1Y1D03*\nM02*\n");
        NEAR(box(t.bounds).minX, 9, 1e-3);
        const auto i = parseGerber("%FSLIX24Y24*%\n%MOMM*%\n%ADD10R,2X2*%\nD10*\nX100000Y0D03*\nX100000Y0D03*\nM02*\n");
        NEAR(box(i.bounds).maxX, 21, 1e-3);
    }

    // ---- Apertures ----
    void apertureAreas() {
        NEAR(G("%ADD10C,2*%\nD10*\nX0Y0D03*").area, PI, 0.01);
        NEAR(G("%ADD10R,3X2*%\nD10*\nX0Y0D03*").area, 6, 1e-6);
        NEAR(G("%ADD10O,4X2*%\nD10*\nX0Y0D03*").area, 2 * 2 + PI, 0.01);
        const auto hex = G("%ADD10P,2X6*%\nD10*\nX0Y0D03*");
        NEAR(hex.area, 3 * std::sqrt(3.0) / 2, 1e-3);
        NEAR(box(hex.bounds).maxX, 1, 1e-3);
        QCOMPARE(G("%ADD10C,2*%\nD10*\nX0Y0D03*\nX5000000Y0D03*").flashes.size(), size_t(2));
    }
    void apertureHole() {
        NEAR(G("%ADD10C,4X2*%\nD10*\nX0Y0D03*").area, PI * (4 - 1), 0.02);
        NEAR(G("%ADD10R,4X4X2*%\nD10*\nX0Y0D03*").area, 16 - PI, 0.02);
    }
    void roundLine() {
        const auto g = G("%ADD10C,0.5*%\nD10*\nX0Y0D02*\nX10000000Y0D01*");
        NEAR(g.area, 10 * 0.5 + PI * 0.25 * 0.25, 0.01);
        NEAR(*g.minStrokeWidth, 0.5, 1e-9);
        QCOMPARE(g.strokes.size(), size_t(1));
    }
    void rectLineIsHull() { NEAR(G("%ADD10R,1X1*%\nD10*\nX0Y0D02*\nX5000000Y0D01*").area, 6, 1e-6); }

    // ---- Arcs ----
    void fullCircleG75() {
        const auto g = G("G75*\n%ADD10C,0.2*%\nD10*\nX1000000Y0D02*\nG03*\nX1000000Y0I-1000000J0D01*");
        NEAR(g.area, PI * (1.1 * 1.1 - 0.9 * 0.9), 0.01);
        NEAR(box(g.bounds).minX, -1.1, 1e-2);
    }
    void arcDirections() {
        const auto ccw = G("G75*\n%ADD10C,0.1*%\nD10*\nX1000000Y0D02*\nG03*\nX-1000000Y0I-1000000J0D01*");
        const auto cw = G("G75*\n%ADD10C,0.1*%\nD10*\nX1000000Y0D02*\nG02*\nX-1000000Y0I-1000000J0D01*");
        NEAR(box(ccw.bounds).maxY, 1.05, 0.01);
        NEAR(box(cw.bounds).minY, -1.05, 0.01);
        NEAR(box(cw.bounds).maxY, 0.05, 0.01);
    }
    void quarterG74() {
        const auto g = G("G74*\n%ADD10C,0.1*%\nD10*\nX1000000Y0D02*\nG03*\nX0Y1000000I1000000J0D01*");
        NEAR(box(g.bounds).maxX, 1.05, 0.01);
        NEAR(box(g.bounds).maxY, 1.05, 0.01);
        double worst = 0;
        for (const Pt& p : g.strokes[0].pts) worst = std::max(worst, std::abs(std::hypot(p.x, p.y) - 1));
        NEAR(worst, 0, 1e-3);
    }
    void badArcCentreWarned() {
        const auto g = G("G75*\n%ADD10C,0.1*%\nD10*\nX1000000Y0D02*\nG03*\nX0Y1000000I-5000000J0D01*");
        QVERIFY(g.warnings.join(' ').contains("Mittelpunkt"));
    }
    void regionDisc() {
        const auto g = G("G75*\nG36*\nX2000000Y0D02*\nG03*\nX2000000Y0I-2000000J0D01*\nG37*");
        NEAR(g.area, PI * 4, 0.02);
        QCOMPARE(g.regionCount, 1);
    }

    // ---- Regions and polarity ----
    void regionTwoContours() {
        const auto g = G("G36*\nX0Y0D02*\nG01*\nX1000000Y0D01*\nX1000000Y1000000D01*\nX0Y0D01*\nX5000000Y0D02*\nX6000000Y0D01*\nX6000000Y1000000D01*\nX5000000Y0D01*\nG37*");
        NEAR(g.area, 1, 1e-6);
        QCOMPARE(g.polys.size(), size_t(2));
    }
    void regionKeyhole() {
        const auto g = G("G36*\nX0Y0D02*\nG01*\nX4000000Y0D01*\nX4000000Y4000000D01*\nX0Y4000000D01*\nX0Y0D01*\nX1000000Y1000000D01*\nX1000000Y3000000D01*\nX3000000Y3000000D01*\nX3000000Y1000000D01*\nX1000000Y1000000D01*\nX0Y0D01*\nG37*");
        NEAR(g.area, 16 - 4, 1e-3);
        QVERIFY(!pointInPolys(2, 2, g.polys));
        QVERIFY(pointInPolys(0.5, 2, g.polys));
    }
    void polarity() {
        const std::string sq = "G36*\nX0Y0D02*\nG01*\nX10000000Y0D01*\nX10000000Y10000000D01*\nX0Y10000000D01*\nX0Y0D01*\nG37*";
        const auto g = G(sq + "\n%LPC*%\n%ADD10C,4*%\nD10*\nX5000000Y5000000D03*\n%LPD*%\n%ADD11C,2*%\nD11*\nX5000000Y5000000D03*");
        NEAR(g.area, 100 - PI * 4 + PI, 0.03);
        QVERIFY(pointInPolys(5, 5, g.polys));
        QVERIFY(!pointInPolys(5, 6.5, g.polys));
        QVERIFY(pointInPolys(1, 1, g.polys));
        const auto a = G("%LPC*%\n%ADD10C,4*%\nD10*\nX5000000Y5000000D03*\n%LPD*%\n" + sq);
        NEAR(a.area, 100, 1e-3);
    }
    void stepRepeat() {
        const auto g = G("%SRX3Y2I10J5*%\n%ADD10R,1X1*%\nD10*\nX0Y0D03*\n%SR*%");
        NEAR(g.area, 6, 1e-6);
        NEAR(box(g.bounds).maxX, 20.5, 1e-3);
        NEAR(box(g.bounds).maxY, 5.5, 1e-3);
        QCOMPARE(g.flashes.size(), size_t(6));
    }
    void warnings() {
        QVERIFY(G("%IPNEG*%\n%ADD10C,1*%\nD10*\nX0Y0D03*").warnings.join(' ').contains("IPNEG"));
        QVERIFY(G("D99*\nX0Y0D03*").warnings.join(' ').contains("D99"));
        QVERIFY_THROWS_EXCEPTION(GerberError, parseGerber("Hallo Welt"));
    }

    // ---- Macros ----
    void macroExpr() {
        const std::map<int, double> v{{1, 3}, {2, 4}};
        NEAR(evalMacroExpr("$1+2x$2", v), 11, 1e-9);
        NEAR(evalMacroExpr("($1+2)x$2", v), 20, 1e-9);
        NEAR(evalMacroExpr("-$1/2", v), -1.5, 1e-9);
        NEAR(evalMacroExpr("$1X$2-.5", v), 11.5, 1e-9);
    }
    void macroRoundRect() {
        const auto g = G("%AMRR*$4=$1-2x$3*$5=$2-2x$3*21,1,$4,$2,0,0,0*21,1,$1,$5,0,0,0*1,1,2x$3,$4/2,$5/2*1,1,2x$3,-$4/2,$5/2*1,1,2x$3,$4/2,-$5/2*1,1,2x$3,-$4/2,-$5/2*%\n%ADD10RR,4X2X0.5*%\nD10*\nX0Y0D03*");
        NEAR(g.area, 4 * 2 - (4 - PI) * 0.25, 0.01);
        NEAR(box(g.bounds).maxX, 2, 1e-3);
    }
    void macroExposureOff() { NEAR(G("%AMLOCH*21,1,4,4,0,0,0*1,0,2,0,0*%\n%ADD10LOCH*%\nD10*\nX0Y0D03*").area, 16 - PI, 0.02); }
    void macroPrimitives() {
        const auto d = G("%AMD*21,1,4,2,0,0,90*%\n%ADD10D*%\nD10*\nX0Y0D03*");
        NEAR(box(d.bounds).maxY, 2, 1e-3);
        NEAR(box(d.bounds).maxX, 1, 1e-3);
        NEAR(G("%AMU*4,1,3,0,0,2,0,2,2,0,0,0*%\n%ADD10U*%\nD10*\nX0Y0D03*").area, 2, 1e-3);
        NEAR(G("%AML*20,1,1,0,0,5,0,0*%\n%ADD10L*%\nD10*\nX0Y0D03*").area, 5, 1e-3);
        NEAR(G("%AMP*5,1,4,0,0,2,0*%\n%ADD10P*%\nD10*\nX0Y0D03*").area, 2, 1e-3);
        const auto ll = G("%AMQ*22,1,2,1,1,1,0*%\n%ADD10Q*%\nD10*\nX0Y0D03*");
        NEAR(box(ll.bounds).minX, 1, 1e-3);
        NEAR(box(ll.bounds).maxY, 2, 1e-3);
    }
    void macroThermal() {
        const auto g = G("%AMT*7,0,0,4,2,0.5,0*%\n%ADD10T*%\nD10*\nX0Y0D03*");
        QCOMPARE(g.polys.size(), size_t(4));
        NEAR(g.area, PI * (4 - 1) - 4 * 0.5 * 1, 0.05);
        QVERIFY(!pointInPolys(1.5, 0, g.polys));
        QVERIFY(pointInPolys(1.06, 1.06, g.polys));
    }
    void macroInch() {
        NEAR(parseGerber("%FSLAX24Y24*%\n%MOIN*%\n%AMR1*21,1,$1,$1,0,0,0*%\n%ADD10R1,1*%\nD10*\nX0Y0D03*\nM02*\n").area, 25.4 * 25.4, 0.01);
    }
    void kicadRoundRectFile() {
        const QByteArray t = fixture("kicad-F_Cu.gbr");
        const auto g = parseGerber(std::string_view(t.constData(), size_t(t.size())));
        QVERIFY2(g.warnings.isEmpty(), qPrintable(g.warnings.join(" | ")));
        NEAR(g.area, 2.5 * 1.5 - (4 - PI) * 0.0625, 0.01);
        NEAR(box(g.bounds).maxX, 11.25, 2e-3);
        QCOMPARE(g.fileFunction, QStringLiteral("Copper,L1,Top"));
        QCOMPARE(classifyLayer("egal.gbr", std::string_view(t.constData(), size_t(t.size()))), LayerKind::CopperTop);
    }
    void oldExports() {
        const auto g = parseGerber("%FSLAX24Y24*%\n%MOMM*%\nG04 Fuellung 50% *\n%ADD10C,1*%\nG54D10*\nG01X0Y0D02*\nX100000D01*\nX200000*\nM02*\n");
        NEAR(box(g.bounds).maxX, 20.5, 2e-3);
        NEAR(g.area, 20 + PI * 0.25, 0.02);
    }

    // ---- Excellon ----
    void excellonMetric() {
        const auto d = parseExcellon("M48\nMETRIC,TZ\nT1C0.800\nT2C3.0\n%\nG90\nG05\nT1\nX10.5Y20.25\nX11Y21\nT2\nX0Y0\nM30\n");
        QCOMPARE(d.hits.size(), size_t(3));
        NEAR(d.hits[0].x, 10.5, 1e-9); NEAR(d.hits[0].y, 20.25, 1e-9); NEAR(d.hits[0].dia, 0.8, 1e-9);
        NEAR(d.hits[2].dia, 3, 1e-9);
    }
    void excellonInchTZ() {
        const auto d = parseExcellon("M48\nINCH,TZ\nT1C0.0320\n%\nT1\nX10000Y5000\nM30\n");
        NEAR(d.hits[0].x, 25.4, 1e-6); NEAR(d.hits[0].y, 12.7, 1e-6); NEAR(d.hits[0].dia, 0.8128, 1e-6);
    }
    void excellonInchLZ() {
        const auto d = parseExcellon("M48\nINCH,LZ\nT1C0.03\n%\nT1\nX01Y005\nM30\n");
        NEAR(d.hits[0].x, 25.4, 1e-6); NEAR(d.hits[0].y, 12.7, 1e-6);
    }
    void excellonFormats() {
        const QByteArray t = fixture("altium_zoll.TXT");
        const auto a = parseExcellon(std::string_view(t.constData(), size_t(t.size())));
        NEAR(a.hits[0].x, 25.4, 1e-6);
        const auto b = parseExcellon("M48\nMETRIC,LZ,000.00\nT1C1\n%\nT1\nX01000Y00500\nM30\n");
        NEAR(b.hits[0].x, 10, 1e-6); NEAR(b.hits[0].y, 5, 1e-6);
    }
    void excellonModalAndSlots() {
        const auto d = parseExcellon("M48\nMETRIC\nT1C1.0\n%\nT1\nX1.0Y2.0\nY3.0\nX5.0Y5.0G85X8.0Y5.0\nM30\n");
        QCOMPARE(d.hits.size(), size_t(2));
        NEAR(d.hits[1].x, 1, 1e-9); NEAR(d.hits[1].y, 3, 1e-9);
        QCOMPARE(d.slotHoles.size(), size_t(1));
        NEAR(d.slotHoles[0].b.x, 8, 1e-9); NEAR(d.slotHoles[0].b.y, 5, 1e-9);
        const auto r = parseExcellon("M48\nMETRIC\nT1C1.0\n%\nT1\nG00X1.0Y1.0\nM15\nG01X4.0Y1.0\nM16\nG05\nX9.0Y9.0\nM30\n");
        QCOMPARE(r.slotHoles.size(), size_t(1));
        QCOMPARE(r.hits.size(), size_t(1));
    }

    // ---- Layer detection ----
    void classify_data() {
        QTest::addColumn<QString>("name");
        QTest::addColumn<QString>("kind");
        const std::pair<const char*, const char*> cases[] = {
            {"board.GTL", "copper-top"}, {"board.GBL", "copper-bottom"}, {"board.GTS", "mask-top"}, {"board.GBS", "mask-bottom"},
            {"board.GTO", "silk-top"}, {"board.GBO", "silk-bottom"}, {"board.GKO", "outline"}, {"board.GM1", "outline"},
            {"board.GML", "outline"}, {"board.G1", "copper-inner"}, {"board.GTP", "paste-top"}, {"board.TXT", "drill"},
            {"board.DRL", "drill"}, {"proj-F_Cu.gbr", "copper-top"}, {"proj-B_Cu.gbr", "copper-bottom"}, {"proj-F.Cu.gbr", "copper-top"},
            {"proj-F_Mask.gbr", "mask-top"}, {"proj-B_Mask.gbr", "mask-bottom"}, {"proj-F_Silkscreen.gbr", "silk-top"},
            {"proj-B_SilkS.gbr", "silk-bottom"}, {"proj-Edge_Cuts.gbr", "outline"}, {"proj-F_Paste.gbr", "paste-top"},
            {"proj-In1_Cu.gbr", "copper-inner"}, {"proj-PTH.drl", "drill"}, {"proj-NPTH.drl", "drill"}, {"proj-job.gbrjob", "other"},
            {"Gerber_TopLayer.GTL", "copper-top"}, {"Gerber_BottomSolderMaskLayer.GBS", "mask-bottom"},
            {"Gerber_BoardOutlineLayer.GKO", "outline"}, {"Drill_PTH_Through.DRL", "drill"}, {"eagle.cmp", "copper-top"},
            {"eagle.sol", "copper-bottom"}, {"eagle.stc", "mask-top"}, {"eagle.plc", "silk-top"}, {"eagle.dim", "outline"},
            {"liesmich.pdf", "other"},
        };
        for (const auto& [n, k] : cases) QTest::newRow(n) << QString::fromLatin1(n) << QString::fromLatin1(k);
    }
    void classify() {
        QFETCH(QString, name);
        QFETCH(QString, kind);
        QCOMPARE(layerKey(classifyLayer(name)), kind);
    }
    void classifyByContent() {
        QCOMPARE(classifyLayer("egal.gbr", "%TF.FileFunction,Copper,L2,Bot*%\n"), LayerKind::CopperBottom);
        QCOMPARE(classifyLayer("egal.gbr", "%TF.FileFunction,Soldermask,Top*%\n"), LayerKind::MaskTop);
        QCOMPARE(classifyLayer("egal.gbr", "%TF.FileFunction,Profile,NP*%\n"), LayerKind::Outline);
        QCOMPARE(classifyLayer("x.gbr", "G04 #@! TF.FileFunction,Soldermask,Bot*\n"), LayerKind::MaskBottom);
        QCOMPARE(classifyLayer("bohr-ohne-endung", "M48\nMETRIC\n"), LayerKind::Drill);
    }

    // ---- Example board ----
    void exampleBoard() {
        const auto files = example();
        QCOMPARE(files.size(), size_t(7));
        const LayerKind want[] = {LayerKind::CopperTop, LayerKind::CopperBottom, LayerKind::MaskTop, LayerKind::MaskBottom,
                                  LayerKind::SilkTop, LayerKind::Outline, LayerKind::Drill};
        for (size_t i = 0; i < files.size(); ++i) {
            QCOMPARE(files[i].kind, want[i]);
            QVERIFY2(files[i].error.isEmpty(), qPrintable(files[i].error));
            const QStringList w = files[i].gerber ? files[i].gerber->warnings : files[i].drill->warnings;
            QVERIFY2(w.isEmpty(), qPrintable(files[i].name + ": " + w.join(" | ")));
        }
        const Board b = *buildBoard(files);
        QVERIFY(b.outlineFromFile);
        QCOMPARE(b.outline.size(), size_t(1));
        NEAR(b.bounds.width(), 60, 0.01);
        NEAR(b.bounds.height(), 40, 0.01);
        NEAR(std::abs(polysArea(b.outline)), 60 * 40 - (4 - PI) * 4, 0.1);
        QCOMPARE(b.drills.size(), size_t(26));
        QCOMPARE(std::count_if(b.drills.begin(), b.drills.end(), [](const DrillHit& d) { return std::abs(d.dia - 0.8) < 1e-9; }), 20);
        QCOMPARE(std::count_if(b.drills.begin(), b.drills.end(), [](const DrillHit& d) { return std::abs(d.dia - 3.2) < 1e-9; }), 4);
        const SideArt& top = *b.copper[0];
        NEAR(*top.minStroke, 0.6, 1e-6);
        QVERIFY(top.area > 100 && top.area < 400);
        QVERIFY(pointInPolys(26.19, 23.81, top.polys));
        const SideArt& bot = *b.copper[1];
        QVERIFY(bot.area > 1500 && bot.area < 2184);
        QVERIFY(!pointInPolys(4, 4, bot.polys));
        QVERIFY(pointInPolys(15, 30, bot.polys));
        QVERIFY(pointInPolys(26.19, 21.27, bot.polys));
        QVERIFY(!pointInPolys(26.19 + 1.1, 21.27 + 0.3, bot.polys));
        const auto ct = minClearance(top.polys), cb = minClearance(bot.polys);
        QVERIFY(ct && ct->mm > 0.25);
        QVERIFY(cb && cb->mm > 0.25);
        qInfo("Beispiel: Kupfer oben %.1f mm2, unten %.1f mm2, Abstand oben %.3f mm, unten %.3f mm", top.area, bot.area, ct->mm, cb->mm);
    }

    // ---- Clearance, outline ----
    void clearance() {
        NEAR(minClearance(G("%ADD10R,2X2*%\nD10*\nX0Y0D03*\nX2500000Y0D03*").polys)->mm, 0.5, 1e-3);
        QVERIFY(!minClearance(G("%ADD10C,4X3.9*%\nD10*\nX0Y0D03*").polys));
        QVERIFY(!minClearance(G("%ADD10R,2X2*%\nD10*\nX0Y0D03*\nX9000000Y0D03*").polys, 2));
        const Polys loops = stitchLoops({{{0, 0}, {5, 0}}, {{5, 5}, {5, 0}}, {{5, 5}, {0, 5}}, {{0, 5}, {0, 0}}});
        QCOMPARE(loops.size(), size_t(1));
        NEAR(std::abs(polysArea(loops)), 25, 1e-6);
    }

    // ---- Plan ----
    void interval() {
        NEAR(lineInterval(0.2, 50), 0.1, 1e-9);
        NEAR(lineInterval(0.04, 50), 0.03, 1e-9);
        NEAR(buildPlan(twoPads(), S()).layers[0].intervalMm, 0.1, 1e-9);
    }
    void rasterNegative() {
        JobSettings s = S();
        s.drillMarks = false;
        const Plan plan = buildPlan(twoPads(), s);
        const PlanLayer* r = layerOf(plan, ProcessKey::Resist);
        QVERIFY(r);
        QCOMPARE(r->mode, LayerMode::Fill);
        QCOMPARE(r->process, QStringLiteral("Gravieren"));
        const double edgeArea = 21 * 11 - (4 - PI) * 0.25;
        const double padArea = 2 * (2.2 * 2.2 - (4 - PI) * 0.01);
        NEAR(polysArea(r->polys), edgeArea - padArea, 0.05);
        QVERIFY(!pointInPolys(5, 5, r->polys));
        QVERIFY(pointInPolys(10, 5, r->polys));
        for (const Poly& p : r->polys) QVERIFY(p.front() == p.back());
    }
    void isolation() {
        JobSettings s = S();
        s.method = ResistMethod::Isolation;
        s.passes = 2;
        s.drillMarks = false;
        const Plan plan = buildPlan(twoPads(), s);
        const PlanLayer* r = layerOf(plan, ProcessKey::Resist);
        QCOMPARE(r->mode, LayerMode::Line);
        QCOMPARE(r->process, QStringLiteral("Markieren"));
        QCOMPARE(r->polys.size(), size_t(4));   // two pads, two lines each
        std::vector<double> xs;
        for (const Poly& p : r->polys) xs.push_back(maxX({p}));
        std::sort(xs.begin(), xs.end());
        NEAR(xs[0], 6.1, 1e-3); NEAR(xs[1], 6.2, 1e-3); NEAR(xs[2], 16.1, 1e-3); NEAR(xs[3], 16.2, 1e-3);
        QVERIFY(!layerOf(plan, ProcessKey::Resist, true));
    }
    void isolationSpacingAndOffset() {
        JobSettings s = S();
        s.method = ResistMethod::Isolation;
        s.passes = 3;
        s.passSpacingMm = 0.25;
        s.isolationOffsetMm = 0.05;
        s.drillMarks = false;
        const Plan plan = buildPlan(twoPads(), s);
        const PlanLayer* r = layerOf(plan, ProcessKey::Resist);
        QCOMPARE(r->polys.size(), size_t(6));
        std::vector<double> xs;
        for (const Poly& p : r->polys) xs.push_back(maxX({p}));
        std::sort(xs.begin(), xs.end());
        // pad edge at 6, first line at beam/2 + offset = 0.15, then +0.25 each
        NEAR(xs[0], 6.15, 1e-3); NEAR(xs[1], 6.40, 1e-3); NEAR(xs[2], 6.65, 1e-3);
    }
    void isolationRest() {
        JobSettings s = S();
        s.method = ResistMethod::Isolation;
        s.passes = 2;
        s.removeRest = true;
        s.drillMarks = false;
        const Plan plan = buildPlan(twoPads(), s);
        const PlanLayer* rest = layerOf(plan, ProcessKey::Resist, true);
        QVERIFY(rest);
        QCOMPARE(rest->mode, LayerMode::Fill);
        QVERIFY(!pointInPolys(6.1, 5, rest->polys));
        QVERIFY(pointInPolys(10, 5, rest->polys));
    }
    void isolationInsideOutline() {
        std::vector<PcbFile> f = {readPcbFile("c.GTL", fileBody("%ADD10R,2X2*%\nD10*\n" + pad(1, 5))), readPcbFile("c.GKO", fixture("zwei_pads.GKO"))};
        JobSettings s = S();
        s.method = ResistMethod::Isolation;
        s.passes = 8;
        s.drillMarks = false;
        const Plan plan = buildPlan(*buildBoard(f), s);
        const PlanLayer* r = layerOf(plan, ProcessKey::Resist);
        QVERIFY(minX(r->polys) >= -0.5 - 1e-3);
    }
    void exposeFilm() {
        JobSettings s = S();
        s.method = ResistMethod::Expose;
        const Plan plan = buildPlan(twoPads(), s);
        const PlanLayer* r = layerOf(plan, ProcessKey::Resist);
        QVERIFY(!pointInPolys(10, 5, r->polys));
        QVERIFY(pointInPolys(5.5, 5.5, r->polys));
        QVERIFY(!pointInPolys(5, 5, r->polys));
        QVERIFY(!layerOf(plan, ProcessKey::Drill));
    }
    void drillMarks() {
        JobSettings s = S();
        s.drillMarkMm = 0.5;
        const Plan pd = buildPlan(twoPads(), s);
        const PlanLayer* dot = layerOf(pd, ProcessKey::Drill);
        NEAR(polysArea(dot->polys), 2 * PI * 0.0625, 0.01);
        QVERIFY(pointInPolys(5, 5, dot->polys));
        QVERIFY(!pointInPolys(5.5, 5, dot->polys));
        s.drillMarkMm = 5;
        const Plan pbig = buildPlan(twoPads(), s);
        QVERIFY(maxX(layerOf(pbig, ProcessKey::Drill)->polys) - 15 <= 0.41);
        s.drillCross = true;
        s.drillMarkMm = 0.6;
        const Plan pc = buildPlan(twoPads(), s);
        const PlanLayer* cross = layerOf(pc, ProcessKey::Drill);
        QVERIFY(pointInPolys(5.25, 5, cross->polys));
        QVERIFY(!pointInPolys(5.25, 5.25, cross->polys));
    }
    void fiducialsMatchWhenTurned() {
        const Board b = twoPads();
        for (int count : {2, 4}) {
            JobSettings s = S();
            s.fiducials = count;
            const Plan plan = buildPlan(b, s);
            QCOMPARE(int(plan.fiducials.size()), count);
            std::set<std::pair<long, long>> top, bot;
            for (const Pt& f : plan.fiducials) {
                const Pt a = toJob(f, plan.bounds, false), c = toJob(f, plan.bounds, true);
                top.insert({std::lround(a.x * 1000), std::lround(a.y * 1000)});
                bot.insert({std::lround(c.x * 1000), std::lround(c.y * 1000)});
            }
            QVERIFY(top == bot);
            QVERIFY(layerOf(plan, ProcessKey::Fiducial));
        }
        QVERIFY(fiducialPoints(b.bounds, 0, 3).empty());
    }
    void mirror() {
        const Plan plan = buildPlan(twoPads(), S());
        const Box& b = plan.bounds;
        QCOMPARE(toJob({5, 5}, b, false), (Pt{5, 5}));
        QCOMPARE(toJob({5, 7}, b, false), (Pt{5, 3}));
        QCOMPARE(toJob({5, 5}, b, true), (Pt{15, 5}));
        // The bottom copper of the example, mirrored, lands where the top drills are when turned over.
        const Board ex = *buildBoard(example());
        JobSettings s = S();
        s.side = Side::Bottom;
        s.mirror = true;
        const Plan pb = buildPlan(ex, s);
        const PlanLayer* r = layerOf(pb, ProcessKey::Resist);
        const Pt hole = toJob({4, 4}, pb.bounds, true);   // mounting hole bottom left becomes bottom right
        NEAR(hole.x, pb.bounds.maxX - 4, 1e-9);
        NEAR(hole.y, pb.bounds.maxY - 4, 1e-9);
        QVERIFY(r);
    }
    void checks() {
        std::vector<PcbFile> f = {readPcbFile("t.GTL", fileBody("%ADD10C,0.1*%\n%ADD12R,2X2*%\nD12*\nX0Y0D03*\nX2100000Y0D03*\nD10*\nX0Y5000000D02*\nX5000000Y5000000D01*")),
                                  readPcbFile("c.GKO", fixture("zwei_pads.GKO"))};
        const Board tight = *buildBoard(f);
        JobSettings s = S();
        s.beamMm = 0.15;
        const auto find = [](const std::vector<DesignCheck>& cs, const char* id) { for (const auto& c : cs) if (c.id == QLatin1String(id)) return c.tone; return Tone::Ok; };
        const Pt origin{100, 100};
        auto cs = designChecks(designFacts(tight, Side::Top), s, buildPlan(tight, s), origin);
        QCOMPARE(find(cs, "clearance"), Tone::Bad);
        QCOMPARE(find(cs, "trace"), Tone::Bad);
        s.beamMm = 0.05;
        QCOMPARE(find(designChecks(designFacts(tight, Side::Top), s, buildPlan(tight, s), origin), "clearance"), Tone::Ok);
        JobSettings b = S();
        b.side = Side::Bottom;
        b.mirror = false;
        const Board ex = twoPads();
        const auto ids = designChecks(designFacts(ex, Side::Bottom), b, buildPlan(ex, b), {9999, 0});
        QStringList list;
        for (const auto& c : ids) list << c.id;
        QVERIFY(list.contains("bed"));
        QVERIFY(list.contains("mirror"));
    }
    void startValues() {
        const JobSettings s = defaultSettings();
        for (double p : s.power) QVERIFY(p >= Limits::MIN_RELIABLE_POWER_PCT);
    }
    void estimate() {
        PlanLayer l;
        l.polys = {{{0, 0}, {10, 0}, {10, 10}, {0, 10}, {0, 0}}};
        l.intervalMm = 0.1;
        l.speed = 600;
        l.mode = LayerMode::Fill;
        NEAR(estimateSeconds(l, 0), 100, 1.5);
        l.mode = LayerMode::Line;
        NEAR(estimateSeconds(l), 4, 1e-9);
    }

    // ---- Into the document ----
    void intoDocument() {
        const Board board = *buildBoard(example());
        JobSettings s = defaultSettings();
        s.mask = true;
        s.silk = true;
        s.fiducials = 4;
        const Plan plan = buildPlan(board, s);
        Document doc;
        const QStringList ids = applyPlanToDoc(doc, plan, s, Stage::Resist, 1, {50, 60});
        QCOMPARE(doc.plateCount, 2);
        QStringList names;
        for (const Layer& l : doc.layers) names << l.name;
        for (const char* n : {"Gravieren", "Linie", "Schneiden", "Platine Ätzresist", "Platine Bohrmarken", "Platine Passmarken", "Platine Umriss", "Platine Lötstopp", "Platine Beschriftung"})
            QVERIFY2(names.contains(QString::fromUtf8(n)), n);
        QCOMPARE(qsizetype(doc.elements.size()), ids.size());
        std::set<QString> groups;
        for (const Element& e : doc.elements) { groups.insert(*e.groupId); QCOMPARE(e.plate, 1); QCOMPARE(e.kind, QStringLiteral("Platine")); }
        QCOMPARE(groups.size(), size_t(1));
        const auto layer = [&](const char* n) -> const Layer& { for (const Layer& l : doc.layers) if (l.name == QString::fromUtf8(n)) return l; qFatal("fehlt"); };
        QVERIFY(layer("Platine Ätzresist").output);
        QVERIFY(layer("Platine Bohrmarken").output);
        QVERIFY(layer("Platine Passmarken").output);
        QVERIFY(!layer("Platine Lötstopp").output);
        QVERIFY(!layer("Platine Beschriftung").output);
        QVERIFY(!layer("Platine Umriss").output);
        QCOMPARE(layer("Platine Ätzresist").mode, LayerMode::Fill);
        QCOMPARE(layer("Platine Umriss").mode, LayerMode::Line);
        QCOMPARE(layer("Platine Umriss").extra.value("process").toString(), QStringLiteral("Markieren"));
        NEAR(layer("Platine Ätzresist").intervalMm, lineInterval(s.beamMm, s.overlapPct), 1e-12);
        for (const Element& e : doc.elements) {
            const Layer* l = doc.layer(e.layerId);
            if (l->mode == LayerMode::Fill) for (PolyView p : e.paths) QVERIFY(isClosed(p));
            const Box w = *e.worldBounds();
            QVERIFY(w.minX >= 50 - 1e-6 && w.minY >= 60 - 1e-6);
            QVERIFY(w.maxX <= 50 + 60 + 2 * 3.5 + 1e-6 && w.maxY <= 60 + 40 + 2 * 3.5 + 1e-6);
        }
        // Round trip through the project file.
        const Document back = Document::fromJson(doc.toJson());
        QCOMPARE(back.elements.size(), doc.elements.size());
        QCOMPARE(back.elements[0].paths.pointCount(), doc.elements[0].paths.pointCount());
        // Again: layers reused, earlier PCB parts on that plate replaced; the mask stage switches outputs.
        const size_t n = doc.layers.size(), count = doc.elements.size();
        applyPlanToDoc(doc, plan, s, Stage::Mask, 1, {50, 60});
        QCOMPARE(doc.layers.size(), n);
        QCOMPARE(doc.elements.size(), count);
        QVERIFY(layer("Platine Lötstopp").output);
        QVERIFY(!layer("Platine Ätzresist").output);
    }

    // ---- Large board: on all cores, stays responsive enough ----
    void bigBoard() {
        std::string body = "%ADD10C,0.25*%\n%ADD11C,1.5*%\nG36*\nX0Y0D02*\nG01*\nX150000000Y0D01*\nX150000000Y100000000D01*\nX0Y100000000D01*\nX0Y0D01*\nG37*\n%LPC*%\n";
        const auto u = [](double v) { return std::to_string(std::lround(v * 1000000)); };
        body += "%ADD12C,2.1*%\nD12*\n";
        for (int i = 0; i < 40; ++i) for (int k = 0; k < 25; ++k) body += "X" + u(3 + i * 3.5) + "Y" + u(3 + k * 3.8) + "D03*\n";
        body += "%LPD*%\nD11*\n";
        for (int i = 0; i < 40; ++i) for (int k = 0; k < 25; ++k) body += "X" + u(3 + i * 3.5) + "Y" + u(3 + k * 3.8) + "D03*\n";
        body += "D10*\n";
        for (int i = 0; i < 39; ++i) for (int k = 0; k < 25; ++k)
            body += "X" + u(3 + i * 3.5) + "Y" + u(3 + k * 3.8) + "D02*\nX" + u(3 + (i + 1) * 3.5) + "Y" + u(3 + k * 3.8) + "D01*\n";
        QElapsedTimer t;
        t.start();
        const PcbFile f = readPcbFile("gross.GTL", fileBody(body));
        const qint64 parsed = t.elapsed();
        const Board b = *buildBoard({f});
        JobSettings s = defaultSettings();
        s.fiducials = 0;
        const Plan plan = buildPlan(b, s);
        s.method = ResistMethod::Isolation;
        const Plan iso = buildPlan(b, s);
        const qint64 planned = t.elapsed();
        designFacts(b, Side::Top);
        const qint64 checked = t.elapsed();
        QVERIFY(!plan.layers.empty() && !iso.layers.empty());
        qInfo("Große Platine 150 x 100 mm, 1000 Pads: lesen %lld ms, Raster+Isolation %lld ms, Prüfung %lld ms", parsed, planned - parsed, checked - planned);
        QVERIFY(parsed < 5000);
        QVERIFY(planned - parsed < 10000);
        QVERIFY(checked - planned < 10000);
    }
};

QTEST_GUILESS_MAIN(TestPcb)
#include "test_pcb.moc"
