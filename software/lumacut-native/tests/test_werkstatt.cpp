/**
 * Werkstatt-Generatoren mit festen Zahlen: QR gegen die Python-Bibliothek qrcode, Box-Flächen wie Android,
 * Zahnrad, Lineal, Materialtest-Raster, Seriennummern, Stempel, Rahmen und das Umsetzen in Elemente.
 */
#include "core/geometry.h"
#include "core/werkstatt/generators.h"
#include "core/werkstatt/qr.h"

#include <QtTest>
#include <cmath>
#include <numbers>
#include <set>

using namespace lumacut;
namespace W = lumacut::Werkstatt;

namespace {
/** Fake font: every character a 0.6 × 1 box, so tests need no font. */
PolySet fakeShape(const QString& text, double h, bool) {
    PolySet out;
    for (int i = 0; i < text.size(); ++i) {
        if (text[i] == QLatin1Char(' ')) continue;
        const double x = i * h * 0.7, w = h * 0.6;
        out.add({Pt{x, 0}, Pt{x + w, 0}, Pt{x + w, h}, Pt{x, h}, Pt{x, 0}});
    }
    return out;
}
double area(PolyView p) {
    double a = 0;
    for (size_t i = 1; i < p.size(); ++i) a += p[i - 1].x * p[i].y - p[i].x * p[i - 1].y;
    return std::fabs(a / 2);
}
const W::GenPart* part(const W::GenResult& r, const QString& name) {
    for (const auto& p : r.parts) if (p.name == name) return &p;
    return nullptr;
}
}  // namespace

class TestWerkstatt : public QObject {
    Q_OBJECT
private slots:
    void qrReedSolomon() {
        const std::vector<int> data{32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17};
        QCOMPARE(Qr::rsRemainder(data, Qr::rsDivisor(10)), (std::vector<int>{196, 35, 39, 119, 235, 215, 231, 226, 93, 23}));
    }
    void qrMatchesPythonQrcode() {
        const Qr::Code q = Qr::encode(QStringLiteral("https://lumacut.example/abc?x=1"));
        QCOMPARE(q.version, 3);
        QCOMPARE(q.mask, 2);
        QCOMPARE(q.size, 29);
        const char* want[] = {
            "11111110000000011011101111111", "10000010011100000000001000001", "10111010110100101000101011101",
            "10111010111110001111001011101", "10111010101101110111101011101", "10000010100111111100001000001",
            "11111110101010101010101111111", "00000000101011010000000000000", "10111110010000110100101111100",
            "01011101000100011011111110001", "11011011001010000010110110000", "00111100001100101000101011010",
            "11000010010100001101000001100", "10011100100001110011101110001", "10001010010111111110100111100",
            "00001100001001010010000100010", "10110011011000110100000001100", "10110101110110011011101110101",
            "10001110110100000110000110100", "10111100110110101000010110010", "10101010101100000111111110111",
            "00000000100001110101100011111", "11111110001111111101101011100", "10000010111101010001100010001",
            "10111010110100111100111110101", "10111010111111000101010101100", "10111010111111011011011111110",
            "10000010010001011010101011010", "11111110100111001111011100100"};
        for (int y = 0; y < q.size; ++y) {
            QByteArray row;
            for (int x = 0; x < q.size; ++x) row += q.dark(x, y) ? '1' : '0';
            QCOMPARE(row, QByteArray(want[y]));
        }
    }
    void qrFormatAndLimits() {
        for (const QString& t : {QStringLiteral("HELLO"), QStringLiteral("Ä ö ü – Straße 12345678901234567890123456789012345678901234567890")}) {
            const Qr::Code q = Qr::encode(t);
            QCOMPARE(q.size, q.version * 4 + 17);
            int f = 0;
            const int pos[15][2] = {{8, 0}, {8, 1}, {8, 2}, {8, 3}, {8, 4}, {8, 5}, {8, 7}, {8, 8}, {7, 8}, {5, 8}, {4, 8}, {3, 8}, {2, 8}, {1, 8}, {0, 8}};
            for (int i = 0; i < 15; ++i) if (q.dark(pos[i][0], pos[i][1])) f |= 1 << i;
            const int un = f ^ 0x5412;
            QCOMPARE((un >> 13) & 3, 0);          // level M
            QCOMPARE((un >> 10) & 7, q.mask);
            QVERIFY(q.dark(8, q.size - 8));
        }
        QCOMPARE(Qr::encode(QStringLiteral("HELLO")).version, 1);
        QCOMPARE(Qr::capacity(1), 14);
        QCOMPARE(Qr::capacity(10), 213);
        QVERIFY_THROWS_EXCEPTION(std::invalid_argument, Qr::encode(QString()));
        QVERIFY_THROWS_EXCEPTION(std::invalid_argument, Qr::encode(QString(500, QLatin1Char('x'))));
        const Qr::Code a = Qr::encode(QStringLiteral("A"));
        const PolySet polys = Qr::polys(a, 1);
        for (PolyView p : polys) QVERIFY(isClosed(p));
        QCOMPARE(*boundsOf(polys), (Box{0, 0, 21, 21}));
        const W::GenResult r = W::qr({QStringLiteral("x"), 1, true});
        QCOMPARE(r.parts.size(), size_t(2));
        QCOMPARE(r.parts[0].layer, QStringLiteral("Gravieren"));
        QCOMPARE(r.parts[1].layer, QStringLiteral("Schneiden"));
        QCOMPARE(boundsOf(r.parts[1].paths)->minX, -4.0);
        QCOMPARE(W::qr({QStringLiteral("x"), 0.5, false}).warnings.size(), 1);
    }

