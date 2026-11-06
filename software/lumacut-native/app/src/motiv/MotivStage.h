#pragma once
#include <QColor>
#include <QElapsedTimer>
#include <QHash>
#include <QTimer>
#include <QtQml/qqmlregistration.h>
#include <memory>
#include <optional>
#include <vector>
#include "Editor.h"
#include "OverlayItem.h"
#include "core/image.h"
#include "gpu/StageItem.h"

/**
 * The drawing surface: StageItem fed from the document, and everything the mouse and keyboard do on it. Dragging never
 * touches the document: elements move through StageItem::setTransforms, the result lands as one commit on release. So
 * moving 100,000 paths costs one texture update per frame. Handles, guides and drawn previews are on OverlayItem; text
 * labels are in QML, placed from the properties here.
 */
class MotivStage : public StageItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QColor accentColor MEMBER m_accent NOTIFY colorsChanged)
    Q_PROPERTY(QColor accentSoftColor MEMBER m_accentSoft NOTIFY colorsChanged)
    Q_PROPERTY(QColor surfaceColor MEMBER m_surface NOTIFY colorsChanged)
    Q_PROPERTY(QColor badColor MEMBER m_bad NOTIFY colorsChanged)
    Q_PROPERTY(QColor warnColor MEMBER m_warn NOTIFY colorsChanged)
    Q_PROPERTY(QString pillText READ pillText NOTIFY pillChanged)
    Q_PROPERTY(qreal pillX READ pillX NOTIFY pillChanged)
    Q_PROPERTY(qreal pillY READ pillY NOTIFY pillChanged)
    Q_PROPERTY(QPointF mouseItem READ mouseItem NOTIFY mouseItemChanged)
    Q_PROPERTY(bool mouseInside READ mouseInside NOTIFY mouseItemChanged)
    Q_PROPERTY(int zoomPercent READ zoomPercent NOTIFY viewChanged)
    Q_PROPERTY(double dragMs READ dragMs NOTIFY statsChanged)
    Q_PROPERTY(int scanCount READ scanCount NOTIFY statsChanged)
    Q_PROPERTY(bool hasDraft READ hasDraft NOTIFY pillChanged)
public:
    explicit MotivStage(QQuickItem* parent = nullptr);
    ~MotivStage() override;

    QString pillText() const { return m_pillText; }
    qreal pillX() const { return m_pillPos.x(); }
    qreal pillY() const { return m_pillPos.y(); }
    QPointF mouseItem() const { return m_mouseItem; }
    bool mouseInside() const { return m_mouseInside; }
    int zoomPercent() const;
    double dragMs() const { return m_lastDragMs; }
    int scanCount() const { return m_lastScan; }
    bool hasDraft() const { return !m_draft.empty(); }

    Q_INVOKABLE void fitBed();
    Q_INVOKABLE void fitSelection();
    Q_INVOKABLE void zoomCentered(qreal factor);
    Q_INVOKABLE bool escape();
    Q_INVOKABLE void finishDraft(bool closed);
    Q_INVOKABLE bool deleteActiveNode();
    Q_INVOKABLE QVariantMap frameInfo() const;
    /** For tests: a selected element's node in item px. */
    Q_INVOKABLE QPointF nodeItemPos(int path, int node) const;
    Q_INVOKABLE QPointF handleItemPos(const QString& handle) const;

signals:
    void colorsChanged();
    void pillChanged();
    void mouseItemChanged();
    void statsChanged();
    void contextMenuRequested(qreal sceneX, qreal sceneY);
    /** Strg+S and friends: new, open, save, saveLocal, import, export. */
    void fileKey(const QString& action);

protected:
    void mousePressEvent(QMouseEvent* e) override;
    void mouseMoveEvent(QMouseEvent* e) override;
    void mouseReleaseEvent(QMouseEvent* e) override;
    void hoverMoveEvent(QHoverEvent* e) override;
    void hoverLeaveEvent(QHoverEvent* e) override;
    void wheelEvent(QWheelEvent* e) override;
    bool eventFilter(QObject* watched, QEvent* event) override;
    void itemChange(ItemChange change, const ItemChangeData& data) override;
    void geometryChange(const QRectF& now, const QRectF& old) override;

