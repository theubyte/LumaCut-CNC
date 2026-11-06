#include "Materials.h"
#include "AppSettings.h"
#include "Fmt.h"
#include "Machine.h"
#include "PiClient.h"
#include "Toast.h"
#include "Workspace.h"
#include <QCollator>
#include <QJsonArray>
#include <QJsonDocument>
#include <QUrl>
#include <algorithm>
#include <cmath>

static constexpr double kMinReliablePower = 8;   // below this a burning layer does not fire reliably (STAND.md §4)
static constexpr double kMaxFocusDrop = 3;
static const QStringList kProcesses = {"Gravieren", "Markieren", "Schneiden"};

Materials::Materials(QObject* parent) : QObject(parent) {
    const QByteArray cached = AppSettings::instance()->value("materialsCache").toByteArray();
    if (!cached.isEmpty()) m_items = QJsonDocument::fromJson(cached).toVariant().toList();
    connect(PiClient::instance(), &PiClient::baseUrlChanged, this, &Materials::load);
}
void Materials::saveCache() {
    AppSettings::instance()->setValue("materialsCache", QJsonDocument(QJsonArray::fromVariantList(m_items)).toJson(QJsonDocument::Compact));
}
void Materials::load() {
    m_loading = true;
    emit changed();
    PiClient::instance()->get(QStringLiteral("/api/materials"), PiCallback([this](const PiReply& r) {
        m_loading = false;
        if (r.ok()) {
            const QVariantMap m = r.map();
            m_items = m.value("materials").toList();
            m_rev = m.value("revision").toInt();
            m_fromPi = true;
            m_error.clear();
            saveCache();
        } else {
            m_fromPi = false;
            m_error = r.error;
        }
        emit changed();
    }));
}
QString Materials::groupKey(const QString& name, double thicknessMm) { return name + u'|' + QString::number(thicknessMm); }
QVariantList Materials::groups(const QString& query) const {
    const QString q = query.trimmed().toLower();
    QList<QVariantMap> out;
    for (const QVariant& v : m_items) {
        const QVariantMap m = v.toMap();
        const QString name = m.value("name").toString();
        if (!q.isEmpty() && !name.toLower().contains(q) && !m.value("process").toString().toLower().contains(q)) continue;
        const double t = m.value("thickness_mm").toDouble();
        const QString key = groupKey(name, t);
        auto it = std::find_if(out.begin(), out.end(), [&](const QVariantMap& g) { return g.value("key").toString() == key; });
        if (it == out.end()) out.append({{"key", key}, {"name", name}, {"thicknessMm", t}, {"entries", QVariantList{m}}});
        else { QVariantList e = it->value("entries").toList(); e.append(m); it->insert("entries", e); }
    }
    QCollator coll{QLocale(QLocale::German)};
    coll.setCaseSensitivity(Qt::CaseInsensitive);
    std::sort(out.begin(), out.end(), [&](const QVariantMap& a, const QVariantMap& b) {
        const int c = coll.compare(a.value("name").toString(), b.value("name").toString());
        return c != 0 ? c < 0 : a.value("thicknessMm").toDouble() < b.value("thicknessMm").toDouble();
    });
    QVariantList list;
    for (auto& g : out) {
        // The processes in the fixed order, for the list's second line.
        QStringList present;
        for (const QString& p : kProcesses) if (!entryOf(g, p).isEmpty()) present << p;
        bool allBuiltin = true, anyBuiltin = false;
        for (const QVariant& e : g.value("entries").toList()) { const bool b = e.toMap().value("builtin").toBool(); allBuiltin &= b; anyBuiltin |= b; }
        g.insert("processes", present.join(QStringLiteral(", ")));
        g.insert("allBuiltin", allBuiltin);
        g.insert("anyBuiltin", anyBuiltin);
        list.append(g);
    }
    return list;
}
QVariantMap Materials::entryOf(const QVariantMap& group, const QString& process) {
    for (const QVariant& e : group.value("entries").toList()) {
        const QVariantMap m = e.toMap();
        if (m.value("process").toString().compare(process, Qt::CaseInsensitive) == 0) return m;
    }
    return {};
}
int Materials::effectivePasses(const QVariantMap& m) {
    const double depth = m.value("depth_per_pass_mm").toDouble();
    if (depth > 0) {
        const double t = m.value("thickness_mm").toDouble();
        if (t <= 0) return 1;
        return std::min(30, std::max(1, int(std::ceil(t / depth - 1e-9))));
    }
    return m.value("passes", 1).toInt();
}
QVariantMap Materials::newProcess(const QString& name, double thickness, const QString& process) {
    // Start values, never meant as tested values; the view says so.
    QVariantMap m{{"name", name}, {"thickness_mm", thickness}, {"process", process},
                  {"mode", process == QLatin1String("Gravieren") ? "fill" : "line"}, {"passes", 1}, {"interval_mm", 0.1}, {"depth_per_pass_mm", 0}, {"z_step_mm", 0}};
    if (process == QLatin1String("Gravieren")) { m["power_pct"] = 25; m["speed_mm_min"] = 3000; }
    else if (process == QLatin1String("Markieren")) { m["power_pct"] = 40; m["speed_mm_min"] = 1500; }
    else { m["power_pct"] = 85; m["speed_mm_min"] = 400; }
    return m;
}
bool Materials::lowPower(const QVariantMap& m) { const double p = m.value("power_pct").toDouble(); return p > 0 && p < kMinReliablePower; }
bool Materials::focusDropOk(int passes, double zStep) { return (passes - 1) * zStep <= kMaxFocusDrop + 1e-9; }
QVariantList Materials::tonePoints(const QVariantMap& material) {
    struct P { double e, tone; bool clean; double power, speed; };
    QList<P> pts;
    for (const QVariant& v : material.value("tone_curve").toMap().value("points").toList()) {
        const QVariantMap p = v.toMap();
        const double power = p.value("power").toDouble(), speed = p.value("speed").toDouble();
        if (power > 0 && speed > 0) pts.append({power / speed, p.value("tone").toDouble(), p.value("clean", true).toBool(), power, speed});
    }
    if (pts.size() < 2) return {};
    std::sort(pts.begin(), pts.end(), [](const P& a, const P& b) { return a.e < b.e; });
    const double lo = std::log(pts.first().e), hi = std::log(pts.last().e), span = std::max(hi - lo, 1e-6);
    QVariantList out;
    for (const P& p : pts) out.append(QVariantMap{{"x", (std::log(p.e) - lo) / span}, {"y", std::clamp(p.tone, 0.0, 1.0)}, {"clean", p.clean},
        {"label", QStringLiteral("%1 %, %2 mm/min: Ton %3").arg(Fmt::trim(p.power, 2), Fmt::trim(p.speed, 2), Fmt::trim(p.tone, 2))}});
    return out;
}

