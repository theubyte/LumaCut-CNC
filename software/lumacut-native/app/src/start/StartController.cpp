#include "StartController.h"
#include "AppSettings.h"
#include "Fmt.h"
#include "Machine.h"
#include "MachineActions.h"
#include "Materials.h"
#include "PiClient.h"
#include "Toast.h"
#include "Workspace.h"
#include "core/frame.h"
#include "doc/Document.h"
#include <QFile>
#include <QFileInfo>
#include <QSaveFile>
#include <QSet>
#include <QUrl>
#include <algorithm>
#include <cmath>

using namespace startchecks;

namespace {
constexpr double kPlaySeconds = 14;
constexpr int kLongMs = 120000;

QString metres(double mm) {
    if (mm >= 1000) return Fmt::de(mm / 1000, 2) + QStringLiteral(" m");
    return QString::number(qRound(mm)) + QStringLiteral(" mm");
}
QString sizeOf(double bytes) {
    if (bytes >= 1048576) return Fmt::de(bytes / 1048576, 1) + QStringLiteral(" MB");
    return QString::number(std::max(1, int(std::round(bytes / 1024)))) + QStringLiteral(" KB");
}
QString enc(const QString& s) { return QString::fromLatin1(QUrl::toPercentEncoding(s)); }
QString dash(bool building) { return building ? QStringLiteral("…") : QStringLiteral("–"); }

struct Phase { const char* label; QStringList states; };
const std::vector<Phase>& phaseList() {
    static const std::vector<Phase> p = {
        {"Referenzieren", {"homing"}}, {"Material abtasten", {"probing"}}, {"Höhe korrigieren", {"focusing"}},
        {"Lasern", {"running"}}, {"Parken", {"finishing", "parking"}}};
    return p;
}
}

StartController::StartController(QObject* parent) : QObject(parent) {
    m_dockOpen = AppSettings::instance()->value("start/dock", false).toBool();
    auto* b = JobBuilder::instance();
    connect(b, &JobBuilder::stateChanged, this, &StartController::refresh);
    connect(b, &JobBuilder::findingsChanged, this, &StartController::refresh);
    connect(b, &JobBuilder::shownChanged, this, &StartController::onShown);
    connect(Machine::instance(), &Machine::changed, this, &StartController::onMachine);
    connect(Machine::instance(), &Machine::bedChanged, this, &StartController::refresh);
    connect(Workspace::instance(), &Workspace::changed, this, &StartController::refresh);
    connect(Materials::instance(), &Materials::changed, this, &StartController::refresh);
    connect(Document::instance(), &Document::changed, this, [this] {
        // A changed project makes an old refusal pointless.
        if (!isSaved() && !m_rejection.isEmpty()) m_rejection.clear();
        refresh();
    });
}

void StartController::enter() {
    m_entered = true;
    m_chosenPlate = Document::instance()->activePlate();
    auto* b = JobBuilder::instance();
    b->setPlate(m_chosenPlate);
    b->setActive(true);
    if (Workspace::instance()->revision() < 0) Workspace::instance()->load();
    Materials::instance()->load();
    reloadJobs();
    followRunningJob();
    refresh();
}
void StartController::leave() {
    m_entered = false;
    m_playing = false;
    JobBuilder::instance()->setActive(false);
    emit playChanged();
}

QVariantMap StartController::jobMap() const { return Machine::instance()->status().value("job").toMap(); }
bool StartController::running() const { return Machine::instance()->jobActive(); }
bool StartController::framing() const { return Machine::instance()->frameActive(); }

