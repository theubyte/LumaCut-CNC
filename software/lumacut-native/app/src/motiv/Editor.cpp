#include "Editor.h"
#include "AppSettings.h"
#include "Fmt.h"
#include "Machine.h"
#include "PiClient.h"
#include "Toast.h"
#include "core/boolean.h"
#include "core/contour.h"
#include "core/create.h"
#include "core/export.h"
#include "core/import/import.h"
#include "core/parallel.h"
#include "core/parts.h"
#include "core/text.h"
#include "core/tools.h"
#include "core/vectorize.h"
#include "gpu/ComputeImage.h"
#include <QFile>
#include <QFileInfo>
#include <QFutureWatcher>
#include <QRegularExpression>
#include <QSet>
#include <QUrl>
#include <QSaveFile>
#include <QtConcurrent/QtConcurrentRun>
#include <algorithm>
#include <cmath>

namespace lc = lumacut;
using lc::Box;
using lc::CurveNode;
using lc::CurvePath;
using lc::Element;
using lc::ImageMode;
using lc::Layer;
using lc::LayerMode;
using lc::PolySet;
using lc::PolyView;
using lc::Pt;
using lc::Transform;
using State = Document::State;
using ElementPtr = Document::ElementPtr;
using ElementList = Document::ElementList;

namespace {
constexpr double kDegToRad = 0.017453292519943295;
constexpr int kManyUpserts = 2000;   // more changed shapes than this: rebuild the stage on its worker
constexpr qsizetype kFewSelected = 8;

double norm180(double a) {
    double r = std::fmod(a, 360.0);
    if (r > 180) r -= 360;
    if (r <= -180) r += 360;
    return r;
}
Pt rotatePt(Pt p, Pt c, double deg) {
    const double r = deg * kDegToRad, cs = std::cos(r), s = std::sin(r), dx = p.x - c.x, dy = p.y - c.y;
    return {c.x + dx * cs - dy * s, c.y + dx * s + dy * cs};
}
QString num(double v, int digits = 1) { return Fmt::trim(v, digits); }

std::optional<Box> worldBox(const Element& e) {
    if (e.isImage()) return lc::boundsOf(PolyView(e.imageCorners()));
    const PolyView pts = e.paths.allPoints();
    if (pts.empty()) return std::nullopt;
    const Transform& t = e.transform;
    const double r = t.rotation * kDegToRad, c = std::cos(r), s = std::sin(r);
    Box b{1e300, 1e300, -1e300, -1e300};
    for (const Pt& p : pts) {
        const double sx = p.x * t.scaleX, sy = p.y * t.scaleY;
        const double x = sx * c - sy * s + t.x, y = sx * s + sy * c + t.y;
        b.minX = std::min(b.minX, x); b.maxX = std::max(b.maxX, x);
        b.minY = std::min(b.minY, y); b.maxY = std::max(b.maxY, y);
    }
    return b;
}
std::optional<Box> localBox(const Element& e) {
    if (e.isImage()) return Box{0, 0, e.imageWidthMm, e.imageHeightMm};
    return lc::boundsOf(e.paths);
}
void addBox(std::optional<Box>& into, const Box& b) { into = into ? into->united(b) : b; }

Element movedBy(Element e, double dx, double dy) { e.transform.x += dx; e.transform.y += dy; return e; }

/** Paths in world coordinates, transform reduced to a translation. Curves follow. */
template <class Map>
void bake(Element& e, const Map& map) {
    PolySet world = e.worldPaths();
    for (Pt& p : world.allPoints()) p = map(p);
    const auto b = lc::boundsOf(world);
    if (!b) return;
    const Transform old = e.transform;
    const auto local = [&](Pt p) { return Pt{p.x - b->minX, p.y - b->minY}; };
    for (Pt& p : world.allPoints()) p = local(p);
    e.paths = std::move(world);
    e.transform = Transform{b->minX, b->minY, 1, 1, 0};
    if (e.curves) e.curves = lc::mapCurves(*e.curves, [&](Pt p) { return local(map(old.apply(p))); });
}
/** Axis-aligned scale about `a`. A rotated shape cannot express that in its transform, so it is baked; images stay proportional. */
void scaledAbout(Element& e, Pt a, double kx, double ky) {
    const Transform t = e.transform;
    const bool rotated = std::abs(std::fmod(t.rotation, 180.0)) > 1e-6, uneven = std::abs(kx - ky) > 1e-9;
    if (rotated && uneven) {
        if (!e.isImage()) { bake(e, [&](Pt p) { return Pt{a.x + (p.x - a.x) * kx, a.y + (p.y - a.y) * ky}; }); return; }
        kx = ky = std::max(kx, ky);
    }
    e.transform.x = a.x + (t.x - a.x) * kx;
    e.transform.y = a.y + (t.y - a.y) * ky;
    e.transform.scaleX = t.scaleX * kx;
    e.transform.scaleY = t.scaleY * ky;
}
/** Scale in the element's own axes with `anchor` (world) staying where it is. */
void scaledLocal(Element& e, Pt anchor, double kx, double ky) {
    const Transform t = e.transform;
    const Pt a = t.invert(anchor);
    Transform n = t;
    n.x = 0; n.y = 0; n.scaleX = t.scaleX * kx; n.scaleY = t.scaleY * ky;
    const Pt moved = n.apply(a);
    n.x = anchor.x - moved.x;
    n.y = anchor.y - moved.y;
    e.transform = n;
}
void rotatedAbout(Element& e, Pt c, double deg) {
    const Pt t = rotatePt({e.transform.x, e.transform.y}, c, deg);
    e.transform.x = t.x; e.transform.y = t.y;
    e.transform.rotation = norm180(e.transform.rotation + deg);
}
void mirroredImage(Element& e, bool horizontal, const std::function<Pt(Pt)>& m) {
    const int w = e.raster.width(), h = e.raster.height();
    const auto& src = e.raster.gray();
    std::vector<uint8_t> out(src.size());
    for (int y = 0; y < h; ++y) for (int x = 0; x < w; ++x)
        out[size_t(y) * w + x] = src[horizontal ? size_t(y) * w + (w - 1 - x) : size_t(h - 1 - y) * w + x];
    const auto b = lc::boundsOf(PolyView(e.imageCorners()));
    const Pt c = m(b->center());
    Transform t = e.transform;
    t.rotation = norm180(-t.rotation); t.x = 0; t.y = 0;
    const Pt ctr = t.apply({e.imageWidthMm / 2, e.imageHeightMm / 2});
    t.x = c.x - ctr.x; t.y = c.y - ctr.y;
    e.raster = lc::Raster::ofGray(w, h, std::move(out));
    e.transform = t;
}

Element curveElement(const QString& layerId, const QString& kind, std::vector<CurvePath> curves, Pt origin) {
    Element e = lc::newElement(layerId, kind);
    e.paths = lc::flattenCurves(curves);
    e.curves = std::move(curves);
    e.transform.x = origin.x; e.transform.y = origin.y;
    return e;
}
QString modeName(ImageMode m) {
    switch (m) {
    case ImageMode::Dither: return QStringLiteral("dither");
    case ImageMode::Threshold: return QStringLiteral("threshold");
    case ImageMode::DitherJarvis: return QStringLiteral("jarvis");
    case ImageMode::DitherStucki: return QStringLiteral("stucki");
    default: return QStringLiteral("grayscale");
    }
}
ImageMode modeOf(const QString& s) {
    if (s == QLatin1String("dither")) return ImageMode::Dither;
    if (s == QLatin1String("threshold")) return ImageMode::Threshold;
    if (s == QLatin1String("jarvis")) return ImageMode::DitherJarvis;
    if (s == QLatin1String("stucki")) return ImageMode::DitherStucki;
    return ImageMode::Grayscale;
}
QString processOf(const Layer& l) {
    if (lc::Document::isStandardLayer(l.name)) return l.name;
    if (l.mode == LayerMode::Fill) return QStringLiteral("Gravieren");
    const QString p = l.extra.value(QLatin1String("process")).toString();
    return p.isEmpty() ? QStringLiteral("Linie") : p;
}
double safeZStep(int passes, double z) {
    return passes > 1 ? std::max(0.0, std::min({z, lc::Limits::Z_STEP_MAX, lc::Limits::MAX_FOCUS_DROP_MM / (passes - 1)})) : 0.0;
}
QString colorCss(qint64 argb) { return QStringLiteral("#%1").arg(qulonglong(argb) & 0xFFFFFF, 6, 16, QLatin1Char('0')); }
lc::Document shellOf(const State& s) {
    lc::Document d;
    d.title = s.title;
    d.layers = s.layers();
    d.plateCount = s.plateCount;
    d.activePlate = s.activePlate;
    d.extra = s.extra;
    return d;
}
}  // namespace

QTransform Editor::matrixOf(const Transform& t) {
    const double r = t.rotation * kDegToRad, c = std::cos(r), s = std::sin(r);
    return QTransform(t.scaleX * c, t.scaleX * s, -t.scaleY * s, t.scaleY * c, t.x, t.y);
}
QTransform Editor::imageMatrixOf(const Element& e) {
    QTransform m = matrixOf(e.transform);
    m.scale(e.imageWidthMm, e.imageHeightMm);
    return m;
}

Editor::Editor(QObject* parent) : QObject(parent) {
    auto* s = AppSettings::instance();
    m_snapGrid = s->value("motiv.snapGrid", true).toBool();
    m_snapObjects = s->value("motiv.snapObjects", true).toBool();
    m_lockAspect = s->value("motiv.lockAspect", true).toBool();
    auto* doc = Document::instance();
    connect(doc, &Document::changed, this, &Editor::onDocChanged);
    connect(doc, &Document::selectionChanged, this, &Editor::onSelectionChanged);
    connect(doc, &Document::activeLayerChanged, this, [this] { refreshLayers(); });
    connect(doc, &Document::replaced, this, [this] { m_lastPlate = -1; m_lastList.reset(); setTool(QStringLiteral("select")); onDocChanged(); });
    connect(Machine::instance(), &Machine::bedChanged, this, &Editor::onBedChanged);
    onDocChanged();
}

// ---- Scene ----

