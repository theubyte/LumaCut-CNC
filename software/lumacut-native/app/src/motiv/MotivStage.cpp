#include "MotivStage.h"
#include "Fmt.h"
#include "Shell.h"
#include "Toast.h"
#include "core/parallel.h"
#include <QCursor>
#include <QGuiApplication>
#include <QHoverEvent>
#include <QKeyEvent>
#include <QMouseEvent>
#include <QQuickWindow>
#include <QWheelEvent>
#include <QtConcurrent/QtConcurrentRun>
#include <algorithm>
#include <cmath>

namespace lc = lumacut;
using lc::Box;
using lc::CurveNode;
using lc::CurvePath;
using lc::Element;
using lc::Pt;

namespace {
constexpr double kPi = 3.14159265358979323846;
constexpr double kPxPerMm100 = 96.0 / 25.4;
constexpr int kNodeLimit = 5000;
constexpr size_t kHoverPointLimit = 40000;
constexpr quint64 kBackgroundId = 1;
constexpr double kFitPad = 30;

QPointF qp(Pt p) { return {p.x, p.y}; }
Pt pt(QPointF p) { return {p.x(), p.y()}; }
QString num(double v, int digits = 1) { return Fmt::trim(v, digits); }
double dist(QPointF a, QPointF b) { return std::hypot(a.x() - b.x(), a.y() - b.y()); }

Pt constrain45(Pt a, Pt b) {
    const double dx = b.x - a.x, dy = b.y - a.y, l = std::hypot(dx, dy), s = kPi / 4, ang = std::round(std::atan2(dy, dx) / s) * s;
    return {a.x + std::cos(ang) * l, a.y + std::sin(ang) * l};
}
struct AxisHit { double d = 0; std::optional<double> guide; };
/** Best correction of probes onto lines; objects beat the grid. */
AxisHit axis(std::initializer_list<double> probes, const std::vector<double>& lines, std::initializer_list<double> gridProbes, double grid, double tol) {
    double best = 1e300;
    AxisHit hit;
    for (double p : probes) for (double l : lines) {
        const double q = std::abs(l - p);
        if (q < best && q <= tol) { best = q; hit.d = l - p; hit.guide = l; }
    }
    if (hit.guide || grid <= 0) return hit;
    for (double p : gridProbes) {
        const double l = std::round(p / grid) * grid, q = std::abs(l - p);
        if (q < best && q <= std::max(tol, grid / 2)) { best = q; hit.d = l - p; }
    }
    return hit;
}
QTransform aroundAxes(Pt anchor, double rotDeg, double kx, double ky) {
    QTransform t;
    t.translate(anchor.x, anchor.y);
    t.rotate(rotDeg);
    t.scale(kx, ky);
    t.rotate(-rotDeg);
    t.translate(-anchor.x, -anchor.y);
    return t;
}
StageElement toStage(const SceneItem& it, int layerId) {
    StageElement s;
    s.id = it.sid;
    s.layer = layerId;
    s.transform = Editor::matrixOf(it.e->transform);
    s.paths.reserve(it.e->paths.size());
    for (lc::PolyView poly : it.e->paths) {
        std::vector<QPointF>& out = s.paths.emplace_back(poly.size());
        for (size_t i = 0; i < poly.size(); ++i) out[i] = {poly[i].x, poly[i].y};
    }
    return s;
}
// Zoom and pan survive leaving the view, which destroys the item.
struct SavedView { bool valid = false, fitted = true; qreal zoom = 0; QPointF pan; };
SavedView s_view;
}  // namespace

MotivStage::MotivStage(QQuickItem* parent) : StageItem(parent), m_overlay(new OverlayItem(this)) {
    setAcceptedMouseButtons(Qt::LeftButton | Qt::RightButton | Qt::MiddleButton);
    setAcceptHoverEvents(true);
    m_overlay->setZ(10);
    auto* ed = Editor::instance();
    connect(ed, &Editor::sceneReset, this, &MotivStage::rebuildStage);
    connect(ed, &Editor::sceneChanged, this, &MotivStage::onSceneChanged);
    connect(ed, &Editor::selectionResolved, this, &MotivStage::syncSelection);
    connect(ed, &Editor::stageLayersChanged, this, &MotivStage::syncLayers);
    connect(ed, &Editor::bedChanged, this, &MotivStage::syncBed);
    connect(ed, &Editor::backgroundChanged, this, &MotivStage::syncBackground);
    connect(ed, &Editor::toolChanged, this, [this] {
        m_draft.clear();
        if (Editor::instance()->tool() != QLatin1String("node")) m_nodeRef.reset();
        if (Editor::instance()->tool() != QLatin1String("measure")) { m_measure.reset(); m_measurePending = false; }
        m_guideX.reset(); m_guideY.reset();
        setPill({}, {});
        updateCursor(m_mouseItem);
        repaint();
    });
    connect(ed, &Editor::warningsChanged, this, [this] { repaint(); });
    // A closed dialog gives the keys back to the stage.
    connect(ed, &Editor::dialogChanged, this, [this] { if (Editor::instance()->dialog().isEmpty()) forceActiveFocus(Qt::OtherFocusReason); });
    connect(Document::instance(), &Document::replaced, this, [this] { if (m_drag.kind != DragKind::None) { m_drag = {}; } m_draft.clear(); m_nodeRef.reset(); });
    connect(this, &GpuViewItem::viewChanged, this, [this] { repaint(); });
    connect(this, &MotivStage::colorsChanged, this, [this] { repaint(); });
    if (s_view.valid && !s_view.fitted) { setZoom(s_view.zoom); setPan(s_view.pan); m_fitted = false; }
    syncBed();
    syncLayers();
    rebuildStage();
    syncSelection();
    syncBackground();
}
MotivStage::~MotivStage() {
    s_view = {true, m_fitted, zoom(), pan()};
    if (window()) window()->removeEventFilter(this);
}

void MotivStage::itemChange(ItemChange change, const ItemChangeData& data) {
    StageItem::itemChange(change, data);
    if (change == ItemSceneChange) {
        // Keys hold wherever the focus is, as long as nothing is being typed; arrows never reach the jog keys here.
        if (data.window) data.window->installEventFilter(this);
    }
}
void MotivStage::geometryChange(const QRectF& now, const QRectF& old) {
    StageItem::geometryChange(now, old);
    m_overlay->setSize(now.size());
    if (m_fitted && now.size() != old.size() && now.width() > 0 && now.height() > 0) fitBed();
}
Pt MotivStage::toWorld(QPointF px) const { return pt(itemToMm(px)); }
QPointF MotivStage::toItem(Pt p) const { return mmToItem(qp(p)); }
int MotivStage::zoomPercent() const { return int(std::lround(effectiveZoom() / kPxPerMm100 * 100)); }

// ---- View ----

void MotivStage::fitBed() {
    const double W = Editor::instance()->bedW(), H = Editor::instance()->bedH();
    const double availW = width() - 2 * kFitPad, availH = height() - 2 * kFitPad;
    if (availW <= 0 || availH <= 0) return;
    const double z = std::min(availW / W, availH / H);
    setZoom(z);
    setPan({(width() - W * z) / 2, (height() - H * z) / 2});
    m_fitted = true;
}
void MotivStage::fitSelection() {
    const auto b = Editor::instance()->selectionBox();
    if (!b) { fitBed(); return; }
    const double pad = 56, w = std::max(b->width(), 1.0), h = std::max(b->height(), 1.0);
    const double z = std::clamp(std::min((width() - 2 * pad) / w, (height() - 2 * pad) / h), 0.3, 400.0);
    setZoom(z);
    setPan({(width() - w * z) / 2 - b->minX * z, (height() - h * z) / 2 - b->minY * z});
    m_fitted = false;
}
void MotivStage::zoomCentered(qreal factor) {
    m_fitted = false;
    zoomAt({width() / 2, height() / 2}, factor);
}
void MotivStage::wheelEvent(QWheelEvent* e) {
    m_fitted = false;
    zoomAt(e->position(), std::pow(1.0015, e->angleDelta().y()));
    e->accept();
}

// ---- Stage contents ----