QString StartController::name() const {
    if (isSaved()) return m_saved;
    auto* d = Document::instance();
    return JobBuilder::jobNameFrom(d->plateCount() > 1 ? QStringLiteral("%1 Platte %2").arg(d->title()).arg(plate() + 1) : d->title());
}
int StartController::plate() const { return std::clamp(m_chosenPlate, 0, std::max(0, Document::instance()->plateCount() - 1)); }
bool StartController::multi() const { return Document::instance()->plateCount() > 1; }
QVariantList StartController::plateOptions() const {
    QVariantList out;
    auto* d = Document::instance();
    for (int i = 0; i < d->plateCount(); ++i)
        out.append(QVariantMap{{"value", i}, {"label", QString::number(i + 1)}, {"tip", QStringLiteral("Platte %1: %2 Elemente").arg(i + 1).arg(d->plateSize(i))}});
    return out;
}
QString StartController::overlay() const {
    auto* b = JobBuilder::instance();
    if (running() && b->shown()) return {};
    if (b->building()) return b->shown() ? QString() : QStringLiteral("building");
    if (!isSaved() && Document::instance()->plateSize(plate()) == 0) return QStringLiteral("empty");
    if (!b->error().isEmpty()) return QStringLiteral("error");
    return {};
}
QString StartController::emptyTitle() const {
    const QString o = overlay();
    if (o == QLatin1String("building")) return QStringLiteral("Auftrag wird berechnet …");
    if (o == QLatin1String("error")) return QStringLiteral("Keine Vorschau möglich");
    return multi() ? QStringLiteral("Platte %1 ist leer").arg(plate() + 1) : QStringLiteral("Noch kein Motiv");
}
QString StartController::emptyText() const {
    const QString o = overlay();
    if (o == QLatin1String("building")) return {};
    if (o == QLatin1String("error")) return QStringLiteral("Rechts unter „Prüfungen“ steht, was zu tun ist.");
    return multi() ? QStringLiteral("Eine andere Platte wählen oder im Motiv etwas auf diese Platte legen.")
                   : QStringLiteral("Lege im Bereich Motiv etwas an. Hier erscheint dann, was der Laser fährt.");
}

bool StartController::materialChosen() const { return Workspace::instance()->hasMaterial(); }
QString StartController::materialText() const {
    auto* w = Workspace::instance();
    if (w->revision() < 0) return QStringLiteral("…");
    if (!w->hasMaterial()) return QStringLiteral("Noch keines gewählt");
    return QStringLiteral("%1, %2 mm").arg(w->materialName(), Fmt::trim(w->materialThickness(), 2));
}
QString StartController::estimate() const {
    const auto j = JobBuilder::instance()->built();
    return j ? lumacut::formatDuration(j->tp.stats.seconds) : dash(JobBuilder::instance()->building());
}
QString StartController::cutLength() const {
    const auto j = JobBuilder::instance()->built();
    return j ? metres(j->tp.stats.cutMm) : dash(JobBuilder::instance()->building());
}
QString StartController::travelLength() const {
    const auto j = JobBuilder::instance()->built();
    return j ? metres(j->tp.stats.travelMm) : dash(JobBuilder::instance()->building());
}
QString StartController::sizeText() const {
    const auto j = JobBuilder::instance()->built();
    if (!j || !j->tp.bounds) return dash(JobBuilder::instance()->building());
    return QStringLiteral("%1 × %2 mm").arg(qRound(j->tp.bounds->width())).arg(qRound(j->tp.bounds->height()));
}
QVariantList StartController::layerRows() const { return JobBuilder::instance()->findings().layerRows; }

void StartController::recomputeChecks() {
    auto* b = JobBuilder::instance();
    auto* m = Machine::instance();
    auto* w = Workspace::instance();
    Input in;
    in.findings = b->findings();
    if (const auto job = b->built()) {
        in.hasToolpath = true;
        in.bounds = job->tp.bounds;
        in.warnings = job->tp.stats.warnings;
        in.gcodeBytes = job->gcode.size();
    }
    in.buildError = b->error();
    in.rejection = m_rejection;
    in.status = m->status();
    in.online = m->online();
    in.jobActive = m->jobActive();
    in.frameActive = m->frameActive();
    in.materialKnown = w->revision() >= 0;
    in.hasMaterial = w->hasMaterial();
    in.materialName = w->materialName();
    if (in.hasMaterial && Materials::instance()->fromPi()) {
        // Laser only on values that were tried on this machine: an entry the operator saved or measured.
        bool tested = false;
        const QString wanted = w->materialName().trimmed().toLower();
        for (const QVariant& v : Materials::instance()->items()) {
            const QVariantMap e = v.toMap();
            if (e.value("name").toString().trimmed().toLower() != wanted) continue;
            if (std::abs(e.value("thickness_mm").toDouble() - w->materialThickness()) >= 0.01) continue;
            if (!e.value("builtin").toBool() || !e.value("tone_curve").isNull()) { tested = true; break; }
        }
        in.materialTested = tested;
    }
    const std::vector<Check> list = computeChecks(in);
    m_checks.clear();
    m_serious = false;
    m_firstBad.clear();
    for (const Check& c : list) {
        if (c.tone != QLatin1String("info")) m_serious = true;
        if (m_firstBad.isEmpty() && c.tone == QLatin1String("bad")) m_firstBad = c.text;
        QString html = c.text.toHtmlEscaped();
        if (!c.goLabel.isEmpty()) html += QStringLiteral(" <a href=\"%1\">%2</a>").arg(c.goDest, c.goLabel.toHtmlEscaped());
        m_checks.append(QVariantMap{{"id", c.id}, {"tone", c.tone}, {"text", c.text}, {"html", html}, {"goDest", c.goDest}});
    }
    m_blocked = blocksStart(list);
}
void StartController::refresh() {
    recomputeChecks();
    emit changed();
    emit playChanged();
}
void StartController::onShown() {
    m_pos = -1;
    m_playing = false;
    refresh();
}
void StartController::onMachine() {
    if (m_entered) { followRunningJob(); updateJobs(); }
    refresh();
}
void StartController::followRunningJob() {
    const QString file = jobMap().value("file").toString();
    auto* b = JobBuilder::instance();
    if (!running() || file.isEmpty() || file == name()) {
        m_runFetched.clear();
        b->clearRun();
        return;
    }
    if (file == m_runFetched) return;
    m_runFetched = file;
    PiClient::instance()->get(QStringLiteral("/api/jobs/%1/content").arg(enc(file)), PiCallback([this, file](const PiReply& r) {
        if (r.ok() && file == m_runFetched) JobBuilder::instance()->showRun(file, r.body);
    }), kLongMs);
}