void Editor::fillItem(SceneItem& it, const ElementPtr& e) const {
    it.e = e;
    const auto b = worldBox(*e);
    it.hasBox = bool(b);
    it.box = b.value_or(Box{});
    it.warn = 0;
    if (b) {
        if (!lc::Work::contains(*b)) it.warn = 1;
        else if (lc::Work::touchesPark(*b) && e->touchesPark()) it.warn = 2;
    }
}
int Editor::layerIndexOf(const QString& id) const {
    const auto& ls = Document::instance()->layers();
    for (size_t i = 0; i < ls.size(); ++i) if (ls[i].id == id) return int(i);
    return -1;
}
void Editor::assignLayers() {
    QString last;
    int lastIdx = -1;
    for (SceneItem& it : m_items) {
        if (it.e->layerId != last) { last = it.e->layerId; lastIdx = layerIndexOf(last); }
        it.layer = lastIdx;
    }
}
void Editor::rebuildAll() {
    auto* doc = Document::instance();
    const int plate = doc->activePlate();
    const ElementList& list = doc->elements();
    m_docToItem.assign(list.size(), -1);
    std::vector<ElementPtr> now;
    now.reserve(list.size());
    for (size_t i = 0; i < list.size(); ++i) if (list[i]->plate == plate) { m_docToItem[i] = int(now.size()); now.push_back(list[i]); }
    m_items.assign(now.size(), {});
    lc::parallelBlocks(std::ptrdiff_t(now.size()), 256, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
        for (std::ptrdiff_t i = a; i < b; ++i) fillItem(m_items[size_t(i)], now[size_t(i)]);
    });
    for (SceneItem& it : m_items) {
        auto f = m_sids.constFind(it.e->id);
        if (f == m_sids.constEnd()) f = m_sids.insert(it.e->id, m_nextSid++);
        it.sid = *f;
    }
    m_itemOfValid = false;
    m_usageDirty = true;
    m_countsDirty = true;
}
/** One element changed in place: box and warning, a plain move without looking at the points again. */
void Editor::updateItem(SceneItem& it, const ElementPtr& e, bool sameShape) const {
    const Element& old = *it.e;
    const bool translateOnly = sameShape && !e->isImage() && old.transform.scaleX == e->transform.scaleX
        && old.transform.scaleY == e->transform.scaleY && old.transform.rotation == e->transform.rotation;
    if (translateOnly && it.hasBox && it.warn == 0) {
        const double dx = e->transform.x - old.transform.x, dy = e->transform.y - old.transform.y;
        it.box = Box{it.box.minX + dx, it.box.minY + dy, it.box.maxX + dx, it.box.maxY + dy};
        it.e = e;
        if (!lc::Work::contains(it.box)) it.warn = 1;
        else if (lc::Work::touchesPark(it.box) && e->touchesPark()) it.warn = 2;
    } else {
        fillItem(it, e);
    }
}
void Editor::onDocChanged() {
    auto* doc = Document::instance();
    const State& st = doc->state();
    const bool plateChanged = st.activePlate != m_lastPlate;
    const bool listChanged = st.elementList != m_lastList;
    const bool layersChanged = st.layerList != m_lastLayers;
    const std::shared_ptr<ElementList> oldList = m_lastList;
    m_lastPlate = st.activePlate;
    m_lastList = st.elementList;
    m_lastLayers = st.layerList;
    if (st.plateCount != int(m_counts.size())) m_countsDirty = true;

    const auto classify = [](const Element& a, const Element& b) {
        return a.layerId == b.layerId && a.isImage() == b.isImage() && a.paths == b.paths;
    };
    if (plateChanged || !oldList) {
        rebuildAll();
        assignLayers();
        emit sceneReset();
    } else if (listChanged) {
        const ElementList& list = *st.elementList;
        const ElementList& old = *oldList;
        // Same elements in the same order, some changed? Tell by the pointers, without touching the 100,000 others.
        std::vector<int> changed;
        bool inPlace = list.size() >= old.size();
        const size_t common = std::min(list.size(), old.size());
        if (inPlace) for (size_t i = 0; i < common; ++i) if (old[i] != list[i]) {
            if (old[i]->id != list[i]->id || old[i]->plate != list[i]->plate) { inPlace = false; break; }
            changed.push_back(int(i));
        }
        SceneDelta delta;
        if (inPlace) {
            std::vector<std::pair<int, int>> items;   // doc index, item index
            items.reserve(changed.size());
            for (int c : changed) {
                if (old[size_t(c)]->layerId != list[size_t(c)]->layerId) m_usageDirty = true;
                if (m_docToItem[size_t(c)] >= 0) items.emplace_back(c, m_docToItem[size_t(c)]);
            }
            std::vector<uint8_t> sameShape(items.size());
            lc::parallelBlocks(std::ptrdiff_t(items.size()), 64, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
                for (std::ptrdiff_t k = a; k < b; ++k) {
                    SceneItem& it = m_items[size_t(items[size_t(k)].second)];
                    const ElementPtr& e = list[size_t(items[size_t(k)].first)];
                    sameShape[size_t(k)] = classify(*it.e, *e) ? 1 : 0;
                    updateItem(it, e, sameShape[size_t(k)] != 0);
                }
            });
            for (size_t k = 0; k < items.size(); ++k) {
                const int item = items[k].second;
                if (sameShape[k]) delta.moved.push_back(item);
                else { m_items[size_t(item)].layer = layerIndexOf(m_items[size_t(item)].e->layerId); delta.upserts.push_back(item); }
            }
            // New elements at the end, the usual way to add.
            for (size_t i = common; i < list.size(); ++i) {
                const ElementPtr& e = list[i];
                m_docToItem.push_back(-1);
                m_usageDirty = true;
                m_countsDirty = true;
                if (e->plate != st.activePlate) continue;
                const int item = int(m_items.size());
                m_docToItem.back() = item;
                SceneItem& it = m_items.emplace_back();
                fillItem(it, e);
                it.layer = layerIndexOf(e->layerId);
                auto f = m_sids.constFind(e->id);
                if (f == m_sids.constEnd()) f = m_sids.insert(e->id, m_nextSid++);
                it.sid = *f;
                delta.upserts.push_back(item);
                if (m_itemOfValid) m_itemOf.insert(e->id, item);
            }
        } else {
            // Removed or reordered: match by pointer first, then by id.
            const int plate = st.activePlate;
            std::vector<ElementPtr> now;
            now.reserve(list.size());
            m_docToItem.assign(list.size(), -1);
            for (size_t i = 0; i < list.size(); ++i) if (list[i]->plate == plate) { m_docToItem[i] = int(now.size()); now.push_back(list[i]); }
            QHash<const Element*, int> oldAt;
            oldAt.reserve(qsizetype(m_items.size()));
            for (size_t i = 0; i < m_items.size(); ++i) oldAt.insert(m_items[i].e.get(), int(i));
            std::vector<SceneItem> next(now.size());
            std::vector<uint8_t> used(m_items.size(), 0);
            std::vector<int> fresh;
            for (size_t i = 0; i < now.size(); ++i) {
                const auto f = oldAt.constFind(now[i].get());
                if (f != oldAt.constEnd()) { next[i] = m_items[size_t(*f)]; used[size_t(*f)] = 1; }
                else fresh.push_back(int(i));
            }
            QHash<QString, int> oldUnmatched;
            for (size_t i = 0; i < m_items.size(); ++i) if (!used[i]) oldUnmatched.insert(m_items[i].e->id, int(i));
            lc::parallelBlocks(std::ptrdiff_t(fresh.size()), 64, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
                for (std::ptrdiff_t k = a; k < b; ++k) fillItem(next[size_t(fresh[size_t(k)])], now[size_t(fresh[size_t(k)])]);
            });
            for (int i : fresh) {
                SceneItem& it = next[size_t(i)];
                it.layer = layerIndexOf(it.e->layerId);
                auto was = oldUnmatched.find(it.e->id);
                if (was != oldUnmatched.end()) {
                    const SceneItem& oldItem = m_items[size_t(*was)];
                    it.sid = oldItem.sid;
                    if (classify(*oldItem.e, *it.e)) delta.moved.push_back(i); else delta.upserts.push_back(i);
                    oldUnmatched.erase(was);
                } else {
                    auto f = m_sids.constFind(it.e->id);
                    if (f == m_sids.constEnd()) f = m_sids.insert(it.e->id, m_nextSid++);
                    it.sid = *f;
                    delta.upserts.push_back(i);
                }
            }
            for (auto it = oldUnmatched.constBegin(); it != oldUnmatched.constEnd(); ++it) delta.removed.push_back(m_items[size_t(*it)].sid);
            m_items = std::move(next);
            m_itemOfValid = false;
            m_usageDirty = true;
            m_countsDirty = true;
        }
        if (int(delta.upserts.size()) > kManyUpserts) emit sceneReset();
        else if (!delta.upserts.empty() || !delta.moved.empty() || !delta.removed.empty()) emit sceneChanged(delta);
    }
    if (layersChanged) {
        assignLayers();
        emit stageLayersChanged();
    } else if (plateChanged) {
        emit stageLayersChanged();
    }
    resolveSelection();
    refreshFrame();
    refreshSel();
    refreshLayers();
    refreshStats();
    refreshWarnings();
    emit selectionResolved();
}
void Editor::onSelectionChanged() {
    resolveSelection();
    refreshFrame();
    refreshSel();
    refreshLayers();
    emit selectionResolved();
}
void Editor::resolveSelection() {
    auto* doc = Document::instance();
    m_selIdx.clear();
    if (doc->selectionCount() == 0) return;
    if (!m_itemOfValid) {
        m_itemOf.clear();
        m_itemOf.reserve(qsizetype(m_items.size()));
        for (size_t i = 0; i < m_items.size(); ++i) m_itemOf.insert(m_items[i].e->id, int(i));
        m_itemOfValid = true;
    }
    const QStringList ids = doc->selection();
    m_selIdx.reserve(size_t(ids.size()));
    for (const QString& id : ids) {
        const auto f = m_itemOf.constFind(id);
        if (f != m_itemOf.constEnd()) m_selIdx.push_back(*f);
    }
    std::sort(m_selIdx.begin(), m_selIdx.end());
}
std::optional<Box> Editor::boxOfItems(const std::vector<int>& idx) const {
    std::optional<Box> b;
    for (int i : idx) if (m_items[size_t(i)].hasBox) addBox(b, m_items[size_t(i)].box);
    return b;
}
std::optional<Box> Editor::selectionBox() const { return boxOfItems(m_selIdx); }
std::vector<ElementPtr> Editor::selectedElements() const {
    std::vector<ElementPtr> out;
    out.reserve(m_selIdx.size());
    for (int i : m_selIdx) out.push_back(m_items[size_t(i)].e);
    return out;
}
void Editor::refreshFrame() {
    m_frame = {};
    if (m_selIdx.empty()) return;
    if (m_selIdx.size() == 1) {
        const Element& e = *m_items[size_t(m_selIdx[0])].e;
        const auto s = localBox(e);
        if (!s) return;
        const Pt c[4] = {{s->minX, s->minY}, {s->maxX, s->minY}, {s->maxX, s->maxY}, {s->minX, s->maxY}};
        for (int i = 0; i < 4; ++i) { const Pt w = e.transform.apply(c[i]); m_frame.corners[i] = {w.x, w.y}; }
        m_frame.rot = e.transform.rotation;
        m_frame.single = true;
    } else {
        const auto b = selectionBox();
        if (!b) return;
        m_frame.corners[0] = {b->minX, b->minY}; m_frame.corners[1] = {b->maxX, b->minY};
        m_frame.corners[2] = {b->maxX, b->maxY}; m_frame.corners[3] = {b->minX, b->maxY};
    }
    m_frame.center = (m_frame.corners[0] + m_frame.corners[2]) / 2;
    m_frame.valid = true;
}

