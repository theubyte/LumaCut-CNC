#include "Workshop.h"
#include <QColor>
#include <QSet>
#include <algorithm>
#include <cmath>
#include "Toast.h"
#include "core/text.h"
#include "doc/Document.h"
#include "gpu/StageItem.h"

namespace lc = lumacut;
namespace ws = lumacut::Werkstatt;

namespace {
QVariantMap num(const QString& key, const QString& label, const QString& unit, double min, double max, double step = 1, int digits = 1, const QString& hint = {}) {
    return {{"type", "num"}, {"key", key}, {"label", label}, {"unit", unit}, {"min", min}, {"max", max}, {"step", step}, {"digits", digits}, {"hint", hint}};
}
QVariantMap mm(const QString& key, const QString& label, double min, double max, double step = 1, int digits = 1, const QString& hint = {}) {
    return num(key, label, QStringLiteral("mm"), min, max, step, digits, hint);
}
QVariantMap seg(const QString& key, const QString& label, const QList<std::pair<QString, QString>>& opts, const QString& hint = {}) {
    QVariantList o;
    for (const auto& [v, l] : opts) o.push_back(QVariantMap{{"value", v}, {"label", l}});
    return {{"type", "seg"}, {"key", key}, {"label", label}, {"options", o}, {"hint", hint}};
}
QVariantMap text(const QString& key, const QString& label, const QString& hint = {}, const QString& placeholder = {}) {
    return {{"type", "text"}, {"key", key}, {"label", label}, {"hint", hint}, {"placeholder", placeholder}};
}
QVariantMap check(const QString& key, const QString& label) { return {{"type", "check"}, {"key", key}, {"label", label}}; }
QVariantMap row(const QVariantList& f) { return {{"type", "row"}, {"fields", f}}; }
QVariantMap section(const QString& label) { return {{"type", "section"}, {"label", label}}; }
QVariantMap note(const QString& t, const QString& tone = QStringLiteral("info")) { return {{"type", "note"}, {"text", t}, {"tone", tone}}; }

double d(const QVariantMap& p, const char* k) { return p.value(QLatin1String(k)).toDouble(); }
int i(const QVariantMap& p, const char* k) { return int(std::lround(p.value(QLatin1String(k)).toDouble())); }
QString s(const QVariantMap& p, const char* k) { return p.value(QLatin1String(k)).toString(); }
bool b(const QVariantMap& p, const char* k) { return p.value(QLatin1String(k)).toBool(); }

double cutThickness() {
    for (const lc::Layer& l : Document::instance()->layers())
        if (l.name == QLatin1String("Schneiden") && l.thicknessMm > 0) return l.thicknessMm;
    return 3;
}
}  // namespace

Workshop::Workshop(QObject* parent) : QObject(parent) {
    buildTools();
    m_timer.setSingleShot(true);
    m_timer.setInterval(40);
    connect(&m_timer, &QTimer::timeout, this, &Workshop::recompute);
    // The frame around the motif follows the project.
    connect(Document::instance(), &Document::changed, this, [this] {
        if (m_tool == QLatin1String("rahmen") && params().value("source").toString() == QLatin1String("motiv")) m_timer.start();
    });
    setTool(QStringLiteral("materialtest"));
}

lc::PolySet Workshop::shape(const QString& t, double h, bool bold) {
    if (t.trimmed().isEmpty()) return {};
    const QString key = QString::number(h, 'g', 10) + (bold ? QLatin1Char('b') : QLatin1Char('r')) + t;
    auto f = m_textCache.constFind(key);
    if (f != m_textCache.constEnd()) return *f;
    if (m_textCache.size() > 4000) m_textCache.clear();
    // Cap height is about 0.7 of the em size in the common sans fonts.
    lc::PolySet out = lc::textPaths(t, h / 0.7, bold);
    m_textCache.insert(key, out);
    return out;
}