private:
    enum class DragKind { None, Pan, Move, Scale, Rotate, Band, Shape, PenNode, Node, Measure };
    enum class Handle { None, NW, N, NE, E, SE, S, SW, W, Rot };
    struct Targets { std::vector<double> xs, ys; std::vector<lumacut::Pt> points; };
    struct SnapHit { double dx = 0, dy = 0; std::optional<double> gx, gy; };
    struct Drag {
        DragKind kind = DragKind::None;
        QPointF startPx, lastPx;
        lumacut::Pt start, a, b;
        bool started = false, dup = false, shift = false;
        int clickItem = -1;
        double dx = 0, dy = 0;
        lumacut::Box box{};
        Targets targets;
        std::vector<std::pair<quint64, QTransform>> base;      // vector elements of the selection, at the start
        std::vector<std::pair<quint64, QTransform>> imageBase; // pictures of the selection
        std::vector<std::pair<quint64, QTransform>> scratch;
        std::vector<QPointF> ghost;
        // scale / rotate
        Handle handle = Handle::None;
        SelFrame frame;
        double kx = 1, ky = 1, angle = 0, deg = 0, a0 = 0;
        lumacut::Pt anchor{};
        QTransform live;
        // node
        QString nodeEl;
        int path = 0, node = 0, which = 0;  // 0 node, 1 in, 2 out
        std::vector<lumacut::CurvePath> curves;
        bool moved = false;
    };

    void pressed(QMouseEvent* e);
    void doubleClicked(QPointF px);
    void pointerMoved(QPointF px, Qt::KeyboardModifiers mods);
    void pressSelect(QMouseEvent* e, QPointF px, lumacut::Pt w);
    void pressNode(QPointF px, lumacut::Pt w);
    void pressDraw(QMouseEvent* e, QPointF px, lumacut::Pt w);
    void dragMove(QPointF px, lumacut::Pt w, Qt::KeyboardModifiers mods);
    void dragScale(lumacut::Pt w, Qt::KeyboardModifiers mods);
    void dragRotate(lumacut::Pt w, Qt::KeyboardModifiers mods);
    void dragPen(QPointF px, lumacut::Pt w, Qt::KeyboardModifiers mods);
    void dragNode(QPointF px, lumacut::Pt w, Qt::KeyboardModifiers mods);
    void finishBand();
    void beginMoveBase();
    void applyLive(const QTransform& world);
    void cancelDrag();
    bool handleKey(QKeyEvent* e);
    void arrow(int key, double step, bool repeat);

    Targets targetsFor(bool excludeSelection) const;
    lumacut::Pt snapped(lumacut::Pt p, const Targets& t, bool ctrl);
    lumacut::Pt snapMeasure(lumacut::Pt w, const Targets& t) const;
    SnapHit snapAxisBox(const lumacut::Box& b, const Targets& t) const;
    double gridStep() const;
    lumacut::Box shapeBox() const;
    lumacut::Pt toWorld(QPointF px) const;
    QPointF toItem(lumacut::Pt p) const;
    QPointF toItem(QPointF mm) const { return mmToItem(mm); }
    Handle handleAt(QPointF px) const;
    QPointF handlePos(const SelFrame& f, Handle h) const;
    bool nodeHit(const lumacut::Element& e, const std::vector<lumacut::CurvePath>& curves, QPointF px, int& path, int& node, int& which) const;
    void updateCursor(QPointF px);
    void setPill(const QString& text, QPointF pos);
    void repaint();
    void rebuildOverlay();
    void paintFrame(const SelFrame& f, bool handles);
    void paintNodes(const lumacut::Element& e);
    void paintDraft();
    void addStroke(const lumacut::Element& e, const QColor& c, qreal width);

    void rebuildStage();
    void onSceneChanged(const SceneDelta& d);
    void syncSelection();
    void syncLayers();
    void syncBed();
    void syncBackground();
    void setStageImage(const SceneItem& it);
    void requestPreview(const SceneItem& it);
    void reAddImages();

    OverlayItem* m_overlay;
    Drag m_drag;
    QColor m_accent, m_accentSoft, m_surface, m_bad, m_warn;
    QString m_pillText;
    QPointF m_pillPos;
    QPointF m_mouseItem;
    bool m_mouseInside = false;
    bool m_space = false, m_fitted = true, m_measurePending = false;
    bool m_shift = false, m_alt = false;
    int m_hover = -1;
    std::optional<double> m_guideX, m_guideY;
    std::optional<lumacut::Pt> m_cursorWorld;
    std::vector<lumacut::CurveNode> m_draft;
    std::optional<std::pair<lumacut::Pt, lumacut::Pt>> m_measure;
    struct NodeRef { QString el; int path = 0, node = 0; };
    std::optional<NodeRef> m_nodeRef;
    QHash<QString, int> m_layerIds;
    int m_nextLayerId = 1;
    bool m_repaintQueued = false;
    double m_lastDragMs = 0;
    int m_lastScan = 0;

    struct ImageState {
        QImage preview;
        const void* data = nullptr;
        lumacut::ImageMode mode{};
        int b = 0, c = 0, s = 0;
        bool invert = false;
        bool busy = false, again = false;
        Document::ElementPtr wanted;
    };
    QHash<quint64, std::shared_ptr<ImageState>> m_images;
    bool m_bgShown = false;
};