int Editor::hitTest(Pt w, double tol) const {
    int inside = -1;
    double area = 1e300;
    const double tol2 = tol * tol;
    for (int i = int(m_items.size()) - 1; i >= 0; --i) {
        const SceneItem& it = m_items[size_t(i)];
        if (!it.hasBox) continue;
        if (w.x < it.box.minX - tol || w.x > it.box.maxX + tol || w.y < it.box.minY - tol || w.y > it.box.maxY + tol) continue;
        if (!editableItem(i)) continue;
        const Element& e = *it.e;
        const double a = std::max(it.box.width() * it.box.height(), 0.01);
        if (e.isImage()) {
            const Pt q = e.transform.invert(w);
            if (q.x >= 0 && q.y >= 0 && q.x <= e.imageWidthMm && q.y <= e.imageHeightMm && a < area) { inside = i; area = a; }
            continue;
        }
        const Transform& t = e.transform;
        const double r = t.rotation * kDegToRad, c = std::cos(r), s = std::sin(r);
        const auto world = [&](Pt p) { const double sx = p.x * t.scaleX, sy = p.y * t.scaleY; return Pt{sx * c - sy * s + t.x, sx * s + sy * c + t.y}; };
        bool odd = false, anyClosed = false;
        for (PolyView poly : e.paths) {
            if (poly.size() < 2) continue;
            const bool closed = lc::isClosed(poly);
            anyClosed |= closed;
            Pt p0 = world(poly[0]);
            for (size_t k = 1; k < poly.size(); ++k) {
                const Pt p1 = world(poly[k]);
                const double dx = p1.x - p0.x, dy = p1.y - p0.y, len2 = dx * dx + dy * dy;
                const double u = len2 > 0 ? std::clamp(((w.x - p0.x) * dx + (w.y - p0.y) * dy) / len2, 0.0, 1.0) : 0.0;
                const double qx = p0.x + u * dx - w.x, qy = p0.y + u * dy - w.y;
                if (qx * qx + qy * qy <= tol2) return i;
                if (closed && (p0.y > w.y) != (p1.y > w.y) && w.x < p0.x + (w.y - p0.y) * dx / dy) odd = !odd;
                p0 = p1;
            }
        }
        if (anyClosed && odd && a < area) { inside = i; area = a; }
    }
    return inside;
}
bool Editor::editableItem(int item) const {
    const int l = m_items[size_t(item)].layer;
    if (l < 0) return false;
    const Layer& layer = Document::instance()->layers()[size_t(l)];
    return layer.visible && !layer.locked;
}
std::vector<int> Editor::expandGroup(int item) const {
    const Element& e = *m_items[size_t(item)].e;
    if (!e.groupId) return {item};
    std::vector<int> out;
    for (size_t i = 0; i < m_items.size(); ++i) if (m_items[i].e->groupId == e.groupId) out.push_back(int(i));
    return out;
}
std::vector<CurvePath> Editor::curvesOf(const Element& e) const { return e.curves ? *e.curves : lc::curvesFromPaths(e.paths); }
int Editor::nodeItem() const {
    if (m_selIdx.size() != 1) return -1;
    const Element& e = *m_items[size_t(m_selIdx[0])].e;
    return e.isImage() || e.text ? -1 : m_selIdx[0];
}
void Editor::selectItems(const std::vector<int>& items) {
    QStringList ids;
    ids.reserve(qsizetype(items.size()));
    for (int i : items) ids.push_back(m_items[size_t(i)].e->id);
    Document::instance()->select(ids);
}
void Editor::addToSelection(const std::vector<int>& items) {
    auto* doc = Document::instance();
    QStringList ids = doc->selection();
    for (int i : items) if (!doc->isSelected(m_items[size_t(i)].e->id)) ids.push_back(m_items[size_t(i)].e->id);
    doc->select(ids);
}
void Editor::removeFromSelection(const std::vector<int>& items) {
    auto* doc = Document::instance();
    QStringList ids = doc->selection();
    for (int i : items) ids.removeAll(m_items[size_t(i)].e->id);
    doc->select(ids);
}

// ---- Panels ----