// ---- Writes: each names the revision it builds on ----
void Materials::write(const QString& what, const std::function<void(int, std::function<void(const PiReply&)>)>& fn, Done done) {
    if (!m_fromPi) { if (done) done(false, {}, QStringLiteral("Materialien ändern geht nur mit Verbindung zum Pi")); return; }
    fn(m_rev, [this, what, done](const PiReply& r) {
        if (r.ok()) {
            const QVariantMap m = r.map();
            // The reply carries the new revision, so a following write in the same action does not collide.
            if (m.contains("revision")) m_rev = m.value("revision").toInt();
            load();
            if (done) done(true, m.value("material").toMap(), {});
            return;
        }
        if (r.status == 409) {
            load();
            if (done) done(false, {}, QStringLiteral("Die Liste wurde inzwischen geändert und neu geladen. Bitte noch einmal %1.").arg(what));
            return;
        }
        if (done) done(false, {}, r.error);
    });
}
void Materials::create(const QVariantMap& m, Done done) {
    write(QStringLiteral("anlegen"), [m](int rev, std::function<void(const PiReply&)> cb) {
        QVariantMap body = m; body["base_revision"] = rev;
        PiClient::instance()->postJson(QStringLiteral("/api/materials"), body, PiCallback(std::move(cb)));
    }, std::move(done));
}
void Materials::update(const QString& id, const QVariantMap& patch, Done done) {
    write(QStringLiteral("speichern"), [id, patch](int rev, std::function<void(const PiReply&)> cb) {
        QVariantMap body = patch; body["base_revision"] = rev;
        PiClient::instance()->putJson(QStringLiteral("/api/materials/") + QString::fromLatin1(QUrl::toPercentEncoding(id)), body, PiCallback(std::move(cb)));
    }, std::move(done));
}
void Materials::remove(const QString& id, Done done) {
    write(QStringLiteral("löschen"), [id](int rev, std::function<void(const PiReply&)> cb) {
        PiClient::instance()->del(QStringLiteral("/api/materials/%1?base_revision=%2").arg(QString::fromLatin1(QUrl::toPercentEncoding(id))).arg(rev), PiCallback(std::move(cb)));
    }, std::move(done));
}
static Materials::Done toastOnError() {
    return [](bool ok, const QVariantMap&, const QString& e) { if (!ok) Toast::instance()->show(e, "bad"); };
}
void Materials::addProcess(const QString& name, double thickness, const QString& process) { create(newProcess(name, thickness, process), toastOnError()); }
void Materials::patch(const QString& id, const QVariantMap& fields) { update(id, fields, toastOnError()); }
void Materials::removeEntry(const QString& id) { remove(id, toastOnError()); }

