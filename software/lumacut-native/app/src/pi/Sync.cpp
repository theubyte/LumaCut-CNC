#include "Sync.h"
#include "AppSettings.h"
#include "Fmt.h"
#include "Machine.h"
#include "PiClient.h"
#include "Toast.h"
#include "doc/Document.h"
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPointer>
#include <QRegularExpression>
#include <QSaveFile>
#include <QStandardPaths>
#include <QThreadPool>
#include <QTimer>
#include <QUrl>
#include <QtConcurrent/QtConcurrentRun>

namespace {
const char* const kDevice = "Windows-PC";
constexpr int kLongMs = 60000;
constexpr int kPushMs = 2000;
constexpr int kAutosaveMs = 4000;

QString enc(const QString& s) { return QString::fromLatin1(QUrl::toPercentEncoding(s)); }
QString sizeOf(double bytes) {
    if (bytes >= 1048576) return Fmt::de(bytes / 1048576, 1) + QStringLiteral(" MB");
    return QString::number(std::max(1, int(bytes / 1024 + 0.5))) + QStringLiteral(" KB");
}
QString revKey() { return QStringLiteral("sync/%1/project").arg(PiClient::instance()->baseUrl()); }
QString withSuffix(const QString& path) { return path.endsWith(QLatin1String(".lumacut"), Qt::CaseInsensitive) ? path : path + QStringLiteral(".lumacut"); }
QString localPath(const QString& path) { return path.startsWith(QLatin1String("file:")) ? QUrl(path).toLocalFile() : path; }

/** The project as text, without blocking the window: `then` runs on this thread again. */
template <class Then>
void jsonOnWorker(QObject* ctx, Then then) {
    const Document::Snapshot snap = Document::instance()->snapshot();
    const quint64 rev = Document::instance()->revision();
    QThreadPool::globalInstance()->start([ctx = QPointer<QObject>(ctx), snap, rev, then = std::move(then)]() mutable {
        auto json = std::make_shared<QByteArray>(snap.build().toJson());
        if (ctx) QMetaObject::invokeMethod(ctx.data(), [json, rev, then = std::move(then)]() mutable { then(*json, rev); }, Qt::QueuedConnection);
    });
}
/** Parses on a worker. Pictures make these files large. */
template <class Then>
void parseOnWorker(QObject* ctx, QByteArray text, Then then) {
    QThreadPool::globalInstance()->start([ctx = QPointer<QObject>(ctx), text = std::move(text), then = std::move(then)]() mutable {
        auto doc = std::make_shared<lumacut::Document>();
        QString error;
        try { *doc = lumacut::Document::fromJson(text); }
        catch (const std::exception& e) { error = QString::fromUtf8(e.what()); }
        if (ctx) QMetaObject::invokeMethod(ctx.data(), [doc, error, then = std::move(then)]() mutable { then(doc, error); }, Qt::QueuedConnection);
    });
}
}

Sync::Sync(QObject* parent) : QObject(parent), m_pushTimer(new QTimer(this)), m_autosaveTimer(new QTimer(this)) {
    m_pushTimer->setSingleShot(true);
    m_pushTimer->setInterval(kPushMs);
    connect(m_pushTimer, &QTimer::timeout, this, &Sync::push);
    m_autosaveTimer->setSingleShot(true);
    m_autosaveTimer->setInterval(kAutosaveMs);
    connect(m_autosaveTimer, &QTimer::timeout, this, &Sync::writeAutosave);
}

void Sync::start() {
    if (m_started) return;
    m_started = true;
    auto* d = Document::instance();
    connect(d, &Document::changed, this, &Sync::onDocChanged);
    connect(d, &Document::dirtyChanged, this, [this] { m_autosaveTimer->start(); emit stateChanged(); });
    connect(d, &Document::filePathChanged, this, &Sync::fileChanged);
    checkRecovered();
    // Automated runs start many fresh windows against one simulator: they share only when asked to.
    m_shared = !qEnvironmentVariableIsSet("LUMACUT_AUTOMATION_PORT") || qEnvironmentVariableIsSet("LUMACUT_SYNC");
    if (!m_shared) return;
    auto* m = Machine::instance();
    connect(m, &Machine::syncChanged, this, &Sync::onSync);
    connect(m, &Machine::changed, this, [this, m] {
        if (m->online() && !m_wasOnline) { pull(); m_pushTimer->start(); }
        m_wasOnline = m->online();
    });
}