void Editor::refreshSel() {
    QVariantMap m;
    const int n = int(m_selIdx.size());
    m["count"] = n;
    if (n) {
        const auto box = m_liveBox ? m_liveBox : selectionBox();
        int vectors = 0, units = 0;
        bool anyGroup = false, canSplit = false, anyImage = false, anyText = false, out = false, park = false;
        QSet<QString> groups;
        for (int i : m_selIdx) {
            const SceneItem& it = m_items[size_t(i)];
            const Element& e = *it.e;
            if (e.isImage()) anyImage = true; else ++vectors;
            if (e.text) anyText = true;
            if (e.groupId) { anyGroup = true; groups.insert(*e.groupId); } else ++units;
            if (!e.isImage() && !e.text && e.paths.size() >= 2) canSplit = true;
            out |= it.warn == 1;
            park |= it.warn == 2;
        }
        units += int(groups.size());
        m["vectors"] = vectors; m["units"] = units; m["anyGroup"] = anyGroup; m["canSplit"] = canSplit;
        m["anyImage"] = anyImage; m["anyText"] = anyText;
        if (box) {
            m["hasBox"] = true;
            m["x"] = box->minX; m["y"] = box->minY;
            m["w"] = box->width(); m["h"] = box->height();
            m["boxW"] = box->width(); m["boxH"] = box->height();
        }
        m["rot"] = 0.0;
        if (n == 1) {
            const Element& e = *m_items[size_t(m_selIdx[0])].e;
            m["kind"] = e.kind;
            m["id"] = e.id;
            m["rot"] = e.transform.rotation;
            const auto s = localBox(e);
            if (s && !m_liveBox) {
                m["w"] = s->width() * std::abs(e.transform.scaleX);
                m["h"] = s->height() * std::abs(e.transform.scaleY);
            }
            if (e.text) {
                m["isText"] = true;
                m["text"] = *e.text;
                m["fontFamily"] = e.fontFamily;
                m["fontLabel"] = fontLabel(e.fontFamily);
                m["fontSize"] = e.fontSizeMm;
                m["bold"] = e.bold;
            }
            if (e.isImage()) {
                m["isImage"] = true;
                m["imageKey"] = QString::number(quintptr(e.raster.gray().data()));
                m["imageMode"] = modeName(e.imageMode);
                m["brightness"] = e.adjust.brightness;
                m["contrast"] = e.adjust.contrast;
                m["sharpen"] = e.adjust.sharpen;
                m["invert"] = e.adjust.invert;
                m["pxW"] = e.raster.width();
                m["pxH"] = e.raster.height();
                const double wmm = e.imageWidthMm * std::abs(e.transform.scaleX);
                m["dpi"] = int(std::lround(e.raster.width() / std::max(wmm, 0.01) * 25.4));
            }
        }
        if (out) {
            m["warnTone"] = "bad";
            m["warnText"] = "Ragt über die Arbeitsfläche. So startet der Auftrag nicht.";
            m["warnAction"] = "In die Arbeitsfläche schieben";
        } else if (park) {
            const bool band = lc::Work::bandBlocked();
            m["warnTone"] = "warn";
            m["warnText"] = band ? "Liegt im gesperrten Streifen. Dort darf der Kopf nicht hin." : "Liegt in der Park-Ecke. Dort steht der Kopf in der Ruhelage.";
            m["warnAction"] = band ? "Aus dem Streifen schieben" : "Aus der Park-Ecke schieben";
        }
    }
    m_sel = std::move(m);
    emit selChanged();
}
void Editor::setLiveBox(std::optional<Box> box) {
    const bool ended = m_liveBox && !box;
    m_liveBox = box;
    if (ended) { refreshSel(); return; }
    if (!box) return;
    // Called on every mouse move: only the numbers change, the selection does not.
    m_sel["x"] = box->minX; m_sel["y"] = box->minY;
    m_sel["w"] = box->width(); m_sel["h"] = box->height();
    m_sel["boxW"] = box->width(); m_sel["boxH"] = box->height();
    emit selChanged();
}
void Editor::setMouse(std::optional<Pt> mm) {
    m_mouse = mm;
    const QString t = mm ? QStringLiteral("X %1  Y %2 mm").arg(num(mm->x), num(mm->y)) : QStringLiteral("X –  Y –");
    if (t != m_mouseText) { m_mouseText = t; emit mouseChanged(); }
}
void Editor::refreshLayers() {
    auto* doc = Document::instance();
    const auto& ls = doc->layers();
    const QString active = doc->activeLayer();
    if (m_usageDirty) {
        m_usageDirty = false;
        m_usage.clear();
        QString last;
        int run = 0;
        for (const ElementPtr& e : doc->elements()) {
            if (e->layerId != last) { if (run) m_usage[last] += run; last = e->layerId; run = 0; }
            ++run;
        }
        if (run) m_usage[last] += run;
    }
    const QHash<QString, int>& usage = m_usage;

    QSet<QString> selLayers;
    for (int i : m_selIdx) { const QString& id = m_items[size_t(i)].e->layerId; if (!selLayers.contains(id)) selLayers.insert(id); }
    const QString focus = selLayers.size() == 1 ? *selLayers.constBegin() : selLayers.isEmpty() ? active : QString();

    QStringList ids;
    m_layerRows.clear();
    for (const Layer& l : ls) {
        const int count = usage.value(l.id);
        const bool standard = lc::Document::isStandardLayer(l.name);
        if (!count && !(l.id == active && !standard)) continue;
        ids.push_back(l.id);
        int incoming = 0;
        for (int i : m_selIdx) if (m_items[size_t(i)].e->layerId != l.id) ++incoming;
        QVariantMap r;
        r["id"] = l.id; r["name"] = l.name; r["label"] = l.label(); r["color"] = colorCss(l.color); r["count"] = count;
        r["standard"] = standard; r["focused"] = l.id == focus; r["incoming"] = incoming;
        r["fill"] = l.mode == LayerMode::Fill; r["process"] = processOf(l);
        r["power"] = l.powerPct; r["speed"] = l.speed; r["passes"] = l.passes; r["zStep"] = l.zStepMm;
        r["interval"] = l.intervalMm; r["overscan"] = l.overscanMm;
        r["output"] = l.output; r["visible"] = l.visible;
        r["lowPower"] = l.powerPct > 0 && l.powerPct < lc::Limits::MIN_RELIABLE_POWER_PCT;
        r["minPower"] = lc::Limits::MIN_RELIABLE_POWER_PCT;
        r["focusDrop"] = l.focusDropMm();
        r["materialName"] = l.materialName.value_or(QString());
        r["thickness"] = l.thicknessMm;
        m_layerRows.insert(l.id, r);
    }
    QString focusName;
    if (const Layer* fl = doc->layer(focus)) focusName = fl->name;
    m_processValue = lc::Document::isStandardLayer(focusName) ? focusName : QString();

    int cutAt = -1;
    m_cutNotLast = false;
    for (int i = 0; i < ids.size(); ++i) {
        const Layer* l = doc->layer(ids[i]);
        if (cutAt < 0 && l->name == QLatin1String("Schneiden") && l->output && l->visible) cutAt = i;
        else if (cutAt >= 0 && l->output && l->visible && usage.value(l->id) > 0) m_cutNotLast = true;
    }
    ++m_layersRev;
    if (ids != m_layerIds) { m_layerIds = ids; emit layerIdsChanged(); }
    emit layersRevChanged();
}
QVariantMap Editor::layerRow(const QString& id, int) const { return m_layerRows.value(id); }
QVariantList Editor::layerMenu() const {
    QVariantList out;
    auto* doc = Document::instance();
    for (const QString& id : m_layerIds) {
        bool any = false;
        for (int i : m_selIdx) if (m_items[size_t(i)].e->layerId != id) { any = true; break; }
        if (!any) continue;
        if (const Layer* l = doc->layer(id)) out.push_back(QVariantMap{{"id", id}, {"label", l->label()}});
    }
    return out;
}
void Editor::refreshStats() {
    auto* doc = Document::instance();
    if (m_countsDirty) {
        m_countsDirty = false;
        m_counts.assign(size_t(std::max(1, doc->plateCount())), 0);
        for (const ElementPtr& e : doc->elements()) if (e->plate >= 0 && e->plate < int(m_counts.size())) ++m_counts[size_t(e->plate)];
        QVariantList plates;
        for (int c : m_counts) plates.push_back(c);
        m_plateCounts = plates;
    }
    std::optional<Box> all;
    for (const SceneItem& it : m_items) if (it.hasBox) addBox(all, it.box);
    QVariantMap s;
    s["count"] = int(m_items.size());
    if (all) { s["w"] = all->width(); s["h"] = all->height(); }
    m_stats = s;
    emit statsChanged();
}
void Editor::refreshWarnings() {
    auto* doc = Document::instance();
    const auto& ls = doc->layers();
    std::vector<WarnBox> list;
    QHash<QString, int> units;
    std::optional<Box> bad[2];
    int raw = 0;
    for (const SceneItem& it : m_items) {
        if (!it.warn || it.layer < 0) continue;
        const Layer& l = ls[size_t(it.layer)];
        if (!l.output || !l.visible) continue;
        ++raw;
        addBox(bad[it.warn - 1], it.box);
        if (raw > 64) continue;
        const QString key = it.e->groupId.value_or(it.e->id);
        const auto f = units.constFind(key);
        if (f == units.constEnd()) { units.insert(key, int(list.size())); list.push_back({it.box, it.warn}); }
        else { WarnBox& u = list[size_t(*f)]; u.box = u.box.united(it.box); if (it.warn == 1) u.kind = 1; }
    }
    if (raw > 64 || list.size() > 6) {
        list.clear();
        for (int k = 0; k < 2; ++k) if (bad[k]) list.push_back({*bad[k], k + 1});
    }
    m_warnBoxes = std::move(list);
    emit warningsChanged();
}
QVariantList Editor::warningsList() const {
    QVariantList out;
    for (const WarnBox& w : m_warnBoxes) {
        out.push_back(QVariantMap{{"kind", w.kind}, {"minX", w.box.minX}, {"minY", w.box.minY}, {"maxX", w.box.maxX}, {"maxY", w.box.maxY},
            {"text", w.kind == 1 ? QStringLiteral("Ragt über die Arbeitsfläche")
                     : lc::Work::bandBlocked() ? QStringLiteral("Liegt im gesperrten Streifen") : QStringLiteral("Liegt in der Park-Ecke")}});
    }
    return out;
}
void Editor::onBedChanged() {
    emit bedChanged();
    // Warnings hang on the work area.
    lc::parallelBlocks(std::ptrdiff_t(m_items.size()), 64, [this](std::ptrdiff_t a, std::ptrdiff_t b) {
        for (std::ptrdiff_t i = a; i < b; ++i) fillItem(m_items[size_t(i)], Document::ElementPtr(m_items[size_t(i)].e));
    });
    refreshSel();
    refreshWarnings();
    emit selectionResolved();
}
double Editor::bedW() const { return lc::Work::width(); }
double Editor::bedH() const { return lc::Work::height(); }
double Editor::parkLeft() const { return lc::Work::park().minX; }
double Editor::parkW() const { return lc::Work::park().width(); }
double Editor::parkH() const { return lc::Work::park().height(); }
QString Editor::parkName() const { return lc::Work::parkName(); }
QString Editor::bedLabel() const { return QStringLiteral("Arbeitsfläche %1 × %2 mm").arg(num(bedW()), num(bedH())); }

// ---- Tool and preferences ----

void Editor::setTool(const QString& t) {
    if (t == m_tool) return;
    m_tool = t;
    emit toolChanged();
}
QString Editor::hint() const {
    static const QHash<QString, QString> hints = {
        {QStringLiteral("node"), QStringLiteral("Knoten ziehen. Doppelklick auf die Linie fügt einen Knoten ein, Doppelklick auf einen Knoten macht ihn rund oder eckig, Entf löscht ihn.")},
        {QStringLiteral("rect"), QStringLiteral("Rechteck aufziehen. Umschalt: Quadrat, Alt: von der Mitte aus.")},
        {QStringLiteral("ellipse"), QStringLiteral("Ellipse aufziehen. Umschalt: Kreis, Alt: von der Mitte aus.")},
        {QStringLiteral("poly"), QStringLiteral("Punkte setzen. Klick auf den ersten Punkt schließt die Form, Doppelklick oder Enter beendet, Rücktaste nimmt den letzten zurück.")},
        {QStringLiteral("pen"), QStringLiteral("Klick setzt eine Ecke, Ziehen eine runde Stelle. Klick auf den ersten Punkt schließt, Enter beendet.")},
        {QStringLiteral("text"), QStringLiteral("Klicken, wo der Text beginnen soll.")},
        {QStringLiteral("measure"), QStringLiteral("Von Punkt zu Punkt ziehen. Ecken und Mitten rasten ein.")},
    };
    return hints.value(m_tool);
}
void Editor::setSnapGrid(bool v) { if (v != m_snapGrid) { m_snapGrid = v; AppSettings::instance()->setValue("motiv.snapGrid", v); emit prefsChanged(); } }
void Editor::setSnapObjects(bool v) { if (v != m_snapObjects) { m_snapObjects = v; AppSettings::instance()->setValue("motiv.snapObjects", v); emit prefsChanged(); } }
void Editor::setLockAspect(bool v) { if (v != m_lockAspect) { m_lockAspect = v; AppSettings::instance()->setValue("motiv.lockAspect", v); emit prefsChanged(); } }
void Editor::setBusy(const QString& text) { if (text != m_busyText) { m_busyText = text; emit busyChanged(); } }

template <class R>
void Editor::work(const QString& what, std::function<R()> job, std::function<void(R&&)> done) {
    setBusy(what);
    auto* watcher = new QFutureWatcher<R>(this);
    connect(watcher, &QFutureWatcherBase::finished, this, [this, watcher, done = std::move(done)] {
        setBusy({});
        R r = watcher->result();
        watcher->deleteLater();
        done(std::move(r));
    });
    watcher->setFuture(QtConcurrent::run(std::move(job)));
}

// ---- Moving and transforming ----