// Several writes in a row: one after the other, stop at the first error.
template <typename Step>
static void chain(int i, int n, Step step, std::function<void(bool, const QString&)> finish) {
    if (i >= n) { finish(true, {}); return; }
    step(i, [=](bool ok, const QVariantMap&, const QString& e) {
        if (!ok) { finish(false, e); return; }
        chain(i + 1, n, step, finish);
    });
}
static std::function<void(bool, const QString&)> jsFinish(QJSValue cb, const QString& key) {
    return [cb, key](bool ok, const QString& e) mutable {
        if (!ok) Toast::instance()->show(e, "bad");
        if (cb.isCallable()) cb.call({ok, key});
    };
}
void Materials::createGroup(const QString& name, double thickness, const QString& processes, const QJSValue& cb) {
    const QStringList wanted = processes.split(u',');
    QStringList ordered;
    for (const QString& p : kProcesses) if (wanted.contains(p)) ordered << p;
    chain(0, int(ordered.size()), [this, name, thickness, ordered](int i, Done next) { create(newProcess(name, thickness, ordered[i]), std::move(next)); },
          jsFinish(cb, groupKey(name, thickness)));
}
void Materials::renameGroup(const QVariantMap& group, const QString& name, double thickness, const QJSValue& cb) {
    const QVariantList entries = group.value("entries").toList();
    const QString oldName = group.value("name").toString();
    const double oldT = group.value("thicknessMm").toDouble();
    chain(0, int(entries.size()), [this, entries, name, thickness](int i, Done next) {
        update(entries[i].toMap().value("id").toString(), QVariantMap{{"name", name}, {"thickness_mm", thickness}}, std::move(next));
    }, [cb, oldName, oldT, name, thickness](bool ok, const QString& e) mutable {
        auto finish = jsFinish(cb, groupKey(name, thickness));
        auto* w = Workspace::instance();
        if (ok && w->materialName() == oldName && w->materialThickness() == oldT) {
            w->setMaterial(name, thickness, [finish](bool ok2, const QString& e2) { finish(ok2, e2); });
            return;
        }
        finish(ok, e);
    });
}
void Materials::removeGroup(const QVariantMap& group, const QJSValue& cb) {
    const QVariantList entries = group.value("entries").toList();
    chain(0, int(entries.size()), [this, entries](int i, Done next) { remove(entries[i].toMap().value("id").toString(), std::move(next)); },
          jsFinish(cb, QString()));
}
void Materials::use(const QVariantMap& group) {
    const QString name = group.value("name").toString();
    const double t = group.value("thicknessMm").toDouble();
    Workspace::instance()->setMaterial(name, t, [this, group, name, t](bool ok, const QString& e) {
        if (!ok) { Toast::instance()->show(QStringLiteral("Nicht übernommen: %1").arg(e), "bad"); return; }
        emit applyToLayers(group);
        Toast::instance()->show(QStringLiteral("„%1, %2 mm“ ist jetzt das aktuelle Material. Die Ebenen haben die Werte übernommen.").arg(name, Fmt::trim(t, 2)), "ok");
    });
}
