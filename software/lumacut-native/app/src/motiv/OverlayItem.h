#pragma once
#include <QColor>
#include <QPointF>
#include <QQuickItem>
#include <span>
#include <vector>

/**
 * Editor marks on top of the stage: handles, guides, the shape being drawn. Antialiased triangles with a soft edge in one
 * draw call, rebuilt only when something changed, so a mouse move costs microseconds even with thousands of nodes.
 * Coordinates are item px. Call clear(), the drawing functions, then commit().
 */
class OverlayItem : public QQuickItem {
    Q_OBJECT
public:
    explicit OverlayItem(QQuickItem* parent = nullptr);

    void clear();
    void commit();
    void line(QPointF a, QPointF b, const QColor& c, qreal width = 1);
    /** Dash pattern in px; used for guides and warnings. */
    void dashed(QPointF a, QPointF b, const QColor& c, qreal dash = 4, qreal gap = 3, qreal width = 1);
    void polyline(std::span<const QPointF> pts, bool closed, const QColor& c, qreal width = 1);
    void quad(const QPointF (&corners)[4], const QColor& c);
    void rect(const QRectF& r, const QColor& c);
    void rectOutline(const QRectF& r, const QColor& c, qreal width = 1);
    void disc(QPointF center, qreal radius, const QColor& c);
    /** A filled convex polygon, for previews of simple shapes. */
    void convexFill(std::span<const QPointF> pts, const QColor& c);

protected:
    QSGNode* updatePaintNode(QSGNode* old, UpdatePaintNodeData*) override;

private:
    struct Vertex { float x, y; quint8 r, g, b, a; };
    quint32 vertex(QPointF p, const QColor& premul, qreal alpha = 1);
    void tri(quint32 a, quint32 b, quint32 c);
    std::vector<Vertex> m_v;
    std::vector<quint32> m_i;
    bool m_dirty = false;
};
