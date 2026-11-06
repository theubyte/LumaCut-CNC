#pragma once
#include <QObject>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>
#include "Singleton.h"

class QSettings;

/**
 * Per-device conveniences: theme, Pi address, last view. Everything that matters lives on the Pi.
 * With LUMACUT_AUTOMATION_PORT nothing touches the user's registry: values stay in memory,
 * or in the file named by LUMACUT_SETTINGS_FILE.
 */
class AppSettings : public QObject {
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    LC_SINGLETON(AppSettings)
    Q_PROPERTY(QString theme READ theme WRITE setTheme NOTIFY themeChanged)   // system, light, dark
    Q_PROPERTY(QString piUrl READ piUrl WRITE setPiUrl NOTIFY piUrlChanged)
public:
    explicit AppSettings(QObject* parent);
    static inline const QString defaultPi = QStringLiteral("http://192.168.2.89:8080");
    QString theme() const;
    void setTheme(const QString& v);
    QString piUrl() const;
    void setPiUrl(const QString& v);
    Q_INVOKABLE QVariant value(const QString& key, const QVariant& fallback = {}) const;
    Q_INVOKABLE void setValue(const QString& key, const QVariant& v);
    /** Normalizes a typed address: {url} or {error}. Only home-network http, as in the Tauri shell. */
    Q_INVOKABLE static QVariantMap parseAddress(const QString& text);
    /** Empty when the base URL may be used, else the reason. */
    static QString refusedBase(const QString& url);
signals:
    void themeChanged();
    void piUrlChanged();
private:
    QSettings* m_store = nullptr;
    QVariantMap m_memory;
};
