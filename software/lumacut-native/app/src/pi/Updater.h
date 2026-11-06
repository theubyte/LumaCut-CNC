#pragma once
#include <QObject>
#include <QtQml/qqmlregistration.h>
#include <functional>
#include "Singleton.h"

class QNetworkAccessManager;

/**
 * Updates: GitHub pre-releases "windows-<version>" with LumaCut-Studio.msi and LumaCut-Studio.json (size, sha256).
 * Marked pre-release so the Pi's /releases/latest (Android) never sees them.
 * Install: download, check SHA-256, msiexec /i /passive, quit. In a test run nothing leaves this PC: only a loopback
 * address from LUMACUT_UPDATE_API is asked, and msiexec is never started (installState says "verified").
 */
class Updater : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    LC_SINGLETON(Updater)
    Q_PROPERTY(QString current READ current CONSTANT)
    Q_PROPERTY(bool checking READ checking NOTIFY changed)
    Q_PROPERTY(bool checked READ checked NOTIFY changed)
    Q_PROPERTY(bool available READ available NOTIFY changed)
    Q_PROPERTY(QString version READ version NOTIFY changed)
    Q_PROPERTY(QString notes READ notes NOTIFY changed)
    Q_PROPERTY(double sizeBytes READ sizeBytes NOTIFY changed)
    Q_PROPERTY(QString error READ error NOTIFY changed)
    Q_PROPERTY(bool installing READ installing NOTIFY changed)
    Q_PROPERTY(QString installState READ installState NOTIFY changed)
public:
    explicit Updater(QObject* parent);
    QString current() const;
    bool checking() const { return m_checking; }
    bool checked() const { return m_checked; }
    bool available() const { return m_available; }
    QString version() const { return m_version; }
    QString notes() const { return m_notes; }
    double sizeBytes() const { return m_size; }
    QString error() const { return m_error; }
    bool installing() const { return m_installing; }
    QString installState() const { return m_installState; }
    Q_INVOKABLE void check();
    Q_INVOKABLE void install();
    static bool newer(const QString& a, const QString& b);
signals:
    void changed();
private:
    using JsonCb = std::function<void(const QVariant&, const QString& error)>;
    void fetchJson(const QString& url, JsonCb cb);
    void latest(std::function<void(bool found, const QString& error)> cb);
    QString apiBase() const;
    QNetworkAccessManager* m_net;
    bool m_checking = false, m_checked = false, m_available = false, m_installing = false;
    QString m_version, m_notes, m_error, m_msiUrl, m_sha, m_installState;
    double m_size = 0;
};
