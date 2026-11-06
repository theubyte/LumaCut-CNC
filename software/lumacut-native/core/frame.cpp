#include "core/frame.h"
#include "core/geometry.h"

#include <algorithm>
#include <charconv>
#include <stdexcept>

namespace lumacut {
namespace {
inline double clamp(double v, double lo, double hi) { return v < lo ? lo : v > hi ? hi : v; }
}

std::vector<Pt> convexHull(PolyView points) {
    std::vector<Pt> pts(points.begin(), points.end());
    std::sort(pts.begin(), pts.end(), [](Pt a, Pt b) { return a.x < b.x || (a.x == b.x && a.y < b.y); });
    pts.erase(std::unique(pts.begin(), pts.end()), pts.end());
    if (pts.size() < 3) return pts;
    const auto cross = [](Pt o, Pt a, Pt b) { return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x); };
    std::vector<Pt> lower, upper;
    for (const Pt p : pts) {
        while (lower.size() >= 2 && cross(lower[lower.size() - 2], lower.back(), p) <= 0) lower.pop_back();
        lower.push_back(p);
    }
    for (size_t i = pts.size(); i-- > 0;) {
        const Pt p = pts[i];
        while (upper.size() >= 2 && cross(upper[upper.size() - 2], upper.back(), p) <= 0) upper.pop_back();
        upper.push_back(p);
    }
    lower.pop_back();
    upper.pop_back();
    lower.insert(lower.end(), upper.begin(), upper.end());
    return lower;
}

QByteArray frameProgram(PolyView points, FrameMode mode, int feed) {
    if (points.empty()) throw std::invalid_argument("Kein Motiv für den Rahmen");
    std::vector<Pt> outline;
    if (mode == FrameMode::Box) {
        const Box b = *boundsOf(points);
        outline = {{b.minX, b.minY}, {b.maxX, b.minY}, {b.maxX, b.maxY}, {b.minX, b.maxY}};
    } else {
        outline = convexHull(points);
    }
    const int f = std::clamp(feed, 300, 9000);
    QByteArray out("G21\nG90\nM5 I\n");
    outline.push_back(outline.front());
    const double W = Bed::width(), H = Bed::height();
    for (const Pt p : outline) {
        out += "G0 X" + fmt3(clamp(p.x, 0.0, W)) + " Y" + fmt3(clamp(p.y, 0.0, H)) + " F" + QByteArray::number(f) + "\n";
    }
    return out;
}

std::vector<Pt> cutPoints(const Toolpath& tp) {
    std::vector<Pt> out;
    for (size_t i = 0; i < tp.count(); ++i) {
        if (tp.power[i] == 0) continue;
        const float* s = tp.xy.data() + i * 4;
        out.push_back({double(s[0]), double(s[1])});
        out.push_back({double(s[2]), double(s[3])});
    }
    return out;
}

std::vector<double> testSteps(double from, double to, int n) {
    if (n <= 1) return {from};
    std::vector<double> out(static_cast<size_t>(n));
    for (int i = 0; i < n; ++i) out[size_t(i)] = from + (to - from) * i / (n - 1);
    return out;
}

Document buildMaterialTest(const MaterialTestSpec& s, const std::function<PolySet(const QString&, double)>& label) {
    if (!(s.powerSteps >= 1 && s.powerSteps <= 10 && s.speedSteps >= 1 && s.speedSteps <= 10)) throw std::invalid_argument("Höchstens 10 × 10 Felder");
    if (!(s.powerFrom >= 0 && s.powerFrom <= 100 && s.powerTo >= 0 && s.powerTo <= 100)) throw std::invalid_argument("Leistung 0–100 %");
    if (!(s.speedFrom >= 10 && s.speedFrom <= Limits::SPEED_MAX && s.speedTo >= 10 && s.speedTo <= Limits::SPEED_MAX)) throw std::invalid_argument("Tempo 10–30000 mm/min");
    static constexpr qint64 PALETTE[] = {0xFF4FD8B4LL, 0xFF6CB6FFLL, 0xFFFFB45CLL, 0xFFB98CFFLL, 0xFFFF8AD8LL, 0xFF9BE15DLL};
    const std::vector<double> powers = testSteps(s.powerFrom, s.powerTo, s.powerSteps), speeds = testSteps(s.speedFrom, s.speedTo, s.speedSteps);
    const double labelH = 3.0, left = s.originX + 14.0, top = s.originY + labelH + 3.0, pitch = s.cellMm + s.gapMm;

    Layer text = newLayer(QStringLiteral("Beschriftung"), 0xFFEEF3F8LL, LayerMode::Line);
    text.powerPct = 20;
    text.speed = 1500;

    Document doc;
    doc.title = QStringLiteral("Materialtest");
    doc.layers.clear();
    doc.layers.push_back(text);
    const auto place = [&](const QString& t, double x, double y) {
        PolySet g = label(t, labelH);
        const auto b = boundsOf(g);
        if (!b) return;
        for (Pt& p : g.allPoints()) p = {p.x - b->minX, p.y - b->minY};
        Element e = newElement(text.id, QStringLiteral("Beschriftung"));
        e.text = t;
        e.transform.x = x;
        e.transform.y = y;
        e.paths = std::move(g);
        doc.elements.push_back(std::move(e));
    };
    for (size_t i = 0; i < powers.size(); ++i) place(QStringLiteral("%1%").arg(int(powers[i])), left + double(i) * pitch, s.originY);
    for (size_t j = 0; j < speeds.size(); ++j) place(QString::number(int(speeds[j])), s.originX, top + double(j) * pitch + s.cellMm / 2 - labelH / 2);
    for (size_t j = 0; j < speeds.size(); ++j) {
        for (size_t i = 0; i < powers.size(); ++i) {
            Layer layer = newLayer(QStringLiteral("%1 % · %2 mm/min").arg(int(powers[i])).arg(int(speeds[j])), PALETTE[(i + j) % 6], s.mode);
            layer.powerPct = powers[i];
            layer.speed = speeds[j];
            layer.passes = s.passes;
            layer.intervalMm = s.intervalMm;
            Element e = newElement(layer.id, QStringLiteral("Testfeld"));
            e.transform.x = left + double(i) * pitch;
            e.transform.y = top + double(j) * pitch;
            e.paths.add(Shapes::rect(s.cellMm, s.cellMm));
            doc.layers.push_back(std::move(layer));
            doc.elements.push_back(std::move(e));
        }
    }
    return doc;
}

}  // namespace lumacut
