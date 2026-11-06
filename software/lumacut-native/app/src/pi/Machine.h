#pragma once
#include <QObject>
#include <QPointF>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>
#include "Singleton.h"

class QTimer;

/**
 * Live machine state: polls /api/status (500 ms during a job, otherwise 1 s). One request per interval serves every view.
 * Locks and the headline are sentences with the next step; the Pi still checks everything itself.
 * Work coordinates: from the door, origin at the back left. Machine X = bedWidth - work X.
 */
class Machine : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    LC_SINGLETON(Machine)
    Q_PROPERTY(bool online READ online NOTIFY changed)
    Q_PROPERTY(QString lastError READ lastError NOTIFY changed)
    Q_PROPERTY(QVariantMap status READ status NOTIFY changed)
    Q_PROPERTY(bool connected READ connected NOTIFY changed)
    Q_PROPERTY(bool homed READ homed NOTIFY changed)
    Q_PROPERTY(bool latched READ latched NOTIFY changed)
    Q_PROPERTY(bool laserArmed READ laserArmed NOTIFY changed)
    Q_PROPERTY(bool jobActive READ jobActive NOTIFY changed)
    Q_PROPERTY(bool frameActive READ frameActive NOTIFY changed)
    Q_PROPERTY(bool free READ free NOTIFY changed)
    Q_PROPERTY(bool lights READ lights NOTIFY changed)
    Q_PROPERTY(bool exhaust READ exhaust NOTIFY changed)
    Q_PROPERTY(bool cameraAvailable READ cameraAvailable NOTIFY changed)
    Q_PROPERTY(bool hasPosition READ hasPosition NOTIFY changed)
    Q_PROPERTY(double workX READ workX NOTIFY changed)
    Q_PROPERTY(double workY READ workY NOTIFY changed)
    Q_PROPERTY(double z READ z NOTIFY changed)
    Q_PROPERTY(QString stateText READ stateText NOTIFY changed)
    Q_PROPERTY(double bedWidth READ bedWidth NOTIFY changed)
    Q_PROPERTY(double bedHeight READ bedHeight NOTIFY changed)
    Q_PROPERTY(double parkX READ parkX NOTIFY changed)
    Q_PROPERTY(double parkY READ parkY NOTIFY changed)
    /** Y of the locked strip across the whole width (op=work_band); 0 = only the park corner. */
    Q_PROPERTY(double blockedBandY READ blockedBandY NOTIFY changed)
    // Sentences; empty = free.
    Q_PROPERTY(QString freeLock READ freeLock NOTIFY changed)
    Q_PROPERTY(QString homeLock READ homeLock NOTIFY changed)
    Q_PROPERTY(QString moveLock READ moveLock NOTIFY changed)
    Q_PROPERTY(QString zLock READ zLock NOTIFY changed)
    Q_PROPERTY(QString probeLock READ probeLock NOTIFY changed)
    /** {tone: ok|warn|bad|busy, title, text} */
    Q_PROPERTY(QVariantMap headline READ headline NOTIFY changed)
    /** {tone, text, online} for the top bar. */
    Q_PROPERTY(QVariantMap chip READ chip NOTIFY changed)
    /** {active, percent, phase, file} for the progress strip. */
    Q_PROPERTY(QVariantMap jobInfo READ jobInfo NOTIFY changed)
public:
    explicit Machine(QObject* parent);
    /** Starts or restarts polling on the client's current address. */
    Q_INVOKABLE void start();
    Q_INVOKABLE void refreshNow();
    /** Shows an accepted change at once, so a second click does not act on the previous state. The next poll confirms it. */
    void applyLocal(const QString& key, const QVariant& value);

    bool online() const { return m_online; }
    QString lastError() const { return m_error; }
    QVariantMap status() const { return m_status; }
    bool connected() const { return m_status.value("connected").toBool(); }
    bool homed() const { return m_status.value("homed").toBool(); }
    bool latched() const { return m_status.value("emergency_latched").toBool(); }
    bool laserArmed() const { return m_status.value("laser_armed").toBool(); }
    bool jobActive() const;
    bool frameActive() const;
    bool free() const;
    bool lights() const { return m_status.value("lights").toBool(); }
    bool exhaust() const { return m_status.value("exhaust").toBool(); }
    bool cameraAvailable() const { return m_status.value("camera").toMap().value("available").toBool(); }
    bool hasPosition() const { return m_status.value("position").toList().size() >= 3; }
    double workX() const;
    double workY() const;
    double z() const;
    QString stateText() const;
    double bedWidth() const { return m_bedW; }
    double bedHeight() const { return m_bedH; }
    double parkX() const { return m_parkX; }
    double parkY() const { return m_parkY; }
    double blockedBandY() const { return m_status.value("config").toMap().value("blocked_band_y_mm").toDouble(); }
    QString freeLock() const;
    QString homeLock() const;
    QString moveLock() const;
    QString zLock() const;
    QString probeLock() const;
    QVariantMap headline() const;
    QVariantMap chip() const;
    QVariantMap jobInfo() const;

    Q_INVOKABLE QPointF toMachine(double workX, double workY) const { return {m_bedW - workX, workY}; }
    Q_INVOKABLE QPointF fromMachine(double machineX, double machineY) const { return {m_bedW - machineX, machineY}; }
signals:
    void changed();
    /** The Pi's sync revisions moved: {workspace, project, scan}. */
    void syncChanged(const QVariantMap& sync);
    /** Bed geometry or park corner changed. */
    void bedChanged();
private:
    void tick(bool schedule);
    void take(const QVariantMap& s);
    QTimer* m_timer;
    bool m_online = false;
    QString m_error;
    QVariantMap m_status;
    QVariantMap m_sync;
    double m_bedW = 370, m_bedH = 360, m_parkX = 78, m_parkY = 35;
    int m_gen = 0;
    bool m_inFlight = false;
};
