#include "Updater.h"
#include "Toast.h"
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QHostAddress>
#include <QJsonDocument>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QProcess>
#include <QUrl>

static const char* const kApi = "https://api.github.com/repos/theubyte/LumaCut-CNC";
static const QString kPrefix = QStringLiteral("windows-");

Updater::Updater(QObject* parent) : QObject(parent), m_net(new QNetworkAccessManager(this)) {}
QString Updater::current() const { return QCoreApplication::applicationVersion(); }
bool Updater::newer(const QString& a, const QString& b) {
    const auto parse = [](const QString& s) { QList<qulonglong> v; for (const auto& p : s.split(u'.')) v << p.toULongLong(); return v; };
    return parse(a) > parse(b);
}
QString Updater::apiBase() const {
    if (!qEnvironmentVariableIsSet("LUMACUT_AUTOMATION_PORT")) return QString::fromLatin1(kApi);
    const QString over = qEnvironmentVariable("LUMACUT_UPDATE_API");
    QHostAddress ip;
    if (over.isEmpty() || !ip.setAddress(QUrl(over).host()) || !ip.isLoopback()) return {};  // test run: nothing leaves this PC
    return over;
}
void Updater::fetchJson(const QString& url, JsonCb cb) {
    QNetworkRequest req{QUrl(url)};
    req.setHeader(QNetworkRequest::UserAgentHeader, "LumaCut-Studio");
    req.setTransferTimeout(15000);
    req.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::NoLessSafeRedirectPolicy);
    auto* reply = m_net->get(req);
    connect(reply, &QNetworkReply::finished, this, [reply, cb = std::move(cb)] {
        reply->deleteLater();
        if (reply->error() != QNetworkReply::NoError) { cb({}, reply->errorString()); return; }
        cb(QJsonDocument::fromJson(reply->readAll()).toVariant(), {});
    });
}
void Updater::latest(std::function<void(bool, const QString&)> cb) {
    const QString base = apiBase();
    if (base.isEmpty()) { cb(false, QStringLiteral("Im Testlauf keine Anfrage ins Netz")); return; }
    fetchJson(base + QStringLiteral("/releases?per_page=30"), [this, cb](const QVariant& list, const QString& e) {
        if (!e.isEmpty()) { cb(false, e); return; }
        QVariantMap rel;
        for (const QVariant& v : list.toList())
            if (v.toMap().value("tag_name").toString().startsWith(kPrefix)) { rel = v.toMap(); break; }
        if (rel.isEmpty()) { cb(false, {}); return; }
        QString msi, meta;
        for (const QVariant& a : rel.value("assets").toList()) {
            const QVariantMap m = a.toMap();
            if (m.value("name").toString() == QLatin1String("LumaCut-Studio.msi")) msi = m.value("browser_download_url").toString();
            if (m.value("name").toString() == QLatin1String("LumaCut-Studio.json")) meta = m.value("browser_download_url").toString();
        }
        if (msi.isEmpty() || meta.isEmpty()) { cb(false, {}); return; }
        const QString version = rel.value("tag_name").toString().mid(kPrefix.size());
        const QString notes = rel.value("body").toString();
        fetchJson(meta, [this, cb, msi, version, notes](const QVariant& metaData, const QString& e2) {
            if (!e2.isEmpty()) { cb(false, e2); return; }
            const QVariantMap m = metaData.toMap();
            m_version = version;
            m_notes = notes;
            m_msiUrl = msi;
            m_size = m.value("size").toDouble();
            m_sha = m.value("sha256").toString().toLower();
            cb(true, {});
        });
    });
}
void Updater::check() {
    m_checking = true;
    m_error.clear();
    emit changed();
    latest([this](bool found, const QString& e) {
        m_checking = false;
        m_checked = true;
        m_error = e;
        m_available = found && e.isEmpty() && newer(m_version, current());
        emit changed();
    });
}
void Updater::install() {
    if (!m_available || m_installing) return;
    if (m_sha.size() != 64) { Toast::instance()->show(QStringLiteral("Prüfsumme fehlt"), "bad"); return; }
    m_installing = true;
    m_installState = QStringLiteral("loading");
    emit changed();
    QNetworkRequest req{QUrl(m_msiUrl)};
    req.setHeader(QNetworkRequest::UserAgentHeader, "LumaCut-Studio");
    req.setTransferTimeout(600000);
    req.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::NoLessSafeRedirectPolicy);
    auto* reply = m_net->get(req);
    connect(reply, &QNetworkReply::finished, this, [this, reply] {
        reply->deleteLater();
        const auto fail = [this](const QString& text) {
            m_installing = false;
            m_installState = QStringLiteral("failed");
            Toast::instance()->show(text, "bad");
            emit changed();
        };
        if (reply->error() != QNetworkReply::NoError) { fail(reply->errorString()); return; }
        const QByteArray bytes = reply->readAll();
        const QByteArray sum = QCryptographicHash::hash(bytes, QCryptographicHash::Sha256).toHex();
        if (QString::fromLatin1(sum) != m_sha) { fail(QStringLiteral("Prüfsumme stimmt nicht, Update verworfen")); return; }
        if (qEnvironmentVariableIsSet("LUMACUT_AUTOMATION_PORT")) {
            m_installing = false;
            m_installState = QStringLiteral("verified");
            emit changed();
            return;
        }
        const QString path = QDir::temp().filePath(QStringLiteral("LumaCut-Studio-%1.msi").arg(m_version));
        QFile f(path);
        if (!f.open(QIODevice::WriteOnly) || f.write(bytes) != bytes.size()) { fail(f.errorString()); return; }
        f.close();
        if (!QProcess::startDetached(QStringLiteral("msiexec"), {QStringLiteral("/i"), QDir::toNativeSeparators(path), QStringLiteral("/passive")})) {
            fail(QStringLiteral("Setup ließ sich nicht starten"));
            return;
        }
        QCoreApplication::quit();
    });
}
