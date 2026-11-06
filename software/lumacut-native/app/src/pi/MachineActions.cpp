#include "MachineActions.h"
#include "AppSettings.h"
#include "Fmt.h"
#include "Machine.h"
#include "PiClient.h"
#include "Toast.h"
#include <QHash>
#include <QSet>
#include <cmath>

struct Gate { const char* title; const char* detail; const char* kind; };
static const QHash<QString, Gate>& gates() {
    static const QHash<QString, Gate> g = {
        {"home", {"Referenzfahrt starten?", "Alle Achsen fahren an die Endschalter. Der Kopf muss frei stehen.", "move"}},
        {"park", {"Kopf parken?", "Der Kopf fährt in die Park-Ecke.", "move"}},
        {"moveto", {"Zu dieser Position fahren?", "", "move"}},
        {"probe", {"Abtasten starten?", "Der Kopf senkt sich auf das Material. Liegt das Objekt noch an derselben Stelle? Nach jedem Verschieben neu scannen.", "move"}},
        {"bedmap", {"Bettkarte messen?", "Das leere Bett wird an vielen Punkten abgetastet. Bett frei räumen.", "move"}},
        {"autorun", {"Auftrag starten?", "Referenzieren, Abtasten, Höhenkorrektur, Lasern, Parken laufen automatisch.", "laser"}},
        {"start", {"Auftrag starten?", "", "laser"}},
        {"queue_run", {"Warteschlange starten?", "Alle Aufträge laufen nacheinander.", "laser"}},
        {"frame", {"Rahmen fahren?", "Der Kopf fährt den Umriss ab. Ist auf dem Pi Glimmen eingestellt, läuft dabei ein schwacher Laserpunkt.", "laser"}},
        {"matcal", {"Materialtest starten?", "Es wird gelasert. Testfläche am Rand wählen, kein ungetestetes empfindliches Material unter dem Kopf.", "laser"}},
        {"motion_test", {"Bewegungstest starten?", "Der Kopf fährt schnell hin und her.", "move"}},
        {"line_laser", {"Linienlaser umschalten?", "", "laser"}},
    };
    return g;
}
// Ops that pass without a go. work_band only stores a limit, it moves nothing and fires nothing.
static const QSet<QString> kFree = {
    "jog", "light", "exhaust", "abort", "estop", "estop_reset", "connect", "info", "position", "endstops", "report",
    "bedmap_clear", "origin_set", "origin_clear", "place", "place_clear", "queue_add", "queue_pause", "queue_skip", "queue_remove", "queue_clear",
    "motion_limits", "app_update_check", "firmware_update_check", "work_band"};
// Single-shot helpers the views run without showing the busy spinner.
static const QSet<QString> kQuietBusy = {"jog", "light", "exhaust", "abort", "estop", "origin_set", "origin_clear", "bedmap_clear", "motion_limits", "work_band"};

MachineActions::MachineActions(QObject* parent) : QObject(parent) {
    const double v = AppSettings::instance()->value("jogStep", 1).toDouble();
    m_jogStep = (v == 0.1 || v == 1 || v == 10) ? v : 1;
}
bool MachineActions::isAllowed(const QString& op) { return gates().contains(op) || kFree.contains(op); }
bool MachineActions::needsGo(const QString& op) { return gates().contains(op); }
QString MachineActions::goOkLabel() const {
    const QString s = m_go.value("okLabel").toString();
    if (!s.isEmpty()) return s;
    return goKind() == QLatin1String("laser") ? QStringLiteral("Starten") : QStringLiteral("Fahren");
}
void MachineActions::setJogStep(double v) {
    if (v != 0.1 && v != 1 && v != 10) return;   // only these steps exist
    if (v != m_jogStep) { m_jogStep = v; AppSettings::instance()->setValue("jogStep", v); emit jogStepChanged(); }
}