QString StartController::startLock() const {
    auto* b = JobBuilder::instance();
    if (!m_firstBad.isEmpty()) return m_firstBad;
    if (!b->built() || b->building()) return QStringLiteral("Auftrag wird berechnet …");
    if (!m_busy.isEmpty()) return QStringLiteral("Einen Moment …");
    if (!Machine::instance()->free()) return QStringLiteral("Die Maschine ist noch beschäftigt: einen Moment warten.");
    return {};
}
QString StartController::frameLock() const {
    auto* b = JobBuilder::instance();
    auto* m = Machine::instance();
    if (!m->online()) return QStringLiteral("Der Pi ist nicht erreichbar.");
    if (!b->error().isEmpty()) return b->error();
    if (!b->built() || b->building()) return QStringLiteral("Auftrag wird berechnet …");
    if (!b->built()->tp.bounds) return QStringLiteral("Im Auftrag ist keine Laserbahn.");
    if (!m_busy.isEmpty()) return QStringLiteral("Einen Moment …");
    if (!m->free()) return QStringLiteral("Die Maschine ist noch beschäftigt: einen Moment warten.");
    return {};
}
QString StartController::frameText() const {
    const QVariantMap f = Machine::instance()->status().value("frame").toMap();
    return QStringLiteral("Rahmen abbrechen (%1/%2)").arg(f.value("line").toInt()).arg(f.value("total").toInt());
}

double StartController::fraction() const {
    const QVariantMap j = jobMap();
    const double total = j.value("total").toDouble();
    return total > 0 ? std::min(1.0, j.value("line").toDouble() / total) : 0.0;
}
bool StartController::lasering() const {
    if (!running()) return false;
    const QVariantMap j = jobMap();
    const QString st = j.value("state").toString();
    const QString ph = j.value("phase").toString();
    if ((ph.isEmpty() ? st : ph) == QLatin1String("homing") || ph == QLatin1String("focusing")) return false;
    return st == QLatin1String("running") || st == QLatin1String("finishing") || st == QLatin1String("parking");
}
QString StartController::runFile() const { const QString f = jobMap().value("file").toString(); return f.isEmpty() ? name() : f; }
double StartController::runShare() const {
    const QVariantMap j = jobMap();
    if (lasering()) return fraction();
    const QVariantMap p = j.value("probe").toMap();
    const QString ph = j.value("phase").toString().isEmpty() ? j.value("state").toString() : j.value("phase").toString();
    if (ph == QLatin1String("probing") && p.value("total").toInt() > 0) return p.value("done").toDouble() / p.value("total").toDouble();
    return 0;
}
QString StartController::runPercent() const { return QStringLiteral("%1 %").arg(int(std::floor(runShare() * 100))); }
QString StartController::runRemaining() const {
    const QVariantMap j = jobMap();
    const auto job = JobBuilder::instance()->shown();
    if (lasering() && job) return QStringLiteral("noch ca. %1").arg(lumacut::formatDuration(job->tp.stats.seconds * (1 - fraction())));
    const QVariantMap p = j.value("probe").toMap();
    const QString ph = j.value("phase").toString().isEmpty() ? j.value("state").toString() : j.value("phase").toString();
    if (ph == QLatin1String("probing") && p.value("total").toInt() > 0)
        return QStringLiteral("Messpunkt %1 von %2").arg(p.value("done").toInt()).arg(p.value("total").toInt());
    return QStringLiteral("Vorbereitung …");
}
QVariantList StartController::phases() const {
    const QVariantMap j = jobMap();
    const QString now = j.value("phase").toString().isEmpty() ? j.value("state").toString() : j.value("phase").toString();
    int at = 0;
    const auto& list = phaseList();
    for (size_t i = 0; i < list.size(); ++i) if (list[i].states.contains(now)) at = int(i);
    QVariantList out;
    for (int i = 0; i < int(list.size()); ++i)
        out.append(QVariantMap{{"label", QString::fromUtf8(list[size_t(i)].label)}, {"state", i < at ? "done" : i == at ? "now" : "next"}, {"number", i + 1}});
    return out;
}

