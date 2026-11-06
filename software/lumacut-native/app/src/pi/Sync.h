#pragma once
#include <QObject>
#include <QVariantList>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>
#include <functional>
#include "Singleton.h"

class QTimer;
struct PiReply;
namespace lumacut { struct Document; }

/**
 * Projects: the Pi's shelf (/api/projects), the open project every device shares (/api/workspace/project with
 * base_revision, same rules as Android's PiSyncViewModel), a local .lumacut file, and a local autosave.
 *
 * File menu (QML):
 *   Sync.saveProjectToPi()         dialog "Auf dem Pi speichern"
 *   Sync.openProjectDialog()       dialog "Projekt vom Pi öffnen"
 *   Sync.saveLocal()               to the known file, or asks for a place
 *   Sync.saveLocalAs()             always asks for a place
 *   Sync.openLocal()               asks about unsaved changes, then for a file
 * Same without a system dialog, for tests and for whoever already has a path:
 *   Sync.saveLocalTo(path)   -> bool
 *   Sync.openLocalFrom(path) -> bool (asks about unsaved changes first, the result comes later: see confirmed)
 *   Sync.openLocalNow(path)  -> bool (no question, replaces the open project)
 *
 * Dialogs live in features/start/SyncHost.qml, mounted once in Main.qml.
 *
 * Nothing pops up by surprise: the conflict dialog only opens when the Pi has a newer project AND this device has
 * changes it has not sent. An untouched project follows the Pi with a small toast.
 */
class Sync : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    LC_SINGLETON(Sync)
    /** The Pi and this device both changed the project: the operator decides. */
    Q_PROPERTY(bool conflict READ conflict NOTIFY stateChanged)
    /** "", "save" or "open". */
    Q_PROPERTY(QString dialogMode READ dialogMode NOTIFY stateChanged)
    /** {title, savedAt (ms), when (text)} of unsaved work from an earlier session; empty = none. */
    Q_PROPERTY(QVariantMap recovered READ recovered NOTIFY stateChanged)
    /** Shelf on the Pi: [{id, name, line, bytes, updated_at, updated_by, elements, layers, plates}], newest first as the Pi sends it. */
    Q_PROPERTY(QVariantList projects READ projects NOTIFY projectsChanged)
    Q_PROPERTY(bool projectsLoaded READ projectsLoaded NOTIFY projectsChanged)
    Q_PROPERTY(QString projectsError READ projectsError NOTIFY projectsChanged)
    Q_PROPERTY(bool busy READ busy NOTIFY stateChanged)
    /** The local file of the open project, "" = none yet. */
    Q_PROPERTY(QString filePath READ filePath NOTIFY fileChanged)
    /** True when the open project has something the Pi does not have yet. */
    Q_PROPERTY(bool unsent READ unsent NOTIFY stateChanged)
    Q_PROPERTY(int baseRevision READ baseRevision NOTIFY stateChanged)
public:
    explicit Sync(QObject* parent);
    /** Runs once for the app's lifetime; SyncHost.qml calls it. */
    Q_INVOKABLE void start();

    bool conflict() const { return m_conflict; }
    QString dialogMode() const { return m_dialog; }
    QVariantMap recovered() const;
    QVariantList projects() const { return m_projects; }
    bool projectsLoaded() const { return m_projectsLoaded; }
    QString projectsError() const { return m_projectsError; }
    bool busy() const { return m_busy; }
    QString filePath() const;
    bool unsent() const;
    int baseRevision() const;

    Q_INVOKABLE void saveProjectToPi();
    Q_INVOKABLE void openProjectDialog();
    Q_INVOKABLE void closeDialog();
    Q_INVOKABLE void reloadProjects();
    /** The save dialog's button. The saved name becomes the title, so the next save offers it again. */
    Q_INVOKABLE void saveNamed(const QString& name);
    /** The open dialog's row. `project` is an entry of `projects`. */
    Q_INVOKABLE void openSaved(const QVariantMap& project);
    Q_INVOKABLE void deleteProject(const QVariantMap& project);

    Q_INVOKABLE void saveLocal();
    Q_INVOKABLE void saveLocalAs();
    Q_INVOKABLE void openLocal();
    Q_INVOKABLE bool saveLocalTo(const QString& path);
    Q_INVOKABLE void openLocalFrom(const QString& path);
    Q_INVOKABLE bool openLocalNow(const QString& path);
    /** Proposed file name for a save dialog. */
    Q_INVOKABLE QString suggestedFileName() const;

    /** The operator's answer to a conflict: the Pi's project, or this device's over it. */
    Q_INVOKABLE void resolveConflict(bool takePi);
    Q_INVOKABLE void restoreAutosave();
    Q_INVOKABLE void discardAutosave();
    /** Writes the autosave now (normally 4 s after the last change). */
    Q_INVOKABLE void autosaveNow();
    /** Sends the project now (normally 2 s after the last change). */
    Q_INVOKABLE void pushNow();
signals:
    void stateChanged();
    void projectsChanged();
    void fileChanged();
    /** SyncHost.qml answers with the system dialog and calls saveLocalTo or openLocalFrom. */
    void pickSavePath(const QString& suggestedName);
    void pickOpenPath();
private:
    void onDocChanged();
    void onSync(const QVariantMap& sync);
    void pull();
    void push();
    void next();
    void putProject(const QByteArray& json, int baseRevision, std::function<void(const PiReply&)> done);
    void takeRemote(lumacut::Document&& doc, int rev);
    void readRemote(int rev, std::function<void(bool ok)> done);
    bool canSync() const;
    int piRevision() const;
    void setBase(int rev);
    QString autosavePath() const;
    void writeAutosave();
    void checkRecovered();
    void clearAutosaveFile();
    void askDiscard(std::function<void(bool)> then);
    void setDialog(const QString& mode);
    void setBusy(bool v);
    void setConflict(bool v);

    QTimer* m_pushTimer;
    QTimer* m_autosaveTimer;
    bool m_started = false;
    bool m_shared = false;       // this window talks to the Pi about the open project
    bool m_conflict = false;
    bool m_busy = false;
    bool m_talking = false;      // one conversation with the Pi at a time, so a status poll cannot overtake a save
    bool m_pullAgain = false, m_pushAgain = false;
    bool m_hasSynced = false;    // false: nothing sent or taken in this session
    bool m_wantPush = false;     // the operator opened something: it goes on to the other devices even if not dirty
    quint64 m_syncedRev = 0;     // Document::revision() of what the Pi has from us
    QString m_dialog;
    QVariantMap m_recovered;
    QByteArray m_recoveredJson;  // null = nothing to recover
    QVariantList m_projects;
    bool m_projectsLoaded = false;
    QString m_projectsError;
    int m_lastRev = -1;
    bool m_wasOnline = false;
};