    void boxPanelsLikeAndroid() {
        W::BoxGenSpec s;
        s.w = 100; s.d = 60; s.h = 50; s.t = 3; s.finger = 10;
        const auto panels = W::boxPanels(s);
        std::set<QString> names;
        for (const auto& [n, p] : panels) { names.insert(n); QVERIFY(isClosed(p)); }
        QCOMPARE(names, (std::set<QString>{"Boden", "Hinten", "Links", "Rechts", "Vorne"}));
        const auto get = [&](const char* n) { for (const auto& [k, p] : panels) if (k == QLatin1String(n)) return p; return Poly{}; };
        QCOMPARE(boundsOf(get("Boden"))->width(), 100.0);
        QCOMPARE(boundsOf(get("Boden"))->height(), 60.0);
        QCOMPARE(boundsOf(get("Vorne"))->height(), 50.0);
        QVERIFY(std::fabs(area(get("Vorne")) - (5000 - 5 * 100.0 / 9 * 3 - 4 * 10 * 3)) < 1e-6);
        QVERIFY(std::fabs(area(get("Links")) - (3000 - 3 * 10 * 3 * 2 - 3 * 12 * 3 + 2 * 9)) < 1e-6);
        // Fingers: 9 along 100 mm, 5 along 50 mm, 1 along 15 mm.
        const W::GenResult r = W::box(s);
        QCOMPARE(r.parts.size(), size_t(5));
        QVERIFY(r.notes.join(' ').contains(QStringLiteral("Breite 9, Tiefe 5, Höhe 5")));
        for (const auto& p : r.parts) {
            const Box b = *boundsOf(p.paths);
            QVERIFY(Work::contains(b));
            QVERIFY(!Work::touchesPark(b));
            QCOMPARE(p.layer, QStringLiteral("Schneiden"));
        }
        s.lid = W::BoxLid::Joined;
        QCOMPARE(W::boxPanels(s).size(), size_t(6));
        s.lid = W::BoxLid::Loose;
        QCOMPARE(W::boxPanels(s).back().first, QStringLiteral("Deckel-Einsatz"));
    }
    void boxInnerKerfTooSmall() {
        W::BoxGenSpec s;
        s.w = 100; s.d = 60; s.h = 50; s.t = 3; s.finger = 10; s.inner = true;
        const W::Size3 o = W::boxOuter(s);
        QCOMPARE(o.w, 106.0); QCOMPARE(o.d, 66.0); QCOMPARE(o.h, 53.0);
        s.inner = false;
        const double base = boundsOf(part(W::box(s), "Boden")->paths)->width();
        s.kerf = 0.2;
        const double grown = boundsOf(part(W::box(s), "Boden")->paths)->width();
        QVERIFY(std::fabs(grown - base - 0.2) < 1e-3);
        s.t = 30;
        QVERIFY_THROWS_EXCEPTION(W::GenError, W::boxPanels(s));
        s.t = 3; s.kerf = 0; s.w = 300; s.d = 300; s.h = 200;
        QVERIFY(W::plateCount(W::box(s)) > 1);
    }

