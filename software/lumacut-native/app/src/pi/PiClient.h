#pragma once
#include <QByteArray>
#include <QJSValue>
#include <QJsonDocument>
#include <QJsonObject>
#include <QObject>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>
#include <functional>
#include "Singleton.h"

class QNetworkAccessManager;

struct PiReply {
    int status = 0;            // HTTP status; 0 = no answer
    QByteArray body;
    QString contentType;
    QString error;             // sentence for the user, empty on success
    bool ok() const { return error.isEmpty(); }
    QVariantMap map() const { return QJsonDocument::fromJson(body).object().toVariantMap(); }
    QVariant json() const { return QJsonDocument::fromJson(body).toVariant(); }
};
using PiCallback = std::function<void(const PiReply&)>;

/**
 * Thin client for the Pi API (docs/PI_API_REFERENZ.md). The Pi enforces every limit; this only transports.
 * Only home-network addresses, only /api/, no proxy, no Origin header.
 * With LUMACUT_AUTOMATION_PORT only loopback addresses are reachable, and without LUMACUT_PI_URL nothing at all.
 * C++: PiClient::instance()->get("/api/x", [](const PiReply& r) {...}).
 * QML: Pi.get("/api/x", function(ok, data, error, status) {...}). `/api/action` is not reachable from here:
 * every machine action goes through MachineActions, which owns the go dialog.
 */
class PiClient : public QObject {
    Q_OBJECT
    QML_NAMED_ELEMENT(Pi)
    QML_SINGLETON
    LC_SINGLETON(PiClient)
    Q_PROPERTY(QString baseUrl READ baseUrl NOTIFY baseUrlChanged)
    Q_PROPERTY(QString shortUrl READ shortUrl NOTIFY baseUrlChanged)
    Q_PROPERTY(bool overridden READ overridden CONSTANT)
public:
    explicit PiClient(QObject* parent);
    QString baseUrl() const { return m_base; }
    QString shortUrl() const;
    bool overridden() const { return m_overridden; }
    void setBaseUrl(const QString& url);

    void request(const QByteArray& method, const QString& path, const QByteArray& contentType, const QByteArray& body, int timeoutMs, PiCallback cb);
    void get(const QString& path, PiCallback cb, int timeoutMs = 8000) { request("GET", path, {}, {}, timeoutMs, std::move(cb)); }
    void postJson(const QString& path, const QVariantMap& data, PiCallback cb);
    void putJson(const QString& path, const QVariantMap& data, PiCallback cb);
    void del(const QString& path, PiCallback cb) { request("DELETE", path, {}, {}, 8000, std::move(cb)); }
    void settings(const QVariantMap& fields, PiCallback cb);
    /** POST /api/upload, multipart, field `file`. Name must end in .gcode. */
    void upload(const QString& name, const QByteArray& gcode, PiCallback cb);
    /** One probe of an address that is not the current one (Options, "Prüfen"). */
    void probe(const QString& base, PiCallback cb);

    Q_INVOKABLE void get(const QString& path, const QJSValue& cb, int timeoutMs = 8000);
    Q_INVOKABLE void postJson(const QString& path, const QVariantMap& data, const QJSValue& cb);
    Q_INVOKABLE void putJson(const QString& path, const QVariantMap& data, const QJSValue& cb);
    Q_INVOKABLE void del(const QString& path, const QJSValue& cb);
    Q_INVOKABLE void settings(const QVariantMap& fields, const QJSValue& cb);
    /** cb(ok, text): the sentence for the Options page. */
    Q_INVOKABLE void testAddress(const QString& base, const QJSValue& cb);

    static QByteArray form(const QVariantMap& fields);
signals:
    void baseUrlChanged();
private:
    friend class MachineActions;
    friend class Machine;
    /** POST /api/action. Reachable only through MachineActions and the status poll's owner. */
    void action(const QString& op, const QVariantMap& fields, int timeoutMs, PiCallback cb);
    void send(const QString& base, const QByteArray& method, const QString& path, const QByteArray& contentType, const QByteArray& body, int timeoutMs, PiCallback cb);
    QString refused(const QString& base) const;

    QNetworkAccessManager* m_net;
    QString m_base;
    bool m_overridden = false;
    bool m_automation = false;
};
