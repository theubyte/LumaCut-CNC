#include "GpuViewItem.h"
#include <QMouseEvent>
#include <QQuickWindow>
#include <QWheelEvent>
#include <algorithm>
#include <cmath>

GpuViewItem::GpuViewItem(QQuickItem* parent) : QQuickRhiItem(parent) {
    setAlphaBlending(true);
    connect(this, &GpuViewItem::viewChanged, this, [this] { update(); });
    connect(this, &GpuViewItem::interactiveChanged, this, [this] { setAcceptedMouseButtons(m_interactive ? Qt::AllButtons : Qt::NoButton); });
}

GpuViewItem::View GpuViewItem::view() const {
    if (m_zoom > 0) return {m_zoom, m_pan.x(), m_pan.y()};
    const double w = std::max(1.0, width()), h = std::max(1.0, height());
    const double z = std::min(w / m_bedW, h / m_bedH) * 0.96;
    return {z, (w - m_bedW * z) * 0.5, (h - m_bedH * z) * 0.5};
}
GpuViewItem::Snapshot GpuViewItem::snapshot() const {
    Snapshot s;
    const View v = view();
    s.dpr = window() ? window()->effectiveDevicePixelRatio() : 1.0;
    s.zoom = v.zoom * s.dpr; s.panX = v.panX * s.dpr; s.panY = v.panY * s.dpr;
    s.bedW = m_bedW; s.bedH = m_bedH; s.parkW = m_parkW; s.parkH = m_parkH;
    s.showSheet = m_showSheet; s.showGrid = m_showGrid; s.continuous = m_continuous;
    s.canvas = m_canvas; s.sheet = m_sheet; s.grid = m_grid; s.gridMajor = m_gridMajor; s.edge = m_edge; s.park = m_park;
    return s;
}
void GpuViewItem::setZoom(qreal z) { if (z != m_zoom) { m_zoom = z; emit viewChanged(); } }
void GpuViewItem::setPan(QPointF p) { if (p != m_pan) { m_pan = p; emit viewChanged(); } }
void GpuViewItem::fit() { m_zoom = 0; m_pan = {}; emit viewChanged(); }
void GpuViewItem::zoomAt(QPointF p, qreal factor) {
    const View v = view();
    const double fitted = std::min(std::max(1.0, width()) / m_bedW, std::max(1.0, height()) / m_bedH) * 0.96;
    const double z = std::clamp(v.zoom * factor, fitted * 0.5, 800.0);
    m_pan = {p.x() - (p.x() - v.panX) / v.zoom * z, p.y() - (p.y() - v.panY) / v.zoom * z};
    m_zoom = z;
    emit viewChanged();
}
void GpuViewItem::panBy(QPointF d) {
    const View v = view();
    m_zoom = v.zoom;
    m_pan = {v.panX + d.x(), v.panY + d.y()};
    emit viewChanged();
}
QPointF GpuViewItem::mmToItem(QPointF mm) const { const View v = view(); return {mm.x() * v.zoom + v.panX, mm.y() * v.zoom + v.panY}; }
QPointF GpuViewItem::itemToMm(QPointF px) const { const View v = view(); return {(px.x() - v.panX) / v.zoom, (px.y() - v.panY) / v.zoom}; }

void GpuViewItem::wheelEvent(QWheelEvent* e) {
    if (!m_interactive) { e->ignore(); return; }
    zoomAt(e->position(), std::pow(1.0015, e->angleDelta().y()));
    e->accept();
}
void GpuViewItem::mousePressEvent(QMouseEvent* e) { m_dragging = true; m_dragLast = e->position(); e->accept(); }
void GpuViewItem::mouseMoveEvent(QMouseEvent* e) {
    if (!m_dragging) return;
    panBy(e->position() - m_dragLast);
    m_dragLast = e->position();
    e->accept();
}
void GpuViewItem::mouseReleaseEvent(QMouseEvent* e) { m_dragging = false; e->accept(); }
void GpuViewItem::geometryChange(const QRectF& now, const QRectF& old) {
    QQuickRhiItem::geometryChange(now, old);
    if (now.size() != old.size()) emit viewChanged();
}
