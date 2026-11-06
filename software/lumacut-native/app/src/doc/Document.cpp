#include "Document.h"
#include "Shell.h"
#include "core/parallel.h"
#include <QSet>
#include <algorithm>

using lumacut::Element;
using lumacut::Layer;
using lumacut::Pt;
using lumacut::newId;
using lumacut::parallelFor;
using LDoc = lumacut::Document;

namespace {
constexpr int kHistorySteps = 200;
constexpr qint64 kHistoryBytes = qint64(1) << 30;   // copies held only by the history; the newest step always stays
constexpr int kParallelFrom = 2000;

qint64 elementBytes(const Element& e) { return qint64(e.paths.pointCount()) * qint64(sizeof(Pt)) + 256; }

QString defaultActiveLayer(const std::vector<Layer>& layers) {
    for (const Layer& l : layers) if (l.name == QLatin1String("Gravieren")) return l.id;
    return layers.empty() ? QString() : layers.front().id;
}
Document::State stateOf(LDoc&& d) {
    Document::State s;
    s.title = std::move(d.title);
    s.layerList = std::make_shared<std::vector<Layer>>(std::move(d.layers));
    s.elementList = std::make_shared<Document::ElementList>();
    s.elementList->reserve(d.elements.size());
    for (Element& e : d.elements) s.elementList->push_back(std::make_shared<const Element>(std::move(e)));
    s.plateCount = d.plateCount;
    s.activePlate = d.activePlate;
    s.extra = std::move(d.extra);
    return s;
}
}  // namespace

std::vector<Layer>& Document::State::editLayers() {
    if (layerList.use_count() != 1) layerList = std::make_shared<std::vector<Layer>>(*layerList);
    return *layerList;
}
Document::ElementList& Document::State::editElements() {
    if (elementList.use_count() != 1) elementList = std::make_shared<ElementList>(*elementList);
    return *elementList;
}

LDoc Document::Snapshot::build() const {
    LDoc d;
    d.title = state.title;
    d.layers = *state.layerList;
    d.plateCount = state.plateCount;
    d.activePlate = state.activePlate;
    d.extra = state.extra;
    d.elements.reserve(state.elementList->size());
    for (const ElementPtr& e : *state.elementList) d.elements.push_back(*e);
    return d;
}

Document::Document(QObject* parent) : QObject(parent) {
    m_state = stateOf(LDoc{});
    m_saved = m_state;
    m_activeLayer = defaultActiveLayer(layers());
    auto* shell = Shell::instance();
    shell->setProjectTitle(m_state.title);
    shell->setProjectDirty(false);
    connect(this, &Document::titleChanged, shell, [this, shell] { shell->setProjectTitle(m_state.title); });
    connect(this, &Document::dirtyChanged, shell, [this, shell] { shell->setProjectDirty(m_dirty); });
}

const Layer* Document::layer(const QString& id) const {
    for (const Layer& l : layers()) if (l.id == id) return &l;
    return nullptr;
}
void Document::rebuildIndex() const {
    if (m_indexValid) return;
    m_index.clear();
    const auto& list = elements();
    m_index.reserve(qsizetype(list.size()));
    for (size_t i = 0; i < list.size(); ++i) m_index.insert(list[i]->id, int(i));
    m_indexValid = true;
}
int Document::indexOf(const QString& id) const {
    rebuildIndex();
    return m_index.value(id, -1);
}
const Element* Document::element(const QString& id) const {
    const int i = indexOf(id);
    return i < 0 ? nullptr : elements()[size_t(i)].get();
}
Document::ElementPtr Document::elementPtr(const QString& id) const {
    const int i = indexOf(id);
    return i < 0 ? nullptr : elements()[size_t(i)];
}
const LDoc& Document::doc() const {
    if (!m_built) m_built = std::make_shared<const LDoc>(snapshot().build());
    return *m_built;
}