QString Sync::filePath() const { return Document::instance()->filePath(); }
bool Sync::canSync() const {
    auto* m = Machine::instance();
    return m_shared && m->online() && m->status().value("features").toStringList().contains(QStringLiteral("workspace"));
}
int Sync::piRevision() const { return Machine::instance()->status().value("sync").toMap().value("project").toInt(); }
int Sync::baseRevision() const { return AppSettings::instance()->value(revKey(), 0).toInt(); }
void Sync::setBase(int rev) { AppSettings::instance()->setValue(revKey(), rev); emit stateChanged(); }
bool Sync::unsent() const {
    auto* d = Document::instance();
    return m_hasSynced ? d->revision() != m_syncedRev : d->dirty();
}
void Sync::setDialog(const QString& mode) { if (mode != m_dialog) { m_dialog = mode; emit stateChanged(); } }
void Sync::setBusy(bool v) { if (v != m_busy) { m_busy = v; emit stateChanged(); } }
void Sync::setConflict(bool v) { if (v != m_conflict) { m_conflict = v; emit stateChanged(); } }

void Sync::onDocChanged() {
    m_autosaveTimer->start();
    if (m_hasSynced && Document::instance()->revision() == m_syncedRev) return;
    m_pushTimer->start();
    emit stateChanged();
}
void Sync::onSync(const QVariantMap& sync) {
    const int rev = sync.value("project").toInt();
    if (rev == m_lastRev) return;
    m_lastRev = rev;
    pull();
}
/** One conversation at a time, so a status poll cannot overtake a save. */
void Sync::next() {
    m_talking = false;
    if (m_pullAgain) { m_pullAgain = false; pull(); }
    if (!m_talking && m_pushAgain) { m_pushAgain = false; push(); }
}

void Sync::pull() {
    if (m_talking) { m_pullAgain = true; return; }
    if (!canSync() || m_conflict) return;
    const int rev = piRevision();
    if (rev <= 0) return;
    const bool newer = rev > baseRevision();
    // A window that has neither sent nor taken anything yet follows the Pi, even if it knows that revision.
    if (!newer && m_hasSynced) return;
    if (unsent()) {
        if (newer) setConflict(true);   // the only way the dialog opens: someone else changed it, and so did this device
        return;
    }
    m_talking = true;
    readRemote(rev, [this, newer](bool ok) {
        if (ok && newer) Toast::instance()->show(QStringLiteral("Projekt vom Pi übernommen (an einem anderen Gerät geändert)"), "info");
        next();
    });
}
void Sync::readRemote(int rev, std::function<void(bool)> done) {
    PiClient::instance()->get(QStringLiteral("/api/workspace/project"), PiCallback([this, rev, done](const PiReply& r) {
        // 404: the Pi has nothing yet.
        if (!r.ok()) { done(false); return; }
        parseOnWorker(this, r.body, [this, rev, done](std::shared_ptr<lumacut::Document> doc, const QString& error) {
            if (!error.isEmpty()) { done(false); return; }
            takeRemote(std::move(*doc), rev);
            done(true);
        });
    }), kLongMs);
}
void Sync::takeRemote(lumacut::Document&& doc, int rev) {
    auto* d = Document::instance();
    d->load(std::move(doc));
    m_syncedRev = d->revision();
    m_hasSynced = true;
    m_wantPush = false;
    m_pushTimer->stop();
    setBase(rev);
}
void Sync::putProject(const QByteArray& json, int base, PiCallback done) {
    PiClient::instance()->request("PUT", QStringLiteral("/api/workspace/project?base_revision=%1&by=%2").arg(base).arg(QString::fromLatin1(kDevice)), "application/json", json, kLongMs, std::move(done));
}
void Sync::push() {
    if (m_talking) { m_pushAgain = true; return; }
    if (!canSync() || m_conflict) return;
    auto* d = Document::instance();
    if (m_hasSynced && d->revision() == m_syncedRev) return;
    // A window with an untouched project never replaces what the Pi holds.
    if (!m_hasSynced && !d->dirty() && !m_wantPush) return;
    m_talking = true;
    jsonOnWorker(this, [this](const QByteArray& json, quint64 rev) {
        putProject(json, baseRevision(), [this, rev](const PiReply& r) {
            if (r.ok()) {
                m_syncedRev = rev;
                m_hasSynced = true;
                m_wantPush = false;
                setBase(r.map().value("revision").toInt());
                // More changes in the meantime go out with the timer they started.
            } else if (r.status == 409) {
                setConflict(true);
            }
            next();
        });
    });
}
void Sync::pushNow() { m_pushTimer->stop(); push(); }

