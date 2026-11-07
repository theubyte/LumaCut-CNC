#include "Machine.h"
#include "AppSettings.h"
#include "PiClient.h"
#include "core/model.h"
#include <QJsonDocument>
#include <QTimer>

static const QStringList kActiveJob = {"homing", "probing", "focusing", "running", "finishing", "parking"};
static const QStringList kTransientOwners = {"Frei", "", "monitor", "web"};

Machine::Machine(QObject* parent) : QObject(parent), m_timer(new QTimer(this)) {
    m_timer->setSingleShot(true);
    connect(m_timer, &QTimer::timeout, this, [this] { tick(true); });
    connect(PiClient::instance(), &PiClient::baseUrlChanged, this, &Machine::start);
    connect(AppSettings::instance(), &AppSettings::piUrlChanged, this, [] { PiClient::instance()->setBaseUrl(AppSettings::instance()->piUrl()); });
}
void Machine::start() {
    ++m_gen;
    m_timer->stop();
    m_online = false;
    m_status.clear();
    m_error.clear();
    m_inFlight = false;
    emit changed();
    if (!PiClient::instance()->baseUrl().isEmpty()) tick(true);
}
void Machine::refreshNow() { if (!PiClient::instance()->baseUrl().isEmpty()) tick(false); }

void Machine::applyLocal(const QString& key, const QVariant& value) {
    m_status.insert(key, value);
    emit changed();
}

void Machine::tick(bool schedule) {
    const int gen = m_gen;
    PiClient::instance()->get(QStringLiteral("/api/status"), PiCallback([this, gen, schedule](const PiReply& r) {
        if (gen != m_gen) return;
        if (r.ok()) {
            take(r.map());
        } else {
            m_online = false;
            m_error = r.error;
            emit changed();
        }
        if (schedule) m_timer->start(jobActive() ? 500 : 1000);
    }), 3000);
}

void Machine::take(const QVariantMap& s) {
    m_status = s;
    m_online = true;
    m_error.clear();
    const QVariantMap t = s.value("config").toMap().value("travels").toMap();
    const QVariantMap p = s.value("park_corner_mm").toMap();
    const auto within = [](const QVariant& v, double lo, double hi, double& out) {
        if (!v.isValid()) return false;
        const double d = v.toDouble();
        if (d < lo || d > hi || d == out) return false;
        out = d;
        return true;
    };
    bool bed = within(t.value("x"), 100, 600, m_bedW);
    bed |= within(t.value("y"), 100, 600, m_bedH);
    bed |= within(p.value("x"), 0, 600, m_parkX);
    bed |= within(p.value("y"), 0, 200, m_parkY);
    if (bed) {
        lumacut::Bed::configure(m_bedW, m_bedH, m_parkX, m_parkY);   // everything in core reckons with what the Pi reports
        emit bedChanged();
    }
    emit changed();
    const QVariantMap sync = s.value("sync").toMap();
    if (sync != m_sync) { m_sync = sync; emit syncChanged(sync); }
}

static QString jobState(const QVariantMap& s) { return s.value("job").toMap().value("state").toString(); }
static QString owner(const QVariantMap& s) { return s.value("owner", QStringLiteral("Frei")).toString(); }

bool Machine::jobActive() const { return kActiveJob.contains(jobState(m_status)); }
bool Machine::frameActive() const {
    const QString f = m_status.value("frame").toMap().value("state").toString();
    return f == QLatin1String("running") || f == QLatin1String("starting");
}
bool Machine::free() const { return connected() && !m_status.value("busy").toBool() && owner(m_status) == QLatin1String("Frei") && !latched() && !jobActive() && !frameActive(); }
double Machine::workX() const { const auto p = m_status.value("position").toList(); return p.size() >= 3 ? m_bedW - p[0].toDouble() : 0; }
double Machine::workY() const { const auto p = m_status.value("position").toList(); return p.size() >= 3 ? p[1].toDouble() : 0; }
double Machine::z() const { const auto p = m_status.value("position").toList(); return p.size() >= 3 ? p[2].toDouble() : 0; }
QString Machine::stateText() const { const QString s = m_status.value("state").toString(); return s.isEmpty() ? QStringLiteral("–") : s; }