void MachineActions::askGo(const QVariantMap& request, std::function<void(bool)> cb) {
    if (m_goCb) { cb(false); return; }  // one question at a time; a second one is a no, never queued into a yes
    m_go = request;
    m_goCb = std::move(cb);
    emit goChanged();
}
void MachineActions::askGo(const QVariantMap& request, const QJSValue& cb) {
    askGo(request, std::function<void(bool)>([cb](bool yes) mutable { if (cb.isCallable()) cb.call({yes}); }));
}
void MachineActions::answerGo(bool yes) {
    if (!m_goCb) return;
    auto cb = std::move(m_goCb);
    m_goCb = nullptr;
    emit goChanged();
    cb(yes);
}

void MachineActions::run(const QString& op, const QVariantMap& fields, const QVariantMap& opts, Done done) {
    const auto it = gates().constFind(op);
    if (it == gates().constEnd()) {
        if (!kFree.contains(op)) {
            const QString msg = QStringLiteral("Aktion %1 ist in dieser App nicht freigegeben").arg(op);
            Toast::instance()->show(msg, "bad");
            if (done) done(false, {});
            return;
        }
        send(op, fields, opts, std::move(done));
        return;
    }
    QVariantMap req{{"title", QString::fromUtf8(it->title)}, {"detail", QString::fromUtf8(it->detail)}, {"kind", QString::fromLatin1(it->kind)}};
    const QVariantMap over = opts.value("go").toMap();
    for (auto o = over.constBegin(); o != over.constEnd(); ++o) req.insert(o.key(), o.value());
    if (!kQuietBusy.contains(op)) { m_busy = op; emit busyChanged(); }
    askGo(req, std::function<void(bool)>([this, op, fields, opts, done = std::move(done)](bool yes) mutable {
        if (!yes) {
            if (m_busy == op) { m_busy.clear(); emit busyChanged(); }
            if (done) done(false, {});
            return;
        }
        send(op, fields, opts, std::move(done));
    }));
}
void MachineActions::run(const QString& op, const QVariantMap& fields, const QVariantMap& opts, const QJSValue& cb) {
    run(op, fields, opts, Done([cb](bool ok, const QVariantMap& reply) mutable {
        if (!cb.isCallable()) return;
        QJSEngine* eng = qjsEngine(MachineActions::instance());
        cb.call({ok, eng ? eng->toScriptValue(reply) : QJSValue()});
    }));
}
void MachineActions::send(const QString& op, const QVariantMap& fields, const QVariantMap& opts, Done done) {
    if (!kQuietBusy.contains(op) && m_busy != op) { m_busy = op; emit busyChanged(); }
    if ((op == QLatin1String("exhaust") || op == QLatin1String("light")) && fields.contains("on"))
        Machine::instance()->applyLocal(op == QLatin1String("light") ? QStringLiteral("lights") : op, fields.value("on").toString() == QLatin1String("1"));
    const int timeout = opts.value("timeoutMs", 180000).toInt();  // long moves block their request
    const bool quiet = opts.value("quiet").toBool();
    PiClient::instance()->action(op, fields, timeout, [this, op, quiet, done = std::move(done)](const PiReply& r) {
        if (m_busy == op) { m_busy.clear(); emit busyChanged(); }
        QVariantMap reply = r.map();
        if (!r.ok() && !reply.contains("error")) reply.insert("error", r.error);   // a refusal always carries its sentence, also without an answer from the Pi
        if (r.ok()) {
            const QString msg = reply.value("message").toString();
            if (!msg.isEmpty() && !quiet) Toast::instance()->show(msg, "ok");
        } else {
            Toast::instance()->show(r.error, "bad");
        }
        Machine::instance()->refreshNow();
        if (done) done(r.ok(), reply);
    });
}

