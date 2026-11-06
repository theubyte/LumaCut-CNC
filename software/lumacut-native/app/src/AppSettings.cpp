#include "AppSettings.h"
#include <QHostAddress>
#include <QSettings>
#include <QUrl>

AppSettings::AppSettings(QObject* parent) : QObject(parent) {
    const QByteArray file = qgetenv("LUMACUT_SETTINGS_FILE");
    if (!file.isEmpty()) m_store = new QSettings(QString::fromLocal8Bit(file), QSettings::IniFormat, this);
    else if (!qEnvironmentVariableIsSet("LUMACUT_AUTOMATION_PORT")) m_store = new QSettings(this);
}
QVariant AppSettings::value(const QString& key, const QVariant& fallback) const {
    if (m_store) return m_store->value(key, fallback);
    return m_memory.value(key, fallback);
}
void AppSettings::setValue(const QString& key, const QVariant& v) {
    if (m_store) m_store->setValue(key, v);
    else m_memory.insert(key, v);
}
QString AppSettings::theme() const { return value("theme", "system").toString(); }
void AppSettings::setTheme(const QString& v) { if (v != theme()) { setValue("theme", v); emit themeChanged(); } }
QString AppSettings::piUrl() const { return value("piUrl", defaultPi).toString(); }
void AppSettings::setPiUrl(const QString& v) { if (v != piUrl()) { setValue("piUrl", v); emit piUrlChanged(); } }

QString AppSettings::refusedBase(const QString& url) {
    const QUrl u(url);
    if (u.scheme() != QLatin1String("http")) return QStringLiteral("Nur http im Heimnetz");
    const QString host = u.host();
    QHostAddress ip;
    bool ok = false;
    if (ip.setAddress(host)) {
        if (ip.protocol() == QAbstractSocket::IPv4Protocol) {
            ok = ip.isLoopback() || ip.isLinkLocal() || ip.isInSubnet(QHostAddress(QStringLiteral("10.0.0.0")), 8)
                 || ip.isInSubnet(QHostAddress(QStringLiteral("172.16.0.0")), 12) || ip.isInSubnet(QHostAddress(QStringLiteral("192.168.0.0")), 16);
        } else {
            ok = ip.isLoopback();
        }
    } else {
        ok = host.endsWith(QLatin1String(".local"), Qt::CaseInsensitive) || host.compare(QLatin1String("localhost"), Qt::CaseInsensitive) == 0;
    }
    return ok ? QString() : QStringLiteral("Adresse %1 liegt nicht im Heimnetz").arg(host);
}

QVariantMap AppSettings::parseAddress(const QString& text) {
    static const QString unreadable = QStringLiteral("Adresse nicht lesbar. Beispiele: 192.168.2.89, lumacut.local");
    QString t = text.trimmed();
    while (t.endsWith(u'/')) t.chop(1);
    if (t.isEmpty()) return {{"error", QStringLiteral("Adresse fehlt.")}};
    const bool hasScheme = t.contains(QLatin1String("://"));
    const QUrl u(hasScheme ? t : QStringLiteral("http://") + t, QUrl::StrictMode);
    if (!u.isValid() || u.host().isEmpty()) return {{"error", unreadable}};
    if (!u.userInfo().isEmpty() || u.hasQuery() || u.hasFragment()) return {{"error", QStringLiteral("Adresse ohne Benutzer, ? oder #.")}};
    const QString port = u.port() > 0 ? QStringLiteral(":%1").arg(u.port()) : (hasScheme ? QString() : QStringLiteral(":8080"));
    const QString url = u.scheme() + QStringLiteral("://") + u.host() + port + (u.path() == QLatin1String("/") ? QString() : u.path());
    const QString refused = refusedBase(url);
    if (!refused.isEmpty()) return {{"error", refused + u'.'}};
    return {{"url", url}};
}
