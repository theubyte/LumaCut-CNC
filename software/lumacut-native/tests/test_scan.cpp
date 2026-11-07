/**
 * Kopfkamera mit bekannten Zahlen: Homographie, Linsenmodell hin und zurück, Kalibrierung aus dem Android-JSON,
 * Kachelplan, Mosaik aus synthetischen Fotos einer bekannten Szene, Helligkeitsausgleich, entzerrtes Einzelbild.
 */
#include "core/camera/scan.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QtTest>
#include <cmath>

using namespace lumacut;
namespace C = lumacut::Camera;

namespace {
/** Same picture geometry as the simulator's head camera: 90 mm across the picture, centred on the head. */
C::Calibration simCal(int w = 640, int h = 480) {
    const double hx = 45, hy = 45.0 * h / w;
    return C::Calibration::fromMarks(w, h, {{0, 0}, {double(w), 0}, {double(w), double(h)}, {0, double(h)}}, {{-hx, -hy}, {hx, -hy}, {hx, hy}, {-hx, hy}});
}
/** The bed as a function of work mm: 10 mm checker, dark plate, slow gradient. */
int scene(double x, double y) {
    const bool dark = (int(std::floor(x / 10)) + int(std::floor(y / 10))) % 2 == 0;
    return (dark ? 70 : 190) + int(x / 20);
}
uint32_t grey(int v) { v = std::clamp(v, 0, 255); return 0xFF000000u | uint32_t(v) << 16 | uint32_t(v) << 8 | uint32_t(v); }
std::vector<uint32_t> photoAt(const C::Calibration& cal, Pt head, double gain = 1) {
    std::vector<uint32_t> px(size_t(cal.photoWidth) * size_t(cal.photoHeight));
    for (int y = 0; y < cal.photoHeight; ++y)
        for (int x = 0; x < cal.photoWidth; ++x) {
            const Pt w = cal.pixelToWork({x + 0.5, y + 0.5}, head);
            px[size_t(y) * size_t(cal.photoWidth) + size_t(x)] = grey(int(scene(w.x, w.y) * gain));
        }
    return px;
}
int g(uint32_t c) { return int((c >> 8) & 255); }
}  // namespace