void MotivStage::syncLayers() {
    auto* doc = Document::instance();
    std::vector<StageLayer> out;
    for (const lc::Layer& l : doc->layers()) {
        auto f = m_layerIds.constFind(l.id);
        if (f == m_layerIds.constEnd()) f = m_layerIds.insert(l.id, m_nextLayerId++);
        StageLayer s;
        s.id = *f;
        s.color = QColor::fromRgb(QRgb(quint32(l.color)));
        s.fill = l.mode == lc::LayerMode::Fill;
        s.visible = l.visible;
        s.fillOpacity = 0.42f;
        s.opacity = l.output ? 1.0f : 0.4f;
        out.push_back(s);
    }
    setLayers(std::move(out));
    for (const SceneItem& it : Editor::instance()->items()) if (it.e->isImage()) setStageImage(it);
    repaint();
}
void MotivStage::rebuildStage() {
    auto* ed = Editor::instance();
    auto* doc = Document::instance();
    m_hover = -1;
    QHash<quint64, std::shared_ptr<ImageState>> keptImages;
    for (auto it = m_images.begin(); it != m_images.end(); ++it) removeImage(it.key());
    m_images.clear();
    const auto& items = ed->items();
    // Every layer gets its number first; the conversion runs on all cores.
    std::vector<int> layerOf(doc->layers().size());
    for (size_t i = 0; i < layerOf.size(); ++i) {
        const QString& id = doc->layers()[i].id;
        auto f = m_layerIds.constFind(id);
        if (f == m_layerIds.constEnd()) f = m_layerIds.insert(id, m_nextLayerId++);
        layerOf[i] = *f;
    }
    std::vector<StageElement> all(items.size());
    std::vector<uint8_t> keep(items.size(), 0);
    lc::parallelBlocks(std::ptrdiff_t(items.size()), 256, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
        for (std::ptrdiff_t i = a; i < b; ++i) {
            const SceneItem& it = items[size_t(i)];
            if (it.e->isImage() || it.layer < 0) continue;
            all[size_t(i)] = toStage(it, layerOf[size_t(it.layer)]);
            keep[size_t(i)] = 1;
        }
    });
    std::vector<StageElement> kept;
    kept.reserve(items.size());
    for (size_t i = 0; i < items.size(); ++i) if (keep[i]) kept.push_back(std::move(all[i]));
    setElements(std::move(kept));
    for (const SceneItem& it : items) if (it.e->isImage()) requestPreview(it);
    repaint();
}
void MotivStage::onSceneChanged(const SceneDelta& d) {
    auto* ed = Editor::instance();
    auto* doc = Document::instance();
    m_hover = -1;
    const auto& items = ed->items();
    if (!d.removed.empty()) {
        std::vector<quint64> vectors;
        for (quint64 sid : d.removed) {
            if (m_images.contains(sid)) { removeImage(sid); m_images.remove(sid); }
            else vectors.push_back(sid);
        }
        if (!vectors.empty()) removeElements(std::move(vectors));
    }
    if (!d.moved.empty()) {
        std::vector<std::pair<quint64, QTransform>> t;
        t.reserve(d.moved.size());
        for (int i : d.moved) {
            const SceneItem& it = items[size_t(i)];
            if (it.e->isImage()) requestPreview(it);
            else t.emplace_back(it.sid, Editor::matrixOf(it.e->transform));
        }
        if (!t.empty()) setTransforms(std::move(t));
    }
    if (!d.upserts.empty()) {
        std::vector<StageElement> up;
        up.reserve(d.upserts.size());
        for (int i : d.upserts) {
            const SceneItem& it = items[size_t(i)];
            if (it.layer < 0) continue;
            if (it.e->isImage()) { requestPreview(it); continue; }
            const QString& layerId = doc->layers()[size_t(it.layer)].id;
            auto f = m_layerIds.constFind(layerId);
            if (f == m_layerIds.constEnd()) { f = m_layerIds.insert(layerId, m_nextLayerId++); syncLayers(); }
            up.push_back(toStage(it, *f));
        }
        if (!up.empty()) upsertElements(std::move(up));
    }
    repaint();
}
void MotivStage::syncSelection() {
    auto* ed = Editor::instance();
    std::vector<quint64> ids;
    ids.reserve(ed->selectedItems().size());
    for (int i : ed->selectedItems()) {
        const SceneItem& it = ed->items()[size_t(i)];
        if (!it.e->isImage()) ids.push_back(it.sid);
    }
    setSelection(std::move(ids));
    if (m_nodeRef) {
        const int n = ed->nodeItem();
        if (n < 0 || ed->items()[size_t(n)].e->id != m_nodeRef->el) m_nodeRef.reset();
    }
    repaint();
}
void MotivStage::syncBed() {
    auto* ed = Editor::instance();
    setProperty("bedWidth", ed->bedW());
    setProperty("bedHeight", ed->bedH());
    setProperty("parkWidth", ed->parkW());
    setProperty("parkHeight", ed->parkH());
    if (m_fitted) fitBed();
    syncBackground();
    repaint();
}
void MotivStage::syncBackground() {
    auto* ed = Editor::instance();
    if (ed->background().isNull()) return;
    StageImage bg;
    bg.id = kBackgroundId;
    bg.image = ed->background();
    bg.transform = QTransform::fromScale(ed->bedW(), ed->bedH());
    bg.opacity = float(ed->bgAlpha());
    bg.visible = ed->bgOn();
    bg.below = true;
    setImage(std::move(bg));
}
void MotivStage::setStageImage(const SceneItem& it) {
    const auto f = m_images.constFind(it.sid);
    if (f == m_images.constEnd() || (*f)->preview.isNull()) return;
    StageImage img;
    img.id = it.sid;
    img.image = (*f)->preview;
    img.transform = Editor::imageMatrixOf(*it.e);
    bool visible = true;
    float opacity = 1;
    if (it.layer >= 0) {
        const lc::Layer& l = Document::instance()->layers()[size_t(it.layer)];
        visible = l.visible;
        opacity = l.output ? 1.0f : 0.4f;
    }
    img.visible = visible;
    img.opacity = opacity;
    setImage(std::move(img));
}
void MotivStage::requestPreview(const SceneItem& it) {
    auto& slot = m_images[it.sid];
    if (!slot) slot = std::make_shared<ImageState>();
    const std::shared_ptr<ImageState> st = slot;
    const Element& e = *it.e;
    const void* data = e.raster.gray().data();
    const bool same = !st->preview.isNull() && st->data == data && st->mode == e.imageMode && st->b == e.adjust.brightness
        && st->c == e.adjust.contrast && st->s == e.adjust.sharpen && st->invert == e.adjust.invert;
    if (same && !st->busy) { setStageImage(it); return; }
    st->wanted = it.e;
    if (st->busy) { st->again = true; return; }
    st->busy = true;
    st->again = false;
    const Document::ElementPtr el = it.e;
    const quint64 sid = it.sid;
    QtConcurrent::run([el] {
        lc::PreviewOptions o;
        o.mode = el->imageMode;
        o.adjust = el->adjust;
        lc::PreviewImage p = lc::previewRgba(el->raster, o);
        QImage img(p.rgba.data(), p.width, p.height, p.width * 4, QImage::Format_RGBA8888);
        return img.convertToFormat(QImage::Format_RGBA8888_Premultiplied);
    }).then(this, [this, st, el, sid](QImage img) {
        st->busy = false;
        st->preview = std::move(img);
        st->data = el->raster.gray().data();
        st->mode = el->imageMode;
        st->b = el->adjust.brightness; st->c = el->adjust.contrast; st->s = el->adjust.sharpen; st->invert = el->adjust.invert;
        for (const SceneItem& cur : Editor::instance()->items()) {
            if (cur.sid != sid) continue;
            if (st->again) requestPreview(cur);
            else setStageImage(cur);
            break;
        }
    });
}

// ---- Snapping ----

MotivStage::Targets MotivStage::targetsFor(bool excludeSelection) const {
    auto* ed = Editor::instance();
    Targets t;
    const double W = ed->bedW(), H = ed->bedH();
    t.xs = {0, W / 2, W};
    t.ys = {0, H / 2, H};
    if (!ed->snapObjects()) return t;
    const auto& items = ed->items();
    const auto& ls = Document::instance()->layers();
    std::vector<uint8_t> skip;
    if (excludeSelection) {
        skip.assign(items.size(), 0);
        for (int i : ed->selectedItems()) skip[size_t(i)] = 1;
    }
    const Pt v0 = toWorld({0, 0}), v1 = toWorld({width(), height()});
    int boxes = 0;
    for (size_t i = 0; i < items.size() && boxes <= 3000; ++i) {
        const SceneItem& it = items[i];
        if (!it.hasBox || (excludeSelection && skip[i]) || it.layer < 0 || !ls[size_t(it.layer)].visible) continue;
        const Box& b = it.box;
        // What is off screen cannot be aimed at.
        if (b.maxX < v0.x || b.minX > v1.x || b.maxY < v0.y || b.minY > v1.y) continue;
        ++boxes;
        const double cx = (b.minX + b.maxX) / 2, cy = (b.minY + b.maxY) / 2;
        t.xs.insert(t.xs.end(), {b.minX, cx, b.maxX});
        t.ys.insert(t.ys.end(), {b.minY, cy, b.maxY});
        t.points.insert(t.points.end(), {{b.minX, b.minY}, {b.maxX, b.minY}, {b.maxX, b.maxY}, {b.minX, b.maxY}, {cx, cy}});
    }
    return t;
}
double MotivStage::gridStep() const {
    const double z = effectiveZoom();
    return z >= 25 ? 0.1 : z >= 1 ? 1 : 5;
}
Pt MotivStage::snapped(Pt p, const Targets& t, bool ctrl) {
    auto* ed = Editor::instance();
    m_guideX.reset(); m_guideY.reset();
    if (ctrl || (!ed->snapGrid() && !ed->snapObjects())) return p;
    const double tol = 6 / effectiveZoom(), grid = ed->snapGrid() ? gridStep() : 0;
    static const std::vector<double> none;
    const AxisHit x = axis({p.x}, ed->snapObjects() ? t.xs : none, {p.x}, grid, tol);
    const AxisHit y = axis({p.y}, ed->snapObjects() ? t.ys : none, {p.y}, grid, tol);
    m_guideX = x.guide; m_guideY = y.guide;
    return {p.x + x.d, p.y + y.d};
}
Pt MotivStage::snapMeasure(Pt w, const Targets& t) const {
    double q = 8 / effectiveZoom();
    Pt best = w;
    for (const Pt& p : t.points) {
        const double d = std::hypot(p.x - w.x, p.y - w.y);
        if (d < q) { q = d; best = p; }
    }
    return best;
}
MotivStage::SnapHit MotivStage::snapAxisBox(const Box& b, const Targets& t) const {
    auto* ed = Editor::instance();
    const double tol = 6 / effectiveZoom(), grid = ed->snapGrid() ? gridStep() : 0;
    static const std::vector<double> none;
    const AxisHit x = axis({b.minX, (b.minX + b.maxX) / 2, b.maxX}, ed->snapObjects() ? t.xs : none, {b.minX, b.maxX}, grid, tol);
    const AxisHit y = axis({b.minY, (b.minY + b.maxY) / 2, b.maxY}, ed->snapObjects() ? t.ys : none, {b.minY, b.maxY}, grid, tol);
    return {x.d, y.d, x.guide, y.guide};
}