qint64 Document::stepCost(const State& older, const State& newer) const {
    if (older.elementList == newer.elementList) return 512;
    const auto& a = *older.elementList;
    const auto& b = *newer.elementList;
    qint64 cost = qint64(b.size()) * qint64(sizeof(ElementPtr));
    if (a.size() == b.size()) {
        for (size_t i = 0; i < a.size(); ++i) if (a[i] != b[i]) cost += elementBytes(*a[i]);
    } else if (a.size() > b.size()) {
        // Something was removed: what the older state alone keeps alive is at most the difference.
        for (size_t i = 0, n = a.size() - b.size(); i < n; ++i) cost += 512;
    }
    return cost;
}
void Document::pushPast(const State& s) {
    m_past.push_back({s, 0});
    m_future.clear();
    if (int(m_past.size()) > kHistorySteps) {
        m_historyBytes -= m_past.front().cost;
        m_past.erase(m_past.begin());
    }
}
void Document::setDirty(bool v) {
    if (v == m_dirty) return;
    m_dirty = v;
    emit dirtyChanged();
}
bool Document::matchesSaved() const {
    return m_state.elementList == m_saved.elementList && m_state.layerList == m_saved.layerList
        && m_state.title == m_saved.title && m_state.plateCount == m_saved.plateCount;
}
void Document::noteList(const std::shared_ptr<ElementList>& before) {
    // Same ids in the same order: the id index and the selection stay right. Decided by pointers, untouched elements are not read.
    if (before == m_state.elementList) { m_sameIds = true; return; }
    const ElementList& a = *before;
    const ElementList& b = elements();
    m_sameIds = a.size() == b.size();
    if (m_sameIds) for (size_t i = 0; i < a.size(); ++i) if (a[i] != b[i] && a[i]->id != b[i]->id) { m_sameIds = false; break; }
    if (!m_sameIds) m_indexValid = false;
}
void Document::afterChange(bool titleChangedToo) {
    m_built.reset();
    ++m_revision;
    if (m_past.size() >= 2) {
        // Drop the oldest steps once the copies they alone hold get too large.
        Step& last = m_past.back();
        if (last.cost == 0) {
            last.cost = stepCost(last.state, m_state);
            m_historyBytes += last.cost;
        }
        while (m_historyBytes > kHistoryBytes && m_past.size() > 2) {
            m_historyBytes -= m_past.front().cost;
            m_past.erase(m_past.begin());
        }
    }
    setDirty(!matchesSaved());
    if (titleChangedToo) emit titleChanged();
    emit changed();
    emit historyChanged();
}

void Document::commit(const std::function<void(State&)>& fn) {
    State next = m_state;
    fn(next);
    const bool same = next.elementList == m_state.elementList && next.layerList == m_state.layerList
        && next.title == m_state.title && next.plateCount == m_state.plateCount
        && next.activePlate == m_state.activePlate && next.extra == m_state.extra;
    if (same) return;
    const bool titleDiffers = next.title != m_state.title;
    const auto before = m_state.elementList;
    pushPast(m_state);
    m_state = std::move(next);
    noteList(before);
    applySelectionFilter();
    ensureActiveLayer();
    afterChange(titleDiffers);
}
void Document::mutate(const std::function<void(State&)>& fn) {
    const QString oldTitle = m_state.title;
    // A list nobody else holds gets edited in place: then it must be assumed changed.
    const auto before = m_state.elementList;
    fn(m_state);
    if (before == m_state.elementList) { m_sameIds = false; m_indexValid = false; }
    else noteList(before);
    applySelectionFilter();
    ensureActiveLayer();
    afterChange(oldTitle != m_state.title);
}
void Document::checkpoint() {
    pushPast(m_state);
    emit historyChanged();
}

