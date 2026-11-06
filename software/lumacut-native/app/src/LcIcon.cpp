#include "LcIcon.h"
#include "LucideIcons.h"
#include <QHash>
#include <QPainter>
#include <QSvgRenderer>
#include <memory>

// One parsed renderer per icon, colour and stroke: themes change rarely, repaints stay cheap.
static QSvgRenderer* rendererFor(const QString& name, const QColor& color, qreal stroke) {
    static QHash<QString, std::shared_ptr<QSvgRenderer>> cache;
    const QString key = name + u'|' + color.name(QColor::HexArgb) + u'|' + QString::number(stroke);
    if (auto hit = cache.value(key)) return hit.get();
    const char* body = lucideIconBody(name);
    if (!body) return nullptr;
    const QByteArray svg = QByteArray(R"(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke=")")
        + color.name(QColor::HexRgb).toLatin1() + R"(" stroke-opacity=")" + QByteArray::number(color.alphaF(), 'f', 3)
        + R"(" stroke-width=")" + QByteArray::number(stroke) + R"(" stroke-linecap="round" stroke-linejoin="round">)" + body + "</svg>";
    auto r = std::make_shared<QSvgRenderer>(svg);
    cache.insert(key, r);
    return r.get();
}

LcIcon::LcIcon(QQuickItem* parent) : QQuickPaintedItem(parent) {
    setAntialiasing(true);
    setImplicitSize(m_size, m_size);
}
void LcIcon::paint(QPainter* p) {
    if (auto* r = rendererFor(m_name, m_color, m_stroke)) {
        p->setRenderHint(QPainter::Antialiasing);
        const qreal s = qMin(width(), height());
        r->render(p, QRectF((width() - s) / 2, (height() - s) / 2, s, s));
    }
}
void LcIcon::setName(const QString& v) { if (v != m_name) { m_name = v; update(); emit changed(); } }
void LcIcon::setColor(const QColor& v) { if (v != m_color) { m_color = v; update(); emit changed(); } }
void LcIcon::setSize(int v) { if (v != m_size) { m_size = v; setImplicitSize(v, v); update(); emit changed(); } }
void LcIcon::setStrokeWidth(qreal v) { if (v != m_stroke) { m_stroke = v; update(); emit changed(); } }
