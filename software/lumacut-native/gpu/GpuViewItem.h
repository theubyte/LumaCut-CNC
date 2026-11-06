#pragma once
#include <QColor>
#include <QPointF>
#include <QQuickRhiItem>
#include <QtQml/qqmlregistration.h>

/**
 * Base of the GPU views: one bed in millimetres (y down, origin top left, as in the editor model), a view
 * transform, and the sheet with grid and park corner. Everything here runs on the GUI thread; the renderer
 * takes a Snapshot in synchronize().
 *
 * Zoom and pan are plain properties. Resizing or changing the theme never rebuilds geometry.
 */
class GpuViewItem : public QQuickRhiItem {
    Q_OBJECT
    Q_PROPERTY(qreal bedWidth MEMBER m_bedW NOTIFY viewChanged)
    Q_PROPERTY(qreal bedHeight MEMBER m_bedH NOTIFY viewChanged)
    Q_PROPERTY(qreal zoom READ zoom WRITE setZoom NOTIFY viewChanged)       // item px per mm, 0 = fit the bed
    Q_PROPERTY(QPointF pan READ pan WRITE setPan NOTIFY viewChanged)        // item px, only used when zoom > 0
    Q_PROPERTY(qreal effectiveZoom READ effectiveZoom NOTIFY viewChanged)   // px per mm after fitting
    Q_PROPERTY(bool interactive MEMBER m_interactive NOTIFY interactiveChanged)  // wheel zooms at the cursor, drag pans
    Q_PROPERTY(bool continuous MEMBER m_continuous NOTIFY viewChanged)      // redraw every frame (benchmarks only)
    Q_PROPERTY(bool showSheet MEMBER m_showSheet NOTIFY viewChanged)
    Q_PROPERTY(bool showGrid MEMBER m_showGrid NOTIFY viewChanged)
    Q_PROPERTY(qreal parkWidth MEMBER m_parkW NOTIFY viewChanged)           // park corner, top right of the bed, mm
    Q_PROPERTY(qreal parkHeight MEMBER m_parkH NOTIFY viewChanged)
    Q_PROPERTY(QColor canvasColor MEMBER m_canvas NOTIFY viewChanged)       // around the sheet, default transparent
    Q_PROPERTY(QColor sheetColor MEMBER m_sheet NOTIFY viewChanged)
    Q_PROPERTY(QColor gridColor MEMBER m_grid NOTIFY viewChanged)
    Q_PROPERTY(QColor gridMajorColor MEMBER m_gridMajor NOTIFY viewChanged)
    Q_PROPERTY(QColor edgeColor MEMBER m_edge NOTIFY viewChanged)
    Q_PROPERTY(QColor parkColor MEMBER m_park NOTIFY viewChanged)
public:
    explicit GpuViewItem(QQuickItem* parent = nullptr);

    qreal zoom() const { return m_zoom; }
    void setZoom(qreal z);
    QPointF pan() const { return m_pan; }
    void setPan(QPointF p);
    qreal effectiveZoom() const { return view().zoom; }

    Q_INVOKABLE void fit();                                  // back to "whole bed"
    Q_INVOKABLE void zoomAt(QPointF itemPos, qreal factor);  // the point under itemPos stays where it is
    Q_INVOKABLE void panBy(QPointF deltaPx);
    Q_INVOKABLE QPointF mmToItem(QPointF mm) const;
    Q_INVOKABLE QPointF itemToMm(QPointF px) const;

    struct View { double zoom, panX, panY; };
    View view() const;

    /** What a renderer needs from the GUI thread, in device pixels. */
    struct Snapshot {
        double zoom = 1, panX = 0, panY = 0, dpr = 1, bedW = 370, bedH = 360, parkW = 0, parkH = 0;
        bool showSheet = true, showGrid = true, continuous = false;
        QColor canvas, sheet, grid, gridMajor, edge, park;
    };
    Snapshot snapshot() const;

signals:
    void viewChanged();
    void interactiveChanged();

protected:
    void wheelEvent(QWheelEvent* e) override;
    void mousePressEvent(QMouseEvent* e) override;
    void mouseMoveEvent(QMouseEvent* e) override;
    void mouseReleaseEvent(QMouseEvent* e) override;
    void geometryChange(const QRectF& now, const QRectF& old) override;

private:
    qreal m_bedW = 370, m_bedH = 360, m_zoom = 0, m_parkW = 78, m_parkH = 35;
    QPointF m_pan, m_dragLast;
    bool m_interactive = false, m_continuous = false, m_showSheet = true, m_showGrid = true, m_dragging = false;
    QColor m_canvas{0, 0, 0, 0}, m_sheet{255, 255, 255}, m_grid{64, 74, 128, 20}, m_gridMajor{64, 74, 128, 46},
           m_edge{0xcf, 0xd4, 0xe5}, m_park{207, 51, 64, 26};
};