void Document::mutateElementsIn(State& s, const QStringList& ids, const std::function<void(Element&)>& fn) {
    if (ids.isEmpty()) return;
    ElementList& list = s.editElements();
    std::vector<int> at;
    at.reserve(size_t(ids.size()));
    // Through the id index, so a change to a few elements costs the same at 100,000. The state here came from m_state,
    // whose list has the same ids in the same order. Only callers that added elements earlier in the same commit differ.
    rebuildIndex();
    for (const QString& id : ids) {
        const auto f = m_index.constFind(id);
        if (f != m_index.constEnd() && size_t(*f) < list.size() && list[size_t(*f)]->id == id) at.push_back(*f);
    }
    const auto one = [&](int k) {
        auto copy = std::make_shared<Element>(*list[size_t(k)]);
        fn(*copy);
        list[size_t(k)] = std::move(copy);
    };
    if (int(at.size()) >= kParallelFrom) {
        parallelFor(std::ptrdiff_t(at.size()), [&](std::ptrdiff_t i) { one(at[size_t(i)]); });
    } else {
        for (int k : at) one(k);
    }
}
void Document::updateElements(const QStringList& ids, const std::function<void(Element&)>& fn) {
    if (ids.isEmpty()) return;
    commit([&](State& s) { mutateElementsIn(s, ids, fn); });
}
void Document::mutateElements(const QStringList& ids, const std::function<void(Element&)>& fn) {
    if (ids.isEmpty()) return;
    mutate([&](State& s) { mutateElementsIn(s, ids, fn); });
}

void Document::addElements(std::vector<Element> els) {
    if (els.empty()) return;
    QStringList ids;
    ids.reserve(qsizetype(els.size()));
    commit([&](State& s) {
        ElementList& list = s.editElements();
        list.reserve(list.size() + els.size());
        for (Element& e : els) {
            e.plate = s.activePlate;
            if (e.id.isEmpty()) e.id = newId();
            if (!layer(e.layerId)) e.layerId = m_activeLayer;
            ids.push_back(e.id);
            list.push_back(std::make_shared<const Element>(std::move(e)));
        }
    });
    select(ids);
}

QString Document::layerByName(const QString& name) {
    for (const Layer& l : layers()) if (l.name == name) return l.id;
    if (!LDoc::isStandardLayer(name)) return layers().front().id;
    for (Layer& fresh : LDoc::defaultLayers()) {
        if (fresh.name != name) continue;
        const QString id = fresh.id;
        commit([&](State& s) { s.editLayers().push_back(fresh); });
        return id;
    }
    return layers().front().id;
}

void Document::fromModel(LDoc&& d) {
    const bool wasTitle = d.title != m_state.title;
    m_state = stateOf(std::move(d));
    m_saved = m_state;
    m_past.clear();
    m_future.clear();
    m_historyBytes = 0;
    m_selection.clear();
    m_selectionSet.clear();
    m_activeLayer = defaultActiveLayer(layers());
    m_built.reset();
    m_indexValid = false;
    m_sameIds = false;
    ++m_revision;
    setDirty(false);
    if (wasTitle) emit titleChanged();
    emit selectionChanged();
    emit activeLayerChanged();
    emit changed();
    emit historyChanged();
    emit replaced();
}
void Document::load(LDoc doc, const QString& filePath) {
    fromModel(doc.normalized());
    if (filePath != m_filePath) { m_filePath = filePath; emit filePathChanged(); }
}
bool Document::loadJson(QByteArrayView json, const QString& filePath, QString* error) {
    try {
        load(LDoc::fromJson(json), filePath);
        return true;
    } catch (const std::exception& e) {
        if (error) *error = QString::fromUtf8(e.what());
        return false;
    }
}
void Document::reset() {
    fromModel(LDoc{});
    if (!m_filePath.isEmpty()) { m_filePath.clear(); emit filePathChanged(); }
}
void Document::markSaved(const QString& filePath) {
    m_saved = m_state;
    setDirty(false);
    if (!filePath.isEmpty() && filePath != m_filePath) { m_filePath = filePath; emit filePathChanged(); }
}