class TestScan : public QObject {
    Q_OBJECT
private slots:
    void homographyRoundTrip() {
        const std::vector<Pt> src{{0, 0}, {1, 0}, {1, 1}, {0, 1}}, dst{{10, 20}, {50, 22}, {48, 70}, {8, 60}};
        const auto h = C::homography(src, dst);
        QVERIFY(h);
        for (size_t i = 0; i < 4; ++i) QVERIFY(dist(C::apply(*h, src[i]), dst[i]) < 1e-9);
        const auto inv = C::inverse(*h);
        QVERIFY(inv);
        QVERIFY(dist(C::apply(*inv, C::apply(*h, {0.3, 0.7})), Pt{0.3, 0.7}) < 1e-9);
    }
    void lensRoundTrip() {
        C::Lens l;
        l.cx = 960; l.cy = 540; l.f = 1100; l.k1 = -0.12; l.k2 = 0.03; l.k3 = -0.002;
        l.g = {1 / 60.0, 0.001, 0.02, -0.0005, 1 / 60.0, -0.01, 0, 0, 1};
        for (const Pt rel : {Pt{0, 0}, Pt{20, -15}, Pt{-40, 30}, Pt{55, 33}}) {
            const Pt px = l.toPixel(rel);
            QVERIFY2(dist(l.toRel(px), rel) < 1e-6, "Linse hin und zurück");
        }
    }
    void marksCalibration() {
        const C::Calibration c = simCal();
        QVERIFY(dist(c.pixelToWork({320, 240}, {100, 50}), Pt{100, 50}) < 1e-9);
        QVERIFY(dist(c.workToPixel({145, 83.75}, {100, 50}), Pt{640, 480}) < 1e-9);
        const Box f = c.footprint();
        QVERIFY(std::fabs(f.width() - 90) < 1e-9 && std::fabs(f.height() - 67.5) < 1e-9);
        const Box u = c.usable();
        QVERIFY(std::fabs(u.width() - 90 * 0.84) < 1e-9 && std::fabs(u.height() - 67.5 * 0.84) < 1e-9);
        QCOMPARE(C::mosaicResolution(c), 5.0);   // 640 / 90 × 0.8 = 5.7, capped at 5 px/mm
        QVERIFY(std::fabs(C::mosaicResolution(simCal(320, 240)) - 320.0 / 90 * 0.8) < 1e-9);
    }
    void fromAndroidJson() {
        const QByteArray json = R"({"photoWidth":640,"photoHeight":480,"scanZ":40,
            "photo":[{"x":0,"y":0},{"x":640,"y":0},{"x":640,"y":480},{"x":0,"y":480}],
            "relMm":[{"x":-45,"y":-33.75},{"x":45,"y":-33.75},{"x":45,"y":33.75},{"x":-45,"y":33.75}]})";
        const auto c = C::Calibration::fromJson(QJsonDocument::fromJson(json).object());
        QVERIFY(c);
        QCOMPARE(c->scanZ, 40.0);
        QVERIFY(dist(c->pixelToWork({0, 0}, {200, 100}), Pt{155, 66.25}) < 1e-9);
        QString why;
        QVERIFY(!C::Calibration::fromJson({}, &why));
        QVERIFY(why.contains(QStringLiteral("nicht kalibriert")));
        QVERIFY(!C::Calibration::fromJson(QJsonDocument::fromJson(R"({"photoWidth":640,"photoHeight":480,"photo":[]})").object(), &why));
        // Lens model: the Pi stores what the tablet measured.
        const QByteArray lensJson = R"({"photoWidth":1920,"photoHeight":1080,"scanZ":30,"lens":{"cx":960,"cy":540,"f":1100,"k1":-0.1,"k2":0.02,
            "g":[0.0166667,0,0,0,0.0166667,0,0,0,1],"valid":{"minX":100,"minY":60,"maxX":1820,"maxY":1020}}})";
        const auto l = C::Calibration::fromJson(QJsonDocument::fromJson(lensJson).object());
        QVERIFY(l && l->lens);
        QVERIFY(dist(l->pixelToWork({960, 540}, {10, 10}), Pt{10, 10}) < 1e-6);
        QVERIFY(l->usable().width() > 20 && l->usable().width() < l->footprint().width());
    }
    void tilePlan() {
        const C::Calibration c = simCal();
        // 120 × 80 mm area: usable 75.6 × 56.7, steps 56.7 × 42.5 → 2 × 2 pictures.
        const C::TilePlan p = C::plan(c, {120, 120, 240, 200});
        QCOMPARE(p.heads.size(), size_t(4));
        QVERIFY(p.uncovered.isEmpty());
        const Box u = c.usable();
        Box cover{1e9, 1e9, -1e9, -1e9};
        for (const Pt& h : p.heads) cover = {std::min(cover.minX, h.x + u.minX), std::min(cover.minY, h.y + u.minY), std::max(cover.maxX, h.x + u.maxX), std::max(cover.maxY, h.y + u.maxY)};
        QVERIFY(cover.minX <= 120 + 1e-9 && cover.minY <= 120 + 1e-9 && cover.maxX >= 240 - 1e-9 && cover.maxY >= 200 - 1e-9);
        // Serpentine: the second row runs back.
        QVERIFY(p.heads[1].x > p.heads[0].x && p.heads[3].x < p.heads[2].x);
        // Whole default work area 370 × 360: 7 × 9 pictures.
        QCOMPARE(C::plan(c, {0, 0, Work::width(), Work::height()}).heads.size(), size_t(63));
        QVERIFY_THROWS_EXCEPTION(std::invalid_argument, C::plan(c, {500, 500, 600, 600}));
    }
    void scanHeightAndJog() {
        C::Calibration c = simCal();   // scanZ 20 by default
        c.scanZ = 40;
        // Measured surface, no aboveSurface: the calibration's scanZ, reached by jogging.
        auto h = C::scanHeight(c, 8.0, 20.0);
        QVERIFY(h.lock.isEmpty() && h.z && *h.z == 40 && h.jog);
        // No surface and Z far off: refused with a sentence, never flat over the bed.
        h = C::scanHeight(c, std::nullopt, 1.0);
        QVERIFY(!h.z && h.lock.startsWith(QStringLiteral("Zuerst abtasten")));
        QVERIFY(h.lock.contains(QStringLiteral("Z steht auf 1,0")) && h.lock.contains(QStringLiteral("Z 40,0")));
        // No surface but already within 1 mm: stays where it is.
        h = C::scanHeight(c, std::nullopt, 39.4);
        QVERIFY(h.z && *h.z == 39.4 && !h.jog);
        // Calibrated above the material: surface + distance, capped by Z_TOP.
        c.aboveSurface = 32;
        h = C::scanHeight(c, 10.5, 20);
        QVERIFY(h.z && std::fabs(*h.z - 42.5) < 1e-9);
        QVERIFY(C::scanHeight(c, std::nullopt, 42.5).lock.startsWith(QStringLiteral("Zuerst abtasten")));
        QVERIFY(C::scanHeight(c, 50.0, 20).lock.contains(QStringLiteral("zu hoch")));   // 82 > 80
        c.aboveSurface = 2;
        QVERIFY(C::scanHeight(c, 10.0, 20).lock.contains(QStringLiteral("zu nah")));
        // Jog steps as Android: 21.3 mm = 2 × 10 + 1 + 3 × 0.1.
        QCOMPARE(C::jogSteps(21.3), (std::vector<double>{10, 10, 1, 0.1, 0.1, 0.1}));
        QCOMPARE(C::jogSteps(-1.2), (std::vector<double>{-1, -0.1, -0.1}));
        QVERIFY(C::jogSteps(0.04).empty());
    }
    void mosaicFromTiles() {
        const C::Calibration c = simCal();
        const C::TilePlan p = C::plan(c, {120, 120, 240, 200});
        C::Mosaic m(c, 4);
        QCOMPARE(m.width(), int(Work::width() * 4));
        for (const Pt& h : p.heads) { const auto px = photoAt(c, h); m.add(px.data(), c.photoWidth, c.photoHeight, h); }
        // At the centres of the checker cells the mosaic shows the scene.
        int checked = 0, worst = 0;
        for (double y = 125; y < 200; y += 10)
            for (double x = 125; x < 240; x += 10) {
                const uint32_t v = m.pixels()[size_t(y * 4) * size_t(m.width()) + size_t(x * 4)];
                QVERIFY((v >> 24) == 255);
                worst = std::max(worst, std::abs(g(v) - scene(x, y)));
                ++checked;
            }
        QVERIFY2(worst <= 3, qPrintable(QStringLiteral("Abweichung %1").arg(worst)));
        QCOMPARE(checked, 96);
        // Outside every picture stays transparent.
        QCOMPARE(m.pixels()[0] >> 24, 0u);
        // A picture 25 % brighter (the camera adjusts per picture) is brought back to the mosaic's level.
        const Pt h{180, 160};
        const auto bright = photoAt(c, h, 1.25);
        m.add(bright.data(), c.photoWidth, c.photoHeight, h);
        QVERIFY(std::fabs(m.lastGain()[1] - 0.8) < 0.04);
        const uint32_t v = m.pixels()[size_t(155 * 4) * size_t(m.width()) + size_t(175 * 4)];
        QVERIFY(std::abs(g(v) - scene(175, 155)) <= 6);
    }
    void levelBackground() {
        // Background brightening from 120 to 200 across the picture, one dark mark.
        const int w = 200, h = 100;
        std::vector<uint32_t> px(size_t(w * h));
        for (int y = 0; y < h; ++y)
            for (int x = 0; x < w; ++x) px[size_t(y * w + x)] = grey(120 + 80 * x / w - ((x >= 95 && x < 105 && y >= 45 && y < 55) ? 80 : 0));
        const auto out = C::level(px, w, h, 2);
        const int left = g(out[size_t(20 * w + 15)]), right = g(out[size_t(20 * w + 185)]);
        QVERIFY2(std::abs(left - right) <= 12, qPrintable(QStringLiteral("%1 %2").arg(left).arg(right)));
        QVERIFY(g(out[size_t(50 * w + 100)]) < g(out[size_t(50 * w + 80)]) - 40);   // the mark keeps its contrast
    }
    void rectifiedLive() {
        const C::Calibration c = simCal();
        const Pt h{150, 120};
        const auto px = photoAt(c, h);
        const C::Rectified r = C::rectify(c, px.data(), c.photoWidth, c.photoHeight, h, 4);
        QVERIFY(std::fabs(r.area.width() - 90) < 1e-9 && std::fabs(r.area.minX - 105) < 1e-9);
        QCOMPARE(r.width, 360);
        const uint32_t v = r.argb[size_t((115 - r.area.minY) * 4) * size_t(r.width) + size_t((155 - r.area.minX) * 4)];
        QVERIFY(std::abs(g(v) - scene(155, 115)) <= 3);
        // A snapshot in another size than the calibration's is scaled.
        const C::Calibration big = simCal(1280, 960);
        const auto px2 = photoAt(big, h);
        const C::Rectified r2 = C::rectify(c, px2.data(), 1280, 960, h, 4);
        const uint32_t v2 = r2.argb[size_t((115 - r2.area.minY) * 4) * size_t(r2.width) + size_t((155 - r2.area.minX) * 4)];
        QVERIFY(std::abs(g(v2) - scene(155, 115)) <= 3);
    }
};

QTEST_GUILESS_MAIN(TestScan)
#include "test_scan.moc"
