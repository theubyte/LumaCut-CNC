#include "core/text.h"
#include <QFont>
#include <QFontDatabase>
#include <QFontMetricsF>
#include <QHash>
#include <QPainterPath>
#include <QPolygonF>
#include <QTransform>
#include <algorithm>
#include <cmath>

namespace lumacut {
namespace {

QString resolveFamily(const QString& family) {
    static const QHash<QString, QStringList> generic = {
        {QStringLiteral("sans-serif"), {QStringLiteral("Segoe UI"), QStringLiteral("Arial")}},
        {QStringLiteral("serif"), {QStringLiteral("Times New Roman"), QStringLiteral("Georgia")}},
        {QStringLiteral("monospace"), {QStringLiteral("Consolas"), QStringLiteral("Courier New")}},
    };
    const auto it = generic.constFind(family);
    if (it == generic.constEnd()) return family;
    const QStringList all = QFontDatabase::families();
    for (const QString& name : *it) if (all.contains(name)) return name;
    return it->first();
}

}  // namespace

PolySet textPaths(const QString& text, double sizeMm, bool bold, const QString& family, double tolMm) {
    PolySet out;
    if (text.trimmed().isEmpty() || !(sizeMm > 0)) return out;
    // Qt flattens curves to about half a unit: lay out so that one unit is 2 × tolerance, within what fonts render sanely.
    const int pixelSize = std::clamp(int(std::lround(sizeMm / (2 * tolMm))), 64, 4096);
    QFont font(resolveFamily(family));
    font.setPixelSize(pixelSize);
    font.setBold(bold);
    font.setHintingPreference(QFont::PreferNoHinting);
    font.setStyleStrategy(QFont::StyleStrategy(QFont::ForceOutline | QFont::PreferAntialias));
    const QFontMetricsF metrics(font);
    const double lead = (metrics.ascent() + metrics.descent()) * 1.05;

    QPainterPath path;
    const QStringList lines = QString(text).replace(QStringLiteral("\r\n"), QStringLiteral("\n")).split(QLatin1Char('\n'));
    for (qsizetype i = 0; i < lines.size(); ++i) {
        if (lines[i].trimmed().isEmpty()) continue;
        path.addText(0, double(i) * lead, font, lines[i]);
    }
    const double k = sizeMm / pixelSize;
    const QList<QPolygonF> polys = path.toSubpathPolygons();
    double minX = 1e300, minY = 1e300;
    for (const QPolygonF& poly : polys) for (const QPointF& p : poly) { minX = std::min(minX, p.x()); minY = std::min(minY, p.y()); }
    for (const QPolygonF& poly : polys) {
        if (poly.size() < 3) continue;
        const bool closed = poly.first() == poly.last();
        const std::span<Pt> pts = out.addUninitialized(size_t(poly.size()) + (closed ? 0 : 1));
        for (qsizetype i = 0; i < poly.size(); ++i) pts[size_t(i)] = {(poly[i].x() - minX) * k, (poly[i].y() - minY) * k};
        if (!closed) pts.back() = pts.front();
    }
    return out;
}

QStringList fontFamilies() {
    QStringList out;
    const QStringList all = QFontDatabase::families();
    for (const QString& f : all) if (!f.startsWith(QLatin1Char('@')) && !QFontDatabase::isPrivateFamily(f)) out.push_back(f);
    std::sort(out.begin(), out.end(), [](const QString& a, const QString& b) { return a.localeAwareCompare(b) < 0; });
    return out;
}

}  // namespace lumacut