void Sync::resolveConflict(bool takePi) {
    setBusy(true);
    PiClient::instance()->get(QStringLiteral("/api/status"), PiCallback([this, takePi](const PiReply& st) {
        const int rev = st.ok() ? st.map().value("sync").toMap().value("project").toInt() : piRevision();
        const auto failed = [this](const QString& why) {
            Toast::instance()->show(QStringLiteral("Abgleich mit dem Pi fehlgeschlagen: %1").arg(why), "bad");
            setBusy(false);
        };
        if (!st.ok()) { failed(st.error); return; }
        if (takePi) {
            readRemote(rev, [this, failed](bool ok) {
                if (!ok) { failed(QStringLiteral("Das Projekt kam nicht an.")); return; }
                setConflict(false);
                setBusy(false);
            });
            return;
        }
        jsonOnWorker(this, [this, rev, failed](const QByteArray& json, quint64 docRev) {
            putProject(json, rev, [this, docRev, failed](const PiReply& r) {
                if (!r.ok()) { failed(r.error); return; }
                m_syncedRev = docRev;
                m_hasSynced = true;
                setBase(r.map().value("revision").toInt());
                setConflict(false);
                setBusy(false);
            });
        });
    }), 8000);
}

// ---- Shelf on the Pi ----
void Sync::saveProjectToPi() { reloadProjects(); setDialog(QStringLiteral("save")); }
void Sync::openProjectDialog() { reloadProjects(); setDialog(QStringLiteral("open")); }
void Sync::closeDialog() { setDialog({}); }
void Sync::reloadProjects() {
    m_projectsError.clear();
    PiClient::instance()->get(QStringLiteral("/api/projects"), PiCallback([this](const PiReply& r) {
        m_projectsLoaded = r.ok();
        m_projectsError = r.error;
        m_projects.clear();
        for (const QVariant& v : r.map().value("projects").toList()) {
            QVariantMap p = v.toMap();
            QStringList line;
            const QString when = Fmt::when(p.value("updated_at"));
            if (when != QStringLiteral("–")) line << when;
            if (!p.value("updated_by").toString().isEmpty()) line << p.value("updated_by").toString();
            if (p.contains("elements") && !p.value("elements").isNull()) {
                const int n = p.value("elements").toInt();
                line << (n == 1 ? QStringLiteral("1 Element") : QStringLiteral("%1 Elemente").arg(n));
            }
            line << sizeOf(p.value("bytes").toDouble());
            p.insert("line", line.join(QStringLiteral(" · ")));
            m_projects.append(p);
        }
        emit projectsChanged();
    }));
}
void Sync::saveNamed(const QString& name) {
    const QString title = name.trimmed();
    if (title.isEmpty() || title.size() > 80 || m_busy) return;
    auto* d = Document::instance();
    if (title != d->title()) d->setTitle(title);
    setBusy(true);
    jsonOnWorker(this, [this, title](const QByteArray& json, quint64 rev) {
        PiClient::instance()->request("POST", QStringLiteral("/api/projects?name=%1&by=%2").arg(enc(title), QString::fromLatin1(kDevice)), "application/json", json, kLongMs,
            [this, rev](const PiReply& r) {
                setBusy(false);
                if (!r.ok()) { Toast::instance()->show(r.error, "bad"); return; }
                const QVariantMap p = r.map().value("project").toMap();
                if (Document::instance()->revision() == rev) Document::instance()->markSaved();
                Toast::instance()->show((p.value("replaced").toBool() ? QStringLiteral("„%1“ auf dem Pi ersetzt") : QStringLiteral("„%1“ auf dem Pi gespeichert")).arg(p.value("name").toString()), "ok");
                setDialog({});
            });
    });
}
void Sync::askDiscard(std::function<void(bool)> then) {
    if (!Document::instance()->dirty()) { then(true); return; }
    Confirm::instance()->askNative(QVariantMap{{"title", QStringLiteral("Änderungen verwerfen?")}, {"body", QStringLiteral("Das offene Projekt hat ungespeicherte Änderungen. Sie gehen beim Öffnen verloren.")},
                                               {"okLabel", QStringLiteral("Verwerfen")}, {"danger", true}}, std::move(then));
}
void Sync::openSaved(const QVariantMap& project) {
    const QString id = project.value("id").toString(), pname = project.value("name").toString();
    askDiscard([this, id, pname](bool yes) {
        if (!yes) return;
        setBusy(true);
        PiClient::instance()->get(QStringLiteral("/api/projects/%1").arg(enc(id)), PiCallback([this, pname](const PiReply& r) {
            if (!r.ok()) { setBusy(false); Toast::instance()->show(r.error, "bad"); return; }
            parseOnWorker(this, r.body, [this, pname](std::shared_ptr<lumacut::Document> doc, const QString& error) {
                setBusy(false);
                if (!error.isEmpty()) { Toast::instance()->show(error, "bad"); return; }
                Document::instance()->load(std::move(*doc));
                m_wantPush = true;
                m_pushTimer->start();
                Toast::instance()->show(QStringLiteral("„%1“ geöffnet").arg(pname), "ok");
                setDialog({});
            });
        }), kLongMs);
    });
}
void Sync::deleteProject(const QVariantMap& project) {
    const QString id = project.value("id").toString(), pname = project.value("name").toString();
    Confirm::instance()->askNative(QVariantMap{{"title", QStringLiteral("„%1“ löschen?").arg(pname)}, {"body", QStringLiteral("Das Projekt verschwindet vom Pi und damit von allen Geräten.")},
                                               {"okLabel", QStringLiteral("Löschen")}, {"danger", true}}, [this, id, pname](bool yes) {
        if (!yes) return;
        PiClient::instance()->del(QStringLiteral("/api/projects/%1").arg(enc(id)), PiCallback([this, pname](const PiReply& r) {
            if (!r.ok()) { Toast::instance()->show(r.error, "bad"); return; }
            Toast::instance()->show(QStringLiteral("„%1“ gelöscht").arg(pname), "ok");
            reloadProjects();
        }));
    });
}

