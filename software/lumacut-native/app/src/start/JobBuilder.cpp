#include "JobBuilder.h"
#include "Machine.h"
#include "core/parallel.h"
#include "doc/Document.h"
#include "gpu/SegmentsItem.h"
#include <QRegularExpression>
#include <QTimer>
#include <algorithm>
#include <exception>
namespace lumacut { const char* version(); }

using lumacut::Motion;
using lumacut::Toolpath;

namespace {
constexpr int kDebounceMs = 120;

std::vector<uint32_t> pathStartsOf(const Toolpath& tp) {
    std::vector<uint32_t> out;
    bool was = false;
    for (size_t i = 0, n = tp.count(); i < n; ++i) {
        const bool on = tp.power[i] > 0;
        if (on && !was) out.push_back(uint32_t(i));
        was = on;
    }
    return out;
}
/** Work mm for the view: the file holds machine mm, and the work area is mirrored in X. */
std::shared_ptr<std::vector<GpuSegment>> segmentsOf(const Toolpath& tp) {
    auto v = std::make_shared<std::vector<GpuSegment>>(lumacut::toGpuSegments<GpuSegment>(tp));
    const float w = float(lumacut::Bed::width());
    GpuSegment* s = v->data();
    lumacut::parallelBlocks(std::ptrdiff_t(v->size()), 1 << 15, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
        for (std::ptrdiff_t i = a; i < b; ++i) { s[i].x0 = w - s[i].x0; s[i].x1 = w - s[i].x1; }
    });
    return v;
}
}

struct JobBuilder::Result {
    quint64 gen = 0;
    bool run = false;                   // the job running on the Pi, not the project's
    std::shared_ptr<Built> built;
    std::shared_ptr<std::vector<GpuSegment>> segs;
    QString error;
    qint64 writeMs = 0, parseMs = 0, segsMs = 0;
};

JobBuilder::JobBuilder(QObject* parent) : QObject(parent), m_debounce(new QTimer(this)) {
    m_clock.start();
    m_pool.setMaxThreadCount(2);        // one that may be finishing and the newest: never a pile of old runs
    m_debounce->setSingleShot(true);
    m_debounce->setInterval(kDebounceMs);
    connect(m_debounce, &QTimer::timeout, this, &JobBuilder::runBuild);
    connect(Document::instance(), &Document::changed, this, &JobBuilder::onDocChanged);
    connect(Machine::instance(), &Machine::changed, this, &JobBuilder::onMachine);
    connect(Machine::instance(), &Machine::bedChanged, this, [this] { schedule(false); });
}
JobBuilder::~JobBuilder() {
    m_gen.fetch_add(1);
    m_pool.waitForDone();
}

Motion JobBuilder::motion() const {
    // The Pi reports nulls until the motion was calibrated; then the firmware's values apply, as on Android.
    const QVariantMap m = Machine::instance()->status().value("config").toMap().value("motion").toMap();
    Motion out;
    const double a = m.value("accel").toDouble(), s = m.value("speed").toDouble();
    if (a > 0 && s > 0) { out.accel = a; out.speed = s; }
    return out;
}
QString JobBuilder::jobNameFrom(const QString& title) {
    static const QRegularExpression notWord(QStringLiteral("[^A-Za-z0-9_.-]+"));
    QString base = title.normalized(QString::NormalizationForm_KD);
    base.replace(notWord, QStringLiteral("-"));
    while (base.startsWith(u'-')) base.remove(0, 1);
    while (base.endsWith(u'-')) base.chop(1);
    if (base.isEmpty()) base = QStringLiteral("Auftrag");
    return base.left(60) + QStringLiteral(".gcode");
}

