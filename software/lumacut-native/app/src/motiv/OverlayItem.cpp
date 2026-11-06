#include "OverlayItem.h"
#include <QQuickWindow>
#include <QSGFlatColorMaterial>
#include <QSGGeometryNode>
#include <QSGVertexColorMaterial>
#include <algorithm>
#include <cmath>
#include <cstring>

OverlayItem::OverlayItem(QQuickItem* parent) : QQuickItem(parent) {
    setFlag(ItemHasContents, true);
    setAcceptedMouseButtons(Qt::NoButton);
}
void OverlayItem::clear() { m_v.clear(); m_i.clear(); }
void OverlayItem::commit() {
    // The scene graph drops a node without vertices from its batches and does not take it back reliably: never leave it empty.
    if (m_i.empty()) {
        const QColor none(0, 0, 0, 0);
        tri(vertex({}, none), vertex({}, none), vertex({}, none));
    }
    m_dirty = true;
    update();
}

quint32 OverlayItem::vertex(QPointF p, const QColor& c, qreal alpha) {
    const float a = float(c.alphaF() * alpha);
    m_v.push_back({float(p.x()), float(p.y()), quint8(c.redF() * a * 255 + .5f), quint8(c.greenF() * a * 255 + .5f), quint8(c.blueF() * a * 255 + .5f), quint8(a * 255 + .5f)});
    return quint32(m_v.size() - 1);
}
void OverlayItem::tri(quint32 a, quint32 b, quint32 c) { m_i.push_back(a); m_i.push_back(b); m_i.push_back(c); }