// ---- Local file ----
QString Sync::suggestedFileName() const {
    static const QRegularExpression bad(QStringLiteral("[\\\\/:*?\"<>|]+"));
    QString base = Document::instance()->title();
    base.replace(bad, QStringLiteral("-"));
    base = base.trimmed();
    return (base.isEmpty() ? QStringLiteral("Projekt") : base) + QStringLiteral(".lumacut");
}
void Sync::saveLocal() {
    const QString known = Document::instance()->filePath();
    if (known.isEmpty()) emit pickSavePath(suggestedFileName());
    else saveLocalTo(known);
}
void Sync::saveLocalAs() { emit pickSavePath(suggestedFileName()); }
void Sync::openLocal() {
    askDiscard([this](bool yes) { if (yes) emit pickOpenPath(); });
}
bool Sync::saveLocalTo(const QString& path) {
    const QString target = withSuffix(localPath(path));
    if (target.isEmpty()) return false;
    setBusy(true);
    jsonOnWorker(this, [this, target](const QByteArray& json, quint64 rev) {
        setBusy(false);
        QSaveFile f(target);
        if (!f.open(QIODevice::WriteOnly) || f.write(json) != json.size() || !f.commit()) {
            Toast::instance()->show(QStringLiteral("Speichern fehlgeschlagen: %1").arg(f.errorString()), "bad");
            return;
        }
        if (Document::instance()->revision() == rev) Document::instance()->markSaved(target);
        Toast::instance()->show(QStringLiteral("Gespeichert: %1").arg(QFileInfo(target).fileName()), "ok");
    });
    return true;
}
void Sync::openLocalFrom(const QString& path) {
    askDiscard([this, path](bool yes) { if (yes) openLocalNow(path); });
}
bool Sync::openLocalNow(const QString& path) {
    const QString file = localPath(path);
    QFile f(file);
    if (!f.open(QIODevice::ReadOnly)) {
        Toast::instance()->show(QStringLiteral("Datei nicht lesbar: %1").arg(f.errorString()), "bad");
        return false;
    }
    setBusy(true);
    const QString name = QFileInfo(file).fileName();
    QThreadPool::globalInstance()->start([ctx = QPointer<QObject>(this), this, file, name] {
        QFile in(file);
        QByteArray text;
        if (in.open(QIODevice::ReadOnly)) text = in.readAll();
        if (ctx) QMetaObject::invokeMethod(ctx.data(), [this, text, file, name] {
            parseOnWorker(this, text, [this, file, name](std::shared_ptr<lumacut::Document> doc, const QString& error) {
                setBusy(false);
                if (!error.isEmpty()) { Toast::instance()->show(QStringLiteral("„%1“ ist kein LumaCut-Projekt.").arg(name), "bad"); return; }
                Document::instance()->load(std::move(*doc), file);
                m_wantPush = true;
                m_pushTimer->start();
                Toast::instance()->show(QStringLiteral("„%1“ geöffnet").arg(name), "ok");
            });
        }, Qt::QueuedConnection);
    });
    return true;
}