    void gearTeethAndSize() {
        W::GearSpec s;   // module 2, 24 teeth, 20°, bore 6
        const W::GearDims d = W::gearDims(s);
        QCOMPARE(d.pitch, 48.0); QCOMPARE(d.outer, 52.0); QCOMPARE(d.root, 43.0);
        const Poly o = W::gearOutline(s);
        QVERIFY(isClosed(o));
        const Box b = *boundsOf(o);
        QVERIFY(std::fabs(b.minY) < 1e-9);               // one tooth points up, its tip at y = 0
        QVERIFY(b.width() <= 52 + 1e-9 && b.width() > 51.5);
        // Crossings of the pitch circle: two per tooth.
        int crossings = 0;
        const auto side = [&](Pt p) { return std::hypot(p.x - 26, p.y - 26) > 24; };
        for (size_t i = 1; i < o.size(); ++i) if (side(o[i]) != side(o[i - 1])) ++crossings;
        QCOMPARE(crossings, 48);
        const W::GenResult r = W::gear(s);
        QCOMPARE(r.parts[0].paths.size(), size_t(2));    // outline and bore
        QVERIFY(std::fabs(boundsOf(r.parts[0].paths[1])->width() - 6) < 0.01);
        s.teeth = 12;
        QCOMPARE(W::gear(s).warnings.size(), 1);
        s.boreMm = 30;
        QVERIFY_THROWS_EXCEPTION(W::GenError, W::gear(s));
    }

    void rulerScaleFrame() {
        const W::GenResult r = W::ruler({150, 30, 5, QStringLiteral("Anna")}, fakeShape);
        const W::GenPart* outline = part(r, "Lineal Umriss");
        QCOMPARE(boundsOf(outline->paths)->width(), 169.0);   // 150 + 2 × 5 + hole 5 + 4
        // Perimeter of the rounded outline: 2 × (169 + 30) − 8 × 2 + 2π × 2.
        QVERIFY(std::fabs(polyLength(outline->paths[0]) - (398 - 16 + 4 * std::numbers::pi)) < 0.05);
        QCOMPARE(part(r, "Lineal Striche")->paths.size(), size_t(151));
        QCOMPARE(part(r, "Lineal Striche")->layer, QStringLiteral("Linie"));
        QVERIFY(part(r, "Lineal Text"));
        const W::GenResult sb = W::scaleBar({50, 5, 5, 3}, fakeShape);
        QCOMPARE(boundsOf(part(sb, "Maßstab Rahmen")->paths)->width(), 100.0);   // 5 m at 1:50
        QCOMPARE(part(sb, "Maßstab Felder")->paths.size(), size_t(3));
        W::FrameGenSpec f;
        f.around = Box{100, 100, 140, 120};
        f.style = 0; f.marginMm = 5;
        const W::GenResult fr = W::frame(f);
        QVERIFY(!fr.center);
        QCOMPARE(*boundsOf(fr.parts[0].paths), (Box{95, 95, 145, 125}));
    }

