#include "Workspace.h"
#include "Machine.h"
#include "PiClient.h"
#include <QTimer>

Workspace::Workspace(QObject* parent) : QObject(parent) {
    connect(Machine::instance(), &Machine::syncChanged, this, [this](const QVariantMap& sync) {
        const int scan = sync.value("scan").toInt();
        if (scan != m_scanRev) { m_scanRev = scan; emit changed(); }
        if (sync.value("workspace").toInt() != m_rev && !m_loading) load();
    });
    connect(PiClient::instance(), &PiClient::baseUrlChanged, this, [this] { m_rev = -1; m_material.clear(); emit changed(); });
    // Created on first use, possibly long after the first status: read the stand now, the sync signal will not repeat it.
    m_scanRev = Machine::instance()->status().value("sync").toMap().value("scan").toInt();
    if (Machine::instance()->online()) QTimer::singleShot(0, this, [this] { load(); });
}
void Workspace::take(const QVariantMap& w) {
    m_material = w.value("material").toMap();
    m_rev = w.value("revision").toInt();
    m_areas = w.value("areas").toList();
    m_points = w.value("probe_points").toList();
    emit changed();
}
void Workspace::load(Done done) {
    m_loading = true;
    PiClient::instance()->get(QStringLiteral("/api/workspace"), PiCallback([this, done](const PiReply& r) {
        m_loading = false;
        if (r.ok()) take(r.map());
        if (done) done(r.ok(), r.error);
    }));
}
void Workspace::save(const QVariantMap& fields, Done done) {
    const auto attempt = [this, fields](auto&& self, bool retry, Done finish) -> void {
        QVariantMap body = fields;
        body.insert("base_revision", m_rev);
        body.insert("updated_by", QStringLiteral("Windows"));
        PiClient::instance()->putJson(QStringLiteral("/api/workspace"), body, PiCallback([this, self, retry, finish](const PiReply& r) {
            if (r.ok()) { take(r.map()); if (finish) finish(true, {}); return; }
            if (r.status == 409 && retry) {
                load([self, finish](bool ok, const QString& e) { if (ok) self(self, false, finish); else if (finish) finish(false, e); });
                return;
            }
            if (finish) finish(false, r.error);
        }));
    };
    if (m_rev < 0) load([attempt, done](bool ok, const QString& e) { if (ok) attempt(attempt, true, done); else if (done) done(false, e); });
    else attempt(attempt, true, done);
}
void Workspace::setMaterial(const QString& name, double thicknessMm, Done done) {
    save(QVariantMap{{"material", QVariantMap{{"name", name}, {"thickness_mm", thicknessMm}}}}, std::move(done));
}