void Editor::applyMove(double dx, double dy, bool afterCheckpoint) {
    const auto fn = [dx, dy](Element& e) { e.transform.x += dx; e.transform.y += dy; };
    if (afterCheckpoint) Document::instance()->mutateElements(selectedIds(), fn);
    else Document::instance()->updateElements(selectedIds(), fn);
}
void Editor::applyScale(Pt anchor, double kx, double ky, bool single) {
    Document::instance()->updateElements(selectedIds(), [=](Element& e) {
        if (single) scaledLocal(e, anchor, kx, ky); else scaledAbout(e, anchor, kx, ky);
    });
}
void Editor::applyRotate(Pt center, double deg) {
    Document::instance()->updateElements(selectedIds(), [=](Element& e) { rotatedAbout(e, center, deg); });
}
void Editor::applyCurves(const QString& id, const std::vector<CurvePath>& curves, bool undoStep) {
    const auto fn = [&curves](Element& e) { e.curves = curves; e.paths = lc::flattenCurves(curves); };
    if (undoStep) Document::instance()->updateElements({id}, fn); else Document::instance()->mutateElements({id}, fn);
}
void Editor::nudge(double dx, double dy) { applyMove(dx, dy, false); }
void Editor::setPosX(double v) { if (const auto b = selectionBox()) applyMove(v - b->minX, 0, false); }
void Editor::setPosY(double v) { if (const auto b = selectionBox()) applyMove(0, v - b->minY, false); }
void Editor::setSize(std::optional<double> w, std::optional<double> h) {
    const auto b = selectionBox();
    if (!b) return;
    const bool one = m_selIdx.size() == 1;
    double curW = b->width(), curH = b->height();
    if (one) {
        const Element& e = *m_items[size_t(m_selIdx[0])].e;
        const auto s = localBox(e);
        if (!s) return;
        curW = s->width() * std::abs(e.transform.scaleX);
        curH = s->height() * std::abs(e.transform.scaleY);
    }
    double kx = w && curW > 0 ? std::max(*w, 0.01) / curW : 1, ky = h && curH > 0 ? std::max(*h, 0.01) / curH : 1;
    if (m_lockAspect) { if (w) ky = kx; else kx = ky; }
    const Pt a{b->minX, b->minY};
    const Box box = *b;
    Document::instance()->updateElements(selectedIds(), [=](Element& e) {
        if (!one) { scaledAbout(e, a, kx, ky); return; }
        scaledLocal(e, a, kx, ky);
        if (const auto nb = worldBox(e)) { e.transform.x += box.minX - nb->minX; e.transform.y += box.minY - nb->minY; }
    });
}
void Editor::setSizeW(double v) { setSize(v, std::nullopt); }
void Editor::setSizeH(double v) { setSize(std::nullopt, v); }
void Editor::setRotation(double deg) {
    const auto b = selectionBox();
    if (!b) return;
    const double cur = m_selIdx.size() == 1 ? m_items[size_t(m_selIdx[0])].e->transform.rotation : 0;
    applyRotate(b->center(), deg - cur);
}
void Editor::rotateBy90() {
    const double cur = m_selIdx.size() == 1 ? m_items[size_t(m_selIdx[0])].e->transform.rotation : 0;
    setRotation(cur + 90);
}
void Editor::centerInWork() {
    const auto b = selectionBox();
    if (!b) return;
    const Pt c = b->center(), w = lc::Work::center();
    applyMove(w.x - c.x, w.y - c.y, false);
}
void Editor::keepInside() {
    const auto b = selectionBox();
    if (!b) return;
    const double W = lc::Work::width(), H = lc::Work::height();
    double dx = 0, dy = 0;
    if (b->width() <= W) { if (b->minX < 0) dx = -b->minX; else if (b->maxX > W) dx = W - b->maxX; }
    if (b->height() <= H) { if (b->minY < 0) dy = -b->minY; else if (b->maxY > H) dy = H - b->maxY; }
    const Box park = lc::Work::park();
    if (b->maxX + dx > park.minX && b->minY + dy < park.maxY) {
        const double left = b->maxX + dx - park.minX, down = park.maxY - b->minY - dy;
        if (b->width() <= park.minX && left <= down) dx -= left;
        else if (b->maxY + dy + down <= H) dy += down;
    }
    if (dx == 0 && dy == 0) { Toast::instance()->show(QStringLiteral("Passt nicht auf die Arbeitsfläche. Erst verkleinern."), QStringLiteral("warn")); return; }
    applyMove(dx, dy, false);
}

// ---- Align, distribute, mirror ----

void Editor::applyOffsets(const QHash<QString, Pt>& off) {
    if (off.isEmpty()) return;
    Document::instance()->updateElements(off.keys(), [&off](Element& e) { const Pt o = off.value(e.id); e.transform.x += o.x; e.transform.y += o.y; });
}
void Editor::align(const QString& mode) {
    if (m_selIdx.empty()) return;
    QHash<QString, std::vector<int>> grouped;
    std::vector<QString> order;
    for (int i : m_selIdx) {
        const Element& e = *m_items[size_t(i)].e;
        const QString key = e.groupId.value_or(e.id);
        if (!grouped.contains(key)) order.push_back(key);
        grouped[key].push_back(i);
    }
    const Box ref = order.size() > 1 ? *selectionBox() : Box{0, 0, lc::Work::width(), lc::Work::height()};
    std::vector<Box> boxes;
    std::vector<QString> keys;
    for (const QString& k : order) if (const auto b = boxOfItems(grouped[k])) { boxes.push_back(*b); keys.push_back(k); }
    static const QHash<QString, lc::AlignMode> modes = {{"left", lc::AlignMode::Left}, {"centerX", lc::AlignMode::CenterX}, {"right", lc::AlignMode::Right},
                                                        {"top", lc::AlignMode::Top}, {"centerY", lc::AlignMode::CenterY}, {"bottom", lc::AlignMode::Bottom}};
    const auto offs = lc::Align::offsets(boxes, modes.value(mode), ref);
    QHash<QString, Pt> off;
    for (size_t u = 0; u < keys.size(); ++u) for (int i : grouped[keys[u]]) off.insert(m_items[size_t(i)].e->id, offs[u]);
    applyOffsets(off);
}
void Editor::distribute(bool horizontal) {
    QHash<QString, std::vector<int>> grouped;
    std::vector<QString> order;
    for (int i : m_selIdx) {
        const Element& e = *m_items[size_t(i)].e;
        const QString key = e.groupId.value_or(e.id);
        if (!grouped.contains(key)) order.push_back(key);
        grouped[key].push_back(i);
    }
    if (order.size() < 3) { Toast::instance()->show(QStringLiteral("Zum Verteilen mindestens drei Objekte wählen")); return; }
    std::vector<Box> boxes;
    std::vector<QString> keys;
    for (const QString& k : order) if (const auto b = boxOfItems(grouped[k])) { boxes.push_back(*b); keys.push_back(k); }
    const auto offs = lc::Align::distribute(boxes, horizontal);
    QHash<QString, Pt> off;
    for (size_t u = 0; u < keys.size(); ++u) for (int i : grouped[keys[u]]) off.insert(m_items[size_t(i)].e->id, offs[u]);
    applyOffsets(off);
}
void Editor::mirror(bool horizontal) {
    const auto b = selectionBox();
    if (!b) return;
    const Box box = *b;
    const std::function<Pt(Pt)> m = [box, horizontal](Pt q) { return horizontal ? Pt{box.minX + box.maxX - q.x, q.y} : Pt{q.x, box.minY + box.maxY - q.y}; };
    Document::instance()->updateElements(selectedIds(), [=](Element& e) {
        if (e.isImage()) mirroredImage(e, horizontal, m); else bake(e, m);
    });
}

// ---- Combine and take apart ----

