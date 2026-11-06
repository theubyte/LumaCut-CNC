#include "PiClient.h"
#include "AppSettings.h"
#include <QHostAddress>
#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QNetworkProxy>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QUrl>
#include <QUrlQuery>

PiClient::PiClient(QObject* parent) : QObject(parent), m_net(new QNetworkAccessManager(this)) {
    m_net->setProxy(QNetworkProxy::NoProxy);
    m_automation = qEnvironmentVariableIsSet("LUMACUT_AUTOMATION_PORT");
    const QString over = qEnvironmentVariable("LUMACUT_PI_URL");
    m_overridden = !over.isEmpty();
    if (m_overridden) m_base = over;
    else if (!m_automation) m_base = AppSettings::instance()->piUrl();
    while (m_base.endsWith(u'/')) m_base.chop(1);
}
QString PiClient::shortUrl() const {
    QString s = m_base;
    s.remove(QStringLiteral("http://"));
    return s;
}
void PiClient::setBaseUrl(const QString& url) {
    if (m_overridden || m_automation) return;
    QString u = url;
    while (u.endsWith(u'/')) u.chop(1);
    if (u != m_base) { m_base = u; emit baseUrlChanged(); }
}
QString PiClient::refused(const QString& base) const {
    if (base.isEmpty()) return QStringLiteral("keine Adresse");
    const QString why = AppSettings::refusedBase(base);
    if (!why.isEmpty()) return why;
    if (m_automation) {
        // Test runs never reach a real machine, whatever a test types into the address field.
        const QString host = QUrl(base).host();
        QHostAddress ip;
        const bool loop = host == QLatin1String("localhost") || (ip.setAddress(host) && ip.isLoopback());
        if (!loop) return QStringLiteral("Im Testlauf nur der Simulator auf diesem PC");
    }
    return {};
}
void PiClient::request(const QByteArray& method, const QString& path, const QByteArray& contentType, const QByteArray& body, int timeoutMs, PiCallback cb) {
    if (path.startsWith(QLatin1String("/api/action"))) {   // the go dialog is not optional
        cb(PiReply{0, {}, {}, QStringLiteral("Aktionen laufen nur über MachineActions")});
        return;
    }
    send(m_base, method, path, contentType, body, timeoutMs, std::move(cb));
}
void PiClient::action(const QString& op, const QVariantMap& fields, int timeoutMs, PiCallback cb) {
    QVariantMap all = fields;
    all.insert(QStringLiteral("op"), op);
    send(m_base, "POST", QStringLiteral("/api/action"), "application/x-www-form-urlencoded", form(all), timeoutMs, std::move(cb));
}
void PiClient::probe(const QString& base, PiCallback cb) { send(base, "GET", QStringLiteral("/api/status"), {}, {}, 4000, std::move(cb)); }

void PiClient::send(const QString& base, const QByteArray& method, const QString& path, const QByteArray& contentType, const QByteArray& body, int timeoutMs, PiCallback cb) {
    const QString no = refused(base);
    if (!no.isEmpty()) { cb(PiReply{0, {}, {}, QStringLiteral("Pi nicht erreichbar: ") + no}); return; }
    if (!path.startsWith(QLatin1String("/api/"))) { cb(PiReply{0, {}, {}, QStringLiteral("Nur /api/")}); return; }
    QNetworkRequest req(QUrl(base + path));
    req.setTransferTimeout(timeoutMs);
    req.setAttribute(QNetworkRequest::Http2AllowedAttribute, false);
    req.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::ManualRedirectPolicy);
    if (!contentType.isEmpty()) req.setHeader(QNetworkRequest::ContentTypeHeader, contentType);
    QNetworkReply* reply = m_net->sendCustomRequest(req, method, body);
    connect(reply, &QNetworkReply::finished, this, [reply, cb = std::move(cb)] {
        reply->deleteLater();
        PiReply r;
        r.status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        r.contentType = reply->header(QNetworkRequest::ContentTypeHeader).toString();
        r.body = reply->readAll();
        if (r.status == 0) {
            const auto e = reply->error();
            const QString what = e == QNetworkReply::TimeoutError || e == QNetworkReply::OperationCanceledError ? QStringLiteral("Zeitüberschreitung")
                               : e == QNetworkReply::ConnectionRefusedError || e == QNetworkReply::HostNotFoundError || e == QNetworkReply::UnknownNetworkError ? QStringLiteral("keine Verbindung")
                               : reply->errorString();
            r.error = QStringLiteral("Pi nicht erreichbar: ") + what;
        } else if (r.status >= 400) {
            const QString msg = QJsonDocument::fromJson(r.body).object().value("error").toString();
            r.error = msg.isEmpty() ? QStringLiteral("Fehler %1").arg(r.status) : msg;
        }
        cb(r);
    });
}