std::optional<lc::Box> Workshop::motifBox() const {
    const auto* doc = Document::instance();
    const QSet<QString>& sel = doc->selectionSet();
    std::optional<lc::Box> out;
    for (const auto& e : doc->elements()) {
        if (e->plate != doc->activePlate()) continue;
        if (!sel.isEmpty() && !sel.contains(e->id)) continue;
        const auto q = e->worldBounds();
        if (q) out = out ? out->united(*q) : *q;
    }
    return out;
}

void Workshop::buildTools() {
    const auto shaper = [this](const QString& t, double h, bool bold) { return shape(t, h, bold); };

    m_list.push_back({"materialtest", "Testen", "Materialtest-Raster", "Leistung gegen Tempo, beschriftet", "flask-conical", true,
        [] { return QVariantMap{{"powerFrom", 20}, {"powerTo", 100}, {"powerSteps", 5}, {"speedFrom", 300}, {"speedTo", 3000}, {"speedSteps", 5},
                                {"mode", "fill"}, {"cell", 10}, {"gap", 4}, {"passes", 1}, {"interval", 0.1}}; },
        [](const QVariantMap& p) {
            QVariantList f{
                section("Leistung"),
                row({num("powerFrom", "Von", "%", 8, 100, 5, 0), num("powerTo", "Bis", "%", 8, 100, 5, 0), num("powerSteps", "Stufen", "", 1, 10, 1, 0)}),
                section("Tempo in mm/min"),
                row({num("speedFrom", "Von", "", 10, 30000, 100, 0), num("speedTo", "Bis", "", 10, 30000, 100, 0), num("speedSteps", "Stufen", "", 1, 10, 1, 0)}),
                section("Felder"),
                seg("mode", "Art", {{"fill", "Gefüllt"}, {"line", "Nur Umriss"}}),
                row({mm("cell", "Feldgröße", 2, 50, 1), mm("gap", "Abstand", 0.5, 30, 1), num("passes", "Durchgänge", "", 1, 30, 1, 0)}),
            };
            if (s(p, "mode") == QLatin1String("fill")) f.push_back(mm("interval", "Zeilenabstand", 0.03, 2, 0.01, 2));
            f.push_back(note("Mindestens 8 % Leistung: darunter zündet der Laser nicht sicher. Jedes Feld bekommt eine eigene Ebene mit seinen Werten."));
            return f;
        },
        [shaper](const QVariantMap& p) {
            ws::MatGridSpec m;
            m.powerFrom = d(p, "powerFrom"); m.powerTo = d(p, "powerTo"); m.powerSteps = i(p, "powerSteps");
            m.speedFrom = d(p, "speedFrom"); m.speedTo = d(p, "speedTo"); m.speedSteps = i(p, "speedSteps");
            m.fill = s(p, "mode") == QLatin1String("fill");
            m.cellMm = d(p, "cell"); m.gapMm = d(p, "gap"); m.passes = i(p, "passes"); m.intervalMm = d(p, "interval");
            return ws::matGrid(m, shaper);
        }});

    m_list.push_back({"box", "Teile", "Box mit Fingerzinken", "Maße, Materialstärke, Deckel, Kerf", "box", true,
        [] { return QVariantMap{{"w", 100}, {"d", 80}, {"h", 60}, {"measure", "outer"}, {"t", cutThickness()}, {"finger", 10}, {"lid", "none"}, {"kerf", 0.15}}; },
        [](const QVariantMap&) {
            return QVariantList{
                seg("measure", "Maße gelten", {{"outer", "Außen"}, {"inner", "Innen"}}),
                row({mm("w", "Breite", 20, 340), mm("d", "Tiefe", 20, 340), mm("h", "Höhe", 20, 340)}),
                row({mm("t", "Materialstärke", 0.5, 10, 0.1, 2), mm("finger", "Zinkenbreite", 2, 50)}),
                seg("lid", "Deckel", {{"none", "Offen"}, {"joined", "Verzahnt"}, {"loose", "Aufgelegt"}}),
                mm("kerf", "Schnittbreite (Kerf)", 0, 1, 0.05, 2, "Teile werden um die halbe Schnittbreite größer, damit die Zinken stramm sitzen. Mit einem Probeschnitt messen."),
            };
        },
        [](const QVariantMap& p) {
            ws::BoxGenSpec b;
            b.w = d(p, "w"); b.d = d(p, "d"); b.h = d(p, "h"); b.t = d(p, "t"); b.finger = d(p, "finger"); b.kerf = d(p, "kerf");
            b.inner = s(p, "measure") == QLatin1String("inner");
            const QString lid = s(p, "lid");
            b.lid = lid == QLatin1String("joined") ? ws::BoxLid::Joined : lid == QLatin1String("loose") ? ws::BoxLid::Loose : ws::BoxLid::None;
            return ws::box(b);
        }});

    m_list.push_back({"zahnrad", "Teile", "Zahnrad", "Evolventenverzahnung mit Bohrung", "cog", true,
        [] { return QVariantMap{{"module", 2}, {"teeth", 24}, {"pressure", 20}, {"bore", 6}, {"kerf", 0}}; },
        [](const QVariantMap&) {
            return QVariantList{
                row({mm("module", "Modul", 0.5, 20, 0.5, 2), num("teeth", "Zähne", "", 6, 200, 1, 0)}),
                row({num("pressure", "Eingriffswinkel", "°", 14, 25, 0.5, 1), mm("bore", "Bohrung", 0, 300, 0.5, 1)}),
                mm("kerf", "Schnittbreite (Kerf)", 0, 1, 0.05, 2),
            };
        },
        [](const QVariantMap& p) {
            ws::GearSpec g;
            g.module = d(p, "module"); g.teeth = i(p, "teeth"); g.pressureDeg = d(p, "pressure"); g.boreMm = d(p, "bore"); g.kerf = d(p, "kerf");
            return ws::gear(g);
        }});

    m_list.push_back({"lineal", "Teile", "Lineal", "Millimeterskala mit Zahlen und Loch", "ruler", true,
        [] { return QVariantMap{{"length", 150}, {"width", 30}, {"hole", 5}, {"title", ""}}; },
        [](const QVariantMap&) {
            return QVariantList{
                row({mm("length", "Messlänge", 30, 340, 10, 0), mm("width", "Breite", 15, 80, 1)}),
                mm("hole", "Aufhängeloch", 0, 15, 0.5, 1, "0 = ohne Loch"),
                text("title", "Text auf dem Lineal", {}, "zum Beispiel ein Name"),
            };
        },
        [shaper](const QVariantMap& p) { return ws::ruler({d(p, "length"), d(p, "width"), d(p, "hole"), s(p, "title")}, shaper); }});

    m_list.push_back({"massstab", "Teile", "Maßstabsbalken", "Für Pläne und Modelle, etwa 1:50", "scale-3d", true,
        [] { return QVariantMap{{"scale", 50}, {"real", 5}, {"segments", 5}, {"height", 3}}; },
        [](const QVariantMap&) {
            return QVariantList{
                row({num("scale", "Maßstab 1 :", "", 1, 100000, 10, 0), num("real", "Echte Länge", "m", 0.01, 100000, 1, 2)}),
                row({num("segments", "Felder", "", 1, 20, 1, 0), mm("height", "Balkenhöhe", 1, 20, 0.5)}),
            };
        },
        [shaper](const QVariantMap& p) { return ws::scaleBar({d(p, "scale"), d(p, "real"), i(p, "segments"), d(p, "height")}, shaper); }});

    m_list.push_back({"rahmen", "Teile", "Rahmen", "Um das Motiv oder in freien Maßen", "crop", true,
        [this] { return QVariantMap{{"source", motifBox() ? "motiv" : "frei"}, {"w", 100}, {"h", 60}, {"margin", 5}, {"style", "1"}, {"target", "cut"}}; },
        [](const QVariantMap& p) {
            return QVariantList{
                seg("source", "Größe", {{"motiv", "Um das Motiv"}, {"frei", "Freie Maße"}}),
                s(p, "source") == QLatin1String("motiv") ? QVariant(mm("margin", "Abstand zum Motiv", 0, 100, 1, 1, "Um die Auswahl, sonst um alles auf der aktiven Platte."))
                                                         : QVariant(row({mm("w", "Breite", 5, 340, 5), mm("h", "Höhe", 5, 340, 5)})),
                seg("style", "Stil", {{"0", "Rechteck"}, {"1", "Abgerundet"}, {"2", "Doppelt"}, {"3", "Oval"}, {"4", "Gestrichelt"}}),
                seg("target", "Ebene", {{"cut", "Schneiden"}, {"mark", "Markieren"}}),
            };
        },
        [this](const QVariantMap& p) {
            ws::FrameGenSpec f;
            if (s(p, "source") == QLatin1String("motiv")) {
                f.around = motifBox();
                if (!f.around) throw ws::GenError(QStringLiteral("Auf der aktiven Platte ist noch nichts. Erst etwas anlegen oder „Freie Maße“ wählen."));
            }
            f.widthMm = d(p, "w"); f.heightMm = d(p, "h"); f.marginMm = d(p, "margin"); f.style = i(p, "style"); f.cut = s(p, "target") == QLatin1String("cut");
            return ws::frame(f);
        }});

    m_list.push_back({"serien", "Beschriften", "Seriennummern", "Fortlaufende Schilder, auch über mehrere Platten", "hash", true,
        [] { return QVariantMap{{"template", "SN-{0001}"}, {"count", 24}, {"step", 1}, {"textH", 6}, {"tag", true}, {"tagW", 50}, {"tagH", 16}, {"hole", 3}, {"gap", 2}}; },
        [](const QVariantMap& p) {
            QVariantList f{
                text("template", "Vorlage", "Die Ziffern in { } sind Startwert und Stellenzahl: {0001} ergibt 0001, 0002, …"),
                row({num("count", "Stück", "", 1, ws::MAX_SERIALS, 1, 0), num("step", "Schrittweite", "", 1, 1000, 1, 0), mm("textH", "Schrifthöhe", 1, 50, 0.5)}),
                check("tag", "Schild um jede Nummer ausschneiden"),
            };
            if (b(p, "tag")) f.push_back(row({mm("tagW", "Schildbreite", 10, 340), mm("tagH", "Schildhöhe", 5, 340), mm("hole", "Loch", 0, 15, 0.5, 1)}));
            f.push_back(mm("gap", "Abstand", 0.5, 30, 0.5));
            return f;
        },
        [shaper](const QVariantMap& p) {
            ws::SerialSpec sp;
            sp.templ = s(p, "template"); sp.count = i(p, "count"); sp.step = i(p, "step"); sp.textHeightMm = d(p, "textH");
            const bool tag = b(p, "tag");
            sp.tagWidthMm = tag ? d(p, "tagW") : 0; sp.tagHeightMm = tag ? d(p, "tagH") : 0; sp.holeMm = d(p, "hole"); sp.gapMm = d(p, "gap");
            return ws::serials(sp, shaper, lc::Work::width(), lc::Work::height());
        }});

    m_list.push_back({"stempel", "Beschriften", "Stempel", "Invertiert und gespiegelt, mit Rahmen und Text", "stamp", true,
        [] { return QVariantMap{{"shape", "rect"}, {"w", 60}, {"h", 25}, {"l1", "Musterwerkstatt"}, {"l2", "Hauptstraße 1"}, {"l3", ""}, {"motif", "none"},
                                {"border", 0.8}, {"bold", true}, {"inverted", true}, {"mirrored", true}}; },
        [](const QVariantMap& p) {
            return QVariantList{
                seg("shape", "Form", {{"rect", "Eckig"}, {"round", "Rund"}}),
                s(p, "shape") == QLatin1String("round") ? QVariant(mm("w", "Durchmesser", 10, 300, 1)) : QVariant(row({mm("w", "Breite", 10, 300, 1), mm("h", "Höhe", 10, 300, 1)})),
                text("l1", "Zeile 1"), text("l2", "Zeile 2"), text("l3", "Zeile 3"),
                seg("motif", "Motiv", {{"none", "Keins"}, {"star", "Stern"}, {"heart", "Herz"}, {"drop", "Tropfen"}}),
                mm("border", "Rahmenstärke", 0, 5, 0.1, 1, "0 = ohne Rahmen"),
                check("bold", "Fette Schrift"),
                check("inverted", "Invertiert (Hintergrund wird weggebrannt)"),
                check("mirrored", "Gespiegelt (Abdruck wird lesbar)"),
            };
        },
        [shaper](const QVariantMap& p) {
            ws::StampSpec st;
            st.round = s(p, "shape") == QLatin1String("round");
            st.widthMm = d(p, "w"); st.heightMm = d(p, "h");
            st.lines = {s(p, "l1"), s(p, "l2"), s(p, "l3")};
            const QString m = s(p, "motif");
            st.motif = m == QLatin1String("star") ? ws::StampMotif::Star : m == QLatin1String("heart") ? ws::StampMotif::Heart : m == QLatin1String("drop") ? ws::StampMotif::Drop : ws::StampMotif::None;
            st.borderMm = d(p, "border"); st.bold = b(p, "bold"); st.inverted = b(p, "inverted"); st.mirrored = b(p, "mirrored");
            return ws::stamp(st, shaper);
        }});

    m_list.push_back({"qr", "Beschriften", "QR-Code", "Text oder Adresse als graviertes Muster", "qr-code", true,
        [] { return QVariantMap{{"text", "https://"}, {"module", 1}, {"plate", false}}; },
        [](const QVariantMap&) {
            return QVariantList{
                text("text", "Text oder Adresse", "Stufe M, bis 213 Zeichen. Eigene Umsetzung ohne fremde Bibliothek."),
                mm("module", "Kantenlänge eines Punktes", 0.2, 10, 0.1, 2),
                check("plate", "Umriss zum Ausschneiden, mit hellem Rand"),
            };
        },
        [](const QVariantMap& p) { return ws::qr({s(p, "text"), d(p, "module"), b(p, "plate")}); }});

    m_list.push_back({"foto", "Fotos", "Fotogravur", "Foto vorbereiten mit den Bildwerkzeugen im Motiv", "image", false,
        [] { return QVariantMap{}; }, [](const QVariantMap&) { return QVariantList{}; }, nullptr});
}