// ---- Handles ----

QPointF MotivStage::handlePos(const SelFrame& f, Handle h) const {
    const QPointF a = mmToItem(f.corners[0]), b = mmToItem(f.corners[1]), c = mmToItem(f.corners[2]), d = mmToItem(f.corners[3]);
    switch (h) {
    case Handle::NW: return a;
    case Handle::N: return (a + b) / 2;
    case Handle::NE: return b;
    case Handle::E: return (b + c) / 2;
    case Handle::SE: return c;
    case Handle::S: return (c + d) / 2;
    case Handle::SW: return d;
    case Handle::W: return (d + a) / 2;
    case Handle::Rot: {
        const double r = (f.rot - 90) * kPi / 180;
        return (a + b) / 2 + QPointF(std::cos(r), std::sin(r)) * 24;
    }
    default: return {};
    }
}
static bool frameSmall(const QPointF& a, const QPointF& b, const QPointF& d) { return dist(a, b) < 28 || dist(a, d) < 28; }
MotivStage::Handle MotivStage::handleAt(QPointF px) const {
    const SelFrame& f = Editor::instance()->selFrame();
    if (!f.valid) return Handle::None;
    const bool small = frameSmall(mmToItem(f.corners[0]), mmToItem(f.corners[1]), mmToItem(f.corners[3]));
    for (Handle h : {Handle::Rot, Handle::NW, Handle::NE, Handle::SE, Handle::SW, Handle::N, Handle::E, Handle::S, Handle::W}) {
        if (small && (h == Handle::N || h == Handle::E || h == Handle::S || h == Handle::W)) continue;
        if (dist(handlePos(f, h), px) <= 7) return h;
    }
    return Handle::None;
}
void MotivStage::updateCursor(QPointF px) {
    auto* ed = Editor::instance();
    const QString& t = ed->tool();
    Qt::CursorShape c = Qt::ArrowCursor;
    if (m_drag.kind == DragKind::Pan) c = Qt::ClosedHandCursor;
    else if (m_space) c = Qt::OpenHandCursor;
    else if (t == QLatin1String("text")) c = Qt::IBeamCursor;
    else if (t == QLatin1String("measure") || t == QLatin1String("rect") || t == QLatin1String("ellipse") || t == QLatin1String("poly") || t == QLatin1String("pen")) c = Qt::CrossCursor;
    else if (t == QLatin1String("select")) {
        const Handle h = m_drag.kind == DragKind::None ? handleAt(px) : Handle::None;
        if (h == Handle::Rot) c = Qt::PointingHandCursor;
        else if (h != Handle::None) {
            static const QHash<int, double> angle = {{int(Handle::E), 0}, {int(Handle::SE), 45}, {int(Handle::S), 90}, {int(Handle::SW), 135}, {int(Handle::W), 180}, {int(Handle::NW), 225}, {int(Handle::N), 270}, {int(Handle::NE), 315}};
            const double a = std::fmod(angle.value(int(h)) + ed->selFrame().rot + 360 + 22.5, 180.0);
            static const Qt::CursorShape shapes[] = {Qt::SizeHorCursor, Qt::SizeFDiagCursor, Qt::SizeVerCursor, Qt::SizeBDiagCursor};
            c = shapes[int(a / 45) % 4];
        } else if (m_hover >= 0) c = Qt::SizeAllCursor;
    } else if (t == QLatin1String("node")) c = m_hover >= 0 ? Qt::PointingHandCursor : Qt::ArrowCursor;
    if (cursor().shape() != c) setCursor(c);
}
void MotivStage::setPill(const QString& text, QPointF pos) {
    if (text == m_pillText && pos == m_pillPos) return;
    m_pillText = text;
    m_pillPos = pos;
    emit pillChanged();
}

// ---- Pointer ----