QString StartController::resultKey() const {
    const QVariantMap j = jobMap();
    return j.value("file").toString() + u'|' + j.value("state").toString() + u'|' + j.value("error").toString();
}
QString StartController::resultState() const { return jobMap().value("state").toString(); }
bool StartController::resultShown() const {
    const QString s = resultState();
    return !running() && (s == QLatin1String("complete") || s == QLatin1String("aborted") || s == QLatin1String("error")) && m_dismissed != resultKey();
}
QString StartController::resultTone() const {
    const QString s = resultState();
    return s == QLatin1String("complete") ? QStringLiteral("ok") : s == QLatin1String("error") ? QStringLiteral("bad") : QStringLiteral("info");
}
QString StartController::resultText() const {
    const QVariantMap j = jobMap();
    const QString s = resultState();
    if (s == QLatin1String("complete")) {
        const QString f = j.value("file").toString();
        return QStringLiteral("Fertig: %1 ist gelasert, der Kopf steht geparkt.").arg(f.isEmpty() ? QStringLiteral("der Auftrag") : f);
    }
    if (s == QLatin1String("aborted")) return QStringLiteral("Abgebrochen: der Laser ist aus. Zum Wiederholen erneut starten.");
    const QString e = j.value("error").toString();
    return e.isEmpty() ? QStringLiteral("Der Auftrag wurde wegen eines Fehlers beendet.") : e;
}
void StartController::dismissResult() { m_dismissed = resultKey(); emit changed(); }