void Editor::booleanSel(const QString& op) {
    std::vector<ElementPtr> shapes;
    for (const ElementPtr& e : selectedElements()) if (!e->isImage()) shapes.push_back(e);
    if (shapes.size() < 2) { Toast::instance()->show(QStringLiteral("Mindestens zwei Formen wählen, Bilder gehen nicht")); return; }
    const lc::BooleanOp kind = op == QLatin1String("subtract") ? lc::BooleanOp::Subtract : op == QLatin1String("intersect") ? lc::BooleanOp::Intersect : lc::BooleanOp::Union;
    const QString label = op == QLatin1String("subtract") ? QStringLiteral("Abziehen") : op == QLatin1String("intersect") ? QStringLiteral("Schnittmenge") : QStringLiteral("Verschweißen");
    struct Out { PolySet polys; QString error; };
    const quint64 rev = Document::instance()->revision();
    work<Out>(label + QStringLiteral(" …"), [shapes, kind]() -> Out {
        try {
            std::vector<PolySet> in;
            in.reserve(shapes.size());
            for (const ElementPtr& e : shapes) in.push_back(e->worldPaths());
            return {lc::booleanShapes(kind, in), {}};
        } catch (const std::exception& e) { return {{}, QString::fromUtf8(e.what())}; }
    }, [this, shapes, label, rev](Out&& r) {
        auto* doc = Document::instance();
        if (!r.error.isEmpty()) { Toast::instance()->show(label + QStringLiteral(" ging nicht: ") + r.error, QStringLiteral("bad")); return; }
        if (doc->revision() != rev) return;
        const auto b = lc::boundsOf(r.polys);
        if (r.polys.empty() || !b) { Toast::instance()->show(QStringLiteral("Kein Ergebnis: die Formen überschneiden sich nicht")); return; }
        Element el = lc::newElement(shapes[0]->layerId, label);
        el.transform.x = b->minX; el.transform.y = b->minY;
        for (Pt& p : r.polys.allPoints()) { p.x -= b->minX; p.y -= b->minY; }
        el.paths = std::move(r.polys);
        el.plate = shapes[0]->plate;
        const QString id = el.id;
        QSet<QString> gone;
        for (const ElementPtr& e : shapes) gone.insert(e->id);
        doc->commit([&](State& s) {
            ElementList next;
            for (const ElementPtr& e : s.elements()) if (!gone.contains(e->id)) next.push_back(e);
            next.push_back(std::make_shared<const Element>(std::move(el)));
            s.elementList = std::make_shared<ElementList>(std::move(next));
        });
        doc->select({id});
    });
}
void Editor::group() {
    if (m_selIdx.size() < 2) return;
    const QString gid = lc::newId();
    Document::instance()->updateElements(selectedIds(), [gid](Element& e) { e.groupId = gid; });
}
void Editor::ungroup() {
    bool any = false;
    for (int i : m_selIdx) if (m_items[size_t(i)].e->groupId) { any = true; break; }
    if (any) Document::instance()->updateElements(selectedIds(), [](Element& e) { e.groupId = std::nullopt; });
}
void Editor::splitSel() {
    QHash<QString, std::vector<Element>> pieces;
    int made = 0;
    for (const ElementPtr& e : selectedElements()) {
        std::vector<Element> parts = lc::splitParts(*e);
        for (Element& p : parts) p.curves = std::nullopt;
        if (parts.size() > 1) made += int(parts.size());
        pieces.insert(e->id, std::move(parts));
    }
    if (!made) { Toast::instance()->show(QStringLiteral("Besteht nur aus einem Teil")); return; }
    QStringList ids;
    auto* doc = Document::instance();
    doc->commit([&](State& s) {
        ElementList next;
        for (const ElementPtr& e : s.elements()) {
            auto f = pieces.find(e->id);
            if (f == pieces.end()) { next.push_back(e); continue; }
            for (Element& p : *f) { ids.push_back(p.id); next.push_back(std::make_shared<const Element>(std::move(p))); }
        }
        s.elementList = std::make_shared<ElementList>(std::move(next));
    });
    doc->select(ids);
    Toast::instance()->show(QStringLiteral("In %1 Teile aufgeteilt").arg(made), QStringLiteral("ok"));
}
void Editor::textToPaths() {
    Document::instance()->updateElements(selectedIds(), [](Element& e) {
        if (e.text) { e.text = std::nullopt; e.kind = QStringLiteral("Pfade"); }
    });
}
void Editor::makeContour(double offsetMm, bool removeSource, bool outerOnly) {
    const auto els = selectedElements();
    if (els.empty()) return;
    struct Out { PolySet polys; QString error; };
    const quint64 rev = Document::instance()->revision();
    work<Out>(QStringLiteral("Kontur …"), [els, offsetMm, outerOnly]() -> Out {
        try {
            PolySet src;
            PolySet out;
            for (const ElementPtr& e : els) if (!e->isImage()) src.append(e->worldPaths());
            if (!src.empty()) out = lc::Contour::fromPolys(src, offsetMm, 8, outerOnly);
            for (const ElementPtr& e : els) {
                if (!e->isImage()) continue;
                // Outline of the dark parts of a picture, computed in its own pixels and then placed like the picture.
                const auto& gray = e->raster.gray();
                std::vector<uint8_t> data(gray.size());
                for (size_t i = 0; i < gray.size(); ++i) data[i] = gray[i] < 128 ? 1 : 0;
                const double px = e->raster.width() / std::max(e->imageWidthMm, 0.01), k = std::abs(e->transform.scaleX) > 0 ? std::abs(e->transform.scaleX) : 1;
                PolySet local = lc::Contour::fromMask(lc::Mask(e->raster.width(), e->raster.height(), std::move(data), px, 0, 0), offsetMm / k, 0, outerOnly);
                for (Pt& p : local.allPoints()) p = e->transform.apply(p);
                out.append(local);
            }
            return {std::move(out), {}};
        } catch (const std::exception& e) { return {{}, QString::fromUtf8(e.what())}; }
    }, [this, els, removeSource, rev](Out&& r) {
        auto* doc = Document::instance();
        if (!r.error.isEmpty()) { Toast::instance()->show(QStringLiteral("Kontur ging nicht: ") + r.error, QStringLiteral("bad")); return; }
        if (doc->revision() != rev) return;
        const auto b = lc::boundsOf(r.polys);
        if (!b) { Toast::instance()->show(QStringLiteral("Keine Kontur gefunden")); return; }
        const QString cutLayer = doc->layerByName(QStringLiteral("Schneiden"));
        const QString gid = removeSource ? QString() : els[0]->groupId.value_or(lc::newId());
        Element contour = lc::newElement(cutLayer, QStringLiteral("Kontur"));
        contour.transform.x = b->minX; contour.transform.y = b->minY;
        for (Pt& p : r.polys.allPoints()) { p.x -= b->minX; p.y -= b->minY; }
        contour.paths = std::move(r.polys);
        contour.plate = els[0]->plate;
        if (!gid.isEmpty()) contour.groupId = gid;
        QSet<QString> ids;
        for (const ElementPtr& e : els) ids.insert(e->id);
        QStringList nextSel = removeSource ? QStringList() : QStringList(ids.begin(), ids.end());
        nextSel.push_back(contour.id);
        doc->commit([&](State& s) {
            ElementList next;
            for (const ElementPtr& e : s.elements()) {
                if (!ids.contains(e->id)) { next.push_back(e); continue; }
                if (removeSource) continue;
                auto copy = std::make_shared<Element>(*e);
                copy->groupId = gid;
                next.push_back(std::move(copy));
            }
            next.push_back(std::make_shared<const Element>(std::move(contour)));
            s.elementList = std::make_shared<ElementList>(std::move(next));
        });
        doc->select(nextSel);
        setDialog({});
    });
}
void Editor::vectorizeSel(int threshold, bool invert, bool smooth, bool outerOnly, bool removeSource) {
    ElementPtr im;
    for (const ElementPtr& e : selectedElements()) if (e->isImage()) { im = e; break; }
    if (!im) return;
    struct Out { PolySet polys; QString error; };
    const quint64 rev = Document::instance()->revision();
    work<Out>(QStringLiteral("Vektorisieren …"), [im, threshold, invert, smooth, outerOnly]() -> Out {
        try {
            lc::VectorizeOptions o;
            o.threshold = threshold; o.invert = invert; o.smooth = smooth; o.outerOnly = outerOnly;
            o.widthMm = im->imageWidthMm; o.heightMm = im->imageHeightMm;
            return {lc::vectorizeRaster(im->raster, o), {}};
        } catch (const std::exception& e) { return {{}, QString::fromUtf8(e.what())}; }
    }, [this, im, removeSource, rev](Out&& r) {
        auto* doc = Document::instance();
        if (!r.error.isEmpty()) { Toast::instance()->show(QStringLiteral("Vektorisieren ging nicht: ") + r.error, QStringLiteral("bad")); return; }
        if (doc->revision() != rev) return;
        if (r.polys.empty()) { Toast::instance()->show(QStringLiteral("Nichts gefunden. Schwellwert ändern.")); return; }
        Element el = lc::newElement(im->layerId, QStringLiteral("Vektor"));
        el.transform = im->transform;
        const size_t n = r.polys.size();
        el.paths = std::move(r.polys);
        el.plate = im->plate;
        const QString id = el.id;
        doc->commit([&](State& s) {
            ElementList next;
            for (const ElementPtr& e : s.elements()) if (!(removeSource && e->id == im->id)) next.push_back(e);
            next.push_back(std::make_shared<const Element>(std::move(el)));
            s.elementList = std::make_shared<ElementList>(std::move(next));
        });
        doc->select({id});
        setDialog({});
        Toast::instance()->show(QStringLiteral("%1 Pfade erzeugt").arg(n), QStringLiteral("ok"));
    });
}

// ---- Clipboard, duplicate, delete, order ----

static std::vector<Element> copiesOf(const std::vector<ElementPtr>& els, double dx, double dy, std::optional<int> plate) {
    QHash<QString, QString> groups;
    std::vector<Element> out;
    out.reserve(els.size());
    for (const ElementPtr& e : els) {
        Element c = movedBy(*e, dx, dy);
        c.id = lc::newId();
        if (e->groupId) {
            auto f = groups.find(*e->groupId);
            if (f == groups.end()) f = groups.insert(*e->groupId, lc::newId());
            c.groupId = *f;
        }
        if (plate) c.plate = *plate;
        out.push_back(std::move(c));
    }
    return out;
}
void Editor::duplicate() {
    auto c = copiesOf(selectedElements(), 5, 5, std::nullopt);
    if (!c.empty()) Document::instance()->addElements(std::move(c));
}
void Editor::copySel() {
    m_clipboard = selectedElements();
    m_pasteShift = 0;
    emit clipboardChanged();
}
void Editor::cutSel() {
    auto s = selectedElements();
    if (s.empty()) return;
    m_clipboard = std::move(s);
    m_pasteShift = -5;
    emit clipboardChanged();
    deleteSel();
}
void Editor::paste() {
    if (m_clipboard.empty()) return;
    m_pasteShift += 5;
    auto* doc = Document::instance();
    auto c = copiesOf(m_clipboard, m_pasteShift, m_pasteShift, doc->activePlate());
    for (Element& e : c) if (!doc->layer(e.layerId)) e.layerId = doc->activeLayer();
    doc->addElements(std::move(c));
}
void Editor::deleteSel() {
    auto* doc = Document::instance();
    if (!doc->selectionCount()) return;
    const QSet<QString>& ids = doc->selectionSet();
    doc->commit([&](State& s) {
        ElementList next;
        next.reserve(s.elements().size());
        for (const ElementPtr& e : s.elements()) if (!ids.contains(e->id)) next.push_back(e);
        s.elementList = std::make_shared<ElementList>(std::move(next));
    });
    doc->clearSelection();
}
void Editor::selectAll() {
    std::vector<int> all;
    all.reserve(m_items.size());
    for (size_t i = 0; i < m_items.size(); ++i) if (editableItem(int(i))) all.push_back(int(i));
    selectItems(all);
}
void Editor::toFront(bool front) {
    auto* doc = Document::instance();
    if (!doc->selectionCount()) return;
    const QSet<QString>& ids = doc->selectionSet();
    doc->commit([&](State& s) {
        ElementList on, off;
        for (const ElementPtr& e : s.elements()) (ids.contains(e->id) ? on : off).push_back(e);
        ElementList next = front ? std::move(off) : std::move(on);
        const ElementList& rest = front ? on : off;
        next.insert(next.end(), rest.begin(), rest.end());
        s.elementList = std::make_shared<ElementList>(std::move(next));
    });
}
void Editor::spawnCopies() {
    auto* doc = Document::instance();
    auto c = copiesOf(selectedElements(), 0, 0, std::nullopt);
    QStringList ids;
    ids.reserve(qsizetype(c.size()));
    for (const Element& e : c) ids.push_back(e.id);
    doc->mutate([&](State& s) {
        ElementList& list = s.editElements();
        for (Element& e : c) list.push_back(std::make_shared<const Element>(std::move(e)));
    });
    doc->select(ids);
}

// ---- Creating ----

void Editor::addRect(const Box& b) {
    Document::instance()->addElements({curveElement(Document::instance()->activeLayer(), QStringLiteral("Rechteck"), {lc::rectCurve(b.width(), b.height())}, {b.minX, b.minY})});
}
void Editor::addEllipse(const Box& b) {
    Document::instance()->addElements({curveElement(Document::instance()->activeLayer(), QStringLiteral("Ellipse"), {lc::ellipseCurve(b.width(), b.height())}, {b.minX, b.minY})});
}
void Editor::addDrawn(const QString& kind, const CurvePath& path) {
    const PolySet flat = lc::flattenCurves({path});
    const auto b = lc::boundsOf(flat);
    if (!b) return;
    auto shifted = lc::mapCurves({path}, [&](Pt p) { return Pt{p.x - b->minX, p.y - b->minY}; });
    Document::instance()->addElements({curveElement(Document::instance()->activeLayer(), kind, std::move(shifted), {b->minX, b->minY})});
}
void Editor::addTextAt(Pt at) {
    auto* doc = Document::instance();
    Element e = lc::newElement(doc->activeLayer(), QStringLiteral("Text"));
    e.text = QStringLiteral("Text");
    e.fontSizeMm = 10;
    e.paths = lc::textPaths(*e.text, e.fontSizeMm, false, e.fontFamily);
    e.transform.x = at.x; e.transform.y = at.y;
    doc->addElements({std::move(e)});
    m_textEditing = false;
    emit focusTextRequested();
}
void Editor::updateText(const std::function<void(Element&)>& change, bool undoStep) {
    auto* doc = Document::instance();
    if (m_selIdx.size() != 1) return;
    const QString id = m_items[size_t(m_selIdx[0])].e->id;
    const auto fn = [&change](Element& e) {
        change(e);
        e.paths = lc::textPaths(e.text.value_or(QString()), e.fontSizeMm, e.bold, e.fontFamily);
    };
    if (undoStep) doc->updateElements({id}, fn); else doc->mutateElements({id}, fn);
}
void Editor::typeText(const QString& text) {
    if (text.trimmed().isEmpty()) return;
    if (m_selIdx.size() != 1 || !m_items[size_t(m_selIdx[0])].e->text || *m_items[size_t(m_selIdx[0])].e->text == text) return;
    if (!m_textEditing) { m_textEditing = true; Document::instance()->checkpoint(); }
    updateText([&text](Element& e) { e.text = text; }, false);
}
void Editor::setFontFamily(const QString& family) { updateText([&](Element& e) { e.fontFamily = family; }, true); }
void Editor::setFontSize(double mm) { updateText([&](Element& e) { e.fontSizeMm = mm; }, true); }
void Editor::setBold(bool on) { updateText([&](Element& e) { e.bold = on; }, true); }
QStringList Editor::fontFamilies() const {
    static const QStringList all = lc::fontFamilies();
    return QStringList{QStringLiteral("sans-serif"), QStringLiteral("serif"), QStringLiteral("monospace")} + all;
}
QString Editor::fontLabel(const QString& family) const {
    if (family == QLatin1String("sans-serif")) return QStringLiteral("Standard");
    if (family == QLatin1String("serif")) return QStringLiteral("Standard mit Serifen");
    if (family == QLatin1String("monospace")) return QStringLiteral("Standard feste Breite");
    return family;
}

