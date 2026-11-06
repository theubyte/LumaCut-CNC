#pragma once
#include <QJSValue>
#include <QObject>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>
#include "Singleton.h"

/**
 * What the tabs Kamera, Kalibrieren and System read from the Pi besides the status, and the checks and starts that belong to them.
 */
class Calibration : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    LC_SINGLETON(Calibration)
    Q_PROPERTY(QVariantMap camera READ camera NOTIFY changed)           // /api/camera/settings
    Q_PROPERTY(QVariantMap calibration READ calibration NOTIFY changed) // /api/camera/calibration
    Q_PROPERTY(bool cameraOk READ cameraOk NOTIFY changed)
    Q_PROPERTY(QString cameraError READ cameraError NOTIFY changed)
    Q_PROPERTY(QVariantMap system READ system NOTIFY changed)           // /api/system
    Q_PROPERTY(QString systemError READ systemError NOTIFY changed)
    Q_PROPERTY(QVariantMap bedMap READ bedMap NOTIFY changed)           // /api/bedmap, full grid
    /** The list on the left of Kalibrieren: [{id, group, title, tone, state, value}] */
    Q_PROPERTY(QVariantList items READ items NOTIFY itemsChanged)
    Q_PROPERTY(QString firmwareName READ firmwareName NOTIFY itemsChanged)
    Q_PROPERTY(QStringList recentLines READ recentLines NOTIFY itemsChanged)
public:
    explicit Calibration(QObject* parent);
    QVariantMap camera() const { return m_camera; }
    QVariantMap calibration() const { return m_cal; }
    bool cameraOk() const;
    QString cameraError() const { return m_cameraError; }
    QVariantMap system() const { return m_system; }
    QString systemError() const { return m_systemError; }
    QVariantMap bedMap() const { return m_bedMap; }
    QVariantList items() const;
    QString firmwareName() const;
    QStringList recentLines() const;

    Q_INVOKABLE void loadCamera();
    Q_INVOKABLE void loadSystem();
    Q_INVOKABLE void loadBedMap();
    /** Merges the fields and writes all four camera values. */
    Q_INVOKABLE void saveCamera(const QVariantMap& patch);
    /** Entered offsets and heights go to /api/settings; the Pi then forgets the measured surface. cb(ok). */
    Q_INVOKABLE void saveSettings(const QVariantMap& fields, const QJSValue& cb);
    /** Sentence why the material test cannot start, empty when it can. */
    Q_INVOKABLE QString matcalLock(const QString& kind, bool raised) const;
    Q_INVOKABLE void startMatcal(const QString& kind, bool raised);
    Q_INVOKABLE void motionTest(double accel, double speed, double span, int cycles);
    Q_INVOKABLE void motionSave(double accel, double speed);
    Q_INVOKABLE void motionReset();
    Q_INVOKABLE void clearBedMap();
    Q_INVOKABLE void clearOrigin();
    /** Bed heights as seen from the door: [{text, level 0..1}], row by row. */
    Q_INVOKABLE QVariantList bedCells() const;
    /** Sicherung herunterladen: writes to `path` (no dialog here). cb(ok, text). */
    Q_INVOKABLE void saveBackup(const QString& path, const QJSValue& cb);
    Q_INVOKABLE static QString uptimeText(const QVariant& seconds);
    Q_INVOKABLE static QString gbText(const QVariant& bytes);
    /** Asks Windows for a place to save; empty if cancelled. Never used in test runs: tests call saveBackup with a path. */
    Q_INVOKABLE static QString askSavePath(const QString& suggested);
signals:
    void changed();
    void itemsChanged();
private:
    QVariantMap m_camera, m_cal, m_system, m_bedMap;
    QString m_cameraError, m_systemError, m_bedStamp;
};