QString Machine::freeLock() const {
    if (!m_online) return QStringLiteral("Pi nicht erreichbar. Adresse unter Optionen prüfen.");
    if (latched()) return QStringLiteral("Not-Aus aktiv. SKR zurücksetzen, dann quittieren und neu referenzieren.");
    if (m_status.contains("connected") && !connected()) return QStringLiteral("Steuerung nicht verbunden. USB-Kabel zum SKR prüfen.");
    const QString fw = m_status.value("firmware_update").toMap().value("state").toString();
    if (fw == QLatin1String("uploading") || fw == QLatin1String("rebooting")) return QStringLiteral("Firmware-Update läuft. Bitte abwarten.");
    if (jobActive()) return QStringLiteral("Auftrag „%1“ läuft. Erst abwarten oder abbrechen.").arg(m_status.value("job").toMap().value("file").toString());
    if (frameActive()) return QStringLiteral("Rahmenfahrt läuft. Erst abwarten oder abbrechen.");
    const QString own = owner(m_status);
    if (own == QLatin1String("lightburn")) return QStringLiteral("LightBurn hat die Steuerung. Erst dort trennen.");
    if (!kTransientOwners.contains(own)) return QStringLiteral("Steuerung belegt durch %1. Bitte abwarten.").arg(own);
    return {};
}
QString Machine::homeLock() const {
    const QString f = freeLock();
    if (!f.isEmpty()) return f;
    const QVariantMap cfg = m_status.value("config").toMap();
    if (cfg.contains("validated") && !cfg.value("validated").toBool()) return QStringLiteral("Mechanik nicht freigegeben. Die Freigabe erfolgt vor Ort an der Maschine.");
    return {};
}
QString Machine::moveLock() const {
    const QString h = homeLock();
    if (!h.isEmpty()) return h;
    if (!homed()) {
        const QString lost = m_status.value("reference").toMap().value("lost").toString();
        return lost.isEmpty() ? QStringLiteral("Nicht referenziert. Erst die Referenzfahrt starten.") : QStringLiteral("Referenz verloren: %1 Erst referenzieren.").arg(lost);
    }
    return {};
}
QString Machine::zLock() const {
    const QString m = moveLock();
    if (!m.isEmpty()) return m;
    if (m_status.value("workpiece_surface_z").isNull()) return QStringLiteral("Z erst nach dem Abtasten: Ohne gemessene Oberfläche lässt der Pi keine Z-Fahrt zu.");
    return {};
}
QString Machine::probeLock() const {
    const QString m = moveLock();
    if (!m.isEmpty()) return m;
    const QVariant zp = m_status.value("z_probe_supported");
    if (zp.isValid() && !zp.isNull() && !zp.toBool()) return QStringLiteral("Die Firmware meldet keinen Z-Taster.");
    const QVariantList off = m_status.value("probe_xy_offset_mm").toList();
    if (off.size() < 2) return QStringLiteral("Taster-Versatz fehlt. Unter Kalibrieren eintragen.");
    // Same rule as the Pi (transport._probe_head_ok): the head, shifted by the probe offset, stays 10 mm inside the travel.
    const QVariantList p = m_status.value("position").toList();
    if (p.size() >= 2) {
        const double hx = p[0].toDouble() - off[0].toDouble(), hy = p[1].toDouble() - off[1].toDouble();
        if (hx < 10 || hx > m_bedW - 10 || hy < 10 || hy > m_bedH - 10)
            return QStringLiteral("Hier erreicht der Taster das Material nicht. Erst weiter zur Mitte fahren.");
    }
    return {};
}