// ---- Images ----

void Editor::setImageMode(const QString& mode) {
    const ImageMode m = modeOf(mode);
    Document::instance()->updateElements(selectedIds(), [m](Element& e) { if (e.isImage()) e.imageMode = m; });
}
void Editor::adjustImage(const QString& field, int value) {
    auto* doc = Document::instance();
    if (!m_adjusting) { m_adjusting = true; doc->checkpoint(); }
    doc->mutateElements(selectedIds(), [&](Element& e) {
        if (!e.isImage()) return;
        if (field == QLatin1String("brightness")) e.adjust.brightness = value;
        else if (field == QLatin1String("contrast")) e.adjust.contrast = value;
        else if (field == QLatin1String("sharpen")) e.adjust.sharpen = value;
    });
}
void Editor::setImageInvert(bool on) {
    Document::instance()->updateElements(selectedIds(), [on](Element& e) { if (e.isImage()) e.adjust.invert = on; });
}

// ---- Layers ----

void Editor::pickProcess(const QString& name) {
    auto* doc = Document::instance();
    const QString id = doc->layerByName(name);
    doc->setActiveLayer(id);
    moveSelectionToLayer(id);
}
void Editor::moveSelectionToLayer(const QString& id) {
    bool any = false;
    for (int i : m_selIdx) if (m_items[size_t(i)].e->layerId != id) { any = true; break; }
    if (any) Document::instance()->updateElements(selectedIds(), [id](Element& e) { e.layerId = id; });
}
void Editor::setLayerValue(const QString& id, const QString& key, const QVariant& value) {
    auto* doc = Document::instance();
    doc->commit([&](State& s) {
        for (Layer& l : s.editLayers()) {
            if (l.id != id) continue;
            if (key == QLatin1String("powerPct")) l.powerPct = std::clamp(value.toDouble(), lc::Limits::POWER_MIN, lc::Limits::POWER_MAX);
            else if (key == QLatin1String("speed")) l.speed = std::clamp(value.toDouble(), lc::Limits::SPEED_MIN, lc::Limits::SPEED_MAX);
            else if (key == QLatin1String("passes")) { l.passes = std::clamp(value.toInt(), lc::Limits::PASSES_MIN, lc::Limits::PASSES_MAX); l.zStepMm = safeZStep(l.passes, l.zStepMm); }
            else if (key == QLatin1String("zStepMm")) l.zStepMm = safeZStep(l.passes, value.toDouble());
            else if (key == QLatin1String("intervalMm")) l.intervalMm = std::clamp(value.toDouble(), 0.03, 2.0);
            else if (key == QLatin1String("overscanMm")) l.overscanMm = std::clamp(value.toDouble(), 0.0, 30.0);
            else if (key == QLatin1String("visible")) l.visible = value.toBool();
            else if (key == QLatin1String("output")) l.output = value.toBool();
            else if (key == QLatin1String("name")) l.name = value.toString();
            else if (key == QLatin1String("color")) l.color = qint64(0xFF000000LL) + value.toString().mid(1).toLongLong(nullptr, 16);
        }
    });
}
void Editor::setLayerProcess(const QString& id, const QString& process) {
    auto* doc = Document::instance();
    const Layer* l = doc->layer(id);
    if (!l || processOf(*l) == process) return;
    if (!lc::Document::isStandardLayer(l->name)) {
        doc->commit([&](State& s) {
            for (Layer& x : s.editLayers()) if (x.id == id) {
                x.mode = process == QLatin1String("Gravieren") ? LayerMode::Fill : LayerMode::Line;
                x.extra.insert(QLatin1String("process"), process);
            }
        });
        return;
    }
    const QString target = doc->layerByName(process);
    int n = 0;
    QStringList ids;
    for (const ElementPtr& e : doc->elements()) if (e->layerId == id) { ids.push_back(e->id); ++n; }
    doc->updateElements(ids, [target](Element& e) { e.layerId = target; });
    doc->setActiveLayer(target);
    Toast::instance()->show(QStringLiteral("%1 %2 jetzt auf %3").arg(n).arg(n == 1 ? QStringLiteral("Teil liegt") : QStringLiteral("Teile liegen"),
                            process == QLatin1String("Linie") ? QStringLiteral("Markieren") : process));
}
void Editor::addLayer() {
    auto* doc = Document::instance();
    static const qint64 palette[] = {0xFFFFB45CLL, 0xFFB98CFFLL, 0xFFFF8AD8LL, 0xFF9BE15DLL, 0xFF5CE1E6LL};
    QSet<QString> taken;
    for (const Layer& l : doc->layers()) taken.insert(l.name);
    int k = 1;
    while (taken.contains(QStringLiteral("Ebene %1").arg(k))) ++k;
    Layer l = lc::newLayer(QStringLiteral("Ebene %1").arg(k), palette[doc->layers().size() % 5], LayerMode::Line);
    l.powerPct = 50; l.speed = 1200;
    const QString id = l.id;
    doc->commit([&](State& s) { s.editLayers().push_back(l); });
    doc->setActiveLayer(id);
}
void Editor::deleteLayer(const QString& id) {
    auto* doc = Document::instance();
    doc->commit([&](State& s) {
        auto& ls = s.editLayers();
        ls.erase(std::remove_if(ls.begin(), ls.end(), [&](const Layer& l) { return l.id == id && !lc::Document::isStandardLayer(l.name); }), ls.end());
        ElementList next;
        for (const ElementPtr& e : s.elements()) if (e->layerId != id) next.push_back(e);
        s.elementList = std::make_shared<ElementList>(std::move(next));
    });
}
void Editor::moveLayer(const QString& id, const QString& before) {
    if (id == before) return;
    Document::instance()->commit([&](State& s) {
        const auto& cur = s.layers();
        std::vector<Layer> rest;
        std::optional<Layer> moved;
        for (const Layer& l : cur) if (l.id == id) moved = l; else rest.push_back(l);
        if (!moved) return;
        size_t at = rest.size();
        for (size_t i = 0; i < rest.size(); ++i) if (rest[i].id == before) { at = i; break; }
        rest.insert(rest.begin() + std::ptrdiff_t(at), *moved);
        bool same = true;
        for (size_t i = 0; i < rest.size(); ++i) if (rest[i].id != cur[i].id) { same = false; break; }
        if (!same) s.layerList = std::make_shared<std::vector<Layer>>(std::move(rest));
    });
}

// ---- Plates ----

void Editor::setPlate(int i) { Document::instance()->setActivePlate(i); }
void Editor::addPlate() { Document::instance()->addPlate(); Document::instance()->clearSelection(); }
void Editor::deletePlate(int i) { Document::instance()->removePlate(i); Document::instance()->clearSelection(); }
void Editor::moveSelectionToPlate(int target) {
    auto* doc = Document::instance();
    if (!doc->selectionCount() || target == doc->activePlate()) return;
    const QStringList ids = doc->selection();
    doc->commit([&](State& s) {
        if (target >= s.plateCount) s.plateCount += 1;
        const int t = std::min(target, s.plateCount - 1);
        s.activePlate = t;
        ElementList& list = s.editElements();
        const QSet<QString> set(ids.begin(), ids.end());
        for (ElementPtr& p : list) if (set.contains(p->id)) { auto c = std::make_shared<Element>(*p); c->plate = t; p = std::move(c); }
    });
    doc->select(ids);
}

// ---- Files ----

