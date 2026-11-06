#pragma once
#include <QAtomicInteger>
#include <QFutureWatcher>
#include <QImage>
#include <QPolygonF>
#include <QTransform>
#include <functional>
#include <memory>
#include <vector>
#include "GpuViewItem.h"

/** A layer of the document. The list order is the draw order, first = bottom. */
struct StageLayer {
    int id = 0;
    QColor color{0x4f, 0xd8, 0xb4};
    bool fill = false;           // true: the whole layer fills even-odd, like the hatching in the job
    bool visible = true;
    float fillOpacity = 0.42f;   // of the fill area
    float opacity = 1.0f;        // the whole layer, e.g. 0.4 for a layer without output
};

/**
 * A shape on a layer. Paths are polylines in element-local mm; a path counts as closed when its first and last point
 * coincide (as isClosed() in the model). Closed paths take part in the fill of a fill layer; open ones are only
 * stroked. Curves arrive flattened.
 */
struct StageElement {
    quint64 id = 0;
    int layer = 0;
    std::vector<std::vector<QPointF>> paths;
    QTransform transform;        // element-local mm to bed mm; moving an element needs no new geometry
    bool visible = true;
};

/** A bitmap on the bed. Drawn below all layers, in the order of first setImage(). */
struct StageImage {
    quint64 id = 0;
    QImage image;                // any format; alpha is honoured
    QTransform transform;        // from the unit square (0,0)-(1,1), y down, to bed mm
    float opacity = 1.0f;
    bool visible = true;
    bool below = false;          // goes under all other images, e.g. a camera background
};

/**
 * The editor's stage: sheet with grid and park corner, then images, filled layers, lines, selection.
 * All on the GPU: lines are instances (same technique as SegmentsItem), one draw call per layer; fills are
 * stencil-then-cover over the whole layer in even-odd; images are mipmapped textures. Element transform, visibility and
 * selection live in a small data texture, so changing them touches no geometry.
 *
 * Every call is GUI thread and returns at once. Coordinates: bed mm, y down, as in the model.
 *
 *   stage->setLayers(layers);                 // whenever colours, modes, order, visibility change
 *   stage->setElements(std::move(all));       // whole document: on a worker, never blocks, drawn when ready
 *   stage->upsertElement(e);                  // one element changed its shape, or is new
 *   stage->removeElements({id});
 *   stage->setTransforms({{id, t}, ...});     // dragging: cheap even for 100,000 elements, call on every mouse move
 *   stage->setElementVisible(id, false);      // e.g. hide while its live preview is drawn differently
 *   stage->setSelection({id, ...});           // highlight in selectionColor
 *   stage->setSelectionFrame(corners);        // 4 corners in bed mm, frame with 8 handles; empty = none
 *   stage->setMarquee(QRectF(...));           // rubber band, in bed mm; null = none
 *   stage->setImage(img); stage->removeImage(id);
 *   stage->setImageTransform(id, t);          // moving a picture: no conversion, no new texture
 *
 * View: properties zoom/pan, zoomAt(), panBy(), fit(), mmToItem(), itemToMm() from GpuViewItem. `interactive` = true
 * gives wheel zoom and drag pan straight away; leave it false if the editor routes the mouse itself. Text such as
 * rulers and the "Park-Ecke" label belongs in QML on top, placed with mmToItem().
 *
 * Calls made while setElements() is still working are kept and applied after it, in order.
 * After a lost GPU device everything is rebuilt from the data held here, without the editor doing anything.
 */
class StageItem : public GpuViewItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QColor selectionColor MEMBER m_selectionColor NOTIFY viewChanged)
    Q_PROPERTY(qreal lineWidth MEMBER m_lineWidth NOTIFY viewChanged)          // item px
    Q_PROPERTY(qreal selectedLineWidth MEMBER m_selectedWidth NOTIFY viewChanged)
    Q_PROPERTY(bool loading READ loading NOTIFY loadingChanged)                // worker or upload still running
    Q_PROPERTY(int elementCount READ elementCount)                             // poll, for tests
    Q_PROPERTY(int instanceCount READ instanceCount)                           // poll: line segments held
    Q_PROPERTY(int pendingUpload READ pendingUpload)                           // poll: segments not yet on the GPU
public:
    explicit StageItem(QQuickItem* parent = nullptr);
    ~StageItem() override;
    QQuickRhiItemRenderer* createRenderer() override;

    void setLayers(std::vector<StageLayer> layers);
    void setElements(std::vector<StageElement> elements);
    void upsertElement(StageElement element);
    void upsertElements(std::vector<StageElement> elements);
    void removeElements(std::vector<quint64> ids);
    void setTransforms(std::vector<std::pair<quint64, QTransform>> transforms);
    void setElementVisible(quint64 id, bool visible);
    void setSelection(std::vector<quint64> ids);
    void setSelectionFrame(QPolygonF corners);
    void setMarquee(QRectF rect);
    void setImage(StageImage image);
    void removeImage(quint64 id);
    void setImageTransform(quint64 id, QTransform transform);

    /** Test content on the worker: `paths` closed shapes of `segmentsPerPath` segments on a fill and a line layer. */
    Q_INVOKABLE void loadBenchmark(int paths, int segmentsPerPath);
    /** Test: move every `step`-th element by (dx, dy) through setTransforms. Returns the number moved. */
    Q_INVOKABLE int benchmarkMove(int step, qreal dx, qreal dy);
    /** Test: new shape for one element through upsertElement. */
    Q_INVOKABLE void benchmarkReshape(int index);
    /** Test: a small generated picture, so textures can be seen on screen. */
    Q_INVOKABLE void benchmarkImage();
    /** Test: two overlapping squares and an open path on a fill layer, ids 1, 2, 3, on a white bed without the rest. */
    Q_INVOKABLE void benchmarkEvenOdd();
    Q_INVOKABLE void benchmarkHide(int id) { setElementVisible(quint64(id), false); }
    /** Test: selects the first `n` elements and puts a frame around rect. */
    Q_INVOKABLE void benchmarkSelect(int n, QRectF frame);

    bool loading() const { return m_loading; }
    int elementCount() const { return m_elementCount.loadRelaxed(); }
    int instanceCount() const { return m_instanceCount.loadRelaxed(); }
    int pendingUpload() const { return m_pendingUpload.loadRelaxed(); }

    struct Scene;
    using Op = std::function<void(Scene&)>;

signals:
    void loadingChanged();

private:
    friend class StageRenderer;
    void push(Op op);
    void startWorker(std::function<std::shared_ptr<Scene>()> make);
    void workerDone();

    std::shared_ptr<Scene> m_scene;              // applied on sync, read by the renderer, survives a device change
    std::vector<Op> m_ops, m_held;
    QFutureWatcher<std::shared_ptr<Scene>> m_watcher;
    std::function<std::shared_ptr<Scene>()> m_nextWork;
    std::vector<StageLayer> m_layers;
    std::vector<QTransform> m_benchTransforms;   // test only
    std::vector<quint64> m_benchIds;
    bool m_workerBusy = false, m_loading = false;
    QColor m_selectionColor{0x4a, 0x57, 0xe3};
    qreal m_lineWidth = 1.25, m_selectedWidth = 1.75;
    QAtomicInt m_elementCount = 0, m_instanceCount = 0, m_pendingUpload = 0;
};
