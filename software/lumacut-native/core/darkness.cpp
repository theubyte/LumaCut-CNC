#include "core/darkness.h"

#include <algorithm>
#include <cmath>
#include <vector>

namespace lumacut {
namespace {

inline double clamp(double v, double lo, double hi) { return v < lo ? lo : v > hi ? hi : v; }
struct Knot { double x, tone; };

/** (ln Energie, Ton) nach Energie, der Ton fällt nie: Rauschen darf die Kurve nicht umdrehen. */
std::vector<Knot> curveOf(const DarknessCurve& c) {
    std::vector<const DarknessPoint*> pts;
    for (const DarknessPoint& p : c.points) if (p.power > 0 && p.speed > 0) pts.push_back(&p);
    std::stable_sort(pts.begin(), pts.end(), [](const DarknessPoint* a, const DarknessPoint* b) { return a->power / a->speed < b->power / b->speed; });
    std::vector<Knot> out;
    out.reserve(pts.size());
    double top = 0;
    for (const DarknessPoint* p : pts) {
        top = std::max(top, p->tone);
        out.push_back({std::log(p->power / p->speed), top});
    }
    return out;
}
double minPower(const Layer& l) { return l.darkness ? l.darkness->minPowerPct : Darkness::RELIABLE_POWER_PCT; }
QString num0(double v) { return QString::fromLatin1(fmtFixed(v, 0)); }
QString num2de(double v) { return QString::fromLatin1(fmtFixed(v, 2, ',')); }

}  // namespace

namespace CurveTools {
bool usable(const DarknessCurve& c) {
    const auto k = curveOf(c);
    return k.size() >= 2 && k.back().tone > k.front().tone;
}
std::pair<double, double> toneRange(const DarknessCurve& c) {
    const auto k = curveOf(c);
    if (k.empty()) return {0, 0};
    return {k.front().tone, k.back().tone};
}
double tone(const DarknessCurve& c, double energy) {
    const auto k = curveOf(c);
    if (k.empty()) return 0;
    const double x = std::log(energy);
    if (x <= k.front().x) return k.front().tone;
    if (x >= k.back().x) return k.back().tone;
    std::ptrdiff_t i = -1;
    for (std::ptrdiff_t j = std::ptrdiff_t(k.size()) - 1; j >= 0; --j) if (k[size_t(j)].x <= x) { i = j; break; }
    i = std::min(i, std::ptrdiff_t(k.size()) - 2);
    const Knot a = k[size_t(i)], b = k[size_t(i) + 1];
    return b.x - a.x < 1e-9 ? b.tone : a.tone + (b.tone - a.tone) * (x - a.x) / (b.x - a.x);
}
double energyFor(const DarknessCurve& c, double tone) {
    const auto k = curveOf(c);
    if (k.size() < 2) return 0;
    const double t = clamp(tone, k.front().tone, k.back().tone);
    size_t i = 1;
    for (size_t j = 0; j < k.size(); ++j) if (k[j].tone >= t) { i = std::max<size_t>(j, 1); break; }
    const Knot a = k[i - 1], b = k[i];
    return std::exp(b.tone - a.tone < 1e-9 ? a.x : a.x + (b.x - a.x) * (t - a.tone) / (b.tone - a.tone));
}
}  // namespace CurveTools

namespace Darkness {
std::pair<double, double> speedRange(const Layer& l, double maxFeed) {
    const double ratio = l.powerPct / l.speed;
    const DarknessCurve* c = l.darkness ? &*l.darkness : nullptr;
    const double lo = std::max(minPower(l) / ratio, c ? c->speedMin : SPEED_FLOOR);
    const double hi = std::min({100.0 / ratio, c ? c->speedMax : maxFeed, maxFeed});
    return lo <= hi ? std::pair{lo, hi} : std::pair{hi, hi};
}
Result atSpeed(const Layer& l, double speed, double maxFeed) {
    const auto [lo, hi] = speedRange(l, maxFeed);
    const double v = clamp(speed, lo, hi);
    Result r{l, std::nullopt};
    if (speed < lo - 0.5) {
        if (l.powerPct * lo / l.speed <= minPower(l) + 0.05)
            r.limit = QStringLiteral("Langsamer geht nicht: der Laser zündet unter %1 % nicht sicher.").arg(num0(minPower(l)));
        else r.limit = QStringLiteral("Langsamer ist nicht kalibriert.");
    } else if (speed > hi + 0.5) {
        r.limit = QStringLiteral("Schneller geht nicht.");
    }
    r.layer.speed = v;
    r.layer.powerPct = l.powerPct * v / l.speed;
    return r;
}
double speedPosition(const Layer& l, double maxFeed) {
    const auto [lo, hi] = speedRange(l, maxFeed);
    if (hi - lo < 1.0) return 0.5;
    return clamp(std::log(l.speed / lo) / std::log(hi / lo), 0.0, 1.0);
}
double speedAt(const Layer& l, double position, double maxFeed) {
    const auto [lo, hi] = speedRange(l, maxFeed);
    return lo * std::exp(clamp(position, 0.0, 1.0) * std::log(hi / lo));
}
std::optional<double> tone(const Layer& l) {
    if (!l.darkness || !CurveTools::usable(*l.darkness) || l.mode != LayerMode::Fill) return std::nullopt;
    const DarknessCurve& c = *l.darkness;
    return CurveTools::tone(c, l.powerPct / l.speed * c.intervalMm / l.intervalMm);
}
Result atTone(const Layer& l, double tone, double maxFeed) {
    if (!l.darkness || !CurveTools::usable(*l.darkness) || l.mode != LayerMode::Fill)
        return {l, QStringLiteral("Für diese Ebene gibt es keine Schwärze-Kurve.")};
    const DarknessCurve& c = *l.darkness;
    const double ratio = CurveTools::energyFor(c, tone) * l.intervalMm / c.intervalMm;
    double v = l.speed;
    std::optional<QString> limit;
    if (ratio * v < c.minPowerPct) v = c.minPowerPct / ratio;
    if (ratio * v > 100.0) v = 100.0 / ratio;
    if (v > maxFeed) {
        v = maxFeed;
        limit = QStringLiteral("Heller geht nicht: der Laser zündet unter %1 % nicht sicher und ist schon am schnellsten.").arg(num0(c.minPowerPct));
    }
    const double p = clamp(ratio * v, c.minPowerPct, 100.0);
    const auto [a, b] = CurveTools::toneRange(c);
    if (!limit && !(tone >= a && tone <= b))
        limit = QStringLiteral("Außerhalb der gemessenen Töne (%1–%2).").arg(num2de(a), num2de(b));
    Result r{l, limit};
    r.layer.speed = v;
    r.layer.powerPct = p;
    return r;
}
}  // namespace Darkness

}  // namespace lumacut
