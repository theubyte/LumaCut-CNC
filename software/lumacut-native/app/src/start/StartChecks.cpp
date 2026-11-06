#include "StartChecks.h"
#include "Fmt.h"
#include <QColor>
#include <QSet>
#include <cmath>

using namespace lumacut;

namespace startchecks {
namespace {
QString labelOf(const Element& e) {
    const QString t = e.text ? e.text->trimmed() : QString();
    return QStringLiteral("„%1“").arg(t.isEmpty() ? e.kind : t);
}
void add(std::vector<Check>& out, const QString& id, const QString& tone, const QString& text, const QString& goLabel = {}, const QString& goDest = {}) {
    for (const Check& c : out) if (c.id == id) return;
    out.push_back({id, tone, text, goLabel, goDest});
}
QString num(double v) { return Fmt::trim(v, 1); }
QString toMotiv() { return QStringLiteral("Zum Motiv"); }
QString motivDest() { return QStringLiteral("motiv"); }
}

QString machineBlocker(const QVariantMap& s, bool online, bool jobActive, bool frameActive) {
    if (!online) return QStringLiteral("Der Pi ist nicht erreichbar: WLAN und Pi-Adresse prüfen.");
    if (s.value("emergency_latched").toBool()) return QStringLiteral("Not-Aus ist aktiv: Ursache beseitigen, dann oben „Not-Aus quittieren“.");
    if (s.contains("connected") && !s.value("connected").toBool()) return QStringLiteral("Die Steuerung ist nicht verbunden: USB-Kabel am Pi prüfen.");
    const QString owner = s.value("owner").toString();
    if (!owner.isEmpty() && owner != QLatin1String("Frei") && owner != QLatin1String("monitor") && !jobActive && !frameActive) {
        if (owner == QLatin1String("job") || owner == QLatin1String("frame") || owner == QLatin1String("web") || owner == QLatin1String("shutdown"))
            return QStringLiteral("Die Maschine ist noch beschäftigt: einen Moment warten.");
        return QStringLiteral("Der Laser wird gerade von %1 benutzt: dort zuerst trennen.").arg(owner == QLatin1String("lightburn") ? QStringLiteral("LightBurn") : owner);
    }
    const QVariantMap cfg = s.value("config").toMap();
    if (cfg.contains("validated") && !cfg.value("validated").toBool()) return QStringLiteral("Die Mechanik ist noch nicht freigegeben: unter Maschine prüfen und freigeben.");
    return {};
}

Findings docFindings(const Document& doc, int plate, bool multi, const Motion& motion) {
    Findings f;
    f.hasDoc = true;
    f.empty = doc.elements.empty();
    auto& out = f.checks;
    if (f.empty) {
        add(out, "nothing", "bad", multi ? QStringLiteral("Platte %1 ist leer: eine andere Platte wählen.").arg(plate + 1) : QStringLiteral("Noch kein Motiv: zuerst etwas gestalten."), toMotiv(), motivDest());
        return f;
    }
    QSet<QString> active, used, present;
    for (const Layer& l : doc.layers) if (l.output && l.visible) active.insert(l.id);
    bool anyActive = false;
    for (const Element& e : doc.elements) { present.insert(e.layerId); anyActive = anyActive || active.contains(e.layerId); }
    if (!anyActive) add(out, "off", "bad", QStringLiteral("Alle Elemente liegen auf ausgeschalteten Ebenen: im Motiv eine Ebene einschalten."), toMotiv(), motivDest());
    const bool band = Work::bandBlocked();
    for (const Element& e : doc.elements) {
        if (!active.contains(e.layerId)) continue;
        used.insert(e.layerId);
        const auto b = e.worldBounds();
        if (b && !Work::contains(*b)) {
            add(out, "outside", "bad", QStringLiteral("%1 ragt über die Arbeitsfläche hinaus: im Motiv verschieben oder verkleinern.").arg(labelOf(e)), toMotiv(), motivDest());
            f.ownFinding = true;
        }
        if (e.touchesPark()) {
            if (band) add(out, "band", "bad", QStringLiteral("%1 liegt im gesperrten Streifen (oben): dort wird nicht gelasert.").arg(labelOf(e)), toMotiv(), motivDest());
            else add(out, "park", "bad", QStringLiteral("%1 liegt in der Park-Ecke (oben rechts): dort wird nicht gelasert.").arg(labelOf(e)), toMotiv(), motivDest());
            f.ownFinding = true;
        }
        if (e.isImage() && std::abs(e.transform.rotation) > 1e-6) {
            add(out, "rotated", "bad", QStringLiteral("Das Bild %1 ist gedreht: gedrehte Bilder gehen noch nicht, Drehung auf 0° setzen.").arg(labelOf(e)), toMotiv(), motivDest());
            f.ownFinding = true;
        }
    }
    const double maxFeed = motion.maxFeed();
    for (const Layer& l : doc.layers) {
        if (!used.contains(l.id)) continue;
        if (l.speed > maxFeed + 1e-6) {
            add(out, QStringLiteral("fast-") + l.id, "bad", QStringLiteral("Ebene „%1“ ist zu schnell: %2 mm/min, die Maschine fährt höchstens %3 mm/min.").arg(l.label(), num(l.speed), num(maxFeed)), toMotiv(), motivDest());
            f.ownFinding = true;
        }
        if (l.powerPct > 0 && l.powerPct < Limits::MIN_RELIABLE_POWER_PCT)
            add(out, QStringLiteral("weak-") + l.id, "warn", QStringLiteral("Ebene „%1“ hat nur %2 % Leistung: unter %3 % zündet der Laser nicht sicher.").arg(l.label(), num(l.powerPct), num(Limits::MIN_RELIABLE_POWER_PCT)));
    }
    // The table of what will run, in layer order, only layers with something on them.
    for (const Layer& l : doc.layers) {
        if (!present.contains(l.id)) continue;
        const bool on = l.output && l.visible;
        bool filled = l.mode == LayerMode::Fill;
        if (!filled) for (const Element& e : doc.elements) if (e.layerId == l.id && e.isImage()) { filled = true; break; }
        const QColor c = QColor::fromRgba(QRgb(quint32(l.color)));
        f.layerRows.append(QVariantMap{
            {"id", l.id}, {"name", l.label()}, {"color", c.name()}, {"on", on},
            {"power", Fmt::trim(l.powerPct, 1) + QStringLiteral(" %")}, {"speed", QString::number(qRound(l.speed))}, {"passes", QString::number(l.passes)},
            {"interval", filled ? Fmt::trim(l.intervalMm, 2) : QStringLiteral("–")}, {"weak", l.powerPct > 0 && l.powerPct < Limits::MIN_RELIABLE_POWER_PCT}});
    }
    return f;
}

std::vector<Check> computeChecks(const Input& i) {
    std::vector<Check> out;
    if (!i.rejection.isEmpty()) add(out, "rejected", "bad", i.rejection);
    const QString blocker = machineBlocker(i.status, i.online, i.jobActive, i.frameActive);
    if (!blocker.isEmpty()) add(out, "machine", "bad", blocker, QStringLiteral("Zur Maschine"), QStringLiteral("maschine"));
    if (i.materialKnown && !i.hasMaterial)
        add(out, "material", "bad", QStringLiteral("Kein Material gewählt: die Stärke bestimmt die Fahrhöhe, der Pi startet ohne sie nicht."), QStringLiteral("Material wählen"), QStringLiteral("material"));
    for (const Check& c : i.findings.checks) add(out, c.id, c.tone, c.text, c.goLabel, c.goDest);
    const bool own = i.findings.ownFinding;
    if (!i.buildError.isEmpty() && !own && !i.findings.empty) add(out, "build", "bad", i.buildError);

    if (i.hasToolpath) {
        if (i.bounds && !own) {
            const double W = Bed::width();
            const Box work{W - i.bounds->maxX, i.bounds->minY, W - i.bounds->minX, i.bounds->maxY};
            if (!Work::contains(work)) add(out, "outside", "bad", QStringLiteral("Der Auftrag ragt über die Arbeitsfläche hinaus."));
            else if (Work::touchesPark(work)) {
                if (Work::bandBlocked()) add(out, "band", "bad", QStringLiteral("Der Auftrag berührt den gesperrten Streifen (oben): dort wird nicht gelasert."));
                else add(out, "park", "bad", QStringLiteral("Der Auftrag berührt die Park-Ecke (oben rechts): dort wird nicht gelasert."));
            }
        }
        if (!i.bounds) add(out, "empty", "bad", QStringLiteral("Im Auftrag ist keine Laserbahn: es gäbe nichts zu lasern."));
        int n = 0;
        for (const QString& w : i.warnings) {
            ++n;
            if (w.contains(QLatin1String("Park-Ecke")) || w.contains(QLatin1String("gesperrter Streifen")) || w.contains(QLatin1String("Keine Laserbewegung"))) continue;
            add(out, QStringLiteral("stat-%1").arg(n), "warn", w);
        }
        if (i.gcodeBytes > kMaxUploadBytes)
            add(out, "toolarge", "bad", QStringLiteral("Der Auftrag ist mit %1 MB zu groß, der Pi nimmt höchstens 32 MB an: Abstand vergrößern oder das Motiv verkleinern.").arg(Fmt::de(double(i.gcodeBytes) / 1048576.0, 1)), toMotiv(), motivDest());
    }
    if (i.hasMaterial && i.materialTested.has_value() && !*i.materialTested)
        add(out, "untested", "warn", QStringLiteral("Ungetestetes Material: für „%1“ gibt es keine eigenen Werte. Erst einen Materialtest machen.").arg(i.materialName), QStringLiteral("Zum Material"), QStringLiteral("material"));
    if (i.findings.hasDoc && i.findings.empty) return out;
    add(out, "moved", "info", QStringLiteral("Objekt verschoben? Dann vor dem Start neu scannen, sonst sitzt der Laser daneben."));
    return out;
}

bool blocksStart(const std::vector<Check>& checks) {
    for (const Check& c : checks) if (c.tone == QLatin1String("bad")) return true;
    return false;
}

}  // namespace startchecks
