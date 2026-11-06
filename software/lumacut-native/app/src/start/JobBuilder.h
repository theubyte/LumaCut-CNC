#pragma once
#include <QByteArray>
#include <QElapsedTimer>
#include <QObject>
#include <QPointer>
#include <QThreadPool>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>
#include <atomic>
#include <memory>
#include <vector>
#include "Singleton.h"
#include "StartChecks.h"
#include "core/gcode.h"
#include "core/toolpath.h"

class QTimer;
class SegmentsItem;
struct GpuSegment;

/**
 * The job of the chosen plate as it would leave this PC, built on a worker: G-code, toolpath, GPU segments.
 * A change to the project starts a new run after a short pause; a run that is overtaken stops at its next stage and its
 * result is dropped, so the newest state always wins. Works only while someone looks (setActive), the editor stays
 * free of this cost. A saved job (or the one running on the Pi) goes the same way, without the writer.
 */
class JobBuilder : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    LC_SINGLETON(JobBuilder)
    Q_PROPERTY(bool building READ building NOTIFY stateChanged)
    Q_PROPERTY(QString error READ error NOTIFY stateChanged)
    Q_PROPERTY(bool hasJob READ hasJob NOTIFY stateChanged)
    /** Of the last run, in ms: write, parse, segments, total (change to end of run), preview (change to everything on the GPU), count, bytes. */
    Q_PROPERTY(QVariantMap timings READ timings NOTIFY timingsChanged)
public:
    struct Built {
        QString name;
        QByteArray gcode;
        lumacut::Toolpath tp;
        std::vector<uint32_t> pathStarts;     // segment index where each laser path begins
    };
    using BuiltPtr = std::shared_ptr<const Built>;

    explicit JobBuilder(QObject* parent);
    ~JobBuilder() override;

    void setActive(bool on);
    void setPlate(int plate);
    int plate() const { return m_plate; }
    /** Build from the open project. */
    void useDocument();
    /** A saved job was chosen, its text is on the way: the project's numbers and sentences are gone at once. */
    void beginSaved();
    /** Show a saved job: parses its text, nothing else. */
    void useSaved(const QString& name, const QByteArray& gcode);
    void setSavedError(const QString& message);
    /** While another job runs on the Pi, this one is shown instead. */
    void showRun(const QString& name, const QByteArray& gcode);
    void clearRun();

    /** The SegmentsItem of the open view. Gets whatever is shown now, and everything after. */
    Q_INVOKABLE void attachPreview(QObject* item);

    bool building() const { return m_building; }
    QString error() const { return m_error; }
    bool hasJob() const { return bool(m_built); }
    QVariantMap timings() const { return m_timings; }
    /** The job for start and frame. */
    BuiltPtr built() const { return m_built; }
    /** What the preview holds: the job running on the Pi if it is another one, otherwise built(). */
    BuiltPtr shown() const { return m_run ? m_run : m_built; }
    const startchecks::Findings& findings() const { return m_findings; }
    lumacut::Motion motion() const;
    static QString jobNameFrom(const QString& title);
signals:
    void stateChanged();
    void shownChanged();
    void timingsChanged();
    /** New findings (layers, sentences) before the job itself is done. */
    void findingsChanged();
private:
    struct Result;
    void schedule(bool now);
    void runBuild();
    void finish(std::shared_ptr<Result> r);
    void push(std::shared_ptr<std::vector<GpuSegment>> segs);
    void onDocChanged();
    void onMachine();
    void setBuilding(bool on);
    QString buildKey() const;

    QThreadPool m_pool;
    QTimer* m_debounce;
    QElapsedTimer m_clock;
    std::atomic<quint64> m_gen{0};
    quint64 m_runGen = 0;
    bool m_active = false, m_stale = true, m_building = false, m_useSaved = false;
    int m_plate = 0;
    QString m_key, m_motionKey, m_error;
    qint64 m_changedAt = -1;
    bool m_awaitingPreview = false;
    BuiltPtr m_built, m_run;
    startchecks::Findings m_findings;
    QVariantMap m_timings;
    QPointer<SegmentsItem> m_item;
};
