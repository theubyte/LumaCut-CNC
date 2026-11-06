#pragma once
#include <QObject>
#include <QPointF>
#include <QVariantList>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>
#include <vector>
#include "JobBuilder.h"
#include "Singleton.h"
#include "StartChecks.h"

/**
 * The view "Starten": what will run, what speaks against it, the run itself, queue and saved jobs. QML only shows this.
 * Every start and frame goes through MachineActions and its go dialog; the Pi checks everything again.
 */
class StartController : public QObject {
    Q_OBJECT
    QML_NAMED_ELEMENT(Start)
    QML_SINGLETON
    LC_SINGLETON(StartController)
    // What is shown
    Q_PROPERTY(bool isSaved READ isSaved NOTIFY changed)
    Q_PROPERTY(QString name READ name NOTIFY changed)
    Q_PROPERTY(int plate READ plate NOTIFY changed)
    Q_PROPERTY(bool multi READ multi NOTIFY changed)
    Q_PROPERTY(QVariantList plateOptions READ plateOptions NOTIFY changed)
    Q_PROPERTY(QString overlay READ overlay NOTIFY changed)         // "", building, empty, error
    Q_PROPERTY(QString emptyTitle READ emptyTitle NOTIFY changed)
    Q_PROPERTY(QString emptyText READ emptyText NOTIFY changed)
    // Plan and numbers
    Q_PROPERTY(bool materialChosen READ materialChosen NOTIFY changed)
    Q_PROPERTY(QString materialText READ materialText NOTIFY changed)
    Q_PROPERTY(QString estimate READ estimate NOTIFY changed)
    Q_PROPERTY(QString cutLength READ cutLength NOTIFY changed)
    Q_PROPERTY(QString travelLength READ travelLength NOTIFY changed)
    Q_PROPERTY(QString sizeText READ sizeText NOTIFY changed)
    Q_PROPERTY(QVariantList layerRows READ layerRows NOTIFY changed)
    Q_PROPERTY(QVariantList checks READ checks NOTIFY changed)      // {id, tone, text, html, goDest}
    Q_PROPERTY(bool serious READ serious NOTIFY changed)
    // Buttons
    Q_PROPERTY(QString busy READ busy NOTIFY changed)               // "", start, frame, queue
    Q_PROPERTY(QString startLock READ startLock NOTIFY changed)
    Q_PROPERTY(QString frameLock READ frameLock NOTIFY changed)
    // Run
    Q_PROPERTY(bool running READ running NOTIFY changed)
    Q_PROPERTY(bool framing READ framing NOTIFY changed)
    Q_PROPERTY(QString frameText READ frameText NOTIFY changed)
    Q_PROPERTY(QString runFile READ runFile NOTIFY changed)
    Q_PROPERTY(double runShare READ runShare NOTIFY changed)
    Q_PROPERTY(QString runPercent READ runPercent NOTIFY changed)
    Q_PROPERTY(QString runRemaining READ runRemaining NOTIFY changed)
    Q_PROPERTY(QVariantList phases READ phases NOTIFY changed)      // {label, state: done|now|next, number}
    Q_PROPERTY(bool resultShown READ resultShown NOTIFY changed)
    Q_PROPERTY(QString resultState READ resultState NOTIFY changed)
    Q_PROPERTY(QString resultTone READ resultTone NOTIFY changed)
    Q_PROPERTY(QString resultText READ resultText NOTIFY changed)
    // Preview
    Q_PROPERTY(int segmentCount READ segmentCount NOTIFY changed)
    Q_PROPERTY(bool live READ live NOTIFY changed)
    Q_PROPERTY(bool playing READ playing NOTIFY playChanged)
    Q_PROPERTY(int sliderValue READ sliderValue NOTIFY playChanged)
    Q_PROPERTY(int visibleCount READ visibleCount NOTIFY playChanged)
    Q_PROPERTY(QString readout READ readout NOTIFY playChanged)
    Q_PROPERTY(bool showTravel READ showTravel WRITE setShowTravel NOTIFY playChanged)
    Q_PROPERTY(bool hasBounds READ hasBounds NOTIFY changed)
    Q_PROPERTY(double boundsX0 READ boundsX0 NOTIFY changed)
    Q_PROPERTY(double boundsY0 READ boundsY0 NOTIFY changed)
    Q_PROPERTY(double boundsX1 READ boundsX1 NOTIFY changed)
    Q_PROPERTY(double boundsY1 READ boundsY1 NOTIFY changed)
    Q_PROPERTY(bool headVisible READ headVisible NOTIFY playChanged)
    Q_PROPERTY(QPointF head READ head NOTIFY playChanged)           // work mm
    Q_PROPERTY(QString parkName READ parkName NOTIFY changed)
    // Dock
    Q_PROPERTY(bool dockOpen READ dockOpen WRITE setDockOpen NOTIFY dockChanged)
    Q_PROPERTY(QVariantList queueItems READ queueItems NOTIFY changed)  // {id, file, state, label, tone, error, canSkip, canRemove}
    Q_PROPERTY(QString queueTitle READ queueTitle NOTIFY changed)
    Q_PROPERTY(int queueWaiting READ queueWaiting NOTIFY changed)
    Q_PROPERTY(bool queueActive READ queueActive NOTIFY changed)
    Q_PROPERTY(bool queuePausing READ queuePausing NOTIFY changed)
    Q_PROPERTY(QString queueRunLabel READ queueRunLabel NOTIFY changed)
    Q_PROPERTY(bool queueCanRun READ queueCanRun NOTIFY changed)
    Q_PROPERTY(QVariantList jobs READ jobs NOTIFY jobsChanged)          // {name, line, locked, lockText, selected}
public:
    explicit StartController(QObject* parent);

