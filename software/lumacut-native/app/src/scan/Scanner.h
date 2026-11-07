#pragma once
#include <QImage>
#include <QObject>
#include <QPointer>
#include <QQuickItem>
#include <QTimer>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>
#include <atomic>
#include <functional>
#include <memory>
#include <optional>
#include "Singleton.h"
#include "core/camera/scan.h"

class StageItem;

/**
 * Head camera in the app, like Android's WorkspaceViewModel: the workplace scan (one go, then the head moves picture by
 * picture, the mosaic is built on all cores and stored on the Pi with its revision), the scan as background (taken over
 * whenever another device scanned), and the live picture (small window, optionally rectified onto the motif stage).
 * The Pi switches the camera light on for every picture itself. Every move goes through MachineActions.
 * QML: Scanner.
 */
class Scanner : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    LC_SINGLETON(Scanner)
    Q_PROPERTY(bool calibrated READ calibrated NOTIFY calibrationChanged)
    Q_PROPERTY(QString calibrationNote READ calibrationNote NOTIFY calibrationChanged)
    Q_PROPERTY(bool running READ running NOTIFY progressChanged)
    Q_PROPERTY(int step READ step NOTIFY progressChanged)
    Q_PROPERTY(int steps READ steps NOTIFY progressChanged)
    Q_PROPERTY(QString stepText READ stepText NOTIFY progressChanged)
    Q_PROPERTY(QString lastResult READ lastResult NOTIFY progressChanged)
    Q_PROPERTY(QString region READ region WRITE setRegion NOTIFY regionChanged)
    Q_PROPERTY(int backgroundRevision READ backgroundRevision NOTIFY backgroundChanged)
    Q_PROPERTY(QString backgroundStamp READ backgroundStamp NOTIFY backgroundChanged)
    Q_PROPERTY(bool liveOn READ liveOn WRITE setLiveOn NOTIFY liveChanged)
    Q_PROPERTY(bool liveOverlay READ liveOverlay WRITE setLiveOverlay NOTIFY liveChanged)
    Q_PROPERTY(bool liveLight READ liveLight WRITE setLiveLight NOTIFY liveChanged)
    Q_PROPERTY(int liveFrames READ liveFrames NOTIFY liveFrame)
    Q_PROPERTY(QString liveError READ liveError NOTIFY liveFrame)
    Q_PROPERTY(QString liveNote READ liveNote NOTIFY liveFrame)
    /** Where the rectified live picture lies on the stage, empty when none ("X 113–203, Y 138–205"). */
    Q_PROPERTY(QString overlayArea READ overlayArea NOTIFY liveFrame)
public:
    explicit Scanner(QObject* parent);

    bool calibrated() const { return bool(m_cal); }
    QString calibrationNote() const { return m_calNote; }
    bool running() const { return m_running; }
    int step() const { return m_step; }
    int steps() const { return int(m_heads.size()); }
    QString stepText() const { return m_stepText; }
    QString lastResult() const { return m_lastResult; }
    QString region() const { return m_region; }
    void setRegion(const QString& r);
    int backgroundRevision() const { return m_bgRev; }
    QString backgroundStamp() const { return m_bgStamp; }
    bool liveOn() const { return m_liveOn; }
    void setLiveOn(bool v);
    bool liveOverlay() const { return m_overlay; }
    void setLiveOverlay(bool v);
    bool liveLight() const { return m_liveLight; }
    void setLiveLight(bool v) { if (v != m_liveLight) { m_liveLight = v; emit liveChanged(); } }
    int liveFrames() const { return m_liveFrames; }
    QString liveError() const { return m_liveError; }
    QString liveNote() const { return m_liveNote; }
    QString overlayArea() const { return m_overlayArea; }
    QImage liveImage() const { return m_liveImage; }

    Q_INVOKABLE void loadCalibration();
    /** Scans the chosen region: "all", "motif" (motif + 10 mm) or "view" (the visible part of the stage, see setViewBox). */
    Q_INVOKABLE void scan();
    /** Scans this box in work mm. */
    Q_INVOKABLE void scanArea(double x0, double y0, double x1, double y1);
    Q_INVOKABLE void cancel();
    /** The part of the bed the motif stage shows now (work mm), for the region "view". */
    Q_INVOKABLE void setViewBox(double x0, double y0, double x1, double y1) { m_view = lumacut::Box{x0, y0, x1, y1}; }
    /** The scan from the Pi, now (also when the revision did not change). */
    Q_INVOKABLE void reloadBackground();
    /** The motif stage, for the rectified live picture. */
    Q_INVOKABLE void attachMotivStage(QQuickItem* stage);
    /** Sentence why scanning cannot start now, empty when it can. */
    Q_INVOKABLE QString lock(const QVariant& dependsOn = {}) const;

signals:
    void calibrationChanged();
    void progressChanged();
    void regionChanged();
    void backgroundChanged();
    void liveChanged();
    void liveFrame();

private:
    void startPlan(const lumacut::Box& area, const QString& what);
    void nextStep();
    /** Z to `target` in jog steps (laser off), then checks what the Pi reports; done(ok). */
    void zTo(double target, std::function<void(bool)> done);
    /** Measured surface and current Z: the height the scan uses, or the sentence why it cannot go. */
    lumacut::Camera::ScanHeight height() const;
    void shot(lumacut::Pt at);
    void finish();
    void fail(const QString& why);
    void fetchBackground(bool force);
    void liveTick();
    void showOverlay();
    QString snapshotPath(bool light) const;

    std::optional<lumacut::Camera::Calibration> m_cal;
    QString m_calNote = QStringLiteral("Kalibrierung wird geladen.");
    bool m_running = false, m_cancel = false;
    int m_step = 0;
    double m_scanZ = 0;
    QString m_stepText, m_lastResult, m_what;
    QString m_region = QStringLiteral("all");
    std::optional<lumacut::Box> m_view;
    std::vector<lumacut::Pt> m_heads;
    std::shared_ptr<lumacut::Camera::Mosaic> m_mosaic;
    QStringList m_notes;
    int m_bgRev = -1;
    bool m_bgLoading = false;
    QString m_bgStamp;

    bool m_liveOn = false, m_overlay = false, m_liveLight = true, m_liveBusy = false;
    int m_liveFrames = 0;
    QString m_liveError, m_liveNote, m_overlayArea;
    QImage m_liveImage;
    lumacut::Pt m_liveHead;
    QTimer m_liveTimer;
    QPointer<StageItem> m_stage;
};