QVariantList Workshop::tools() const {
    QVariantList out;
    for (const Tool& t : m_list) out.push_back(QVariantMap{{"id", t.id}, {"group", t.group}, {"title", t.title}, {"blurb", t.blurb}, {"icon", t.icon}, {"compute", t.compute}});
    return out;
}
const Workshop::Tool* Workshop::current() const {
    for (const Tool& t : m_list) if (t.id == m_tool) return &t;
    return nullptr;
}
QVariantMap Workshop::toolInfo() const {
    const Tool* t = current();
    if (!t) return {};
    return {{"id", t->id}, {"group", t->group}, {"title", t->title}, {"blurb", t->blurb}, {"icon", t->icon}, {"compute", t->compute}};
}
void Workshop::setTool(const QString& id) {
    if (id == m_tool) return;
    const auto it = std::find_if(m_list.begin(), m_list.end(), [&](const Tool& t) { return t.id == id; });
    if (it == m_list.end()) return;
    m_tool = id;
    if (!m_params.contains(id)) m_params.insert(id, it->defaults());
    m_plate = 0;
    m_fields.clear();
    emit toolChanged();
    emit paramsChanged();
    syncFields();
    recompute();
}
void Workshop::syncFields() {
    const Tool* t = current();
    QVariantList f = t ? t->fields(params()) : QVariantList{};
    if (f == m_fields) return;
    m_fields = std::move(f);
    emit fieldsChanged();
}
void Workshop::setParam(const QString& key, const QVariant& value) {
    QVariantMap& p = m_params[m_tool];
    if (p.value(key) == value) return;
    p.insert(key, value);
    emit paramsChanged();
    syncFields();
    m_timer.start();
}
void Workshop::resetParams() {
    const Tool* t = current();
    if (!t) return;
    m_params.insert(m_tool, t->defaults());
    m_fields.clear();
    emit paramsChanged();
    syncFields();
    recompute();
}
void Workshop::setPreviewPlate(int p) {
    if (!m_res) return;
    p = std::clamp(p, 0, std::max(0, ws::plateCount(*m_res) - 1));
    if (p == m_plate) return;
    m_plate = p;
    m_info.insert("plate", p);
    emit resultChanged();
    showPreview();
}