void Document::setTitle(const QString& v) {
    if (v == m_state.title) return;
    commit([&](State& s) { s.title = v; });
}
void Document::setActiveLayer(const QString& id) {
    if (id == m_activeLayer || !layer(id)) return;
    m_activeLayer = id;
    emit activeLayerChanged();
}
void Document::ensureActiveLayer() {
    if (layer(m_activeLayer)) return;
    m_activeLayer = defaultActiveLayer(layers());
    emit activeLayerChanged();
}
void Document::setActivePlate(int i) {
    if (i < 0 || i >= plateCount() || i == activePlate()) return;
    // Which plate is shown is a view, not an edit: no undo step and not dirty on its own.
    m_state.activePlate = i;
    m_built.reset();
    ++m_revision;
    if (!m_selection.isEmpty()) setSelectionInternal({});
    emit changed();
}

void Document::setSelectionInternal(QStringList ids) {
    m_selection = std::move(ids);
    m_selectionSet = QSet<QString>(m_selection.begin(), m_selection.end());
    emit selectionChanged();
}
void Document::select(const QStringList& ids) {
    if (ids == m_selection) return;
    setSelectionInternal(ids);
}
void Document::applySelectionFilter() {
    if (m_selection.isEmpty() || m_sameIds) return;
    QSet<QString> have;
    have.reserve(qsizetype(elements().size()));
    for (const ElementPtr& e : elements()) if (m_selectionSet.contains(e->id)) have.insert(e->id);
    if (have.size() == m_selection.size()) return;
    QStringList kept;
    for (const QString& id : std::as_const(m_selection)) if (have.contains(id)) kept.push_back(id);
    setSelectionInternal(std::move(kept));
}

void Document::undo() {
    if (m_past.empty()) return;
    Step step = std::move(m_past.back());
    m_past.pop_back();
    m_historyBytes -= step.cost;
    const bool titleDiffers = step.state.title != m_state.title;
    m_future.push_back({m_state, 0});
    const auto before = m_state.elementList;
    m_state = std::move(step.state);
    noteList(before);
    applySelectionFilter();
    ensureActiveLayer();
    afterChange(titleDiffers);
}
void Document::redo() {
    if (m_future.empty()) return;
    Step step = std::move(m_future.back());
    m_future.pop_back();
    const bool titleDiffers = step.state.title != m_state.title;
    m_past.push_back({m_state, 0});
    const auto before = m_state.elementList;
    m_state = std::move(step.state);
    noteList(before);
    applySelectionFilter();
    ensureActiveLayer();
    afterChange(titleDiffers);
}

void Document::addPlate() {
    commit([](State& s) {
        s.activePlate = s.plateCount;
        s.plateCount += 1;
    });
    if (!m_selection.isEmpty()) setSelectionInternal({});
}
void Document::removePlate(int i) {
    if (plateCount() <= 1 || i < 0 || i >= plateCount()) return;
    commit([&](State& s) {
        ElementList kept;
        kept.reserve(s.elements().size());
        for (const ElementPtr& e : s.elements()) {
            if (e->plate == i) continue;
            if (e->plate > i) {
                auto copy = std::make_shared<Element>(*e);
                copy->plate -= 1;
                kept.push_back(std::move(copy));
            } else {
                kept.push_back(e);
            }
        }
        s.elementList = std::make_shared<ElementList>(std::move(kept));
        s.plateCount -= 1;
        s.activePlate = s.activePlate >= i ? std::max(0, s.activePlate - 1) : s.activePlate;
    });
}
int Document::plateSize(int i) const {
    int n = 0;
    for (const ElementPtr& e : elements()) if (e->plate == i) ++n;
    return n;
}
void Document::moveToPlate(const QStringList& ids, int target) {
    if (target < 0 || target >= plateCount() || ids.isEmpty()) return;
    updateElements(ids, [target](Element& e) { e.plate = target; });
    if (!m_selection.isEmpty()) setSelectionInternal({});
}