    /** The view is open: builds and follows. */
    Q_INVOKABLE void enter();
    Q_INVOKABLE void leave();

    bool isSaved() const { return !m_saved.isEmpty(); }
    QString name() const;
    int plate() const;
    bool multi() const;
    QVariantList plateOptions() const;
    QString overlay() const;
    QString emptyTitle() const;
    QString emptyText() const;
    bool materialChosen() const;
    QString materialText() const;
    QString estimate() const;
    QString cutLength() const;
    QString travelLength() const;
    QString sizeText() const;
    QVariantList layerRows() const;
    QVariantList checks() const { return m_checks; }
    bool serious() const { return m_serious; }
    QString busy() const { return m_busy; }
    QString startLock() const;
    QString frameLock() const;
    bool running() const;
    bool framing() const;
    QString frameText() const;
    QString runFile() const;
    double runShare() const;
    QString runPercent() const;
    QString runRemaining() const;
    QVariantList phases() const;
    bool resultShown() const;
    QString resultState() const;
    QString resultTone() const;
    QString resultText() const;
    int segmentCount() const;
    bool live() const { return running(); }
    bool playing() const { return m_playing; }
    int sliderValue() const;
    int visibleCount() const;
    QString readout() const;
    bool showTravel() const { return m_showTravel; }
    void setShowTravel(bool v);
    bool hasBounds() const;
    double boundsX0() const;
    double boundsY0() const;
    double boundsX1() const;
    double boundsY1() const;
    bool headVisible() const;
    QPointF head() const;
    QString parkName() const;
    bool dockOpen() const { return m_dockOpen; }
    void setDockOpen(bool v);
    QVariantList queueItems() const;
    QString queueTitle() const;
    int queueWaiting() const;
    bool queueActive() const;
    bool queuePausing() const;
    QString queueRunLabel() const;
    bool queueCanRun() const;
    QVariantList jobs() const { return m_jobs; }

    Q_INVOKABLE void choosePlate(int plate);
    Q_INVOKABLE void startJob();
    Q_INVOKABLE void frame();
    Q_INVOKABLE void abort();
    Q_INVOKABLE void dismissResult();
    Q_INVOKABLE void togglePlay();
    /** One screen frame of playback; the whole job takes the same few seconds, whatever its length. */
    Q_INVOKABLE void advance(double seconds);
    Q_INVOKABLE void scrub(int value);
    Q_INVOKABLE void toBeginning();
    Q_INVOKABLE void step(int direction);

    Q_INVOKABLE void enqueueCurrent();
    Q_INVOKABLE bool canEnqueueCurrent() const;
    Q_INVOKABLE void queueOp(const QString& op, int id = 0);
    Q_INVOKABLE void reloadJobs();
    Q_INVOKABLE void previewSaved(const QString& name);
    Q_INVOKABLE void backToDoc();
    Q_INVOKABLE void enqueueSaved(const QString& name);
    Q_INVOKABLE void deleteSaved(const QString& name);
    /** G-code from a path: file dialogs and tests come through here. */
    Q_INVOKABLE void uploadFile(const QString& path);
    Q_INVOKABLE void exportSaved(const QString& name, const QString& path);
    /** Measurement: {write, parse, segments, total, preview, count, bytes} of the last build, in ms. */
    Q_INVOKABLE QVariantMap timings() const { return JobBuilder::instance()->timings(); }
signals:
    void changed();
    void playChanged();
    void dockChanged();
    void jobsChanged();
    /** The shown job became another source: the view fits itself again. */
    void sourceSwitched();
private:
    void refresh();
    void recomputeChecks();
    void onMachine();
    void onShown();
    void followRunningJob();
    void setBusy(const QString& v);
    void setRejection(const QString& v);
    void updateJobs();
    int atLineFor(double fraction, const lumacut::Toolpath& tp) const;
    QVariantMap jobMap() const;
    QString resultKey() const;
    double fraction() const;
    bool lasering() const;

    bool m_entered = false;
    QString m_saved;
    int m_chosenPlate = 0;
    int m_savedReq = 0;
    QString m_busy, m_rejection, m_dismissed, m_runFetched, m_jobsKey;
    QVariantList m_checks;
    bool m_serious = false, m_blocked = true;
    QString m_firstBad;
    int m_pos = -1;     // playback segment; -1 = whole job
    bool m_playing = false, m_showTravel = true, m_dockOpen = false;
    double m_playAt = 0;
    QVariantList m_jobs;
    QVariantList m_jobFiles;
};