// ---- Preview ----
int StartController::segmentCount() const { const auto j = JobBuilder::instance()->shown(); return j ? int(j->tp.count()) : 0; }
int StartController::atLineFor(double f, const lumacut::Toolpath& tp) const {
    const uint32_t line = uint32_t(std::lround(f * tp.lineCount));
    return int(std::lower_bound(tp.line.begin(), tp.line.end(), line) - tp.line.begin());
}
int StartController::visibleCount() const {
    if (running()) {
        const auto j = JobBuilder::instance()->shown();
        return j && lasering() ? atLineFor(fraction(), j->tp) : 0;
    }
    return m_pos;
}
int StartController::sliderValue() const {
    const int v = visibleCount();
    return v < 0 ? segmentCount() : v;
}
QString StartController::readout() const {
    const auto j = JobBuilder::instance()->shown();
    if (!j || !j->tp.count()) return QStringLiteral("Kein Auftrag");
    const int upto = sliderValue();
    const auto& st = j->pathStarts;
    const int pathNo = int(std::lower_bound(st.begin(), st.end(), uint32_t(upto)) - st.begin());
    const double share = double(upto) / double(j->tp.count());
    return QStringLiteral("Bahn %1 von %2 · %3").arg(pathNo).arg(st.size()).arg(lumacut::formatDuration(j->tp.stats.seconds * share));
}
void StartController::setShowTravel(bool v) { if (v != m_showTravel) { m_showTravel = v; emit playChanged(); } }
void StartController::togglePlay() {
    const int n = segmentCount();
    if (!n || live()) return;
    m_playing = !m_playing;
    if (m_playing) {
        m_playAt = m_pos >= 0 && m_pos < n ? m_pos : 0;
        m_pos = int(m_playAt);
    }
    emit playChanged();
}
void StartController::advance(double seconds) {
    const int n = segmentCount();
    if (!m_playing || !n || live()) { if (m_playing) { m_playing = false; emit playChanged(); } return; }
    m_playAt = std::min(double(n), m_playAt + seconds * n / kPlaySeconds);
    m_pos = int(m_playAt);
    if (m_pos >= n) m_playing = false;
    emit playChanged();
}
void StartController::scrub(int value) {
    const int n = segmentCount();
    if (!n || live()) return;
    m_playing = false;
    m_pos = value >= n ? -1 : std::max(0, value);
    emit playChanged();
}
void StartController::toBeginning() { scrub(0); }
void StartController::step(int dir) {
    const auto j = JobBuilder::instance()->shown();
    if (!j || !j->tp.count() || live()) return;
    m_playing = false;
    const auto& st = j->pathStarts;
    const int n = int(j->tp.count());
    const int cur = m_pos >= 0 ? m_pos : (dir < 0 ? n : 0);
    if (dir > 0) {
        const auto it = std::upper_bound(st.begin(), st.end(), uint32_t(cur));
        m_pos = it == st.end() ? -1 : int(*it);
    } else {
        const auto it = std::lower_bound(st.begin(), st.end(), uint32_t(cur));
        m_pos = it == st.begin() ? 0 : int(*(it - 1));
    }
    emit playChanged();
}
bool StartController::hasBounds() const { const auto j = JobBuilder::instance()->shown(); return j && j->tp.bounds.has_value(); }
double StartController::boundsX0() const { const auto j = JobBuilder::instance()->shown(); return j && j->tp.bounds ? lumacut::Bed::width() - j->tp.bounds->maxX : 0; }
double StartController::boundsX1() const { const auto j = JobBuilder::instance()->shown(); return j && j->tp.bounds ? lumacut::Bed::width() - j->tp.bounds->minX : 0; }
double StartController::boundsY0() const { const auto j = JobBuilder::instance()->shown(); return j && j->tp.bounds ? j->tp.bounds->minY : 0; }
double StartController::boundsY1() const { const auto j = JobBuilder::instance()->shown(); return j && j->tp.bounds ? j->tp.bounds->maxY : 0; }
bool StartController::headVisible() const {
    if ((running() || framing()) && Machine::instance()->hasPosition()) return true;
    const int n = segmentCount();
    return m_pos > 0 && m_pos < n;
}
QPointF StartController::head() const {
    auto* m = Machine::instance();
    if ((running() || framing()) && m->hasPosition()) return {m->workX(), m->workY()};
    const auto j = JobBuilder::instance()->shown();
    if (j && m_pos > 0 && m_pos < int(j->tp.count())) {
        const size_t k = size_t(m_pos - 1) * 4;
        return {lumacut::Bed::width() - j->tp.xy[k + 2], j->tp.xy[k + 3]};
    }
    return {};
}
QString StartController::parkName() const {
    return lumacut::Work::bandBlocked() ? QStringLiteral("Gesperrter Streifen") : QStringLiteral("Park-Ecke");
}

// ---- Actions ----
void StartController::setBusy(const QString& v) { if (v != m_busy) { m_busy = v; emit changed(); } }
void StartController::setRejection(const QString& v) { if (v != m_rejection) { m_rejection = v; refresh(); } }
void StartController::choosePlate(int p) {
    m_chosenPlate = p;
    m_rejection.clear();
    JobBuilder::instance()->setPlate(p);
    refresh();
}

