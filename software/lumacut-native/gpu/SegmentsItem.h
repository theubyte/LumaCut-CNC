#pragma once
#include <QAtomicInteger>
#include <QFutureWatcher>
#include <functional>
#include <memory>
#include <vector>
#include "GpuViewItem.h"

/** One straight piece of a toolpath in mm. power: 0 = travel, otherwise 0..1. */
struct GpuSegment { float x0, y0, x1, y1; float power; };

/**
 * GPU view of a toolpath (job preview). Each segment is one instance in one vertex buffer, so a million
 * segments cost one draw call, and playing a job only changes a count; nothing is uploaded again.
 *
 * Loading never blocks: setSegments() prepares the data on a worker thread and the render thread uploads it in
 * slices, a little per frame, drawing what has arrived so far. `loading` is true until the buffer is complete.
 *
 * Two looks, chosen per job from how much of its area it covers:
 *  - Vector (outlines): constant line width, always the real segments, culled by chunk when zoomed in.
 *  - Raster (engraving, hatching): zoomed out, the lines would beat against the pixel grid (moire). They are summed
 *    once by the GPU, at real line width, into a mipmapped "burn map", which shows the real average tone at any
 *    zoom and costs one quad per frame however many segments there are. Zoomed in past the map's resolution, the
 *    real segments are drawn instead, at their real width.
 *
 * Limit: 20 million segments (400 MB of GPU memory). Longer jobs are thinned on the worker by joining connected
 * neighbours; `decimated` is then true and `sourceCount` holds the original length. The job itself is not affected.
 */
class SegmentsItem : public GpuViewItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(int segmentCount READ segmentCount NOTIFY segmentsChanged)      // segments held for drawing
    Q_PROPERTY(int sourceCount READ sourceCount NOTIFY segmentsChanged)        // as handed in, before thinning
    Q_PROPERTY(bool decimated READ decimated NOTIFY segmentsChanged)
    Q_PROPERTY(bool rasterLook READ rasterLook NOTIFY segmentsChanged)
    Q_PROPERTY(bool loading READ loading NOTIFY loadingChanged)                // worker or upload still running
    Q_PROPERTY(int uploadedCount READ uploadedCount)                           // poll: progress of the upload
    Q_PROPERTY(QString renderMode READ renderMode)                             // poll: "direct" or "map"
    Q_PROPERTY(int drawnCount READ drawnCount)                                 // poll: segments drawn last frame, after culling
    Q_PROPERTY(int visibleCount READ visibleCount WRITE setVisibleCount NOTIFY visibleCountChanged)  // playback: -1 = all
    Q_PROPERTY(qreal pendingOpacity MEMBER m_pendingOpacity NOTIFY viewChanged)  // what is still to come, 0 = hidden
    Q_PROPERTY(bool burnMap MEMBER m_burnMap NOTIFY viewChanged)               // false: real segments at any zoom (to measure)
    Q_PROPERTY(bool showTravel READ showTravel WRITE setShowTravel NOTIFY viewChanged)
    Q_PROPERTY(qreal lineWidth MEMBER m_lineWidth NOTIFY viewChanged)          // vector look, item px
    Q_PROPERTY(qreal spotMm MEMBER m_spotMm NOTIFY viewChanged)                // raster look, width of the burnt line
    Q_PROPERTY(QColor cutColor MEMBER m_cut NOTIFY viewChanged)                // full power
    Q_PROPERTY(QColor lowColor MEMBER m_low NOTIFY viewChanged)                // low power; the same as cutColor = tone only
    Q_PROPERTY(QColor travelColor MEMBER m_travel NOTIFY viewChanged)
public:
    explicit SegmentsItem(QQuickItem* parent = nullptr);
    ~SegmentsItem() override;
    QQuickRhiItemRenderer* createRenderer() override;

    /** Takes the vector, returns at once. Replaces the current job as soon as the worker is done. */
    void setSegments(std::vector<GpuSegment> segs);
    void clear() { setSegments({}); }
    /** Benchmark content: dense raster rows with `count` segments, built on the worker. */
    Q_INVOKABLE void loadBenchmark(int count);

    int segmentCount() const;
    int sourceCount() const;
    bool decimated() const;
    bool rasterLook() const;
    bool loading() const { return m_loading; }
    int uploadedCount() const { return m_uploaded.loadRelaxed(); }
    int drawnCount() const { return m_drawn.loadRelaxed(); }
    QString renderMode() const { return m_mapShown.loadRelaxed() ? QStringLiteral("map") : QStringLiteral("direct"); }
    int visibleCount() const { return m_visible; }
    void setVisibleCount(int n);
    bool showTravel() const { return m_showTravel; }
    void setShowTravel(bool v);

    /** Prepared job: immutable, shared with the renderer, kept here so a new GPU device can upload it again. */
    struct Data {
        std::vector<GpuSegment> segs;
        std::vector<float> chunkBoxes;       // minX minY maxX maxY per kChunk segments
        float minX = 0, minY = 0, maxX = 0, maxY = 0;
        int sourceCount = 0;
        bool decimated = false, raster = false;
    };
    static constexpr int kChunk = 8192;
    static constexpr int kMaxSegments = 20'000'000;

signals:
    void segmentsChanged();
    void loadingChanged();
    void visibleCountChanged();

private:
    friend class SegmentsRenderer;
    void startWorker(std::function<std::vector<GpuSegment>()> make);
    void uploadFinished(const Data* d);
    std::shared_ptr<const Data> m_data;
    QFutureWatcher<std::shared_ptr<const Data>> m_watcher;
    quint64 m_generation = 0, m_dataVersion = 0;
    bool m_loading = false, m_workerBusy = false;
    std::function<std::vector<GpuSegment>()> m_nextWork;
    int m_visible = -1;
    bool m_showTravel = true, m_burnMap = true;
    qreal m_lineWidth = 1.25, m_spotMm = 0.1, m_pendingOpacity = 0;
    QColor m_cut{0x15, 0x18, 0x27}, m_low{0x15, 0x18, 0x27}, m_travel{0xb4, 0xbb, 0xd2};
    QAtomicInt m_uploaded = 0, m_drawn = 0, m_mapShown = 0;
};