void JobBuilder::setActive(bool on) {
    if (on == m_active) return;
    m_active = on;
    if (on && m_stale && !m_useSaved) {
        m_changedAt = m_clock.elapsed();    // what happened while nobody looked does not count as waiting
        schedule(true);
    }
}
void JobBuilder::setPlate(int plate) {
    if (plate == m_plate) return;
    m_plate = plate;
    if (!m_useSaved) schedule(true);
}
void JobBuilder::useDocument() {
    m_useSaved = false;
    m_error.clear();
    m_key.clear();
    schedule(true);
}
void JobBuilder::onDocChanged() {
    if (m_useSaved) { m_stale = true; return; }
    if (buildKey() == m_key) return;
    schedule(false);
}
void JobBuilder::onMachine() {
    const Motion mo = motion();
    const QString k = QStringLiteral("%1/%2").arg(mo.accel).arg(mo.speed);
    if (k == m_motionKey) return;
    m_motionKey = k;
    if (buildKey() != m_key) schedule(false);
}
QString JobBuilder::buildKey() const {
    const Motion mo = motion();
    return QStringLiteral("%1|%2|%3|%4|%5|%6|%7").arg(Document::instance()->revision()).arg(m_plate).arg(mo.accel).arg(mo.speed)
        .arg(lumacut::Bed::width()).arg(lumacut::Bed::parkX()).arg(lumacut::Bed::parkY());
}
void JobBuilder::schedule(bool now) {
    if (m_changedAt < 0) m_changedAt = m_clock.elapsed();
    m_stale = true;
    if (!m_active || m_useSaved) return;
    // The old run stops at its next stage, and the view says "wird berechnet" at once.
    m_gen.fetch_add(1);
    // An empty plate needs no calculation: no flash of "wird berechnet".
    setBuilding(Document::instance()->plateSize(m_plate) > 0);
    if (now) { m_debounce->stop(); runBuild(); }
    else m_debounce->start();
}
void JobBuilder::setBuilding(bool on) {
    if (on != m_building) { m_building = on; emit stateChanged(); }
}

void JobBuilder::runBuild() {
    if (!m_active || m_useSaved) return;
    m_stale = false;
    m_key = buildKey();
    const quint64 gen = m_gen.fetch_add(1) + 1;
    auto* d = Document::instance();
    const Document::Snapshot snap = d->snapshot();
    const int plateCount = d->plateCount();
    const int plate = std::clamp(m_plate, 0, std::max(0, plateCount - 1));
    const Motion mo = motion();
    const QString title = plateCount > 1 ? QStringLiteral("%1 Platte %2").arg(d->title()).arg(plate + 1) : d->title();

    if (d->plateSize(plate) == 0) {     // nothing to build, nothing to wait for
        m_findings = startchecks::docFindings(lumacut::Document{}, plate, plateCount > 1, mo);
        m_built.reset();
        m_error.clear();
        m_changedAt = -1;
        m_awaitingPreview = false;
        setBuilding(false);
        emit findingsChanged();
        emit stateChanged();
        emit shownChanged();
        if (!m_run) push({});
        return;
    }
    setBuilding(true);
    m_pool.start([this, gen, snap, plate, plateCount, mo, title] {
        auto r = std::make_shared<Result>();
        r->gen = gen;
        const auto stale = [this, gen] { return m_gen.load() != gen; };
        if (stale()) return;
        try {
            QElapsedTimer t;
            t.start();
            // Only this plate's elements are copied.
            lumacut::Document model;
            model.title = snap.state.title;
            model.layers = *snap.state.layerList;
            model.plateCount = snap.state.plateCount;
            model.activePlate = plate;
            model.extra = snap.state.extra;
            for (const auto& e : *snap.state.elementList) if (e->plate == plate) model.elements.push_back(*e);
            auto f = std::make_shared<startchecks::Findings>(startchecks::docFindings(model, plate, plateCount > 1, mo));
            QMetaObject::invokeMethod(this, [this, gen, f] {
                if (m_gen.load() != gen) return;
                m_findings = *f;
                emit findingsChanged();
            }, Qt::QueuedConnection);
            if (stale()) return;
            lumacut::WriteOptions opt;
            opt.appVersion = lumacut::version();
            opt.motion = mo;
            auto b = std::make_shared<Built>();
            b->name = jobNameFrom(title);
            b->gcode = lumacut::writeMarlin(model, opt);
            r->writeMs = t.restart();
            if (stale()) return;
            b->tp = lumacut::parseToolpath(b->gcode);
            b->pathStarts = pathStartsOf(b->tp);
            r->parseMs = t.restart();
            if (stale()) return;
            r->segs = segmentsOf(b->tp);
            r->segsMs = t.elapsed();
            r->built = std::move(b);
        } catch (const lumacut::JobBuildError& e) {
            r->error = e.message();
        } catch (const std::exception& e) {
            r->error = QString::fromUtf8(e.what());
        }
        QMetaObject::invokeMethod(this, [this, r] { finish(r); }, Qt::QueuedConnection);
    });
}