void Workshop::recompute() {
    m_timer.stop();
    const Tool* t = current();
    m_res.reset();
    m_info = {{"ok", false}};
    if (t && t->run) {
        try {
            m_res = t->run(params());
            const ws::GenResult& r = *m_res;
            const int plates = ws::plateCount(r);
            const auto box = ws::partsBounds(r, 0);
            int count = 0;
            for (const auto& p : r.parts) if (!p.paths.empty()) ++count;
            m_plate = std::min(m_plate, std::max(0, plates - 1));
            m_info = {{"ok", count > 0}, {"parts", count}, {"plates", plates}, {"plate", m_plate}, {"notes", r.notes}, {"warnings", r.warnings},
                      {"size", box ? QStringLiteral("%1 × %2 mm").arg(ws::num(box->width()), ws::num(box->height())) : QString()}};
            if (!count) m_info.insert("error", QStringLiteral("Das ergibt nichts zum Lasern. Werte prüfen."));
        } catch (const ws::GenError& e) {
            m_info.insert("error", QString::fromUtf8(e.what()));
        } catch (const std::exception& e) {
            m_info.insert("error", QStringLiteral("Das ließ sich nicht berechnen: %1").arg(QString::fromUtf8(e.what())));
        }
    }
    emit resultChanged();
    showPreview();
}