void MotivStage::mousePressEvent(QMouseEvent* e) {
    e->accept();
    if (Editor::instance()->busy()) return;
    pressed(e);
}
void MotivStage::pressed(QMouseEvent* e) {
    const QPointF px = e->position();
    auto* ed = Editor::instance();
    // A click on the stage ends typing in the panels; keys come here from the window, wherever the focus is.
    forceActiveFocus(Qt::MouseFocusReason);
    m_shift = e->modifiers() & Qt::ShiftModifier;
    m_alt = e->modifiers() & Qt::AltModifier;
    if (e->button() == Qt::MiddleButton || (e->button() == Qt::LeftButton && m_space)) {
        m_drag = {};
        m_drag.kind = DragKind::Pan;
        m_drag.lastPx = px;
        updateCursor(px);
        return;
    }
    const Pt w = toWorld(px);
    if (e->button() == Qt::RightButton) {
        const int hit = ed->hitTest(w, 5 / effectiveZoom());
        if (hit >= 0 && !Document::instance()->isSelected(ed->items()[size_t(hit)].e->id)) ed->selectItems(ed->expandGroup(hit));
        const QPointF scene = mapToScene(px);
        emit contextMenuRequested(scene.x(), scene.y());
        return;
    }
    if (e->button() != Qt::LeftButton) return;
    const QString t = ed->tool();
    const bool ctrl = e->modifiers() & Qt::ControlModifier;
    if (t == QLatin1String("select")) pressSelect(e, px, w);
    else if (t == QLatin1String("node")) pressNode(px, w);
    else if (t == QLatin1String("rect") || t == QLatin1String("ellipse")) {
        m_drag = {};
        m_drag.kind = DragKind::Shape;
        m_drag.targets = targetsFor(false);
        m_drag.a = m_drag.b = snapped(w, m_drag.targets, ctrl);
        m_drag.startPx = px;
    } else if (t == QLatin1String("poly") || t == QLatin1String("pen")) pressDraw(e, px, w);
    else if (t == QLatin1String("text")) {
        const Targets targets = targetsFor(false);
        const Pt at = snapped(w, targets, ctrl);
        m_guideX.reset(); m_guideY.reset();
        ed->addTextAt(at);
        ed->setTool(QStringLiteral("select"));
    } else if (t == QLatin1String("measure")) {
        const Targets targets = targetsFor(false);
        const Pt p = snapMeasure(w, targets);
        if (m_measurePending && m_measure) { m_measure->second = p; m_measurePending = false; }
        else {
            m_measure = std::make_pair(p, p);
            m_drag = {};
            m_drag.kind = DragKind::Measure;
            m_drag.targets = targets;
        }
    }
    repaint();
}
void MotivStage::beginMoveBase() {
    auto* ed = Editor::instance();
    m_drag.base.clear();
    m_drag.imageBase.clear();
    m_drag.base.reserve(ed->selectedItems().size());
    for (int i : ed->selectedItems()) {
        const SceneItem& it = ed->items()[size_t(i)];
        if (it.e->isImage()) m_drag.imageBase.emplace_back(it.sid, Editor::imageMatrixOf(*it.e));
        else m_drag.base.emplace_back(it.sid, Editor::matrixOf(it.e->transform));
    }
}
void MotivStage::pressSelect(QMouseEvent* e, QPointF px, Pt w) {
    auto* ed = Editor::instance();
    auto* doc = Document::instance();
    const Handle h = doc->selectionCount() ? handleAt(px) : Handle::None;
    m_drag = {};
    if (h == Handle::Rot) {
        m_drag.kind = DragKind::Rotate;
        m_drag.frame = ed->selFrame();
        m_drag.a0 = std::atan2(w.y - m_drag.frame.center.y(), w.x - m_drag.frame.center.x());
        beginMoveBase();
        return;
    }
    if (h != Handle::None) {
        m_drag.kind = DragKind::Scale;
        m_drag.handle = h;
        m_drag.frame = ed->selFrame();
        m_drag.targets = targetsFor(true);
        beginMoveBase();
        return;
    }
    const int target = ed->hitTest(w, 5 / effectiveZoom());
    if (target < 0) {
        m_drag.kind = DragKind::Band;
        m_drag.a = m_drag.b = w;
        m_drag.shift = e->modifiers() & Qt::ShiftModifier;
        if (!m_drag.shift) doc->clearSelection();
        return;
    }
    const QString tid = ed->items()[size_t(target)].e->id;
    const bool inSel = doc->isSelected(tid), ctrl = e->modifiers() & Qt::ControlModifier, shift = e->modifiers() & Qt::ShiftModifier;
    const std::vector<int> ids = ctrl ? std::vector<int>{target} : ed->expandGroup(target);
    if (shift) {
        if (inSel) { ed->removeFromSelection(ids); return; }
        ed->addToSelection(ids);
    } else if (!inSel || ctrl) ed->selectItems(ids);
    const auto box = ed->selectionBox();
    if (!box) return;
    m_drag.kind = DragKind::Move;
    m_drag.box = *box;
    m_drag.start = w;
    m_drag.startPx = px;
    m_drag.dup = e->modifiers() & Qt::AltModifier;
    m_drag.clickItem = inSel && !shift && !ctrl ? target : -1;
    m_drag.targets = targetsFor(true);
    beginMoveBase();
}
bool MotivStage::nodeHit(const Element& e, const std::vector<CurvePath>& curves, QPointF px, int& pathOut, int& nodeOut, int& which) const {
    const auto near = [&](Pt p, double r) { return dist(mmToItem(qp(e.transform.apply(p))), px) <= r; };
    for (size_t pi = 0; pi < curves.size(); ++pi) for (size_t ni = 0; ni < curves[pi].nodes.size(); ++ni) {
        const CurveNode& n = curves[pi].nodes[ni];
        if (near({n.x, n.y}, 6)) { pathOut = int(pi); nodeOut = int(ni); which = 0; return true; }
    }
    for (size_t pi = 0; pi < curves.size(); ++pi) {
        const CurvePath& c = curves[pi];
        const int count = int(c.nodes.size());
        for (int ni = 0; ni < count; ++ni) {
            const CurveNode& n = c.nodes[size_t(ni)];
            const bool active = m_nodeRef && m_nodeRef->path == int(pi)
                && (m_nodeRef->node == ni || std::abs(m_nodeRef->node - ni) == 1 || std::abs(m_nodeRef->node - ni) == count - 1);
            if (!active && !(n.smooth && count <= 12)) continue;
            if (n.hasIn() && near(n.handleIn(), 6)) { pathOut = int(pi); nodeOut = ni; which = 1; return true; }
            if (n.hasOut() && near(n.handleOut(), 6)) { pathOut = int(pi); nodeOut = ni; which = 2; return true; }
        }
    }
    return false;
}
void MotivStage::pressNode(QPointF px, Pt w) {
    auto* ed = Editor::instance();
    auto* doc = Document::instance();
    const int item = ed->nodeItem();
    if (item >= 0) {
        const Element& el = *ed->items()[size_t(item)].e;
        auto curves = ed->curvesOf(el);
        int p = 0, n = 0, which = 0;
        if (lc::nodeCount(curves) <= kNodeLimit && nodeHit(el, curves, px, p, n, which)) {
            m_nodeRef = NodeRef{el.id, p, n};
            m_drag = {};
            m_drag.kind = DragKind::Node;
            m_drag.nodeEl = el.id;
            m_drag.path = p; m_drag.node = n; m_drag.which = which;
            m_drag.curves = std::move(curves);
            m_drag.startPx = px;
            m_drag.targets = targetsFor(true);
            repaint();
            return;
        }
    }
    const int target = ed->hitTest(w, 5 / effectiveZoom());
    if (target < 0) { doc->clearSelection(); m_nodeRef.reset(); return; }
    const Element& t = *ed->items()[size_t(target)].e;
    if (t.isImage()) { Toast::instance()->show(QStringLiteral("Bilder haben keine Knoten. Erst vektorisieren.")); return; }
    if (t.text) { Toast::instance()->show(QStringLiteral("Text hat keine Knoten. Rechtsklick: In Pfade umwandeln.")); return; }
    ed->selectItems({target});
    m_nodeRef.reset();
}
void MotivStage::pressDraw(QMouseEvent* e, QPointF px, Pt w) {
    if (!m_draft.empty()) {
        const QPointF s = toItem(Pt{m_draft.front().x, m_draft.front().y});
        if (m_draft.size() >= 2 && dist(s, px) <= 8) { finishDraft(true); return; }
    }
    m_drag = {};
    m_drag.kind = DragKind::PenNode;
    m_drag.startPx = px;
    m_drag.targets = targetsFor(false);
    Pt p = snapped(w, m_drag.targets, e->modifiers() & Qt::ControlModifier);
    if ((e->modifiers() & Qt::ShiftModifier) && !m_draft.empty()) p = constrain45({m_draft.back().x, m_draft.back().y}, p);
    CurveNode n;
    n.x = p.x; n.y = p.y;
    m_draft.push_back(n);
    emit pillChanged();
}
void MotivStage::finishDraft(bool closed) {
    auto* ed = Editor::instance();
    std::vector<CurveNode> nodes = std::move(m_draft);
    m_draft.clear();
    m_guideX.reset(); m_guideY.reset();
    setPill({}, {});
    if (nodes.size() < 2) { repaint(); return; }
    const bool pen = ed->tool() == QLatin1String("pen");
    const QString kind = pen ? QStringLiteral("Kurve") : nodes.size() == 2 && !closed ? QStringLiteral("Linie") : closed ? QStringLiteral("Polygon") : QStringLiteral("Linienzug");
    CurvePath path;
    path.closed = closed && nodes.size() >= 3;
    path.nodes = std::move(nodes);
    ed->addDrawn(kind, path);
    ed->setTool(QStringLiteral("select"));
}
void MotivStage::mouseMoveEvent(QMouseEvent* e) {
    e->accept();
    pointerMoved(e->position(), e->modifiers());
}
void MotivStage::hoverMoveEvent(QHoverEvent* e) {
    pointerMoved(e->position(), e->modifiers());
}
void MotivStage::hoverLeaveEvent(QHoverEvent*) {
    m_mouseInside = false;
    emit mouseItemChanged();
    Editor::instance()->setMouse(std::nullopt);
    if (m_hover != -1) { m_hover = -1; repaint(); }
}
void MotivStage::pointerMoved(QPointF px, Qt::KeyboardModifiers mods) {
    auto* ed = Editor::instance();
    m_shift = mods & Qt::ShiftModifier;
    m_alt = mods & Qt::AltModifier;
    const bool ctrl = mods & Qt::ControlModifier;
    const Pt w = toWorld(px);
    m_mouseItem = px;
    m_mouseInside = true;
    emit mouseItemChanged();
    ed->setMouse(w);
    switch (m_drag.kind) {
    case DragKind::None: {
        const QString& t = ed->tool();
        if (t == QLatin1String("select") || t == QLatin1String("node")) {
            const int h = ed->hitTest(w, 5 / effectiveZoom());
            if (h != m_hover) { m_hover = h; repaint(); }
        } else if (m_hover != -1) m_hover = -1;
        if (t == QLatin1String("poly") || t == QLatin1String("pen")) {
            Pt p = snapped(w, targetsFor(false), ctrl);
            if (m_shift && !m_draft.empty()) p = constrain45({m_draft.back().x, m_draft.back().y}, p);
            m_cursorWorld = p;
            repaint();
        } else if (t == QLatin1String("rect") || t == QLatin1String("ellipse")) {
            snapped(w, targetsFor(false), ctrl);
            repaint();
        }
        updateCursor(px);
        return;
    }
    case DragKind::Pan:
        m_fitted = false;
        panBy(px - m_drag.lastPx);
        m_drag.lastPx = px;
        break;
    case DragKind::Band: m_drag.b = w; break;
    case DragKind::Move: dragMove(px, w, mods); break;
    case DragKind::Scale: dragScale(w, mods); break;
    case DragKind::Rotate: dragRotate(w, mods); break;
    case DragKind::Shape: {
        if (dist(px, m_drag.startPx) > 3) m_drag.moved = true;
        m_drag.b = snapped(w, m_drag.targets, ctrl);
        const Box b = shapeBox();
        if (m_drag.moved) setPill(QStringLiteral("%1 × %2 mm").arg(num(b.width()), num(b.height())), toItem(Pt{b.minX, b.maxY}) + QPointF(0, 8));
        break;
    }
    case DragKind::PenNode: dragPen(px, w, mods); break;
    case DragKind::Node: dragNode(px, w, mods); break;
    case DragKind::Measure:
        if (m_measure) m_measure->second = snapMeasure(w, m_drag.targets);
        break;
    }
    repaint();
}
void MotivStage::applyLive(const QTransform& world) {
    QElapsedTimer timer;
    timer.start();
    auto& scratch = m_drag.scratch;
    const auto& base = m_drag.base;
    scratch.resize(base.size());
    lc::parallelBlocks(std::ptrdiff_t(base.size()), 2048, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
        for (std::ptrdiff_t i = a; i < b; ++i) scratch[size_t(i)] = {base[size_t(i)].first, base[size_t(i)].second * world};
    });
    if (!scratch.empty()) setTransforms(scratch);
    for (const auto& [id, m] : m_drag.imageBase) setImageTransform(id, m * world);
    m_lastDragMs = timer.nsecsElapsed() / 1e6;
    m_lastScan = int(base.size());
    emit statsChanged();
}
void MotivStage::dragMove(QPointF px, Pt w, Qt::KeyboardModifiers mods) {
    auto* ed = Editor::instance();
    auto* doc = Document::instance();
    Drag& d = m_drag;
    if (!d.started) {
        if (dist(px, d.startPx) < 3) return;
        d.started = true;
        if (d.dup) {
            // Copies stay where they are; the copies are what moves. Undo takes back copy and move as one.
            doc->checkpoint();
            ed->spawnCopies();
            beginMoveBase();
        }
    }
    double dx = w.x - d.start.x, dy = w.y - d.start.y;
    const bool shift = mods & Qt::ShiftModifier;
    if (shift) { if (std::abs(dx) > std::abs(dy)) dy = 0; else dx = 0; }
    m_guideX.reset(); m_guideY.reset();
    if (!(mods & Qt::ControlModifier) && (ed->snapGrid() || ed->snapObjects())) {
        const SnapHit h = snapAxisBox({d.box.minX + dx, d.box.minY + dy, d.box.maxX + dx, d.box.maxY + dy}, d.targets);
        if (!shift || dx != 0) { dx += h.dx; m_guideX = h.gx; }
        if (!shift || dy != 0) { dy += h.dy; m_guideY = h.gy; }
    }
    d.dx = dx; d.dy = dy;
    applyLive(QTransform::fromTranslate(dx, dy));
    const Box now{d.box.minX + dx, d.box.minY + dy, d.box.maxX + dx, d.box.maxY + dy};
    ed->setLiveBox(now);
    setPill(QStringLiteral("X %1   Y %2 mm").arg(num(now.minX), num(now.minY)), toItem(Pt{now.minX, now.maxY}) + QPointF(0, 10));
}
void MotivStage::dragScale(Pt w, Qt::KeyboardModifiers mods) {
    auto* ed = Editor::instance();
    Drag& d = m_drag;
    const SelFrame& f = d.frame;
    const double r = f.rot * kPi / 180;
    const QPointF u(std::cos(r), std::sin(r)), n(-u.y(), u.x());
    const auto corner = [&](Handle h) -> QPointF {
        switch (h) {
        case Handle::NW: return f.corners[0];
        case Handle::N: return (f.corners[0] + f.corners[1]) / 2;
        case Handle::NE: return f.corners[1];
        case Handle::E: return (f.corners[1] + f.corners[2]) / 2;
        case Handle::SE: return f.corners[2];
        case Handle::S: return (f.corners[2] + f.corners[3]) / 2;
        case Handle::SW: return f.corners[3];
        default: return (f.corners[3] + f.corners[0]) / 2;
        }
    };
    static const QHash<int, int> opposite = {{int(Handle::NW), int(Handle::SE)}, {int(Handle::N), int(Handle::S)}, {int(Handle::NE), int(Handle::SW)}, {int(Handle::E), int(Handle::W)},
                                             {int(Handle::SE), int(Handle::NW)}, {int(Handle::S), int(Handle::N)}, {int(Handle::SW), int(Handle::NE)}, {int(Handle::W), int(Handle::E)}};
    const QPointF anchor = (mods & Qt::AltModifier) ? f.center : corner(Handle(opposite.value(int(d.handle))));
    const QPointF grab = corner(d.handle);
    const bool axisAligned = std::abs(std::fmod(f.rot, 90.0)) < 1e-6;
    const Pt p = axisAligned ? snapped(w, d.targets, mods & Qt::ControlModifier) : w;
    const auto dot = [](QPointF a, QPointF b) { return a.x() * b.x() + a.y() * b.y(); };
    const QPointF o = grab - anchor, c = qp(p) - anchor;
    const bool hasX = d.handle == Handle::NW || d.handle == Handle::NE || d.handle == Handle::SE || d.handle == Handle::SW || d.handle == Handle::E || d.handle == Handle::W;
    const bool hasY = d.handle == Handle::NW || d.handle == Handle::NE || d.handle == Handle::SE || d.handle == Handle::SW || d.handle == Handle::N || d.handle == Handle::S;
    const double ox = dot(o, u), oy = dot(o, n);
    double kx = hasX && std::abs(ox) > 1e-6 ? std::max(dot(c, u) / ox, 0.005) : 1, ky = hasY && std::abs(oy) > 1e-6 ? std::max(dot(c, n) / oy, 0.005) : 1;
    if (hasX && hasY && ed->lockAspect() != bool(mods & Qt::ShiftModifier)) kx = ky = std::max(kx, ky);
    d.started = true;
    d.kx = kx; d.ky = ky;
    d.anchor = pt(anchor);
    d.live = aroundAxes(d.anchor, f.rot, kx, ky);
    applyLive(d.live);
    Box box{1e300, 1e300, -1e300, -1e300};
    for (const QPointF& q : f.corners) {
        const QPointF m = d.live.map(q);
        box.minX = std::min(box.minX, m.x()); box.maxX = std::max(box.maxX, m.x());
        box.minY = std::min(box.minY, m.y()); box.maxY = std::max(box.maxY, m.y());
    }
    if (f.single) {
        const double w0 = dist(f.corners[0], f.corners[1]) * kx, h0 = dist(f.corners[0], f.corners[3]) * ky;
        setPill(QStringLiteral("%1 × %2 mm").arg(num(w0), num(h0)), toItem(Pt{box.minX, box.maxY}) + QPointF(0, 10));
    } else {
        setPill(QStringLiteral("%1 × %2 mm").arg(num(box.width()), num(box.height())), toItem(Pt{box.minX, box.maxY}) + QPointF(0, 10));
    }
    ed->setLiveBox(box);
}
void MotivStage::dragRotate(Pt w, Qt::KeyboardModifiers mods) {
    Drag& d = m_drag;
    const SelFrame& f = d.frame;
    double deg = (std::atan2(w.y - f.center.y(), w.x - f.center.x()) - d.a0) * 180 / kPi;
    if (mods & Qt::ShiftModifier) deg = std::round(deg / 15) * 15;
    deg = std::fmod(deg + 540, 360) - 180;
    if (deg < -180) deg += 360;
    if (!d.started && std::abs(deg) < 0.2) return;
    d.started = true;
    d.deg = deg;
    d.angle = f.single ? std::fmod(f.rot + deg + 540, 360) - 180 : deg;
    QTransform t;
    t.translate(f.center.x(), f.center.y());
    t.rotate(deg);
    t.translate(-f.center.x(), -f.center.y());
    d.live = t;
    applyLive(t);
    const QPointF c0 = t.map(f.corners[0]), c3 = t.map(f.corners[3]), c2 = t.map(f.corners[2]);
    setPill(QStringLiteral("%1°").arg(num(d.angle)), mmToItem(c0.y() > c3.y() ? c0 : c3) + QPointF(0, 10 + std::max(0.0, (c2.y() - c3.y()) * effectiveZoom())));
}
void MotivStage::dragPen(QPointF px, Pt w, Qt::KeyboardModifiers mods) {
    Drag& d = m_drag;
    if (m_draft.empty()) return;
    if (dist(px, d.startPx) > 3) d.moved = true;
    if (!d.moved) return;
    if (Editor::instance()->tool() == QLatin1String("poly")) {
        m_cursorWorld = snapped(w, d.targets, mods & Qt::ControlModifier);
        return;
    }
    CurveNode& n = m_draft.back();
    const Pt p = (mods & Qt::ShiftModifier) ? constrain45({n.x, n.y}, w) : w;
    n.hx2 = p.x; n.hy2 = p.y;
    n.hx1 = 2 * n.x - p.x; n.hy1 = 2 * n.y - p.y;
    n.smooth = true;
}
void MotivStage::dragNode(QPointF px, Pt w, Qt::KeyboardModifiers mods) {
    auto* ed = Editor::instance();
    Drag& d = m_drag;
    if (!d.started) {
        if (dist(px, d.startPx) < 2) return;
        d.started = true;
        Document::instance()->checkpoint();
    }
    const auto ptr = Document::instance()->elementPtr(d.nodeEl);
    if (!ptr) return;
    const Pt local = ptr->transform.invert(snapped(w, d.targets, mods & Qt::ControlModifier));
    std::vector<CurvePath> curves = d.curves;
    curves[size_t(d.path)] = d.which == 0 ? lc::moveNode(curves[size_t(d.path)], size_t(d.node), local) : lc::moveHandle(curves[size_t(d.path)], size_t(d.node), d.which == 2, local);
    ed->applyCurves(d.nodeEl, curves, false);
}
Box MotivStage::shapeBox() const {
    const Drag& d = m_drag;
    double w = d.b.x - d.a.x, h = d.b.y - d.a.y;
    if (m_shift) {
        const double s = std::max(std::abs(w), std::abs(h));
        w = (w < 0 ? -1 : 1) * s;
        h = (h < 0 ? -1 : 1) * s;
    }
    if (m_alt) return {d.a.x - std::abs(w), d.a.y - std::abs(h), d.a.x + std::abs(w), d.a.y + std::abs(h)};
    return {std::min(d.a.x, d.a.x + w), std::min(d.a.y, d.a.y + h), std::max(d.a.x, d.a.x + w), std::max(d.a.y, d.a.y + h)};
}
void MotivStage::mouseReleaseEvent(QMouseEvent* e) {
    e->accept();
    auto* ed = Editor::instance();
    auto* doc = Document::instance();
    Drag d = std::move(m_drag);
    m_drag = {};
    m_guideX.reset(); m_guideY.reset();
    setPill({}, {});
    switch (d.kind) {
    case DragKind::Band: {
        const bool crossing = d.b.x < d.a.x;
        const double x0 = std::min(d.a.x, d.b.x), x1 = std::max(d.a.x, d.b.x), y0 = std::min(d.a.y, d.b.y), y1 = std::max(d.a.y, d.b.y);
        const double z = effectiveZoom();
        if ((x1 - x0) * z < 2 && (y1 - y0) * z < 2) break;
        const auto& items = ed->items();
        std::vector<int> hits;
        QSet<QString> groups;
        for (size_t i = 0; i < items.size(); ++i) {
            const SceneItem& it = items[i];
            if (!it.hasBox || !ed->editableItem(int(i))) continue;
            const Box& b = it.box;
            const bool hit = crossing ? b.maxX >= x0 && b.minX <= x1 && b.maxY >= y0 && b.minY <= y1 : b.minX >= x0 && b.maxX <= x1 && b.minY >= y0 && b.maxY <= y1;
            if (!hit) continue;
            hits.push_back(int(i));
            if (it.e->groupId) groups.insert(*it.e->groupId);
        }
        if (!groups.isEmpty()) for (size_t i = 0; i < items.size(); ++i) {
            if (items[i].e->groupId && groups.contains(*items[i].e->groupId) && std::find(hits.begin(), hits.end(), int(i)) == hits.end()) hits.push_back(int(i));
        }
        if (d.shift) ed->addToSelection(hits); else ed->selectItems(hits);
        break;
    }
    case DragKind::Move:
        if (d.started) {
            ed->setLiveBox(std::nullopt);
            ed->applyMove(d.dx, d.dy, d.dup);
        } else if (d.clickItem >= 0 && d.clickItem < int(ed->items().size())) {
            const std::vector<int> ids = ed->expandGroup(d.clickItem);
            if (ids.size() < ed->selectedItems().size()) ed->selectItems(ids);
        }
        break;
    case DragKind::Scale:
        if (d.started) {
            ed->setLiveBox(std::nullopt);
            ed->applyScale(d.anchor, d.kx, d.ky, d.frame.single);
        }
        break;
    case DragKind::Rotate:
        if (d.started) {
            ed->setLiveBox(std::nullopt);
            ed->applyRotate({d.frame.center.x(), d.frame.center.y()}, d.deg);
        }
        break;
    case DragKind::Shape: {
        m_drag = d;
        const Box b = d.moved ? shapeBox() : Box{d.a.x, d.a.y, d.a.x + 30, d.a.y + 30};
        m_drag = {};
        if (b.width() > 0.05 && b.height() > 0.05) {
            if (ed->tool() == QLatin1String("rect")) ed->addRect(b); else ed->addEllipse(b);
        }
        ed->setTool(QStringLiteral("select"));
        break;
    }
    case DragKind::PenNode:
        if (ed->tool() == QLatin1String("poly") && d.moved && m_draft.size() == 1 && m_cursorWorld) {
            CurveNode n;
            n.x = m_cursorWorld->x; n.y = m_cursorWorld->y;
            m_draft.push_back(n);
            finishDraft(false);
        }
        break;
    case DragKind::Node:
        break;
    case DragKind::Measure:
        if (m_measure && dist(toItem(m_measure->first), toItem(m_measure->second)) < 3) m_measurePending = true;
        break;
    default:
        break;
    }
    (void)doc;
    updateCursor(e->position());
    repaint();
}
void MotivStage::doubleClicked(QPointF px) {
    auto* ed = Editor::instance();
    auto* doc = Document::instance();
    const Pt w = toWorld(px);
    const QString t = ed->tool();
    if (t == QLatin1String("poly") || t == QLatin1String("pen")) {
        if (m_draft.size() >= 2) {
            // The second click of the double click already added a node on the same spot.
            const CurveNode& a = m_draft[m_draft.size() - 1];
            const CurveNode& b = m_draft[m_draft.size() - 2];
            if (std::hypot(a.x - b.x, a.y - b.y) * effectiveZoom() < 6) m_draft.pop_back();
        }
        finishDraft(false);
        return;
    }
    if (t == QLatin1String("select")) {
        const int hit = ed->hitTest(w, 5 / effectiveZoom());
        if (hit < 0) return;
        const Element& el = *ed->items()[size_t(hit)].e;
        if (el.text) { ed->selectItems({hit}); emit ed->focusTextRequested(); return; }
        if (!el.isImage()) { ed->selectItems({hit}); ed->setTool(QStringLiteral("node")); }
        return;
    }
    if (t == QLatin1String("node")) {
        const int item = ed->nodeItem();
        if (item < 0) return;
        const Element& el = *ed->items()[size_t(item)].e;
        const QString id = el.id;
        auto curves = ed->curvesOf(el);
        int p = 0, n = 0, which = 0;
        if (nodeHit(el, curves, px, p, n, which) && which == 0) {
            curves[size_t(p)] = lc::toggleSmooth(curves[size_t(p)], size_t(n));
            ed->applyCurves(id, curves, true);
            return;
        }
        const Pt q = el.transform.invert(w);
        int bestPath = -1;
        lc::CurveHit best{0, 0, 1e300};
        for (size_t i = 0; i < curves.size(); ++i) {
            const auto h = lc::nearestOnCurve(curves[i], q);
            if (h && h->dist < best.dist) { best = *h; bestPath = int(i); }
        }
        if (bestPath >= 0 && best.dist * effectiveZoom() * std::abs(el.transform.scaleX) < 8) {
            curves[size_t(bestPath)] = lc::insertNode(curves[size_t(bestPath)], best.span, best.t);
            ed->applyCurves(id, curves, true);
            m_nodeRef = NodeRef{id, bestPath, int(best.span) + 1};
            repaint();
        }
    }
    (void)doc;
}
void MotivStage::cancelDrag() {
    auto* ed = Editor::instance();
    Drag d = std::move(m_drag);
    m_drag = {};
    m_guideX.reset(); m_guideY.reset();
    setPill({}, {});
    if (d.started && (d.kind == DragKind::Move || d.kind == DragKind::Scale || d.kind == DragKind::Rotate)) {
        ed->setLiveBox(std::nullopt);
        setTransforms(d.base);
        for (const auto& [id, m] : d.imageBase) setImageTransform(id, m);
        if (d.kind == DragKind::Move && d.dup) Document::instance()->undo();
    }
    if (d.kind == DragKind::Node && d.started) Document::instance()->undo();
    repaint();
}
bool MotivStage::escape() {
    auto* ed = Editor::instance();
    if (m_drag.kind != DragKind::None) { cancelDrag(); return true; }
    if (!m_draft.empty()) { m_draft.clear(); emit pillChanged(); repaint(); return true; }
    if (m_measure) { m_measure.reset(); m_measurePending = false; repaint(); return true; }
    if (ed->tool() != QLatin1String("select")) { ed->setTool(QStringLiteral("select")); return true; }
    if (Document::instance()->selectionCount()) { Document::instance()->clearSelection(); return true; }
    return false;
}
bool MotivStage::deleteActiveNode() {
    auto* ed = Editor::instance();
    if (!m_nodeRef) return false;
    const auto ptr = Document::instance()->elementPtr(m_nodeRef->el);
    if (!ptr) return false;
    auto curves = ed->curvesOf(*ptr);
    if (m_nodeRef->path >= int(curves.size())) return false;
    const auto c = lc::deleteNode(curves[size_t(m_nodeRef->path)], size_t(m_nodeRef->node));
    if (!c) { Toast::instance()->show(QStringLiteral("Weniger Knoten geht bei dieser Form nicht")); return true; }
    curves[size_t(m_nodeRef->path)] = *c;
    const QString id = m_nodeRef->el;
    m_nodeRef.reset();
    ed->applyCurves(id, curves, true);
    return true;
}

