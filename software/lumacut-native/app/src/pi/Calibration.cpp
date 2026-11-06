#include "Calibration.h"
#include "Fmt.h"
#include "Machine.h"
#include "MachineActions.h"
#include "Materials.h"
#include "PiClient.h"
#include "Toast.h"
#include "Workspace.h"
#include <QDate>
#include <QFile>
#include <QJSValue>
#include <QRegularExpression>
#ifdef Q_OS_WIN
#define NOMINMAX
#include <windows.h>
#include <commdlg.h>
#pragma comment(lib, "comdlg32.lib")
#endif
#include <algorithm>
#include <cmath>

Calibration::Calibration(QObject* parent) : QObject(parent) {
    auto* m = Machine::instance();
    connect(m, &Machine::changed, this, [this, m] {
        emit itemsChanged();
        const QString stamp = m->status().value("bed_map").toMap().value("measured_at").toString();
        if (stamp != m_bedStamp) { m_bedStamp = stamp; loadBedMap(); }
    });
}
void Calibration::loadCamera() {
    PiClient::instance()->get(QStringLiteral("/api/camera/settings"), PiCallback([this](const PiReply& r) {
        if (r.ok()) { m_camera = r.map(); m_cameraError.clear(); } else m_cameraError = r.error;
        emit changed(); emit itemsChanged();
    }));
    PiClient::instance()->get(QStringLiteral("/api/camera/calibration"), PiCallback([this](const PiReply& r) {
        if (r.ok()) m_cal = r.map(); else m_cal.clear();
        emit changed(); emit itemsChanged();
    }));
}
void Calibration::loadSystem() {
    PiClient::instance()->get(QStringLiteral("/api/system"), PiCallback([this](const PiReply& r) {
        if (r.ok()) { m_system = r.map(); m_systemError.clear(); } else m_systemError = r.error;
        emit changed();
    }));
}
void Calibration::loadBedMap() {
    PiClient::instance()->get(QStringLiteral("/api/bedmap"), PiCallback([this](const PiReply& r) {
        m_bedMap = r.ok() ? r.map().value("bed_map").toMap() : QVariantMap();
        emit changed();
    }));
}
void Calibration::saveCamera(const QVariantMap& patch) {
    QVariantMap body;
    for (const char* k : {"exposure", "gain", "white_balance", "light"}) {
        const QString key = QString::fromLatin1(k);
        body.insert(key, patch.contains(key) ? patch.value(key) : m_camera.value(key));
        m_camera.insert(key, body.value(key));
    }
    emit changed();
    emit itemsChanged();
    PiClient::instance()->putJson(QStringLiteral("/api/camera/settings"), body, PiCallback([](const PiReply& r) {
        if (!r.ok()) Toast::instance()->show(r.error, "bad");
    }));
}
void Calibration::saveSettings(const QVariantMap& fields, const QJSValue& callback) {
    PiClient::instance()->settings(fields, PiCallback([callback](const PiReply& r) mutable {
        if (r.ok()) Toast::instance()->show(QStringLiteral("Gespeichert. Werkstück vor dem nächsten Auftrag neu abtasten."), "ok");
        else Toast::instance()->show(r.error, "bad");
        Machine::instance()->refreshNow();
        if (callback.isCallable()) callback.call({r.ok()});
    }));
}
bool Calibration::cameraOk() const {
    if (m_cal.isEmpty() || m_cal.value("placeholder").toBool()) return false;
    return m_cal.value("status").toString() == QLatin1String("kalibriert") || !m_cal.value("android").toMap().isEmpty();
}
QVariantList Calibration::items() const {
    auto* m = Machine::instance();
    const QVariantMap s = m->status();
    const QVariantMap cfg = s.value("config").toMap();
    const QVariantMap and_ = m_cal.value("android").toMap();
    const bool camOk = cameraOk();
    const auto item = [](const char* id, const char* group, const QString& title, const char* tone, const QString& state, const QString& value) {
        return QVariantMap{{"id", QString::fromLatin1(id)}, {"group", QString::fromUtf8(group)}, {"title", title}, {"tone", QString::fromLatin1(tone)}, {"state", state}, {"value", value}};
    };
    QVariantList out;
    const int w = and_.value("photoWidth", m_cal.value("image_width")).toInt(), h = and_.value("photoHeight", m_cal.value("image_height")).toInt();
    out << item("kamera", "Grundlagen", QStringLiteral("Kopfkamera"), camOk ? "ok" : "bad", camOk ? QStringLiteral("erledigt") : QStringLiteral("fehlt"),
                camOk ? QStringLiteral("%1 × %2 px").arg(w).arg(h) : QStringLiteral("Grundlage für Scan und Materialtest"));
    const QVariant wb = m_camera.value("white_balance");
    const bool wbFixed = Fmt::isNumber(wb);
    out << item("licht", "Grundlagen", QStringLiteral("Kamera-Licht"), wbFixed ? "ok" : "warn", wbFixed ? QStringLiteral("fest") : QStringLiteral("automatisch"),
                wbFixed ? QStringLiteral("Weißabgleich %1 K").arg(wb.toInt()) : QStringLiteral("Weißabgleich automatisch"));
    const QVariantList off = s.value("probe_xy_offset_mm").toList();
    const bool hasOff = off.size() == 2;
    out << item("taster", "Grundlagen", QStringLiteral("Taster-Versatz"), hasOff ? "ok" : "bad", hasOff ? QStringLiteral("erledigt") : QStringLiteral("fehlt"),
                hasOff ? QStringLiteral("X %1, Y %2 mm").arg(Fmt::de(off[0]), Fmt::de(off[1])) : QStringLiteral("Nötig zum Abtasten"));
    const bool hasFocus = Fmt::isNumber(cfg.value("focus_gap_mm"));
    out << item("fokus", "Grundlagen", QStringLiteral("Laser-Fokus"), hasFocus ? "ok" : "off", QStringLiteral("Wert"),
                hasFocus ? QStringLiteral("Fokusabstand %1 mm").arg(Fmt::de(cfg.value("focus_gap_mm"))) : QStringLiteral("–"));
    const QVariantMap motion = cfg.value("motion").toMap();
    const bool hasMotion = motion.value("accel").toDouble() > 0;
    out << item("bewegung", "Grundlagen", QStringLiteral("Bewegung"), hasMotion ? "ok" : "warn", hasMotion ? QStringLiteral("gespeichert") : QStringLiteral("Firmware-Werte"),
                hasMotion ? QStringLiteral("%1 mm/s², bis %2 mm/s").arg(Fmt::de(motion.value("accel"), 0), Fmt::de(motion.value("speed"), 0)) : QStringLiteral("500 mm/s², bis 150 mm/s"));
    const QVariantMap bed = s.value("bed_map").toMap();
    const bool hasBed = !bed.isEmpty();
    out << item("bett", "Grundlagen", QStringLiteral("Bettkarte"), hasBed ? "ok" : "warn", hasBed ? QStringLiteral("gemessen") : QStringLiteral("offen"),
                hasBed ? QStringLiteral("%1 × %2 Punkte, Spanne %3 mm").arg(bed.value("cols").toInt()).arg(bed.value("rows").toInt()).arg(Fmt::de(bed.value("range"), 2)) : QStringLiteral("Höhenprofil des leeren Betts"));
    const QVariantMap mc = s.value("material_calibration").toMap();
    const QString st = mc.value("state").toString();
    const QString stText = mc.isEmpty() ? QStringLiteral("noch keiner") : st == QLatin1String("running") ? QStringLiteral("läuft") : st == QLatin1String("complete") ? QStringLiteral("fertig")
                         : st == QLatin1String("error") ? QStringLiteral("Fehler") : st == QLatin1String("aborted") ? QStringLiteral("abgebrochen") : st;
    out << item("material", "Je Material", QStringLiteral("Materialtest"), st == QLatin1String("complete") ? "ok" : st == QLatin1String("error") ? "bad" : "off", stText,
                mc.isEmpty() ? QStringLiteral("Gravur und Schnitt mit der Kamera") : QStringLiteral("%1: %2").arg(mc.value("kind").toString() == QLatin1String("engrave") ? QStringLiteral("Gravur") : QStringLiteral("Schnitt"), mc.value("material").toString()));
    return out;
}
QString Calibration::firmwareName() const {
    QString s = Machine::instance()->status().value("identity").toString();
    s.remove(QRegularExpression(QStringLiteral("^FIRMWARE_NAME:")));
    s = s.split(QStringLiteral(" SOURCE_CODE_URL")).first();
    s = s.split(QStringLiteral(" MACHINE_TYPE")).first();
    return s.isEmpty() ? QStringLiteral("–") : s;
}
QStringList Calibration::recentLines() const {
    // The heartbeat's position reports say nothing; the status shows the position anyway.
    static const QRegularExpression pos(QStringLiteral("^X:-?[\\d.]+ Y:"));
    QStringList out;
    for (const QVariant& v : Machine::instance()->status().value("recent").toList()) {
        const QString l = v.toString();
        if (!l.startsWith(QLatin1String("ok")) && !pos.match(l).hasMatch()) out << l;
    }
    return out.mid(std::max<qsizetype>(0, out.size() - 14));
}
QString Calibration::matcalLock(const QString& kind, bool raised, const QVariant&) const {
    auto* m = Machine::instance();
    const QString move = m->moveLock();
    if (!move.isEmpty()) return move;
    if (!m->cameraAvailable()) return QStringLiteral("Keine Kamera am Pi. Kopfkamera anschließen.");
    if (!cameraOk()) return QStringLiteral("Kamera nicht kalibriert. Erst die Kopfkamera einmessen.");
    if (m->status().value("probe_xy_offset_mm").isNull()) return QStringLiteral("Taster-Versatz fehlt. Der Test tastet zuerst ab.");
    if (!Workspace::instance()->hasMaterial()) return QStringLiteral("Kein Material gewählt. Erst im Bereich Material ein Material verwenden.");
    if (!m->hasPosition()) return QStringLiteral("Kopfposition unbekannt.");
    if (kind == QLatin1String("cut") && !raised) return QStringLiteral("Zum Schneiden die Platte hochlegen und unten bestätigen.");
    return {};
}
void Calibration::startMatcal(const QString& kind, bool raised) {
    if (!matcalLock(kind, raised).isEmpty()) return;
    auto* w = Workspace::instance();
    const QVariantList p = Machine::instance()->status().value("position").toList();
    const bool engrave = kind == QLatin1String("engrave");
    const QString what = engrave ? QStringLiteral("Gravur Feld für Feld, bis 18 kleine Felder, etwa 5 bis 15 Minuten") : QStringLiteral("Schnitt Durchgang für Durchgang, 4 Quadrate zu 8 mm, etwa 10 Minuten");
    QVariantMap f{{"kind", kind}, {"x", p[0]}, {"y", p[1]}, {"name", w->materialName()}, {"thickness", w->materialThickness()}};
    if (!engrave) f.insert("raised", 1);
    MachineActions::instance()->run(QStringLiteral("matcal"), f,
        QVariantMap{{"go", QVariantMap{{"detail", QStringLiteral("%1 auf „%2“ ab Kopfposition. Der Pi tastet zuerst ab und lasert dann. Testfläche frei und am Rand? Abluft an, danebenbleiben.").arg(what, w->materialName())}, {"okLabel", QStringLiteral("Lasern")}}}},
        MachineActions::Done([](bool ok, const QVariantMap&) { if (ok) Materials::instance()->load(); }));
}
void Calibration::motionTest(double accel, double speed, double span, int cycles) {
    auto* m = Machine::instance();
    const QVariantList p = m->status().value("position").toList();
    if (p.size() < 2) return;
    const double x = p[0].toDouble(), y = p[1].toDouble();
    if (x - span < 0 || x + span > m->bedWidth() || y - span < 0 || y + span > m->bedHeight()) {
        Toast::instance()->show(QStringLiteral("Für ±%1 mm steht der Kopf zu nah am Rand. Erst zur Mitte fahren.").arg(Fmt::trim(span, 0)), "bad");
        return;
    }
    MachineActions::instance()->run(QStringLiteral("motion_test"), QVariantMap{{"accel", accel}, {"speed", speed}, {"x", x}, {"y", y}, {"span", span}, {"cycles", cycles}},
        QVariantMap{{"go", QVariantMap{{"detail", QStringLiteral("Der Kopf fährt %1-mal um ±%2 mm um die aktuelle Position, mit %3 mm/s² und bis %4 mm/s. Der Laser bleibt aus, es wird laut.").arg(cycles).arg(Fmt::trim(span, 0), Fmt::trim(accel, 0), Fmt::trim(speed, 0))}}}}, MachineActions::Done{});
}
void Calibration::motionSave(double accel, double speed) {
    Confirm::instance()->askNative(QVariantMap{{"title", QStringLiteral("Grenzen speichern?")},
        {"body", QStringLiteral("Alle Aufträge fahren dann mit %1 mm/s² und bis %2 mm/s. Nur speichern, wenn die Testfahrt sauber lief.").arg(Fmt::trim(accel, 0), Fmt::trim(speed, 0))},
        {"okLabel", QStringLiteral("Speichern")}}, [accel, speed](bool yes) {
        if (yes) MachineActions::instance()->run(QStringLiteral("motion_limits"), QVariantMap{{"accel", accel}, {"speed", speed}}, QVariantMap{}, MachineActions::Done{});
    });
}
void Calibration::motionReset() { MachineActions::instance()->run(QStringLiteral("motion_limits"), QVariantMap{}, QVariantMap{}, MachineActions::Done{}); }
void Calibration::clearBedMap() {
    Confirm::instance()->askNative(QVariantMap{{"title", QStringLiteral("Bettkarte löschen?")}, {"body", QStringLiteral("Danach fehlt die Höhenkorrektur des Betts, bis sie neu gemessen ist.")},
        {"okLabel", QStringLiteral("Löschen")}, {"danger", true}}, [](bool yes) {
        if (yes) MachineActions::instance()->run(QStringLiteral("bedmap_clear"), QVariantMap{}, QVariantMap{}, MachineActions::Done{});
    });
}
void Calibration::clearOrigin() {
    Confirm::instance()->askNative(QVariantMap{{"title", QStringLiteral("Ursprung löschen?")}, {"body", QStringLiteral("Aufträge, die sich auf diesen Ursprung beziehen, müssen danach neu platziert werden.")},
        {"okLabel", QStringLiteral("Löschen")}, {"danger", true}}, [](bool yes) {
        if (yes) MachineActions::instance()->run(QStringLiteral("origin_clear"), QVariantMap{}, QVariantMap{}, MachineActions::Done{});
    });
}
QVariantList Calibration::bedCells(const QVariant&) const {
    const int cols = m_bedMap.value("cols").toInt(), rows = m_bedMap.value("rows").toInt();
    const QVariantList z = m_bedMap.value("z").toList();
    if (cols <= 0 || rows <= 0 || z.size() < cols * rows) return {};
    double lo = 1e9, hi = -1e9;
    for (const QVariant& v : z) { lo = std::min(lo, v.toDouble()); hi = std::max(hi, v.toDouble()); }
    const double span = std::max(hi - lo, 0.01);
    QVariantList out;
    for (int r = 0; r < rows; ++r)
        for (int c = 0; c < cols; ++c) {   // machine rows, shown as seen from the door: X reversed
            const double v = z[r * cols + (cols - 1 - c)].toDouble();
            out.append(QVariantMap{{"text", Fmt::de(v, 2)}, {"level", (v - lo) / span}});
        }
    return out;
}
void Calibration::saveBackup(const QString& path, const QJSValue& callback) {
    PiClient::instance()->get(QStringLiteral("/api/backup"), PiCallback([path, callback](const PiReply& r) mutable {
        bool ok = false;
        QString text = r.error;
        if (r.ok()) {
            QFile f(path);
            ok = f.open(QIODevice::WriteOnly) && f.write(r.body) == r.body.size();
            text = ok ? QStringLiteral("Sicherung gespeichert: %1").arg(path) : QStringLiteral("Speichern fehlgeschlagen: %1").arg(f.errorString());
        }
        Toast::instance()->show(text, ok ? "ok" : "bad");
        if (callback.isCallable()) callback.call({ok, text});
    }), 30000);
}
QString Calibration::uptimeText(const QVariant& seconds) {
    if (!Fmt::isNumber(seconds)) return QStringLiteral("–");
    const qint64 s = qint64(seconds.toDouble());
    const qint64 d = s / 86400, h = s / 3600 % 24, m = s / 60 % 60;
    if (d) return QStringLiteral("%1 T %2 Std").arg(d).arg(h);
    if (h) return QStringLiteral("%1 Std %2 Min").arg(h).arg(m);
    return QStringLiteral("%1 Min").arg(m);
}
QString Calibration::gbText(const QVariant& bytes) {
    if (!Fmt::isNumber(bytes)) return QStringLiteral("–");
    return Fmt::de(bytes.toDouble() / 1e9) + QStringLiteral(" GB");
}
QString Calibration::askSavePath(const QString& suggested) {
#ifdef Q_OS_WIN
    if (qEnvironmentVariableIsSet("LUMACUT_AUTOMATION_PORT")) return {};   // the driver cannot leave the window
    wchar_t file[1024] = {};
    suggested.toWCharArray(file);
    OPENFILENAMEW ofn{};
    ofn.lStructSize = sizeof ofn;
    ofn.lpstrFile = file;
    ofn.nMaxFile = 1024;
    ofn.lpstrFilter = L"JSON\0*.json\0";
    ofn.lpstrDefExt = L"json";
    ofn.Flags = OFN_OVERWRITEPROMPT | OFN_NOCHANGEDIR | OFN_PATHMUSTEXIST;
    return GetSaveFileNameW(&ofn) ? QString::fromWCharArray(file) : QString();
#else
    Q_UNUSED(suggested) return {};
#endif
}