QStringList Editor::importFilters() const { return lc::importFilters(); }
static QString localPathOf(const QString& pathOrUrl) {
    return pathOrUrl.startsWith(QLatin1String("file:")) ? QUrl(pathOrUrl).toLocalFile() : pathOrUrl;
}
void Editor::importPaths(const QStringList& paths) {
    if (paths.isEmpty()) return;
    const QString path = localPathOf(paths.first());
    const QStringList rest = paths.mid(1);
    auto* doc = Document::instance();
    const lc::ImportContext ctx = lc::importContextFor(shellOf(doc->state()), doc->activeLayer());
    const QString name = QFileInfo(path).fileName();
    work<lc::ImportResult>(QStringLiteral("Importieren …"), [path, ctx] { return lc::importPath(path, ctx); }, [this, name, rest](lc::ImportResult&& r) {
        auto* doc = Document::instance();
        if (!r.ok()) Toast::instance()->show(name + QStringLiteral(": ") + r.error, QStringLiteral("bad"));
        else if (r.elements.empty()) Toast::instance()->show(r.warnings.value(0, QStringLiteral("In %1 wurde nichts Verwendbares gefunden").arg(name)), QStringLiteral("warn"));
        else {
            // Layers and plates from the shell, elements as they came: one undo step, nothing copied twice.
            lc::Document merged = lc::applyImport(shellOf(doc->state()), r);
            QStringList ids;
            ids.reserve(qsizetype(merged.elements.size()));
            for (const Element& e : merged.elements) ids.push_back(e.id);
            const int n = int(merged.elements.size());
            doc->commit([&](State& s) {
                s.layerList = std::make_shared<std::vector<Layer>>(std::move(merged.layers));
                s.plateCount = merged.plateCount;
                ElementList& list = s.editElements();
                list.reserve(list.size() + merged.elements.size());
                for (Element& e : merged.elements) list.push_back(std::make_shared<const Element>(std::move(e)));
            });
            doc->select(ids);
            for (const QString& w : r.warnings.mid(0, 2)) Toast::instance()->show(w, QStringLiteral("warn"));
            Toast::instance()->show(QStringLiteral("%1: %2 %3 eingefügt").arg(name).arg(n).arg(n == 1 ? QStringLiteral("Objekt") : QStringLiteral("Objekte")), QStringLiteral("ok"));
        }
        if (!rest.isEmpty()) importPaths(rest);
    });
}
static std::optional<lc::ExportFormat> formatOf(const QString& f) {
    if (f == QLatin1String("svg")) return lc::ExportFormat::Svg;
    if (f == QLatin1String("dxf")) return lc::ExportFormat::Dxf;
    if (f == QLatin1String("png")) return lc::ExportFormat::Png;
    return std::nullopt;
}
QVariantMap Editor::exportInfo(const QString& format) const {
    auto* doc = Document::instance();
    const int n = int(m_items.size());
    QVariantMap m;
    m["empty"] = n == 0;
    m["text"] = n ? QStringLiteral("Platte %1 mit %2 %3.").arg(doc->activePlate() + 1).arg(n).arg(n == 1 ? QStringLiteral("Objekt") : QStringLiteral("Objekten"))
                  : QStringLiteral("Auf dieser Platte liegt noch nichts.");
    QStringList warn;
    if (n) if (const auto f = formatOf(format)) warn = lc::exportWarnings(doc->doc(), *f);
    m["warnings"] = warn;
    return m;
}
QString Editor::exportFileName(const QString& format) const {
    auto* doc = Document::instance();
    QString title = doc->title();
    title.replace(QRegularExpression(QStringLiteral("[\\\\/:*?\"<>|]+")), QStringLiteral("-"));
    return title + (doc->plateCount() > 1 ? QStringLiteral("-Platte-%1").arg(doc->activePlate() + 1) : QString()) + QLatin1Char('.') + format;
}
void Editor::exportTo(const QString& path, const QString& format) {
    const auto f = formatOf(format);
    if (!f) return;
    struct Out { QString error; };
    const auto snap = Document::instance()->snapshot();
    const QString target = localPathOf(path);
    work<Out>(QStringLiteral("Exportieren …"), [snap, target, fmt = *f]() -> Out {
        try {
            const lc::Document d = snap.build();
            const QByteArray data = fmt == lc::ExportFormat::Svg ? lc::exportSvg(d) : fmt == lc::ExportFormat::Dxf ? lc::exportDxf(d) : lc::exportPng(d);
            QSaveFile file(target);
            if (!file.open(QIODevice::WriteOnly) || file.write(data) != data.size() || !file.commit()) return {QStringLiteral("Datei lässt sich nicht schreiben.")};
            return {};
        } catch (const std::exception& e) { return {QString::fromUtf8(e.what())}; }
    }, [this, target](Out&& r) {
        if (!r.error.isEmpty()) { Toast::instance()->show(QStringLiteral("Export ging nicht: ") + r.error, QStringLiteral("bad")); return; }
        Toast::instance()->show(QStringLiteral("Gespeichert: ") + target, QStringLiteral("ok"));
        setDialog({});
    });
}

// ---- Picture preview in the panel ----

void Editor::showImageIn(QQuickItem* item) const {
    auto* target = qobject_cast<ComputeImage*>(item);
    if (!target || m_selIdx.size() != 1) return;
    const Element& e = *m_items[size_t(m_selIdx[0])].e;
    if (!e.isImage()) return;
    const int w = e.raster.width(), h = e.raster.height();
    const auto& gray = e.raster.gray();
    QImage img(gray.data(), w, h, w, QImage::Format_Grayscale8);
    // The panel's preview is small: a reduced picture keeps every slider step instant.
    constexpr int kSide = 720;
    target->setImage(std::max(w, h) > kSide ? img.scaled(kSide, kSide, Qt::KeepAspectRatio, Qt::SmoothTransformation) : img.copy());
}

// ---- Camera background ----

void Editor::loadBackground() {
    if (m_bgBusy) return;
    m_bgBusy = true;
    emit backgroundChanged();
    PiClient::instance()->get(QStringLiteral("/api/workspace/scan"), [this](const PiReply& r) {
        m_bgBusy = false;
        if (r.status == 404) {
            Toast::instance()->show(QStringLiteral("Auf dem Pi liegt noch kein Scan. Unter Maschine scannen."));
        } else if (!r.ok()) {
            Toast::instance()->show(QStringLiteral("Scan nicht geladen: ") + r.error, QStringLiteral("bad"));
        } else {
            QImage img = QImage::fromData(r.body);
            if (img.isNull()) Toast::instance()->show(QStringLiteral("Scan nicht lesbar."), QStringLiteral("bad"));
            else { m_bgImage = std::move(img); m_bgOn = true; }
        }
        emit backgroundChanged();
    }, 30000);
}

// ---- Test bench ----

int Editor::stress(int n) {
    lc::Document d;
    d.title = QStringLiteral("Belastung %1").arg(n);
    const int cols = int(std::ceil(std::sqrt(double(n)))), rows = cols;
    const double W = lc::Work::width() - 4, H = lc::Work::height() - 4 - lc::Work::park().height();
    const double dx = W / cols, dy = H / rows, r = std::min(dx, dy) * 0.42;
    d.elements.resize(size_t(n));
    const QString layerIds[3] = {d.layers[0].id, d.layers[1].id, d.layers[2].id};
    lc::parallelBlocks(n, 256, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
        for (std::ptrdiff_t i = a; i < b; ++i) {
            Element e = lc::newElement(layerIds[i % 3], QStringLiteral("Form"));
            const int segs = 24;
            const auto pts = e.paths.addUninitialized(size_t(segs) + 1);
            for (int k = 0; k <= segs; ++k) {
                const double t = (k % segs) * 6.283185307179586 / segs, w = 1 + 0.15 * std::sin(t * 5 + double(i));
                pts[size_t(k)] = {r + r * w * std::cos(t), r + r * w * std::sin(t)};
            }
            e.transform.x = 2 + double(i % cols) * dx;
            e.transform.y = 2 + lc::Work::park().height() + double(i / cols) * dy;
            d.elements[size_t(i)] = std::move(e);
        }
    });
    Document::instance()->load(std::move(d));
    return n;
}
void Editor::sample() {
    auto* doc = Document::instance();
    const QString engrave = doc->layerByName(QStringLiteral("Gravieren"));
    const QString mark = doc->layerByName(QStringLiteral("Linie"));
    const QString cut = doc->layerByName(QStringLiteral("Schneiden"));
    std::vector<Element> els;
    const auto at = [](Element e, double x, double y) { e.transform.x = x; e.transform.y = y; return e; };
    Element frame = curveElement(cut, QStringLiteral("Rechteck"), {lc::rectCurve(240, 170)}, {30, 60});
    els.push_back(std::move(frame));
    els.push_back(curveElement(mark, QStringLiteral("Ellipse"), {lc::ellipseCurve(120, 120)}, {58, 85}));
    els.push_back(curveElement(mark, QStringLiteral("Ellipse"), {lc::ellipseCurve(104, 104)}, {66, 93}));
    const auto text = [&](const QString& s, double size, bool bold, double x, double y) {
        Element e = lc::newElement(engrave, QStringLiteral("Text"));
        e.text = s; e.fontSizeMm = size; e.bold = bold;
        e.paths = lc::textPaths(s, size, bold, e.fontFamily);
        return at(std::move(e), x, y);
    };
    els.push_back(text(QStringLiteral("LumaCut"), 15, true, 80, 132));
    els.push_back(text(QStringLiteral("WERKSTATT"), 6, true, 96, 155));
    Element star = lc::newElement(engrave, QStringLiteral("Stern"));
    star.paths = PolySet{lc::makeShape(lc::ShapeKind::Star, 50, 50)};
    els.push_back(at(std::move(star), 188, 92));
    Element heart = lc::newElement(engrave, QStringLiteral("Herz"));
    heart.paths = PolySet{lc::makeShape(lc::ShapeKind::Heart, 32, 30)};
    els.push_back(at(std::move(heart), 228, 182));
    for (int i = 0; i < 9; ++i) els.push_back(curveElement(cut, QStringLiteral("Ellipse"), {lc::ellipseCurve(9, 9)}, {186.0 + i * 7.0, 170.0 + i * 3.5}));
    // A soft picture, so the raster path shows up.
    const int w = 240, h = 160;
    std::vector<uint8_t> gray(size_t(w) * h);
    for (int y = 0; y < h; ++y) for (int x = 0; x < w; ++x) {
        const double dx = (x - w / 2.0) / w, dy = (y - h / 2.0) / h;
        const double v = 0.5 + 0.5 * std::cos(std::hypot(dx, dy) * 14) * std::exp(-(dx * dx + dy * dy) * 6);
        gray[size_t(y) * w + x] = uint8_t(std::clamp(int(v * 255), 0, 255));
    }
    Element image = lc::newElement(engrave, QStringLiteral("Bild"));
    image.raster = lc::Raster::ofGray(w, h, std::move(gray));
    image.imageWidthMm = 78; image.imageHeightMm = 52;
    image.imageMode = ImageMode::Dither;
    els.push_back(at(std::move(image), 34, 246));
    doc->addElements(std::move(els));
    doc->clearSelection();
}
QVariantMap Editor::elementInfo(int index) const {
    const auto& list = Document::instance()->elements();
    if (index < 0 || index >= int(list.size())) return {};
    const Element& e = *list[size_t(index)];
    const auto b = worldBox(e);
    QVariantMap m{{"id", e.id}, {"kind", e.kind}, {"layer", e.layerId}, {"plate", e.plate}, {"x", e.transform.x}, {"y", e.transform.y},
                  {"sx", e.transform.scaleX}, {"sy", e.transform.scaleY}, {"rot", e.transform.rotation}, {"points", int(e.paths.pointCount())}, {"paths", int(e.paths.size())}};
    if (e.text) m["text"] = *e.text;
    if (b) { m["minX"] = b->minX; m["minY"] = b->minY; m["maxX"] = b->maxX; m["maxY"] = b->maxY; }
    if (e.curves) {
        QVariantList nodes;
        for (const CurvePath& c : *e.curves) for (const CurveNode& n : c.nodes) { const Pt w = e.transform.apply({n.x, n.y}); nodes.push_back(QVariantMap{{"x", w.x}, {"y", w.y}, {"smooth", n.smooth}}); }
        m["nodes"] = nodes;
    }
    if (e.isImage()) m["imageMode"] = modeName(e.imageMode);
    return m;
}