static QVariantMap line(const char* tone, const QString& title, const QString& text) {
    return {{"tone", QString::fromLatin1(tone)}, {"title", title}, {"text", text}};
}
QVariantMap Machine::headline() const {
    if (!m_online) {
        QString u = PiClient::instance()->shortUrl();
        return line("bad", QStringLiteral("Pi nicht erreichbar"), u.isEmpty() ? QStringLiteral("Keine Adresse eingestellt.") : QStringLiteral("Netzwerk und Adresse %1 prüfen.").arg(u));
    }
    if (latched()) return line("bad", QStringLiteral("Not-Aus aktiv"), QStringLiteral("SKR zurücksetzen (Reset-Taste oder kurz stromlos), dann quittieren."));
    if (m_status.contains("connected") && !connected()) {
        const QString fault = m_status.value("fault").toString();
        return line("bad", QStringLiteral("Steuerung getrennt"), fault.isEmpty() ? QStringLiteral("USB-Verbindung zum SKR fehlt.") : fault);
    }
    const QVariantMap fw = m_status.value("firmware_update").toMap();
    const QString fwState = fw.value("state").toString();
    if (fwState == QLatin1String("uploading") || fwState == QLatin1String("rebooting")) return line("busy", QStringLiteral("Firmware-Update"), fw.value("message").toString());
    const QVariantMap frame = m_status.value("frame").toMap();
    if (frameActive()) return line("busy", QStringLiteral("Rahmenfahrt"), QStringLiteral("%1 von %2").arg(frame.value("line").toInt()).arg(frame.value("total").toInt()));
    const QVariantMap j = m_status.value("job").toMap();
    const QString js = j.value("state").toString();
    const QString file = j.value("file").toString();
    if (js == QLatin1String("homing")) return line("busy", QStringLiteral("Referenzfahrt"), file);
    if (js == QLatin1String("probing")) {
        const QVariantMap p = j.value("probe").toMap();
        return line("busy", QStringLiteral("Wird abgetastet"), p.isEmpty() ? file : QStringLiteral("%1 · Punkt %2 von %3").arg(file).arg(p.value("done").toInt()).arg(p.value("total").toInt()));
    }
    if (jobActive()) return line("busy", QStringLiteral("Auftrag läuft"), file);
    const QString own = owner(m_status);
    if (own == QLatin1String("lightburn")) return line("warn", QStringLiteral("LightBurn verbunden"), QStringLiteral("Steuerung über die App erst nach dem Trennen."));
    if (!kTransientOwners.contains(own)) return line("busy", QStringLiteral("Beschäftigt"), QStringLiteral("Belegt durch %1").arg(own));
    if (own == QLatin1String("web") || m_status.value("state").toString() == QLatin1String("Busy")) return line("busy", QStringLiteral("In Bewegung"), QStringLiteral("Die Maschine fährt gerade."));
    if (!homed()) {
        const QString lost = m_status.value("reference").toMap().value("lost").toString();
        if (!lost.isEmpty()) return line("warn", QStringLiteral("Referenz verloren"), lost);
        return line("warn", QStringLiteral("Nicht referenziert"), QStringLiteral("Vor dem Arbeiten die Referenzfahrt starten."));
    }
    if (m_status.value("workpiece_surface_z").isNull()) return line("ok", QStringLiteral("Bereit"), QStringLiteral("Referenziert. Werkstück noch nicht abgetastet."));
    return line("ok", QStringLiteral("Bereit"), QStringLiteral("Referenziert und abgetastet."));
}
QVariantMap Machine::chip() const {
    QString tone = QStringLiteral("ok"), text = QStringLiteral("Bereit");
    if (!m_online) { tone = "bad"; text = QStringLiteral("Pi nicht erreichbar"); }
    else if (latched()) { tone = "bad"; text = QStringLiteral("Not-Aus aktiv"); }
    else if (m_status.contains("connected") && !connected()) { tone = "warn"; text = QStringLiteral("Steuerung nicht verbunden"); }
    else if (laserArmed()) { tone = "bad"; text = QStringLiteral("Laser scharf"); }
    else if (jobActive()) { tone = "accent"; text = QStringLiteral("Auftrag läuft"); }
    else if (frameActive()) { tone = "accent"; text = QStringLiteral("Rahmen läuft"); }
    else if (!homed()) { tone = "warn"; text = QStringLiteral("Nicht referenziert"); }
    return {{"tone", tone}, {"text", text}, {"online", m_online}};
}
QVariantMap Machine::jobInfo() const {
    const QVariantMap j = m_status.value("job").toMap();
    if (!jobActive()) return {{"active", false}};
    const int total = j.value("total").toInt();
    const double pct = total > 0 ? qMin(100.0, 100.0 * j.value("line").toDouble() / total) : 0;
    const QString st = j.value("phase").toString().isEmpty() ? j.value("state").toString() : j.value("phase").toString();   // phase is the finer step
    const QVariantMap p = j.value("probe").toMap();
    QString phase = st;
    if (st == QLatin1String("homing")) phase = QStringLiteral("Referenzfahrt");
    else if (st == QLatin1String("probing")) phase = QStringLiteral("Abtasten %1/%2").arg(p.value("done").toInt()).arg(p.value("total").toInt());
    else if (st == QLatin1String("focusing")) phase = QStringLiteral("Höhenkorrektur");
    else if (st == QLatin1String("running")) phase = QStringLiteral("Lasern");
    else if (st == QLatin1String("finishing")) phase = QStringLiteral("Abschluss");
    else if (st == QLatin1String("parking")) phase = QStringLiteral("Parken");
    return {{"active", true}, {"percent", pct}, {"phase", phase}, {"file", j.value("file").toString()}};
}