    void materialGrid() {
        W::MatGridSpec s;   // 5 × 5
        const W::GenResult r = W::matGrid(s, fakeShape);
        QCOMPARE(r.layers.size(), size_t(26));
        int fields = 0;
        std::set<QString> layers;
        for (const auto& p : r.parts) if (p.name == QLatin1String("Testfeld")) { ++fields; layers.insert(p.layer); }
        QCOMPARE(fields, 25);
        QCOMPARE(layers.size(), size_t(25));
        QVERIFY(layers.count(QStringLiteral("100 % · 3000 mm/min")));
        QVERIFY(layers.count(QStringLiteral("20 % · 300 mm/min")));
        bool found = false;
        for (const Layer& l : r.layers) if (l.name == QStringLiteral("60 % · 1650 mm/min")) { found = true; QCOMPARE(l.powerPct, 60.0); QCOMPARE(l.speed, 1650.0); QVERIFY(l.mode == LayerMode::Fill); }
        QVERIFY(found);
        s.powerFrom = 5;
        QVERIFY_THROWS_EXCEPTION(W::GenError, W::matGrid(s, fakeShape));
        s.powerFrom = 20; s.powerSteps = 11;
        QVERIFY_THROWS_EXCEPTION(W::GenError, W::matGrid(s, fakeShape));
    }

    void serialNumbers() {
        const W::SerialTemplate t = W::parseTemplate(QStringLiteral("SN-{0001}/A"));
        QCOMPARE(t.start, qint64(1)); QCOMPARE(t.width, 4);
        QCOMPARE(W::serialText(t, 9), QStringLiteral("SN-0010/A"));
        QCOMPARE(W::serialText(t, 2, 5), QStringLiteral("SN-0011/A"));
        QVERIFY_THROWS_EXCEPTION(W::GenError, W::parseTemplate(QStringLiteral("ohne")));
        W::SerialSpec s;   // 24 tags 50 × 16
        const W::GenResult r = W::serials(s, fakeShape, Work::width(), Work::height());
        QCOMPARE(r.parts.size(), size_t(48));
        QCOMPARE(W::plateCount(r), 1);
        for (const auto& p : r.parts) { QVERIFY(Work::contains(*boundsOf(p.paths))); QVERIFY(!Work::touchesPark(*boundsOf(p.paths))); }
        s.count = 300;
        QVERIFY(W::plateCount(W::serials(s, fakeShape, Work::width(), Work::height())) > 1);
    }

    void stampAndElements() {
        W::StampSpec s;
        s.lines = QStringList{QStringLiteral("Muster"), QString()};
        const W::GenResult r = W::stamp(s, fakeShape);
        QCOMPARE(r.parts.size(), size_t(2));
        // Inverted: outline, two border rings, six letters.
        QCOMPARE(r.parts[0].paths.size(), size_t(1 + 2 + 6));
        s.lines.clear();
        QVERIFY_THROWS_EXCEPTION(W::GenError, W::stamp(s, fakeShape));

        // Centered result: the middle lands on the work-area centre, local paths start at 0/0, groups shared.
        const W::GenResult g = W::ruler({100, 30, 0, {}}, fakeShape);
        const auto els = W::toElements(g, [](const QString& n) { return n; });
        QCOMPARE(els.size(), size_t(3));
        std::optional<Box> all;
        for (const Element& e : els) {
            QCOMPARE(boundsOf(e.paths)->minX, 0.0);
            QVERIFY(e.groupId && *e.groupId == *els[0].groupId);
            all = all ? all->united(*e.worldBounds()) : *e.worldBounds();
        }
        QVERIFY(std::fabs(all->center().x - Work::center().x) < 1e-9);
        QVERIFY(std::fabs(all->center().y - Work::center().y) < 1e-9);
        QCOMPARE(els[0].layerId, QStringLiteral("Schneiden"));
        QCOMPARE(W::num(12.50), QStringLiteral("12,5"));
    }
};

QTEST_GUILESS_MAIN(TestWerkstatt)
#include "test_werkstatt.moc"
