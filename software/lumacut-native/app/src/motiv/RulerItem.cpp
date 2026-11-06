#include "RulerItem.h"
#include "Fmt.h"
#include <QPainter>
#include <algorithm>
#include <cmath>

RulerItem::RulerItem(QQuickItem* parent) : QQuickPaintedItem(parent) {
    setOpaquePainting(false);
    connect(this, &RulerItem::changed, this, [this] { update(); });
}
void RulerItem::paint(QPainter* p) {
    if (m_zoom <= 0) return;
    const qreal length = m_vertical ? height() : width(), depth = m_vertical ? width() : height();
    const qreal start = m_offset + m_pan;   // ruler px of 0 mm

    static constexpr double kSteps[] = {0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500};
    double major = 500;
    for (double s : kSteps) if (s * m_zoom >= 56) { major = s; break; }
    const int firstDigit = int(std::round(major / std::pow(10.0, std::floor(std::log10(major)))));
    const int parts = firstDigit == 2 ? 4 : firstDigit == 5 ? 5 : 10;
    const double minor = major / parts;

    if (m_hasSel) {
        const qreal a = std::max(0.0, start + m_selFrom * m_zoom), b = std::min(length, start + m_selTo * m_zoom);
        if (b > a) p->fillRect(m_vertical ? QRectF(0, a, depth - 1, b - a) : QRectF(a, 0, b - a, depth - 1), m_band);
    }
    p->setFont(m_font);
    const int i0 = int(std::floor((-start) / m_zoom / minor)), i1 = int(std::ceil((length - start) / m_zoom / minor));
    const int digits = major < 1 ? 1 : 0;
    for (int i = i0; i <= i1; ++i) {
        const double mm = i * minor;
        const qreal at = std::round(mm * m_zoom + start);
        if (at < 0 || at >= length) continue;
        const bool big = i % parts == 0;
        const qreal tick = big ? depth - 10 : 5;
        if (m_vertical) p->fillRect(QRectF(depth - 1 - tick, at, tick, 1), m_tick);
        else p->fillRect(QRectF(at, depth - 1 - tick, 1, tick), m_tick);
        if (!big) continue;
        p->setPen(m_text);
        const QString label = Fmt::trim(mm, digits);
        if (m_vertical) {
            p->save();
            p->translate(11, at + 3);
            p->rotate(-90);
            const QRectF box(-60, -10, 60, 12);
            p->drawText(box, Qt::AlignRight | Qt::AlignVCenter, label);
            p->restore();
        } else {
            p->drawText(QRectF(at + 3, 1, 60, 12), Qt::AlignLeft | Qt::AlignVCenter, label);
        }
    }
}