void StartController::startJob() {
    const auto job = JobBuilder::instance()->built();
    if (!job || !m_busy.isEmpty() || !startLock().isEmpty()) return;
    setBusy(QStringLiteral("start"));
    setRejection({});
    const QString jobName = job->name;
    const bool saved = isSaved();
    const auto launch = [this, job, jobName, saved] {
        const bool needConfirm = Machine::instance()->status().value("home_needs_confirm").toBool();
        const QString detail = QStringLiteral("%1, Dauer ca. %2. Liegt das Material, und liegt es noch an derselben Stelle? ").arg(jobName, lumacut::formatDuration(job->tp.stats.seconds))
            + (needConfirm ? QStringLiteral("Der Pi kennt die Kopfhöhe nicht: steht die Tasterspitze über allem, was auf dem Bett liegt? ") : QString())
            + QStringLiteral("Danach läuft alles von selbst: Referenzieren, Abtasten, Höhenkorrektur, Lasern, Parken.");
        QVariantMap fields{{"name", jobName}};
        if (needConfirm) fields.insert("clear", 1);
        const QString title = multi() && !saved ? QStringLiteral("Platte %1 starten?").arg(plate() + 1) : QStringLiteral("Auftrag starten?");
        MachineActions::instance()->run(QStringLiteral("autorun"), fields, QVariantMap{{"quiet", true}, {"go", QVariantMap{{"title", title}, {"detail", detail}}}},
            MachineActions::Done([this](bool ok, const QVariantMap& reply) {
                setBusy({});
                if (!ok && !reply.isEmpty()) setRejection(reply.value("error").toString());
            }));
    };
    if (saved) { launch(); return; }
    PiClient::instance()->upload(jobName, job->gcode, PiCallback([this, launch](const PiReply& r) {
        if (!r.ok()) { setBusy({}); setRejection(r.error); reloadJobs(); return; }
        reloadJobs();
        launch();
    }));
}

void StartController::frame() {
    const auto job = JobBuilder::instance()->built();
    if (!job || !job->tp.bounds || !m_busy.isEmpty() || !frameLock().isEmpty()) return;
    setBusy(QStringLiteral("frame"));
    setRejection({});
    QByteArray program;
    try {
        const lumacut::Box b = *job->tp.bounds;
        const std::vector<lumacut::Pt> corners{{b.minX, b.minY}, {b.maxX, b.maxY}};
        program = lumacut::frameProgram(corners, lumacut::FrameMode::Box);
    } catch (const std::exception& e) {
        setBusy({});
        setRejection(QString::fromUtf8(e.what()));
        return;
    }
    const QString jobName = job->name;
    const auto runFrame = [this, program, jobName] {
        MachineActions::instance()->run(QStringLiteral("frame"), QVariantMap{{"gcode", QString::fromUtf8(program)}, {"mode", QStringLiteral("box")}},
            QVariantMap{{"quiet", true}, {"go", QVariantMap{{"title", QStringLiteral("Rahmen fahren?")}, {"detail", QStringLiteral("Der Kopf fährt den Umriss von %1 ab.").arg(jobName)}}}},
            MachineActions::Done([this](bool ok, const QVariantMap& reply) {
                setBusy({});
                if (!ok && !reply.isEmpty()) setRejection(reply.value("error").toString());
            }));
    };
    if (Machine::instance()->homed()) { runFrame(); return; }
    QVariantMap fields;
    if (Machine::instance()->status().value("home_needs_confirm").toBool()) fields.insert("clear", 1);
    MachineActions::instance()->run(QStringLiteral("home"), fields,
        QVariantMap{{"quiet", true}, {"go", QVariantMap{{"title", QStringLiteral("Erst referenzieren?")}, {"detail", QStringLiteral("Für den Rahmen muss die Maschine wissen, wo der Kopf steht. Der Kopf fährt an die Endschalter.")}}}},
        MachineActions::Done([this, runFrame](bool ok, const QVariantMap& reply) {
            if (ok) { runFrame(); return; }
            setBusy({});
            if (!reply.isEmpty()) setRejection(reply.value("error").toString());
        }));
}

void StartController::abort() { MachineActions::instance()->run(QStringLiteral("abort"), {}, {}, MachineActions::Done{}); }

