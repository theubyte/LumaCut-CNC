#include "ScanImage.h"
#include <QQuickWindow>
#include <QSGImageNode>
#include "Scanner.h"
#include "motiv/Editor.h"

ScanImage::ScanImage(QQuickItem* parent) : QQuickItem(parent) {
    setFlag(ItemHasContents, true);
    // A request made while hidden or before the window existed is lost: ask again when shown.
    connect(this, &QQuickItem::visibleChanged, this, [this] { m_dirty = true; update(); });
    connect(this, &QQuickItem::windowChanged, this, [this] { m_dirty = true; update(); });
    connect(Editor::instance(), &Editor::backgroundChanged, this, [this] { if (m_source == QLatin1String("background")) pull(); });
    connect(Scanner::instance(), &Scanner::liveFrame, this, [this] { if (m_source == QLatin1String("live")) pull(); });
    pull();
}
void ScanImage::setSource(const QString& s) {
    if (s == m_source) return;
    m_source = s;
    emit sourceChanged();
    pull();
}
void ScanImage::pull() {
    const QImage next = m_source == QLatin1String("background") ? Editor::instance()->background() : Scanner::instance()->liveImage();
    if (next.cacheKey() == m_image.cacheKey()) return;
    m_image = next;
    m_dirty = true;
    emit imageChanged();
    update();
}
QSGNode* ScanImage::updatePaintNode(QSGNode* old, UpdatePaintNodeData*) {
    auto* node = static_cast<QSGImageNode*>(old);
    if (m_image.isNull() || width() < 1 || height() < 1) { delete node; return nullptr; }
    if (!node) {
        node = window()->createImageNode();
        node->setOwnsTexture(true);
        node->setFiltering(QSGTexture::Linear);
        m_dirty = true;
    }
    if (m_dirty) {
        node->setTexture(window()->createTextureFromImage(m_image));
        m_dirty = false;
    }
    QRectF r = boundingRect();
    if (m_source != QLatin1String("background")) {
        // Aspect-fit: the camera picture keeps its shape.
        const double s = std::min(width() / m_image.width(), height() / m_image.height());
        const QSizeF sz(m_image.width() * s, m_image.height() * s);
        r = QRectF(QPointF((width() - sz.width()) / 2, (height() - sz.height()) / 2), sz);
    }
    node->setRect(r);
    return node;
}