void PiClient::postJson(const QString& path, const QVariantMap& data, PiCallback cb) {
    request("POST", path, "application/json", QJsonDocument(QJsonObject::fromVariantMap(data)).toJson(QJsonDocument::Compact), 8000, std::move(cb));
}
void PiClient::putJson(const QString& path, const QVariantMap& data, PiCallback cb) {
    request("PUT", path, "application/json", QJsonDocument(QJsonObject::fromVariantMap(data)).toJson(QJsonDocument::Compact), 8000, std::move(cb));
}
void PiClient::settings(const QVariantMap& fields, PiCallback cb) {
    request("POST", QStringLiteral("/api/settings"), "application/x-www-form-urlencoded", form(fields), 8000, std::move(cb));
}
void PiClient::upload(const QString& name, const QByteArray& gcode, PiCallback cb) {
    const QByteArray boundary = "----lumacut" + QByteArray::number(quint64(reinterpret_cast<quintptr>(this)), 16) + QByteArray::number(qHash(gcode), 16);
    QByteArray body = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"" + name.toUtf8() + "\"\r\nContent-Type: text/plain\r\n\r\n";
    body += gcode;
    body += "\r\n--" + boundary + "--\r\n";
    request("POST", QStringLiteral("/api/upload"), "multipart/form-data; boundary=" + boundary, body, 120000, std::move(cb));
}
QByteArray PiClient::form(const QVariantMap& fields) {
    QByteArray out;
    for (auto it = fields.constBegin(); it != fields.constEnd(); ++it) {
        if (!it.value().isValid()) continue;
        if (!out.isEmpty()) out += '&';
        out += QUrl::toPercentEncoding(it.key()) + '=' + QUrl::toPercentEncoding(it.value().toString());
    }
    return out;
}

// ---- QML face: cb(ok, data, error, status) ----
static PiCallback toJs(QJSValue cb) {
    return [cb](const PiReply& r) mutable {
        if (!cb.isCallable()) return;
        QJSEngine* eng = qjsEngine(PiClient::instance());
        const QJSValue data = eng ? eng->toScriptValue(r.json()) : QJSValue();
        cb.call({r.ok(), data, r.error, r.status});
    };
}
void PiClient::get(const QString& path, const QJSValue& cb, int timeoutMs) { get(path, toJs(cb), timeoutMs); }
void PiClient::postJson(const QString& path, const QVariantMap& data, const QJSValue& cb) { postJson(path, data, toJs(cb)); }
void PiClient::putJson(const QString& path, const QVariantMap& data, const QJSValue& cb) { putJson(path, data, toJs(cb)); }
void PiClient::del(const QString& path, const QJSValue& cb) { del(path, toJs(cb)); }
void PiClient::settings(const QVariantMap& fields, const QJSValue& cb) { settings(fields, toJs(cb)); }
void PiClient::testAddress(const QString& base, const QJSValue& callback) {
    probe(base, [callback, base](const PiReply& r) mutable {
        QString text;
        bool ok = false;
        if (r.status == 200) {
            const QVariantMap s = r.map();
            const QString name = s.value("config").toMap().value("machine_name").toString();
            ok = true;
            text = QStringLiteral("Erreichbar: %1%2").arg(name.isEmpty() ? QStringLiteral("LumaCut") : name,
                     s.value("connected").toBool() ? QStringLiteral(", Steuerung verbunden.") : QStringLiteral(", Steuerung nicht verbunden."));
        } else if (r.status > 0) {
            text = QStringLiteral("Der Pi antwortet mit Fehler %1. Ist das die richtige Adresse?").arg(r.status);
        } else {
            text = QStringLiteral("Keine Antwort von %1. Netzwerk und Adresse prüfen. (%2)").arg(base, r.error);
        }
        if (callback.isCallable()) callback.call({ok, text});
    });
}