// ---- Autosave ----
QString Sync::autosavePath() const {
    QString dir = qEnvironmentVariable("LUMACUT_AUTOSAVE_DIR");
    // Automated runs never touch or find the user's autosave, nor one another's.
    if (dir.isEmpty() && !qEnvironmentVariableIsSet("LUMACUT_AUTOMATION_PORT")) dir = QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation);
    if (dir.isEmpty()) return {};
    QDir().mkpath(dir);
    return QDir(dir).filePath(QStringLiteral("autosave.lumacut"));
}
void Sync::clearAutosaveFile() {
    const QString p = autosavePath();
    if (p.isEmpty()) return;
    QFile::remove(p);
    QFile::remove(p + QStringLiteral(".meta"));
}
void Sync::writeAutosave() {
    const QString p = autosavePath();
    if (p.isEmpty() || !m_recoveredJson.isNull()) return;   // an unanswered question about the old file: it stays
    auto* d = Document::instance();
    if (!d->dirty()) { clearAutosaveFile(); return; }
    const QString title = d->title();
    jsonOnWorker(this, [p, title](const QByteArray& json, quint64) {
        QSaveFile f(p);
        if (!f.open(QIODevice::WriteOnly) || f.write(json) != json.size() || !f.commit()) return;
        QSaveFile m(p + QStringLiteral(".meta"));
        if (m.open(QIODevice::WriteOnly)) {
            m.write(QJsonDocument(QJsonObject{{"title", title}, {"savedAt", double(QDateTime::currentMSecsSinceEpoch())}}).toJson(QJsonDocument::Compact));
            m.commit();
        }
    });
}
void Sync::autosaveNow() { m_autosaveTimer->stop(); writeAutosave(); }
void Sync::checkRecovered() {
    const QString p = autosavePath();
    if (p.isEmpty() || !QFile::exists(p)) return;
    auto* d = Document::instance();
    if (d->dirty() || !d->empty()) return;
    QFile f(p), m(p + QStringLiteral(".meta"));
    if (!f.open(QIODevice::ReadOnly)) return;
    m_recoveredJson = f.readAll();
    QJsonObject meta;
    if (m.open(QIODevice::ReadOnly)) meta = QJsonDocument::fromJson(m.readAll()).object();
    const double at = meta.value("savedAt").toDouble();
    m_recovered = {{"title", meta.value("title").toString(QStringLiteral("Projekt"))}, {"savedAt", at},
                   {"when", at > 0 ? Fmt::when(QDateTime::fromMSecsSinceEpoch(qint64(at)).toString(Qt::ISODate)) : QString()}};
    emit stateChanged();
}
QVariantMap Sync::recovered() const { return m_conflict ? QVariantMap{} : m_recovered; }
void Sync::restoreAutosave() {
    if (m_recoveredJson.isNull()) return;
    const QByteArray text = m_recoveredJson;
    parseOnWorker(this, text, [this](std::shared_ptr<lumacut::Document> doc, const QString& error) {
        m_recovered.clear();
        m_recoveredJson = QByteArray();
        emit stateChanged();
        if (!error.isEmpty()) { Toast::instance()->show(error, "bad"); return; }
        auto* d = Document::instance();
        d->load(std::move(*doc));
        // Restored work counts as unsaved: an own copy of the list differs from what was "saved", without an undo step.
        d->mutate([](Document::State& s) { s.layerList = std::make_shared<std::vector<lumacut::Layer>>(*s.layerList); });
        m_wantPush = true;
        m_pushTimer->start();
        m_autosaveTimer->start();
    });
}
void Sync::discardAutosave() {
    m_recovered.clear();
    m_recoveredJson = QByteArray();
    clearAutosaveFile();
    emit stateChanged();
}
