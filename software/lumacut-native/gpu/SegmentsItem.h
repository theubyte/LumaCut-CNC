#pragma once
#include <QQuickRhiItem>
#include <QColor>
#include <QPointF>
#include <vector>

/**
 * GPU view of a toolpath: each segment is one instance in one vertex buffer, so a million segments
 * cost one draw call. Scrubbing a job only changes the instance count, nothing is re-uploaded.
 */
struct GpuSegment { float x0, y0, x1, y1; float power; };  // power: 0 = travel, else 0..1

class SegmentsItem : public QQuickRhiItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(qreal bedWidth MEMBER m_bedW NOTIFY viewChanged)
    Q_PROPERTY(qreal bedHeight MEMBER m_bedH NOTIFY viewChanged)
    Q_PROPERTY(qreal zoom READ zoom WRITE setZoom NOTIFY viewChanged)   // px per mm, 0 = fit
    Q_PROPERTY(QPointF pan READ pan WRITE setPan NOTIFY viewChanged)
    Q_PROPERTY(int segmentCount READ segmentCount NOTIFY segmentsChanged)
    Q_PROPERTY(int visibleCount READ visibleCount WRITE setVisibleCount NOTIFY visibleCountChanged)
    Q_PROPERTY(bool showTravel READ showTravel WRITE setShowTravel NOTIFY viewChanged)
    Q_PROPERTY(QColor cutColor MEMBER m_cut NOTIFY viewChanged)
    Q_PROPERTY(QColor travelColor MEMBER m_travel NOTIFY viewChanged)
public:
    explicit SegmentsItem(QQuickItem* parent = nullptr);
    QQuickRhiItemRenderer* createRenderer() override;

    void setSegments(std::vector<GpuSegment> segs);
    /** Benchmark content: a dense raster-like path with `count` segments. */
    Q_INVOKABLE void loadBenchmark(int count);

    qreal zoom() const { return m_zoom; }
    void setZoom(qreal z);
    QPointF pan() const { return m_pan; }
    void setPan(QPointF p);
    int segmentCount() const { return int(m_segs.size()); }
    int visibleCount() const { return m_visible; }
    void setVisibleCount(int n);
    bool showTravel() const { return m_showTravel; }
    void setShowTravel(bool v);

signals:
    void viewChanged();
    void segmentsChanged();
    void visibleCountChanged();

private:
    friend class SegmentsRenderer;
    std::vector<GpuSegment> m_segs;
    quint64 m_dataVersion = 0;
    int m_visible = 0;
    qreal m_bedW = 370, m_bedH = 360, m_zoom = 0;
    QPointF m_pan;
    bool m_showTravel = true;
    QColor m_cut{0x15, 0x18, 0x27}, m_travel{0xb4, 0xbb, 0xd2};
};