void MachineActions::home() {
    if (Machine::instance()->status().value("home_needs_confirm").toBool()) {
        run(QStringLiteral("home"), QVariantMap{{"clear", 1}},
            QVariantMap{{"go", QVariantMap{{"title", QStringLiteral("Steht der Kopf frei?")},
                {"detail", QStringLiteral("Der Pi kennt die Kopfhöhe nicht (nach Not-Aus, Stromausfall oder Neustart der Steuerung). Beim Referenzieren fährt der Kopf quer über das Bett in die Ecke. Steht die Tasterspitze über allem, was auf dem Bett liegt?")},
                {"okLabel", QStringLiteral("Ja, referenzieren")}}}}, Done{});
    } else {
        run(QStringLiteral("home"), QVariantMap{}, QVariantMap{}, Done{});
    }
}
void MachineActions::jog(const QString& dir) {
    auto* m = Machine::instance();
    const bool isZ = dir == QLatin1String("zup") || dir == QLatin1String("zdown");
    const QString refused = isZ ? m->zLock() : m->moveLock();
    if (!refused.isEmpty()) { Toast::instance()->show(refused, "warn"); return; }
    if (!m_jog.isEmpty()) return;  // the next step only after the Pi answered
    QString axis;
    double distance = 0;
    const double s = m_jogStep;
    if (isZ) {
        axis = QStringLiteral("Z");
        distance = dir == QLatin1String("zup") ? s : -s;
    } else {
        // On screen, from the door: right = work X+, down = work Y+. The only conversion is toMachine.
        const double wx = dir == QLatin1String("right") ? s : dir == QLatin1String("left") ? -s : 0;
        const double wy = dir == QLatin1String("down") ? s : dir == QLatin1String("up") ? -s : 0;
        if (wx == 0 && wy == 0) return;
        const QPointF a = m->toMachine(0, 0), b = m->toMachine(wx, wy);
        const double dx = std::round((b.x() - a.x()) * 1000) / 1000, dy = std::round((b.y() - a.y()) * 1000) / 1000;
        axis = dx != 0 ? QStringLiteral("X") : QStringLiteral("Y");
        distance = dx != 0 ? dx : dy;
    }
    m_jog = dir;
    emit busyChanged();
    run(QStringLiteral("jog"), QVariantMap{{"axis", axis}, {"distance", distance}}, QVariantMap{{"quiet", true}}, Done([this](bool, const QVariantMap&) {
        m_jog.clear();
        emit busyChanged();
    }));
}
void MachineActions::estop() {
    answerGo(false);   // whatever was being asked is off: an open go dialog must not survive a NOT-AUS
    auto after = [](const PiReply& r) {
        if (r.ok()) Toast::instance()->show(QStringLiteral("NOT-AUS ausgelöst. Laser aus, Bewegung gestoppt."), "bad");
        else Toast::instance()->show(QStringLiteral("NOT-AUS nicht bestätigt: %1. Netzschalter betätigen!").arg(r.error), "bad");
        Machine::instance()->refreshNow();
    };
    PiClient::instance()->action(QStringLiteral("estop"), {}, 3000, [after](const PiReply& first) {
        if (first.ok()) { after(first); return; }
        PiClient::instance()->action(QStringLiteral("estop"), {}, 3000, after);
    });
}
void MachineActions::moveTo(double workX, double workY) {
    auto* m = Machine::instance();
    if (!(workX >= 0 && workX <= m->bedWidth() && workY >= 0 && workY <= m->bedHeight())) {
        Toast::instance()->show(QStringLiteral("Ziel außerhalb der Arbeitsfläche (X 0 bis %1, Y 0 bis %2 mm)").arg(Fmt::trim(m->bedWidth(), 1), Fmt::trim(m->bedHeight(), 1)), "bad");
        return;
    }
    const QPointF t = m->toMachine(workX, workY);
    run(QStringLiteral("moveto"), QVariantMap{{"x", std::round(t.x() * 100) / 100}, {"y", std::round(t.y() * 100) / 100}},
        QVariantMap{{"quiet", true}, {"go", QVariantMap{{"detail", QStringLiteral("Der Kopf fährt nach X %1, Y %2 (von der Tür gesehen). Der Laser bleibt aus.").arg(Fmt::de(workX), Fmt::de(workY))}}}}, Done{});
}