void Workshop::attachPreview(QQuickItem* item) {
    m_stage = qobject_cast<StageItem*>(item);
    showPreview();
}

void Workshop::showPreview() {
    if (!m_stage) return;
    StageItem* st = m_stage;
    st->setProperty("bedWidth", lc::Work::width());
    st->setProperty("bedHeight", lc::Work::height());
    st->setProperty("parkWidth", lc::Work::park().width());
    st->setProperty("parkHeight", lc::Work::park().height());
    std::vector<StageLayer> layers;
    std::vector<StageElement> els;
    QHash<QString, int> ids;
    const auto layerOf = [&](const QString& name) {
        auto f = ids.constFind(name);
        if (f != ids.constEnd()) return *f;
        const lc::Layer* src = nullptr;
        for (const lc::Layer& l : Document::instance()->layers()) if (l.name == name) { src = &l; break; }
        if (!src && m_res) for (const lc::Layer& l : m_res->layers) if (l.name == name) { src = &l; break; }
        static const std::vector<lc::Layer> standard = lc::Document::defaultLayers();
        if (!src) for (const lc::Layer& l : standard) if (l.name == name) { src = &l; break; }
        StageLayer s;
        s.id = int(layers.size()) + 1;
        if (src) { s.color = QColor::fromRgb(QRgb(quint32(src->color))); s.fill = src->mode == lc::LayerMode::Fill; }
        layers.push_back(s);
        ids.insert(name, s.id);
        return s.id;
    };
    // The frame around the motif: show the motif itself faintly.
    if (m_res && !m_res->center && m_tool == QLatin1String("rahmen")) {
        StageLayer ghost;
        ghost.id = 1000;
        ghost.color = QColor(128, 134, 160);
        ghost.opacity = 0.45f;
        layers.push_back(ghost);
        const auto* doc = Document::instance();
        quint64 n = 100000;
        for (const auto& e : doc->elements()) {
            if (e->plate != doc->activePlate() || e->isImage()) continue;
            StageElement se;
            se.id = ++n;
            se.layer = ghost.id;
            for (lc::PolyView p : e->worldPaths()) {
                std::vector<QPointF> q;
                q.reserve(p.size());
                for (const lc::Pt& pt : p) q.push_back({pt.x, pt.y});
                se.paths.push_back(std::move(q));
            }
            els.push_back(std::move(se));
        }
    }
    if (m_res) {
        const lc::Pt o = ws::plateOffset(*m_res, m_plate);
        quint64 n = 0;
        for (const auto& part : m_res->parts) {
            if (part.plate != m_plate || part.paths.empty()) continue;
            StageElement se;
            se.id = ++n;
            se.layer = layerOf(part.layer);
            for (lc::PolyView p : part.paths) {
                std::vector<QPointF> q;
                q.reserve(p.size());
                for (const lc::Pt& pt : p) q.push_back({pt.x + o.x, pt.y + o.y});
                se.paths.push_back(std::move(q));
            }
            els.push_back(std::move(se));
        }
    }
    st->setLayers(std::move(layers));
    st->setElements(std::move(els));
    fitPreview();
}