// ---- Keys ----

bool MotivStage::eventFilter(QObject* watched, QEvent* event) {
    if (watched != window()) return false;
    if (event->type() == QEvent::MouseButtonDblClick) {
        // Items do not get double clicks reliably here; the window always does.
        auto* m = static_cast<QMouseEvent*>(event);
        const QPointF px = mapFromScene(m->scenePosition());
        if (m->button() == Qt::LeftButton && isVisible() && contains(px) && !Shell::instance()->modalOpen() && !Editor::instance()->busy()) doubleClicked(px);
        return false;
    }
    if (event->type() != QEvent::KeyPress && event->type() != QEvent::KeyRelease) return false;
    auto* e = static_cast<QKeyEvent*>(event);
    if (!isVisible() || Shell::instance()->modalOpen() || Shell::instance()->typing()) {
        if (e->key() == Qt::Key_Space && event->type() == QEvent::KeyRelease) m_space = false;
        return false;
    }
    if (e->key() == Qt::Key_Space) {
        m_space = event->type() == QEvent::KeyPress;
        updateCursor(m_mouseItem);
        return true;
    }
    if (event->type() == QEvent::KeyRelease) return false;
    return handleKey(e);
}
void MotivStage::arrow(int key, double step, bool repeat) {
    auto* ed = Editor::instance();
    auto* doc = Document::instance();
    if (!doc->selectionCount()) return;
    const double dx = key == Qt::Key_Left ? -step : key == Qt::Key_Right ? step : 0, dy = key == Qt::Key_Up ? -step : key == Qt::Key_Down ? step : 0;
    // Held down counts as one undo step.
    ed->applyMove(dx, dy, repeat);
}
bool MotivStage::handleKey(QKeyEvent* e) {
    auto* ed = Editor::instance();
    auto* doc = Document::instance();
    const auto mods = e->modifiers() & (Qt::ControlModifier | Qt::ShiftModifier | Qt::AltModifier | Qt::MetaModifier);
    const int key = e->key();
    if (key == Qt::Key_Pause) return false;   // NOT-AUS, always the shell's
    // While dragging or while a calculation runs, only Esc: nothing may change under the hand.
    if (m_drag.kind != DragKind::None) { if (key == Qt::Key_Escape) { cancelDrag(); return true; } return false; }
    if (ed->busy()) return false;
    if (mods & Qt::ControlModifier) {
        const bool shift = mods & Qt::ShiftModifier;
        switch (key) {
        case Qt::Key_Z: if (shift) doc->redo(); else doc->undo(); return true;
        case Qt::Key_Y: doc->redo(); return true;
        case Qt::Key_A: ed->selectAll(); return true;
        case Qt::Key_C: ed->copySel(); return true;
        case Qt::Key_X: ed->cutSel(); return true;
        case Qt::Key_V: ed->paste(); return true;
        case Qt::Key_D: ed->duplicate(); return true;
        case Qt::Key_G: if (shift) ed->ungroup(); else ed->group(); return true;
        case Qt::Key_Equal: case Qt::Key_Plus: zoomCentered(1.25); return true;
        case Qt::Key_Minus: zoomCentered(0.8); return true;
        case Qt::Key_Left: case Qt::Key_Right: case Qt::Key_Up: case Qt::Key_Down: arrow(key, 10, e->isAutoRepeat()); return true;
        case Qt::Key_S: emit fileKey(shift ? QStringLiteral("saveLocal") : QStringLiteral("save")); return true;
        case Qt::Key_O: emit fileKey(QStringLiteral("open")); return true;
        case Qt::Key_N: emit fileKey(QStringLiteral("new")); return true;
        case Qt::Key_I: emit fileKey(QStringLiteral("import")); return true;
        case Qt::Key_E: emit fileKey(QStringLiteral("export")); return true;
        default: return false;   // Strg+1..6 in the shell
        }
    }
    if (mods & Qt::AltModifier) return false;
    switch (key) {
    case Qt::Key_Left: case Qt::Key_Right: case Qt::Key_Up: case Qt::Key_Down:
        arrow(key, (mods & Qt::ShiftModifier) ? 1 : 0.1, e->isAutoRepeat());
        return true;
    case Qt::Key_Delete: case Qt::Key_Backspace:
        if (!m_draft.empty()) { m_draft.pop_back(); emit pillChanged(); repaint(); return true; }
        if (ed->tool() == QLatin1String("node") && deleteActiveNode()) return true;
        ed->deleteSel();
        return true;
    case Qt::Key_Escape: return escape();
    case Qt::Key_Return: case Qt::Key_Enter:
        if (!m_draft.empty()) { finishDraft(false); return true; }
        return false;
    case Qt::Key_PageUp: ed->setPlate(doc->activePlate() - 1); return true;
    case Qt::Key_PageDown: ed->setPlate(doc->activePlate() + 1); return true;
    case Qt::Key_F:
        if (mods & Qt::ShiftModifier) fitSelection(); else fitBed();
        return true;
    default: break;
    }
    if (mods & Qt::ShiftModifier) return false;
    switch (key) {
    case Qt::Key_V: ed->setTool(QStringLiteral("select")); return true;
    case Qt::Key_A: ed->setTool(QStringLiteral("node")); return true;
    case Qt::Key_R: ed->setTool(QStringLiteral("rect")); return true;
    case Qt::Key_E: ed->setTool(QStringLiteral("ellipse")); return true;
    case Qt::Key_L: ed->setTool(QStringLiteral("poly")); return true;
    case Qt::Key_P: ed->setTool(QStringLiteral("pen")); return true;
    case Qt::Key_T: ed->setTool(QStringLiteral("text")); return true;
    case Qt::Key_M: ed->setTool(QStringLiteral("measure")); return true;
    case Qt::Key_I: ed->setTool(QStringLiteral("select")); ed->askImport(true); return true;
    default: return false;
    }
}

