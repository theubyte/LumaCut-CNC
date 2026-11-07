#pragma once
#include <QObject>
#include <QSet>
#include <QStringList>
#include <QTimer>
#include <QVariantList>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>
#include <memory>
#include <vector>
#include "Singleton.h"
#include "core/pcb/job.h"

/**
 * The Platine view's state: files of one board, settings, the computed plan and its checks. Parsing and geometry run on
 * a worker (files on all cores), the window never waits; a newer request makes older results void. Lives as long as the
 * app, so leaving the view keeps the work. "Ins Projekt" puts the plan on its own plate of the open project, with one
 * layer per process (Gravieren or Markieren), so the job goes the normal way through Starten and the go dialog.
 * QML: Platine. Settings go through set(key, value) with the keys of `settings`.
 */
class PlatineController : public QObject {
    Q_OBJECT
    QML_NAMED_ELEMENT(Platine)
    QML_SINGLETON
    LC_SINGLETON(PlatineController)
    Q_PROPERTY(QVariantList files READ files NOTIFY filesChanged)
    Q_PROPERTY(QVariantList kinds READ kinds CONSTANT)
    Q_PROPERTY(bool hasBoard READ hasBoard NOTIFY boardChanged)
    Q_PROPERTY(QVariantMap boardInfo READ boardInfo NOTIFY boardChanged)
    Q_PROPERTY(QStringList warnings READ warnings NOTIFY planChanged)
    Q_PROPERTY(QVariantMap settings READ settings NOTIFY settingsChanged)
    Q_PROPERTY(double interval READ interval NOTIFY settingsChanged)
    Q_PROPERTY(QString stage READ stage NOTIFY settingsChanged)
    Q_PROPERTY(QVariantList stages READ stages NOTIFY planChanged)
    Q_PROPERTY(QVariantList jobLayers READ jobLayers NOTIFY planChanged)
    Q_PROPERTY(QString jobTime READ jobTime NOTIFY planChanged)
    Q_PROPERTY(QVariantList checks READ checks NOTIFY planChanged)
    Q_PROPERTY(int badCount READ badCount NOTIFY planChanged)
    Q_PROPERTY(QVariantList viewLayers READ viewLayers NOTIFY viewChanged)
    Q_PROPERTY(QVariantList workflow READ workflow NOTIFY settingsChanged)
    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(QString busyText READ busyText NOTIFY busyChanged)
    Q_PROPERTY(int revision READ revision NOTIFY planChanged)
    Q_PROPERTY(QString jobSize READ jobSize NOTIFY planChanged)
public:
    explicit PlatineController(QObject* parent);

    QVariantList files() const;
    QVariantList kinds() const;
    bool hasBoard() const { return bool(m_board); }
    QVariantMap boardInfo() const;
    QStringList warnings() const;
    QVariantMap settings() const;
    double interval() const;
    QString stage() const;
    QVariantList stages() const;
    QVariantList jobLayers() const;
    QString jobTime() const;
    QVariantList checks() const { return m_checks; }
    int badCount() const;
    QVariantList viewLayers() const;
    QVariantList workflow() const;
    bool busy() const { return !m_busyText.isEmpty(); }
    QString busyText() const { return m_busyText; }
    int revision() const { return m_revision; }
    QString jobSize() const;

    /** For the preview. Null while nothing is loaded. */
    std::shared_ptr<const lumacut::pcb::Board> board() const { return m_board; }
    std::shared_ptr<const lumacut::pcb::Plan> plan() const { return m_plan; }
    const lumacut::pcb::JobSettings& jobSettings() const { return m_settings; }
    std::optional<lumacut::pcb::Clearance> marker() const;
    bool layerShown(const QString& key) const { return !m_hidden.contains(key); }

    Q_INVOKABLE void loadExample();
    /** Paths or file URLs; ZIP archives are unpacked. Read on the worker. */
    Q_INVOKABLE void loadPaths(const QStringList& paths);
    Q_INVOKABLE void askFiles() { emit filesRequested(); }
    Q_INVOKABLE QStringList fileFilters() const;
    Q_INVOKABLE void removeFile(int index);
    Q_INVOKABLE void setKind(int index, const QString& key);
    Q_INVOKABLE void clear();
    Q_INVOKABLE void set(const QString& key, const QVariant& value);
    Q_INVOKABLE void setStage(const QString& stage);
    Q_INVOKABLE void setProcessValue(const QString& process, const QString& field, double value);
    Q_INVOKABLE void toggleLayer(const QString& key);
    /** Asks first when the checks report problems. */
    Q_INVOKABLE void toProject();
    /** For tests: plain numbers about the current plan. */
    Q_INVOKABLE QVariantMap info() const;

signals:
    void filesChanged();
    void boardChanged();
    void planChanged();
    void settingsChanged();
    void viewChanged();
    void busyChanged();
    void filesRequested();
    /** After "Ins Projekt": the plate the board went to (0-based). */
    void placed(int plate);

private:
    struct Result;
    void schedule(bool files);
    void run();
    void finished(std::shared_ptr<Result> r);
    void setBusy(const QString& text);
    void addFiles(std::vector<std::pair<QString, QByteArray>> entries);
    void refreshChecks();
    void place();

    std::vector<lumacut::pcb::PcbFile> m_files;
    std::shared_ptr<const lumacut::pcb::Board> m_board;
    std::shared_ptr<const lumacut::pcb::Plan> m_plan;
    std::shared_ptr<const lumacut::pcb::DesignFacts> m_facts;
    lumacut::pcb::Side m_factsSide = lumacut::pcb::Side::Top;
    std::vector<double> m_secondsAtUnitSpeed;   // per plan layer: estimate times speed
    lumacut::pcb::JobSettings m_settings;
    lumacut::pcb::Stage m_stage = lumacut::pcb::Stage::Resist;
    QSet<QString> m_hidden;
    QVariantList m_checks;
    QString m_busyText;
    QTimer m_debounce;
    bool m_filesDirty = false, m_running = false, m_again = false;
    quint64 m_generation = 0;
    int m_revision = 0;
    int m_plate[2] = {-1, -1};   // plate per side from the last "Ins Projekt" in this session
};