// ---- Queue ----
QVariantList StartController::queueItems() const {
    QVariantList out;
    static const QVariantMap labels{{"queued", "wartet"}, {"running", "läuft"}, {"done", "fertig"}, {"error", "Fehler"}, {"aborted", "abgebrochen"}, {"skipped", "übersprungen"}};
    static const QVariantMap tones{{"running", "accent"}, {"done", "ok"}, {"error", "bad"}, {"aborted", "warn"}};
    const QVariantList items = Machine::instance()->status().value("queue").toMap().value("items").toList();
    for (const QVariant& v : items) {
        const QVariantMap it = v.toMap();
        const QString st = it.value("state").toString();
        out.append(QVariantMap{{"id", it.value("id")}, {"file", it.value("file")}, {"state", st}, {"label", labels.value(st, st)}, {"tone", tones.value(st, QString())},
                               {"error", it.value("error").toString()}, {"canSkip", st == QLatin1String("queued")}, {"canRemove", st != QLatin1String("running")}});
    }
    return out;
}
int StartController::queueWaiting() const {
    int n = 0;
    for (const QVariant& v : queueItems()) { const QString st = v.toMap().value("state").toString(); if (st == QLatin1String("queued") || st == QLatin1String("running")) ++n; }
    return n;
}
bool StartController::queuePausing() const { return Machine::instance()->status().value("queue").toMap().value("state").toString() == QLatin1String("pausing"); }
bool StartController::queueActive() const {
    const QString s = Machine::instance()->status().value("queue").toMap().value("state").toString();
    return s == QLatin1String("running") || s == QLatin1String("pausing");
}
QString StartController::queueTitle() const {
    const QString s = Machine::instance()->status().value("queue").toMap().value("state").toString();
    int queued = 0;
    for (const QVariant& v : queueItems()) if (v.toMap().value("state").toString() == QLatin1String("queued")) ++queued;
    if (s == QLatin1String("pausing")) return QStringLiteral("Warteschlange hält nach diesem Auftrag an");
    if (queued && s == QLatin1String("paused")) return QStringLiteral("Warteschlange pausiert");
    if (queued && s == QLatin1String("stopped")) return QStringLiteral("Warteschlange angehalten");
    return QStringLiteral("Warteschlange");
}
QString StartController::queueRunLabel() const {
    const QString s = Machine::instance()->status().value("queue").toMap().value("state").toString();
    int queued = 0;
    for (const QVariant& v : queueItems()) if (v.toMap().value("state").toString() == QLatin1String("queued")) ++queued;
    return queued && (s == QLatin1String("paused") || s == QLatin1String("stopped")) ? QStringLiteral("Fortsetzen") : QStringLiteral("Starten");
}
bool StartController::queueCanRun() const {
    int queued = 0;
    for (const QVariant& v : queueItems()) if (v.toMap().value("state").toString() == QLatin1String("queued")) ++queued;
    return queued > 0 && !running();
}
bool StartController::canEnqueueCurrent() const { return !isSaved() && JobBuilder::instance()->built() && !JobBuilder::instance()->building() && m_busy.isEmpty(); }
void StartController::enqueueCurrent() {
    const auto job = JobBuilder::instance()->built();
    if (!job || !canEnqueueCurrent()) return;
    setBusy(QStringLiteral("queue"));
    setRejection({});
    const QString n = job->name;
    PiClient::instance()->upload(n, job->gcode, PiCallback([this, n](const PiReply& r) {
        if (!r.ok()) { setBusy({}); setRejection(r.error); return; }
        MachineActions::instance()->run(QStringLiteral("queue_add"), QVariantMap{{"name", n}}, {}, MachineActions::Done([this](bool ok, const QVariantMap& reply) {
            setBusy({});
            if (!ok && !reply.isEmpty()) setRejection(reply.value("error").toString());
            reloadJobs();
        }));
    }));
}
void StartController::queueOp(const QString& op, int id) {
    static const QSet<QString> allowed{"queue_run", "queue_pause", "queue_skip", "queue_remove", "queue_clear"};
    if (!allowed.contains(op)) return;
    QVariantMap fields;
    if (id > 0) fields.insert("id", id);
    MachineActions::instance()->run(op, fields, QVariantMap{{"quiet", true}}, MachineActions::Done{});
}