void Workshop::fitPreview() {
    if (!m_stage) return;
    std::optional<lc::Box> box;
    if (m_res) {
        box = ws::partsBounds(*m_res, m_plate);
        if (box) {
            const lc::Pt o = ws::plateOffset(*m_res, m_plate);
            box = lc::Box{box->minX + o.x, box->minY + o.y, box->maxX + o.x, box->maxY + o.y};
        }
        if (box && m_tool == QLatin1String("rahmen") && !m_res->center) if (const auto mb = motifBox()) box = box->united(*mb);
    }
    const double w = m_stage->width(), h = m_stage->height();
    if (!box || w < 10 || h < 10) { m_stage->fit(); return; }
    const double bw = std::max(box->width(), 4.0), bh = std::max(box->height(), 4.0);
    const double z = std::min({(w * 0.86) / bw, (h * 0.86) / bh, 40.0});
    const lc::Pt c = box->center();
    m_stage->setZoom(z);
    m_stage->setPan(QPointF(w / 2 - c.x * z, h / 2 - c.y * z));
}

QVariantMap Workshop::apply() {
    if (m_timer.isActive()) recompute();
    if (!m_res || !m_info.value("ok").toBool())
        return {{"ok", false}, {"error", m_info.value("error", QStringLiteral("Nichts zum Übernehmen.")).toString()}};
    const ws::GenResult& r = *m_res;
    auto* doc = Document::instance();
    QStringList selectIds;
    int start = 0, plates = 0, count = 0;
    doc->commit([&](Document::State& st) {
        std::vector<lc::Layer>& layers = st.editLayers();
        const auto ensure = [&](const QString& name) -> QString {
            for (const lc::Layer& l : layers) if (l.name == name) return l.id;
            for (const lc::Layer& g : r.layers)
                if (g.name == name) { lc::Layer l = g; l.id = lc::newId(); layers.push_back(l); return l.id; }
            for (lc::Layer& f : lc::Document::defaultLayers()) if (f.name == name) { layers.push_back(f); return f.id; }
            return layers.front().id;
        };
        std::vector<lc::Element> raw = ws::toElements(r, ensure);
        const auto& existing = st.elements();
        const bool busy = std::any_of(existing.begin(), existing.end(), [&](const auto& e) { return e->plate == st.activePlate; });
        start = r.freshPlate && busy ? st.plateCount : st.activePlate;
        const bool onActive = start == st.activePlate;
        const int before = st.plateCount;
        const auto place = [&](int p) { return p == 0 ? start : onActive ? before + p - 1 : start + p; };
        int maxPlate = before - 1;
        Document::ElementList& list = st.editElements();
        for (lc::Element& e : raw) {
            e.plate = place(e.plate);
            maxPlate = std::max(maxPlate, e.plate);
            if (e.plate == start) selectIds.push_back(e.id);
            list.push_back(std::make_shared<const lc::Element>(std::move(e)));
            ++count;
        }
        plates = ws::plateCount(r);
        st.plateCount = maxPlate + 1;
        st.activePlate = start;
    });
    doc->select(selectIds);
    const QString where = plates > 1 ? QStringLiteral("ab Platte %1 auf %2 Platten").arg(start + 1).arg(plates) : QStringLiteral("auf Platte %1").arg(start + 1);
    Toast::instance()->show(QStringLiteral("%1 %2 ins Projekt gelegt, %3.").arg(count).arg(count == 1 ? QStringLiteral("Teil") : QStringLiteral("Teile"), where), QStringLiteral("ok"));
    return {{"ok", true}, {"count", count}, {"plates", plates}, {"firstPlate", start}};
}