void OverlayItem::polyline(std::span<const QPointF> pts, bool closed, const QColor& c, qreal width) {
    const size_t n = pts.size();
    if (n < 2) return;
    // Cross section: outer edge (transparent), inner edge (full), inner edge, outer edge. One px feather over one device px.
    const qreal k = window() ? 1.0 / window()->effectiveDevicePixelRatio() : 1.0;
    const qreal hw = width / 2, outer = hw + k / 2, inner = std::max(hw - k / 2, 0.0), innerAlpha = hw < k / 2 ? 2 * hw / k : 1.0;
    const size_t count = closed ? n + 1 : n;
    quint32 prev[4] = {0, 0, 0, 0};
    quint32 first[4] = {0, 0, 0, 0};
    for (size_t i = 0; i < count; ++i) {
        const bool last = i == count - 1;
        if (closed && last) {
            for (int s = 0; s < 3; ++s) { tri(prev[s], prev[s + 1], first[s]); tri(prev[s + 1], first[s + 1], first[s]); }
            break;
        }
        const QPointF p = pts[i];
        const QPointF before = i > 0 ? pts[i - 1] : closed ? pts[n - 1] : p;
        const QPointF after = i + 1 < n ? pts[i + 1] : closed ? pts[0] : p;
        QPointF d0 = p - before, d1 = after - p;
        const qreal l0 = std::hypot(d0.x(), d0.y()), l1 = std::hypot(d1.x(), d1.y());
        if (l0 > 1e-9) d0 /= l0; else d0 = {};
        if (l1 > 1e-9) d1 /= l1; else d1 = {};
        QPointF dir = d0 + d1;
        const qreal ld = std::hypot(dir.x(), dir.y());
        if (ld > 1e-6) dir /= ld; else dir = l1 > 1e-9 ? d1 : d0;
        const QPointF normal(-dir.y(), dir.x());
        // Miter, limited so sharp corners do not spike.
        const QPointF n1 = l1 > 1e-9 ? QPointF(-d1.y(), d1.x()) : QPointF(-d0.y(), d0.x());
        const qreal cosHalf = std::abs(normal.x() * n1.x() + normal.y() * n1.y());
        const qreal miter = 1.0 / std::max(cosHalf, 0.5);
        const quint32 now[4] = {vertex(p + normal * outer * miter, c, 0), vertex(p + normal * inner * miter, c, innerAlpha),
                                vertex(p - normal * inner * miter, c, innerAlpha), vertex(p - normal * outer * miter, c, 0)};
        if (i == 0) std::memcpy(first, now, sizeof first);
        else for (int s = 0; s < 3; ++s) { tri(prev[s], prev[s + 1], now[s]); tri(prev[s + 1], now[s + 1], now[s]); }
        std::memcpy(prev, now, sizeof prev);
    }
}
void OverlayItem::line(QPointF a, QPointF b, const QColor& c, qreal width) {
    const QPointF p[2] = {a, b};
    polyline(p, false, c, width);
}
void OverlayItem::dashed(QPointF a, QPointF b, const QColor& c, qreal dash, qreal gap, qreal width) {
    const QPointF d = b - a;
    const qreal len = std::hypot(d.x(), d.y());
    if (len < 1e-6) return;
    const QPointF u = d / len;
    for (qreal t = 0; t < len; t += dash + gap) line(a + u * t, a + u * std::min(t + dash, len), c, width);
}
void OverlayItem::convexFill(std::span<const QPointF> pts, const QColor& c) {
    const size_t n = pts.size();
    if (n < 3) return;
    // Winding-independent feather: move each edge vertex along the direction from the centroid.
    QPointF center;
    for (const QPointF& p : pts) center += p;
    center /= qreal(n);
    const qreal k = window() ? 0.5 / window()->effectiveDevicePixelRatio() : 0.5;
    const quint32 mid = vertex(center, c);
    std::vector<quint32> in(n), out(n);
    for (size_t i = 0; i < n; ++i) {
        QPointF d = pts[i] - center;
        const qreal l = std::hypot(d.x(), d.y());
        d = l > 1e-9 ? d / l : QPointF();
        in[i] = vertex(pts[i] - d * k, c);
        out[i] = vertex(pts[i] + d * k, c, 0);
    }
    for (size_t i = 0; i < n; ++i) {
        const size_t j = (i + 1) % n;
        tri(mid, in[i], in[j]);
        tri(in[i], out[i], in[j]);
        tri(out[i], out[j], in[j]);
    }
}
void OverlayItem::quad(const QPointF (&corners)[4], const QColor& c) { convexFill(std::span<const QPointF>(corners, 4), c); }
void OverlayItem::rect(const QRectF& r, const QColor& c) {
    const quint32 a = vertex(r.topLeft(), c), b = vertex(r.topRight(), c), d = vertex(r.bottomLeft(), c), e = vertex(r.bottomRight(), c);
    tri(a, b, d);
    tri(b, e, d);
}
void OverlayItem::rectOutline(const QRectF& r, const QColor& c, qreal width) {
    const QPointF p[4] = {r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()};
    polyline(std::span<const QPointF>(p, 4), true, c, width);
}
void OverlayItem::disc(QPointF center, qreal radius, const QColor& c) {
    const int segs = std::clamp(int(radius * 5), 12, 48);
    std::vector<QPointF> pts(static_cast<size_t>(segs));
    for (int i = 0; i < segs; ++i) {
        const qreal t = i * 6.283185307179586 / segs;
        pts[size_t(i)] = center + QPointF(std::cos(t), std::sin(t)) * radius;
    }
    convexFill(pts, c);
}

QSGNode* OverlayItem::updatePaintNode(QSGNode* old, UpdatePaintNodeData*) {
    auto* node = static_cast<QSGGeometryNode*>(old);
    if (!node) {
        node = new QSGGeometryNode;
        auto* geo = new QSGGeometry(QSGGeometry::defaultAttributes_ColoredPoint2D(), 0, 0, QSGGeometry::UnsignedIntType);
        geo->setDrawingMode(QSGGeometry::DrawTriangles);
        geo->setVertexDataPattern(QSGGeometry::DynamicPattern);
        geo->setIndexDataPattern(QSGGeometry::DynamicPattern);
        node->setGeometry(geo);
        node->setFlag(QSGNode::OwnsGeometry);
        auto* mat = new QSGVertexColorMaterial;
        node->setMaterial(mat);
        node->setFlag(QSGNode::OwnsMaterial);
    }
    if (m_dirty) {
        m_dirty = false;
        QSGGeometry* geo = node->geometry();
        geo->allocate(int(m_v.size()), int(m_i.size()));
        if (!m_v.empty()) {
            static_assert(sizeof(Vertex) == sizeof(QSGGeometry::ColoredPoint2D));
            std::memcpy(geo->vertexData(), m_v.data(), m_v.size() * sizeof(Vertex));
            std::memcpy(geo->indexData(), m_i.data(), m_i.size() * sizeof(quint32));
        }
        node->markDirty(QSGNode::DirtyGeometry);
    }
    return node;
}