// ---- Overlay ----

void MotivStage::addStroke(const Element& e, const QColor& c, qreal width) {
    if (e.paths.pointCount() > kHoverPointLimit) return;
    const QTransform m = Editor::matrixOf(e.transform);
    const View v = view();
    std::vector<QPointF> pts;
    for (lc::PolyView poly : e.paths) {
        if (poly.size() < 2) continue;
        const bool closed = lc::isClosed(poly);
        const size_t n = closed ? poly.size() - 1 : poly.size();
        pts.resize(n);
        for (size_t i = 0; i < n; ++i) {
            const QPointF q = m.map(QPointF(poly[i].x, poly[i].y));
            pts[i] = {q.x() * v.zoom + v.panX, q.y() * v.zoom + v.panY};
        }
        m_overlay->polyline(pts, closed, c, width);
    }
}
void MotivStage::paintFrame(const SelFrame& f, bool handles) {
    const QPointF pts[4] = {mmToItem(f.corners[0]), mmToItem(f.corners[1]), mmToItem(f.corners[2]), mmToItem(f.corners[3])};
    const bool axis = std::abs(std::fmod(f.rot, 90.0)) < 1e-6;
    if (axis) {
        const QRectF r(std::round(std::min(pts[0].x(), pts[2].x())) + .5, std::round(std::min(pts[0].y(), pts[2].y())) + .5,
                       std::round(std::abs(pts[2].x() - pts[0].x())), std::round(std::abs(pts[2].y() - pts[0].y())));
        m_overlay->rectOutline(r, m_accent);
    } else {
        m_overlay->polyline(std::span<const QPointF>(pts, 4), true, m_accent);
    }
    if (!handles) return;
    const QPointF n = handlePos(f, Handle::N), rot = handlePos(f, Handle::Rot);
    m_overlay->line(n, rot, m_accent);
    m_overlay->disc(rot, 5, m_accent);
    m_overlay->disc(rot, 4, m_surface);
    const bool small = frameSmall(pts[0], pts[1], pts[3]);
    const double r = f.rot * kPi / 180, c = std::cos(r), s = std::sin(r);
    for (Handle h : {Handle::NW, Handle::N, Handle::NE, Handle::E, Handle::SE, Handle::S, Handle::SW, Handle::W}) {
        if (small && (h == Handle::N || h == Handle::E || h == Handle::S || h == Handle::W)) continue;
        QPointF p = handlePos(f, h);
        if (axis) p = {std::round(p.x()), std::round(p.y())};
        const auto square = [&](double half, const QColor& col) {
            const QPointF q[4] = {p + QPointF(-half * c + half * s, -half * s - half * c), p + QPointF(half * c + half * s, half * s - half * c),
                                  p + QPointF(half * c - half * s, half * s + half * c), p + QPointF(-half * c - half * s, -half * s + half * c)};
            m_overlay->quad(q, col);
        };
        square(4, m_accent);
        square(3, m_surface);
    }
}
void MotivStage::paintNodes(const Element& e) {
    auto* ed = Editor::instance();
    addStroke(e, m_accent, 1.25);
    const auto curves = ed->curvesOf(e);
    if (lc::nodeCount(curves) > kNodeLimit) return;
    const auto s = [&](Pt p) { return mmToItem(qp(e.transform.apply(p))); };
    QColor faded = m_accent;
    faded.setAlphaF(0.6f);
    for (size_t pi = 0; pi < curves.size(); ++pi) {
        const CurvePath& c = curves[pi];
        const int count = int(c.nodes.size());
        for (int ni = 0; ni < count; ++ni) {
            const CurveNode& n = c.nodes[size_t(ni)];
            const bool hasRef = m_nodeRef && m_nodeRef->path == int(pi);
            const bool active = hasRef && m_nodeRef->node == ni;
            const bool near = hasRef && (std::abs(m_nodeRef->node - ni) == 1 || std::abs(m_nodeRef->node - ni) == count - 1);
            if (!active && !near && !(n.smooth && count <= 12)) continue;
            const QPointF p = s({n.x, n.y});
            for (int side = 0; side < 2; ++side) {
                if (side == 0 ? !n.hasIn() : !n.hasOut()) continue;
                const Pt h = side == 0 ? n.handleIn() : n.handleOut();
                if (std::hypot(h.x - n.x, h.y - n.y) < 1e-6) continue;
                const QPointF q = s(h);
                m_overlay->line(p, q, faded);
                m_overlay->disc(q, 4, m_accent);
                m_overlay->disc(q, 3, m_surface);
            }
        }
        for (int ni = 0; ni < count; ++ni) {
            const CurveNode& n = c.nodes[size_t(ni)];
            const QPointF p = s({n.x, n.y});
            const bool active = m_nodeRef && m_nodeRef->path == int(pi) && m_nodeRef->node == ni;
            if (n.smooth) {
                m_overlay->disc(p, 4.5, m_accent);
                m_overlay->disc(p, 3.5, active ? m_accent : m_surface);
            } else {
                const QRectF outer(std::round(p.x()) - 4, std::round(p.y()) - 4, 8, 8);
                m_overlay->rect(outer, m_accent);
                if (!active) m_overlay->rect(outer.adjusted(1, 1, -1, -1), m_surface);
            }
        }
    }
}
void MotivStage::paintDraft() {
    if (m_draft.empty()) return;
    const auto s = [&](Pt p) { return toItem(p); };
    std::vector<CurvePath> tmp(1);
    tmp[0].nodes = m_draft;
    const lc::Poly flat = lc::flattenCurve(tmp[0], 0.05);
    std::vector<QPointF> pts;
    pts.reserve(flat.size());
    for (const Pt& p : flat) pts.push_back(s(p));
    m_overlay->polyline(pts, false, m_accent, 1.5);
    const bool pen = Editor::instance()->tool() == QLatin1String("pen");
    if (m_cursorWorld && m_drag.kind != DragKind::PenNode) {
        const CurveNode& last = m_draft.back();
        QColor faded = m_accent;
        faded.setAlphaF(0.6f);
        m_overlay->dashed(s({last.x, last.y}), s(*m_cursorWorld), faded);
        const double len = std::hypot(m_cursorWorld->x - last.x, m_cursorWorld->y - last.y);
        setPill(QStringLiteral("%1 mm").arg(num(len)), s(*m_cursorWorld) + QPointF(12, 12));
    }
    for (size_t i = 0; i < m_draft.size(); ++i) {
        const CurveNode& n = m_draft[i];
        const QPointF p = s({n.x, n.y});
        if (pen && i + 1 == m_draft.size()) {
            for (int side = 0; side < 2; ++side) {
                if (side == 0 ? !n.hasIn() : !n.hasOut()) continue;
                const QPointF q = s(side == 0 ? n.handleIn() : n.handleOut());
                m_overlay->line(p, q, m_accent);
                m_overlay->disc(q, 4, m_accent);
                m_overlay->disc(q, 3, m_surface);
            }
        }
        const qreal r = i == 0 ? 5 : 4;
        m_overlay->disc(p, r, m_accent);
        m_overlay->disc(p, r - 1, m_surface);
    }
}
void MotivStage::repaint() {
    if (m_repaintQueued) return;
    m_repaintQueued = true;
    QMetaObject::invokeMethod(this, &MotivStage::rebuildOverlay, Qt::QueuedConnection);
}
void MotivStage::rebuildOverlay() {
    m_repaintQueued = false;
    auto* ed = Editor::instance();
    auto* doc = Document::instance();
    m_overlay->clear();
    // Warnings sit on the object itself.
    for (const WarnBox& w : ed->warningBoxes()) {
        const QPointF a = toItem(Pt{w.box.minX, w.box.minY}), b = toItem(Pt{w.box.maxX, w.box.maxY});
        const QRectF r(std::round(a.x()) - 3.5, std::round(a.y()) - 3.5, std::round(b.x() - a.x()) + 7, std::round(b.y() - a.y()) + 7);
        const QColor tone = w.kind == 1 ? m_bad : m_warn;
        m_overlay->dashed(r.topLeft(), r.topRight(), tone, 5, 3);
        m_overlay->dashed(r.topRight(), r.bottomRight(), tone, 5, 3);
        m_overlay->dashed(r.bottomRight(), r.bottomLeft(), tone, 5, 3);
        m_overlay->dashed(r.bottomLeft(), r.topLeft(), tone, 5, 3);
    }
    const QString tool = ed->tool();
    // Hover
    if (m_hover >= 0 && m_hover < int(ed->items().size()) && m_drag.kind == DragKind::None && tool == QLatin1String("select")) {
        const SceneItem& it = ed->items()[size_t(m_hover)];
        if (!doc->isSelected(it.e->id) && !it.e->isImage()) {
            QColor c = m_accent;
            c.setAlphaF(0.7f);
            addStroke(*it.e, c, 2);
        }
    }
    // Selection frame
    const bool bandDrag = m_drag.kind == DragKind::Band;
    if (tool == QLatin1String("select") && !bandDrag) {
        SelFrame f = ed->selFrame();
        if (m_drag.kind == DragKind::Move && m_drag.started) {
            const QTransform t = QTransform::fromTranslate(m_drag.dx, m_drag.dy);
            for (QPointF& c : f.corners) c = t.map(c);
            if (f.valid) paintFrame(f, false);
        } else if ((m_drag.kind == DragKind::Scale || m_drag.kind == DragKind::Rotate) && m_drag.started) {
            f = m_drag.frame;
            for (QPointF& c : f.corners) c = m_drag.live.map(c);
            if (m_drag.kind == DragKind::Rotate) f.rot += m_drag.deg;
            f.center = m_drag.live.map(f.center);
            paintFrame(f, true);
        } else if (f.valid) paintFrame(f, true);
    }
    // Node editing
    if (tool == QLatin1String("node")) {
        const int item = ed->nodeItem();
        if (item >= 0) paintNodes(*ed->items()[size_t(item)].e);
        else if (m_hover >= 0 && m_hover < int(ed->items().size())) {
            const SceneItem& it = ed->items()[size_t(m_hover)];
            if (!it.e->isImage()) { QColor c = m_accent; c.setAlphaF(0.7f); addStroke(*it.e, c, 2); }
        }
    }
    // Guides
    QColor guide = m_accent;
    if (m_guideX) { const double x = std::round(*m_guideX * effectiveZoom() + view().panX) + .5; m_overlay->dashed({x, 0}, {x, height()}, guide); }
    if (m_guideY) { const double y = std::round(*m_guideY * effectiveZoom() + view().panY) + .5; m_overlay->dashed({0, y}, {width(), y}, guide); }
    // Rubber band
    if (bandDrag) {
        const QPointF a = toItem(m_drag.a), b = toItem(m_drag.b);
        const QRectF r = QRectF(a, b).normalized();
        m_overlay->rect(r, m_accentSoft);
        const QRectF crisp(std::round(r.x()) + .5, std::round(r.y()) + .5, std::round(r.width()), std::round(r.height()));
        if (b.x() < a.x()) {
            m_overlay->dashed(crisp.topLeft(), crisp.topRight(), m_accent);
            m_overlay->dashed(crisp.topRight(), crisp.bottomRight(), m_accent);
            m_overlay->dashed(crisp.bottomRight(), crisp.bottomLeft(), m_accent);
            m_overlay->dashed(crisp.bottomLeft(), crisp.topLeft(), m_accent);
        } else m_overlay->rectOutline(crisp, m_accent);
    }
    // Shape being drawn
    if (m_drag.kind == DragKind::Shape && m_drag.moved) {
        const Box b = shapeBox();
        const QPointF a = toItem(Pt{b.minX, b.minY}), c = toItem(Pt{b.maxX, b.maxY});
        if (tool == QLatin1String("rect")) {
            const QRectF r(a, c);
            m_overlay->rect(r, m_accentSoft);
            m_overlay->rectOutline(r, m_accent, 1.5);
        } else {
            std::vector<QPointF> pts(72);
            const QPointF mid = (a + c) / 2, rad = (c - a) / 2;
            for (size_t i = 0; i < pts.size(); ++i) {
                const double t = double(i) * 2 * kPi / double(pts.size());
                pts[i] = mid + QPointF(rad.x() * std::cos(t), rad.y() * std::sin(t));
            }
            m_overlay->convexFill(pts, m_accentSoft);
            m_overlay->polyline(pts, true, m_accent, 1.5);
        }
    }
    paintDraft();
    if (m_measure) {
        const QPointF p = toItem(m_measure->first), q = toItem(m_measure->second);
        m_overlay->line(p, q, m_accent, 1.25);
        for (const QPointF& s : {p, q}) { m_overlay->disc(s, 4.5, m_accent); m_overlay->disc(s, 3.5, m_surface); }
        const double dx = m_measure->second.x - m_measure->first.x, dy = m_measure->second.y - m_measure->first.y;
        setPill(QStringLiteral("%1 mm   ΔX %2   ΔY %3").arg(num(std::hypot(dx, dy), 2), num(std::abs(dx), 2), num(std::abs(dy), 2)), (p + q) / 2 + QPointF(10, 10));
    }
    m_overlay->commit();
}