// ---- Saved jobs ----
void StartController::updateJobs() {
    const QVariantMap st = Machine::instance()->status();
    const QString key = QStringLiteral("%1|%2|%3").arg(Machine::instance()->online()).arg(st.value("job").toMap().value("state").toString()).arg(st.value("queue").toMap().value("items").toList().size());
    if (key == m_jobsKey) {
        // Locks follow the queue and the run without asking the Pi again.
        return;
    }
    m_jobsKey = key;
    reloadJobs();
}
void StartController::reloadJobs() {
    if (!Machine::instance()->online() && PiClient::instance()->baseUrl().isEmpty()) return;
    PiClient::instance()->get(QStringLiteral("/api/jobs"), PiCallback([this](const PiReply& r) {
        if (!r.ok()) return;
        QVariantList files = r.map().value("files").toList();
        std::sort(files.begin(), files.end(), [](const QVariant& a, const QVariant& b) { return a.toMap().value("modified").toLongLong() > b.toMap().value("modified").toLongLong(); });
        QVariantList rows;
        for (const QVariant& v : files) {
            const QVariantMap f = v.toMap();
            const QString n = f.value("name").toString();
            const qint64 mod = f.value("modified").toLongLong();
            QStringList line;
            if (mod > 0) line << Fmt::when(mod);
            line << sizeOf(f.value("bytes").toDouble());
            rows.append(QVariantMap{{"name", n}, {"line", line.join(QStringLiteral(" · "))}});
        }
        m_jobs = rows;
        emit jobsChanged();
    }));
}
void StartController::previewSaved(const QString& n) {
    const int req = ++m_savedReq;
    const bool wasDoc = m_saved.isEmpty();
    m_saved = n;
    m_rejection.clear();
    m_pos = -1;
    JobBuilder::instance()->beginSaved();
    if (wasDoc) emit sourceSwitched();
    refresh();
    PiClient::instance()->get(QStringLiteral("/api/jobs/%1/content").arg(enc(n)), PiCallback([this, req, n](const PiReply& r) {
        if (req != m_savedReq) return;
        if (r.ok()) JobBuilder::instance()->useSaved(n, r.body);
        else JobBuilder::instance()->setSavedError(QStringLiteral("Vorschau nicht möglich: ") + r.error);
    }), kLongMs);
}
void StartController::backToDoc() {
    ++m_savedReq;
    m_saved.clear();
    m_rejection.clear();
    JobBuilder::instance()->useDocument();
    emit sourceSwitched();
    refresh();
}
void StartController::enqueueSaved(const QString& n) {
    MachineActions::instance()->run(QStringLiteral("queue_add"), QVariantMap{{"name", n}}, {}, MachineActions::Done{});
}
void StartController::deleteSaved(const QString& n) {
    Confirm::instance()->askNative(QVariantMap{{"title", QStringLiteral("„%1“ löschen?").arg(n)}, {"body", QStringLiteral("Der Auftrag verschwindet vom Pi. Das Projekt bleibt erhalten.")}, {"okLabel", QStringLiteral("Löschen")}, {"danger", true}},
        [this, n](bool yes) {
            if (!yes) return;
            PiClient::instance()->request("POST", QStringLiteral("/api/jobs/%1/delete").arg(enc(n)), {}, {}, 8000, PiCallback([this, n](const PiReply& r) {
                if (!r.ok()) { Toast::instance()->show(r.error, "bad"); return; }
                Toast::instance()->show(r.map().value("message").toString(), "ok");
                if (m_saved == n) backToDoc();
                reloadJobs();
            }));
        });
}
static QString localPath(const QString& path) { return path.startsWith(QLatin1String("file:")) ? QUrl(path).toLocalFile() : path; }
void StartController::uploadFile(const QString& filePath) {
    const QString path = localPath(filePath);
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly)) { Toast::instance()->show(QStringLiteral("Datei nicht lesbar: %1").arg(f.errorString()), "bad"); return; }
    if (f.size() > kMaxUploadBytes) { Toast::instance()->show(QStringLiteral("Der Pi nimmt höchstens 32 MB an."), "bad"); return; }
    const QByteArray data = f.readAll();
    const QString n = QFileInfo(path).fileName();
    PiClient::instance()->upload(n, data, PiCallback([this, n](const PiReply& r) {
        if (!r.ok()) { Toast::instance()->show(r.error, "bad"); return; }
        Toast::instance()->show(r.map().value("message").toString(), "ok");
        reloadJobs();
        previewSaved(n);
    }));
}
void StartController::exportSaved(const QString& n, const QString& filePath) {
    const QString path = localPath(filePath);
    PiClient::instance()->get(QStringLiteral("/api/jobs/%1/content").arg(enc(n)), PiCallback([n, path](const PiReply& r) {
        if (!r.ok()) { Toast::instance()->show(r.error, "bad"); return; }
        QSaveFile out(path);
        if (!out.open(QIODevice::WriteOnly) || out.write(r.body) != r.body.size() || !out.commit()) {
            Toast::instance()->show(QStringLiteral("Speichern fehlgeschlagen: %1").arg(out.errorString()), "bad");
            return;
        }
        Toast::instance()->show(QStringLiteral("%1 exportiert").arg(n), "ok");
    }), kLongMs);
}
void StartController::setDockOpen(bool v) {
    if (v == m_dockOpen) return;
    m_dockOpen = v;
    AppSettings::instance()->setValue("start/dock", v);
    emit dockChanged();
}