void JobBuilder::finish(std::shared_ptr<Result> r) {
    if (r->run) {
        if (r->gen != m_runGen || !r->built) return;
        m_run = r->built;
        emit shownChanged();
        push(r->segs);
        return;
    }
    if (m_gen.load() != r->gen) return;     // overtaken: the newer run brings its own result
    m_built = r->built;
    m_error = r->error;
    setBuilding(false);
    const qint64 total = m_changedAt >= 0 ? m_clock.elapsed() - m_changedAt : -1;
    m_timings = {{"write", double(r->writeMs)}, {"parse", double(r->parseMs)}, {"segments", double(r->segsMs)}, {"total", double(total)}, {"preview", -1.0},
                 {"count", r->built ? double(r->built->tp.count()) : 0.0}, {"bytes", r->built ? double(r->built->gcode.size()) : 0.0}};
    emit timingsChanged();
    emit stateChanged();
    if (!m_run) {
        emit shownChanged();
        m_awaitingPreview = m_item && r->segs && m_changedAt >= 0;
        if (r->segs) push(r->segs);
        else if (m_item) m_item->clear();
    }
    if (!m_awaitingPreview) m_changedAt = -1;
}

void JobBuilder::beginSaved() {
    m_useSaved = true;
    m_debounce->stop();
    m_gen.fetch_add(1);
    m_findings = {};
    m_error.clear();
    m_built.reset();
    m_changedAt = m_clock.elapsed();
    setBuilding(true);
    emit findingsChanged();
    emit stateChanged();
    emit shownChanged();
    if (!m_run) push({});
}
void JobBuilder::useSaved(const QString& name, const QByteArray& gcode) {
    const quint64 gen = m_gen.fetch_add(1) + 1;
    m_pool.start([this, gen, name, gcode] {
        auto r = std::make_shared<Result>();
        r->gen = gen;
        try {
            QElapsedTimer t;
            t.start();
            auto b = std::make_shared<Built>();
            b->name = name;
            b->gcode = gcode;
            b->tp = lumacut::parseToolpath(b->gcode);
            b->pathStarts = pathStartsOf(b->tp);
            r->parseMs = t.restart();
            r->segs = segmentsOf(b->tp);
            r->segsMs = t.elapsed();
            r->built = std::move(b);
        } catch (const std::exception& e) {
            r->error = QStringLiteral("Vorschau nicht möglich: ") + QString::fromUtf8(e.what());
        }
        QMetaObject::invokeMethod(this, [this, r] { finish(r); }, Qt::QueuedConnection);
    });
}
void JobBuilder::setSavedError(const QString& message) {
    m_gen.fetch_add(1);
    m_error = message;
    m_built.reset();
    setBuilding(false);
    emit stateChanged();
    emit shownChanged();
    push({});
}

void JobBuilder::showRun(const QString& name, const QByteArray& gcode) {
    const quint64 gen = ++m_runGen;
    m_pool.start([this, gen, name, gcode] {
        auto r = std::make_shared<Result>();
        r->gen = gen;
        r->run = true;
        try {
            auto b = std::make_shared<Built>();
            b->name = name;
            b->gcode = gcode;
            b->tp = lumacut::parseToolpath(b->gcode);
            b->pathStarts = pathStartsOf(b->tp);
            r->segs = segmentsOf(b->tp);
            r->built = std::move(b);
        } catch (const std::exception&) {
            return;     // the preview simply stays; the run itself is not affected
        }
        QMetaObject::invokeMethod(this, [this, r] { finish(r); }, Qt::QueuedConnection);
    });
}
void JobBuilder::clearRun() {
    ++m_runGen;
    if (!m_run) return;
    m_run.reset();
    emit shownChanged();
    push({});
}

void JobBuilder::attachPreview(QObject* item) {
    if (m_item) disconnect(m_item, nullptr, this, nullptr);
    m_item = qobject_cast<SegmentsItem*>(item);
    if (!m_item) return;
    connect(m_item, &SegmentsItem::loadingChanged, this, [this] {
        if (!m_item || m_item->loading() || !m_awaitingPreview) return;
        m_awaitingPreview = false;
        if (m_changedAt >= 0) m_timings.insert("preview", double(m_clock.elapsed() - m_changedAt));
        m_changedAt = -1;
        emit timingsChanged();
    });
    push({});
}

/** Hands the shown job to the view. Without ready segments they are made again on a worker, from the toolpath. */
void JobBuilder::push(std::shared_ptr<std::vector<GpuSegment>> segs) {
    if (!m_item) return;
    if (segs) { m_item->setSegments(std::move(*segs)); return; }
    const BuiltPtr job = shown();
    if (!job) { m_item->clear(); return; }
    QPointer<SegmentsItem> item = m_item;
    m_pool.start([this, job, item] {
        auto s = segmentsOf(job->tp);
        QMetaObject::invokeMethod(this, [this, job, item, s] {
            if (item && item == m_item && shown() == job) item->setSegments(std::move(*s));
        }, Qt::QueuedConnection);
    });
}