// ---- Test handles ----

QVariantMap MotivStage::frameInfo() const {
    const SelFrame& f = Editor::instance()->selFrame();
    if (!f.valid) return {};
    return {{"x0", f.corners[0].x()}, {"y0", f.corners[0].y()}, {"x2", f.corners[2].x()}, {"y2", f.corners[2].y()}, {"rot", f.rot}};
}
QPointF MotivStage::nodeItemPos(int path, int node) const {
    auto* ed = Editor::instance();
    const int item = ed->nodeItem();
    if (item < 0) return {};
    const Element& e = *ed->items()[size_t(item)].e;
    const auto curves = ed->curvesOf(e);
    const CurveNode& n = curves.at(size_t(path)).nodes.at(size_t(node));
    return mmToItem(qp(e.transform.apply({n.x, n.y})));
}
QPointF MotivStage::handleItemPos(const QString& handle) const {
    static const QHash<QString, Handle> map = {{"nw", Handle::NW}, {"n", Handle::N}, {"ne", Handle::NE}, {"e", Handle::E}, {"se", Handle::SE}, {"s", Handle::S}, {"sw", Handle::SW}, {"w", Handle::W}, {"rot", Handle::Rot}};
    return handlePos(Editor::instance()->selFrame(), map.value(handle, Handle::None));
}
