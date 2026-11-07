#include "PerfboardController.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QFutureWatcher>
#include <QSaveFile>
#include <QStandardPaths>
#include <QUrl>
#include <QUuid>
#include <QtConcurrent/QtConcurrentRun>
#include <algorithm>
#include <cmath>
#include "AppSettings.h"
#include "Shell.h"
#include "Toast.h"
#include "doc/Document.h"

namespace pcb = lumacut::pcb;
using pcb::GridPt;
using pcb::PerfDesign;

namespace {

QString de(double v, int digits) { return QString::number(v, 'f', digits).replace(QLatin1Char('.'), QLatin1Char(',')); }
QString localPath(const QString& p) { const QUrl u(p); return u.isLocalFile() ? u.toLocalFile() : p; }
QString autosavePath() {
    if (qEnvironmentVariableIsSet("LUMACUT_AUTOMATION_PORT")) return qEnvironmentVariable("LUMACUT_PERFBOARD_AUTOSAVE");
    const QString dir = QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation);
    return dir.isEmpty() ? QString() : dir + QStringLiteral("/lochraster-autosave.lumaraster");
}
double distToSegment(lumacut::Pt p, lumacut::Pt a, lumacut::Pt b) {
    const double ex = b.x - a.x, ey = b.y - a.y, l2 = ex * ex + ey * ey;
    const double t = l2 > 0 ? std::clamp(((p.x - a.x) * ex + (p.y - a.y) * ey) / l2, 0.0, 1.0) : 0;
    return std::hypot(a.x + t * ex - p.x, a.y + t * ey - p.y);
}

}  // namespace

PerfboardController::PerfboardController(QObject* parent) : QObject(parent) {
    m_design.board = pcb::PerfBoard::templates()[3];   // 50 × 70
    m_marksTimer.setSingleShot(true);
    m_saveTimer.setSingleShot(true);
    connect(&m_marksTimer, &QTimer::timeout, this, &PerfboardController::computeMarks);
    connect(&m_saveTimer, &QTimer::timeout, this, &PerfboardController::autosave);
    const QString as = autosavePath();
    if (!as.isEmpty() && QFile::exists(as)) {
        QFile f(as);
        if (f.open(QIODevice::ReadOnly)) {
            try { m_design = pcb::perfFromJson(f.readAll()); } catch (const std::exception&) {}
        }
    }
    afterChange();
    m_dirty = false;
}

// ---- Properties ----

QVariantMap PerfboardController::board() const {
    const pcb::PerfBoard& b = m_design.board;
    return {{"name", b.name}, {"width", b.width}, {"height", b.height}, {"pitch", b.pitch}, {"cols", b.cols}, {"rows", b.rows},
            {"padDia", b.padDia}, {"holeDia", b.holeDia}, {"mountDia", b.mountDia}, {"mountInset", b.mountInset}, {"edgeRows", b.edgeRows},
            {"rowLetters", b.rowLetters}, {"note", m_design.note},
            {"size", QStringLiteral("%1 × %2 mm").arg(de(b.width, 1), de(b.height, 1))},
            {"grid", QStringLiteral("%1 × %2 Löcher, A–%3, %4–%5").arg(b.cols).arg(b.rows).arg(pcb::PerfBoard::colName(b.cols - 1), b.rowName(0), b.rowName(b.rows - 1))}};
}
QVariantList PerfboardController::templates() const {
    QVariantList out;
    int i = 0;
    for (const pcb::PerfBoard& b : pcb::PerfBoard::templates())
        out << QVariantMap{{"value", i++}, {"label", QString(b.name).remove(QLatin1Char(' '))}, {"tip", QStringLiteral("%1 × %2 Löcher").arg(b.cols).arg(b.rows)}};
    return out;
}
QVariantList PerfboardController::designTemplates() const {
    QVariantList out;
    for (const pcb::PerfTemplate& t : pcb::perfTemplates()) out << QVariantMap{{"id", t.id}, {"name", t.name}};
    return out;
}
bool PerfboardController::openTemplate(const QString& id) {
    try {
        PerfDesign d = pcb::loadPerfTemplate(id);
        edit([&](PerfDesign& x) { x = std::move(d); });
    } catch (const std::exception& e) {
        Toast::instance()->show(QString::fromUtf8(e.what()), QStringLiteral("bad"));
        return false;
    }
    m_path.clear();
    m_selKind = 0;
    m_assist = -1;
    emit changed();
    emit selectionChanged();
    return true;
}
QVariantList PerfboardController::library() const {
    QVariantList out;
    for (const pcb::PartDef& d : pcb::partLibrary())
        out << QVariantMap{{"id", d.id}, {"name", d.name}, {"category", d.category}, {"prefix", d.prefix}, {"value", d.value}, {"hint", d.hint}, {"pins", int(d.pins.size())}};
    return out;
}
void PerfboardController::setTool(const QString& t) {
    if (t == m_tool) return;
    m_tool = t;
    m_wireStart.reset();
    setGhost({});
    emit toolChanged();
}
void PerfboardController::setWireSolder(bool v) { if (v != m_wireSolder) { m_wireSolder = v; emit toolChanged(); } }
void PerfboardController::setViewBelow(bool v) { if (v != m_viewBelow) { m_viewBelow = v; emit viewChanged(); } }
void PerfboardController::setShowMarks(bool v) { if (v != m_showMarks) { m_showMarks = v; emit viewChanged(); } }
QString PerfboardController::hint() const {
    if (m_tool == QLatin1String("part")) {
        const pcb::PartDef* d = pcb::findPart(m_partId);
        return QStringLiteral("%1: auf ein Loch klicken setzt Pin 1. R dreht, Esc beendet.").arg(d ? d->name : m_partId);
    }
    if (m_tool == QLatin1String("wire"))
        return m_wireStart ? QStringLiteral("Zielloch klicken. Umschalt führt erst senkrecht. Esc beendet.")
                           : QStringLiteral("Startloch klicken. Verbindungen laufen rechtwinklig von Loch zu Loch.");
    if (m_tool == QLatin1String("text")) return QStringLiteral("Klicken, wo die Beschriftung stehen soll. Am Rand bleibt sie ganz.");
    return {};
}
QVariantMap PerfboardController::selection() const {
    const PerfDesign& d = m_design;
    if (m_selKind == 1 && m_selIndex >= 0 && m_selIndex < int(d.parts.size())) {
        const pcb::Placed& p = d.parts[size_t(m_selIndex)];
        const pcb::PartDef* def = pcb::findPart(p.partId);
        QStringList pins;
        if (def) for (const GridPt& g : pcb::pinsOf(p, *def)) pins << d.board.holeName(g);
        return {{"kind", "part"}, {"index", m_selIndex}, {"ref", p.ref}, {"value", p.value}, {"name", def ? def->name : p.partId},
                {"hint", def ? def->hint : QString()}, {"rot", p.rot * 90}, {"pins", pins.join(QStringLiteral(", "))}};
    }
    if (m_selKind == 2 && m_selIndex >= 0 && m_selIndex < int(d.wires.size())) {
        const pcb::Wire& w = d.wires[size_t(m_selIndex)];
        return {{"kind", "wire"}, {"index", m_selIndex}, {"solder", w.solder}, {"net", w.net}, {"thick", pcb::isThick(w)},
                {"from", d.board.holeName(w.pts.front())}, {"to", d.board.holeName(w.pts.back())}};
    }
    if (m_selKind == 3 && m_selIndex >= 0 && m_selIndex < int(d.labels.size())) {
        const pcb::Label& l = d.labels[size_t(m_selIndex)];
        return {{"kind", "label"}, {"index", m_selIndex}, {"text", l.text}, {"height", l.heightMm}, {"solder", l.solder}};
    }
    return {{"kind", "none"}};
}
QVariantList PerfboardController::parts() const {
    QVariantList out;
    for (size_t i = 0; i < m_design.parts.size(); ++i) {
        const pcb::Placed& p = m_design.parts[i];
        const pcb::PartDef* def = pcb::findPart(p.partId);
        const auto box = def ? pcb::bodyBox(p, *def, m_design.board) : std::nullopt;
        out << QVariantMap{{"index", int(i)}, {"ref", p.ref}, {"value", p.value}, {"name", def ? def->name : p.partId},
                           {"x", box ? box->center().x : 0.0}, {"y", box ? box->center().y : 0.0}, {"at", m_design.board.holeName(p.at)}};
    }
    return out;
}
int PerfboardController::badCount() const {
    int n = 0;
    for (const QVariant& c : m_checks) if (c.toMap().value("tone") == QLatin1String("bad")) ++n;
    return n;
}
QVariantList PerfboardController::bomRows() const {
    QVariantList out;
    for (const pcb::BomRow& r : pcb::bom(m_design))
        out << QVariantMap{{"refs", r.refs.join(QStringLiteral(", "))}, {"value", r.value}, {"part", r.part}, {"count", r.count}};
    return out;
}
QVariantList PerfboardController::assistItems() const {
    QVariantList out;
    const auto order = pcb::assemblyOrder(m_design);
    for (size_t k = 0; k < order.size(); ++k) {
        const pcb::Placed& p = m_design.parts[size_t(order[k])];
        const pcb::PartDef* def = pcb::findPart(p.partId);
        out << QVariantMap{{"ref", p.ref}, {"value", p.value}, {"name", def ? def->name : p.partId}, {"hint", def ? def->hint : QString()},
                           {"at", m_design.board.holeName(p.at)}, {"done", k < m_done.size() && m_done[k]}};
    }
    return out;
}
int PerfboardController::assistPart() const {
    if (m_assist < 0) return -1;
    const auto order = pcb::assemblyOrder(m_design);
    return m_assist < int(order.size()) ? order[size_t(m_assist)] : -1;
}
QVariantMap PerfboardController::options() const {
    return {{"holeNumbers", m_design.holeNumbers}, {"markRefs", m_design.markRefs}, {"markValues", m_design.markValues},
            {"beamMm", m_opt.beamMm}, {"padClearMm", m_opt.padClearMm}, {"textMm", m_opt.textMm}, {"power", m_power}, {"speed", m_speed},
            {"minText", pcb::minTextHeight(m_opt.beamMm)}, {"textLost", m_marks ? m_marks->textLostShare : 0.0}};
}
double PerfboardController::bedX() const { return AppSettings::instance()->value(QStringLiteral("perfboard/x"), 185.0).toDouble(); }
double PerfboardController::bedY() const { return AppSettings::instance()->value(QStringLiteral("perfboard/y"), 197.5).toDouble(); }

// ---- Editing ----

QString PerfboardController::newItemId() { return QUuid::createUuid().toString(QUuid::WithoutBraces).left(8); }

void PerfboardController::edit(const std::function<void(PerfDesign&)>& fn) {
    m_past.push_back(m_design);
    if (m_past.size() > 200) m_past.erase(m_past.begin());
    m_future.clear();
    fn(m_design);
    m_dirty = true;
    afterChange();
}
void PerfboardController::afterChange() {
    ++m_revision;
    if (m_selKind == 1 && m_selIndex >= int(m_design.parts.size())) m_selKind = 0;
    if (m_selKind == 2 && m_selIndex >= int(m_design.wires.size())) m_selKind = 0;
    if (m_selKind == 3 && m_selIndex >= int(m_design.labels.size())) m_selKind = 0;
    if (m_done.size() != m_design.parts.size()) m_done.assign(m_design.parts.size(), false);
    m_checks.clear();
    for (const pcb::PerfCheck& c : pcb::perfChecks(m_design, m_opt, lumacut::Pt{bedX(), bedY()}))
        m_checks << QVariantMap{{"id", c.id}, {"tone", c.tone == pcb::PerfTone::Bad ? "bad" : c.tone == pcb::PerfTone::Warn ? "warn" : "info"}, {"text", c.text}};
    if (m_marks && m_marks->textLostShare > 0.3)
        m_checks << QVariantMap{{"id", "text-lost"}, {"tone", "warn"},
                                {"text", QStringLiteral("%1 % der Beschriftung liegt über Pads und wird ausgespart. Freie Beschriftung an den Rand setzen.")
                                             .arg(std::lround(m_marks->textLostShare * 100))}};
    emit changed();
    emit selectionChanged();
    emit assistChanged();
    m_marksTimer.start(60);
    if (m_dirty) m_saveTimer.start(1500);
}
void PerfboardController::computeMarks() {
    if (m_running) { m_again = true; return; }
    m_running = true;
    m_again = false;
    emit marksChanged();
    const PerfDesign d = m_design;
    const pcb::MarkOptions o = m_opt;
    auto* w = new QFutureWatcher<std::shared_ptr<const pcb::PerfMarks>>(this);
    connect(w, &QFutureWatcherBase::finished, this, [this, w] {
        m_marks = w->result();
        w->deleteLater();
        m_running = false;
        if (m_again) { computeMarks(); return; }
        // The text check needs the marks: refresh the checks without a new undo step.
        {
            QVariantList keep;
            for (const QVariant& c : m_checks) if (c.toMap().value("id") != QLatin1String("text-lost")) keep << c;
            m_checks = keep;
            if (m_marks->textLostShare > 0.3)
                m_checks << QVariantMap{{"id", "text-lost"}, {"tone", "warn"},
                                        {"text", QStringLiteral("%1 % der Beschriftung liegt über Pads und wird ausgespart. Freie Beschriftung an den Rand setzen.")
                                                     .arg(std::lround(m_marks->textLostShare * 100))}};
        }
        emit marksChanged();
        emit changed();
    });
    w->setFuture(QtConcurrent::run([d, o]() { return std::make_shared<const pcb::PerfMarks>(pcb::buildMarks(d, o)); }));
}
void PerfboardController::autosave() {
    const QString p = autosavePath();
    if (p.isEmpty()) return;
    QDir().mkpath(QFileInfo(p).absolutePath());
    QSaveFile f(p);
    if (f.open(QIODevice::WriteOnly)) { f.write(pcb::perfToJson(m_design)); f.commit(); }
}

void PerfboardController::newDesign(int templateIndex) {
    const auto t = pcb::PerfBoard::templates();
    edit([&](PerfDesign& d) {
        d = PerfDesign{};
        if (templateIndex >= 0 && templateIndex < int(t.size())) d.board = t[size_t(templateIndex)];
    });
    m_path.clear();
    m_selKind = 0;
    m_assist = -1;
    emit selectionChanged();
}
void PerfboardController::setTemplate(int templateIndex) {
    const auto t = pcb::PerfBoard::templates();
    if (templateIndex < 0 || templateIndex >= int(t.size())) return;
    edit([&](PerfDesign& d) { d.board = t[size_t(templateIndex)]; });
}
void PerfboardController::setBoard(const QString& key, const QVariant& v) {
    edit([&](PerfDesign& d) {
        pcb::PerfBoard& b = d.board;
        if (key == QLatin1String("width")) b.width = std::clamp(v.toDouble(), 10.0, 300.0);
        else if (key == QLatin1String("height")) b.height = std::clamp(v.toDouble(), 10.0, 300.0);
        else if (key == QLatin1String("cols")) b.cols = std::clamp(v.toInt(), 2, 120);
        else if (key == QLatin1String("rows")) b.rows = std::clamp(v.toInt(), 2, 120);
        else if (key == QLatin1String("pitch")) b.pitch = std::clamp(v.toDouble(), 1.0, 5.08);
        else if (key == QLatin1String("padDia")) b.padDia = std::clamp(v.toDouble(), 0.5, b.pitch - 0.2);
        else if (key == QLatin1String("holeDia")) b.holeDia = std::clamp(v.toDouble(), 0.3, b.padDia);
        else if (key == QLatin1String("mountDia")) b.mountDia = std::clamp(v.toDouble(), 0.0, 5.0);
        else if (key == QLatin1String("mountInset")) b.mountInset = std::clamp(v.toDouble(), 0.0, 15.0);
        else if (key == QLatin1String("edgeRows")) b.edgeRows = v.toBool();
        b.name = QStringLiteral("Eigene %1 × %2").arg(b.width).arg(b.height);
    });
}
void PerfboardController::pickPart(const QString& id) {
    if (!pcb::findPart(id)) return;
    m_partId = id;
    m_ghostRot = 0;
    m_tool = QStringLiteral("part");
    m_wireStart.reset();
    emit toolChanged();
}
QString PerfboardController::placePart(const QString& id, int c, int r, int rot) {
    const pcb::PartDef* def = pcb::findPart(id);
    if (!def) return {};
    QString ref;
    edit([&](PerfDesign& d) {
        ref = pcb::nextRef(d, def->prefix);
        d.parts.push_back({newItemId(), id, ref, def->value, {c, r}, ((rot % 4) + 4) % 4});
    });
    m_selKind = 1;
    m_selIndex = int(m_design.parts.size()) - 1;
    emit selectionChanged();
    return ref;
}
void PerfboardController::addWire(int c1, int r1, int c2, int r2, bool solder, bool verticalFirst) {
    if (c1 == c2 && r1 == r2) return;
    edit([&](PerfDesign& d) { d.wires.push_back({newItemId(), solder, 0, {}, pcb::route({c1, r1}, {c2, r2}, verticalFirst)}); });
    m_selKind = 2;
    m_selIndex = int(m_design.wires.size()) - 1;
    emit selectionChanged();
}
void PerfboardController::addLabel(const QString& text, double x, double y) {
    edit([&](PerfDesign& d) { d.labels.push_back({newItemId(), text, {x, y}, std::max(1.5, pcb::minTextHeight(m_opt.beamMm)), m_viewBelow}); });
    m_selKind = 3;
    m_selIndex = int(m_design.labels.size()) - 1;
    emit selectionChanged();
}
void PerfboardController::select(int kind, int index) {
    m_selKind = index >= 0 ? kind : 0;
    m_selIndex = index;
    emit selectionChanged();
}
void PerfboardController::selectRef(const QString& ref) {
    for (size_t i = 0; i < m_design.parts.size(); ++i) if (m_design.parts[i].ref == ref) { select(1, int(i)); return; }
}
void PerfboardController::moveSelected(int dc, int dr) {
    if (!dc && !dr) return;
    if (m_selKind == 1) edit([&](PerfDesign& d) { auto& p = d.parts[size_t(m_selIndex)]; p.at = {p.at.c + dc, p.at.r + dr}; });
    else if (m_selKind == 2) edit([&](PerfDesign& d) { for (GridPt& g : d.wires[size_t(m_selIndex)].pts) g = {g.c + dc, g.r + dr}; });
    else if (m_selKind == 3) edit([&](PerfDesign& d) { auto& l = d.labels[size_t(m_selIndex)]; l.at.x += dc * d.board.pitch; l.at.y += dr * d.board.pitch; });
}
void PerfboardController::rotateSelected() {
    if (m_selKind == 1) edit([&](PerfDesign& d) { auto& p = d.parts[size_t(m_selIndex)]; p.rot = (p.rot + 1) % 4; });
}
void PerfboardController::rotateGhostOrSelection() {
    if (m_tool == QLatin1String("part")) {
        m_ghostRot = (m_ghostRot + 1) % 4;
        Ghost g = m_ghost;
        g.rot = m_ghostRot;
        setGhost(g);
    } else rotateSelected();
}
void PerfboardController::deleteSelected() {
    if (m_selKind == 1) edit([&](PerfDesign& d) { d.parts.erase(d.parts.begin() + m_selIndex); });
    else if (m_selKind == 2) edit([&](PerfDesign& d) { d.wires.erase(d.wires.begin() + m_selIndex); });
    else if (m_selKind == 3) edit([&](PerfDesign& d) { d.labels.erase(d.labels.begin() + m_selIndex); });
    else return;
    select(0, -1);
}
void PerfboardController::setSelValue(const QString& key, const QVariant& v) {
    if (m_selKind == 1) edit([&](PerfDesign& d) {
        auto& p = d.parts[size_t(m_selIndex)];
        if (key == QLatin1String("ref")) p.ref = v.toString().trimmed();
        else if (key == QLatin1String("value")) p.value = v.toString().trimmed();
    });
    else if (m_selKind == 2 && key == QLatin1String("solder")) edit([&](PerfDesign& d) { d.wires[size_t(m_selIndex)].solder = v.toBool(); });
    else if (m_selKind == 3) edit([&](PerfDesign& d) {
        auto& l = d.labels[size_t(m_selIndex)];
        if (key == QLatin1String("text")) l.text = v.toString();
        else if (key == QLatin1String("height")) l.heightMm = std::clamp(v.toDouble(), 0.3, 20.0);
        else if (key == QLatin1String("solder")) l.solder = v.toBool();
    });
}
void PerfboardController::undo() {
    if (m_past.empty()) return;
    m_future.push_back(m_design);
    m_design = m_past.back();
    m_past.pop_back();
    m_dirty = true;
    afterChange();
}
void PerfboardController::redo() {
    if (m_future.empty()) return;
    m_past.push_back(m_design);
    m_design = m_future.back();
    m_future.pop_back();
    m_dirty = true;
    afterChange();
}
void PerfboardController::setOption(const QString& key, const QVariant& v) {
    if (key == QLatin1String("holeNumbers")) edit([&](PerfDesign& d) { d.holeNumbers = v.toBool(); });
    else if (key == QLatin1String("markRefs")) edit([&](PerfDesign& d) { d.markRefs = v.toBool(); });
    else if (key == QLatin1String("markValues")) edit([&](PerfDesign& d) { d.markValues = v.toBool(); });
    else {
        if (key == QLatin1String("beamMm")) m_opt.beamMm = std::clamp(v.toDouble(), 0.03, 1.0);
        else if (key == QLatin1String("padClearMm")) m_opt.padClearMm = std::clamp(v.toDouble(), 0.05, 1.0);
        else if (key == QLatin1String("textMm")) m_opt.textMm = std::clamp(v.toDouble(), 0.5, 5.0);
        else if (key == QLatin1String("power")) m_power = std::clamp(v.toDouble(), lumacut::Limits::MIN_RELIABLE_POWER_PCT, 100.0);
        else if (key == QLatin1String("speed")) m_speed = std::clamp(v.toDouble(), 100.0, 12000.0);
        else return;
        afterChange();
    }
}
void PerfboardController::setBed(double x, double y) {
    AppSettings::instance()->setValue(QStringLiteral("perfboard/x"), x);
    AppSettings::instance()->setValue(QStringLiteral("perfboard/y"), y);
    emit bedChanged();
    afterChange();
}

// ---- Stage input ----

void PerfboardController::setGhost(Ghost g) {
    m_ghost = std::move(g);
    emit ghostChanged();
}
void PerfboardController::hover(std::optional<GridPt> g, lumacut::Pt, bool shift) {
    if (m_tool == QLatin1String("part") && g) setGhost({true, m_partId, *g, m_ghostRot, false, {}});
    else if (m_tool == QLatin1String("wire") && m_wireStart && g) setGhost({true, {}, {}, 0, true, pcb::route(*m_wireStart, *g, shift)});
    else if (m_ghost.on) setGhost({});
}
void PerfboardController::press(std::optional<GridPt> g, lumacut::Pt p, bool shift) {
    const PerfDesign& d = m_design;
    if (m_tool == QLatin1String("part")) { if (g) placePart(m_partId, g->c, g->r, m_ghostRot); return; }
    if (m_tool == QLatin1String("wire")) {
        if (!g) return;
        if (!m_wireStart) { m_wireStart = g; emit toolChanged(); return; }
        if (!(*g == *m_wireStart)) addWire(m_wireStart->c, m_wireStart->r, g->c, g->r, m_wireSolder, shift);
        m_wireStart = g;
        emit toolChanged();
        return;
    }
    if (m_tool == QLatin1String("text")) {
        const lumacut::Pt at = g ? d.board.hole(*g) : p;
        addLabel(QStringLiteral("Text"), at.x, at.y);
        setTool(QStringLiteral("select"));
        return;
    }
    // Select: parts first (a pin or the body), then connections, then labels.
    for (int i = int(d.parts.size()) - 1; i >= 0; --i) {
        const pcb::PartDef* def = pcb::findPart(d.parts[size_t(i)].partId);
        if (!def) continue;
        bool hit = false;
        if (g) for (const GridPt& q : pcb::pinsOf(d.parts[size_t(i)], *def)) hit |= q == *g;
        if (const auto box = pcb::bodyBox(d.parts[size_t(i)], *def, d.board); box && box->contains(p)) hit = true;
        if (hit) { select(1, i); m_dragFrom = g; m_drag = {}; return; }
    }
    for (int i = int(d.wires.size()) - 1; i >= 0; --i) {
        const auto& pts = d.wires[size_t(i)].pts;
        for (size_t k = 0; k + 1 < pts.size(); ++k)
            if (distToSegment(p, d.board.hole(pts[k]), d.board.hole(pts[k + 1])) < 0.7) { select(2, i); m_dragFrom = g; m_drag = {}; return; }
    }
    for (int i = int(d.labels.size()) - 1; i >= 0; --i) {
        const pcb::Label& l = d.labels[size_t(i)];
        if (std::abs(p.x - l.at.x) < std::max(1.0, l.heightMm * 0.35 * l.text.size()) && std::abs(p.y - l.at.y) < l.heightMm) { select(3, i); m_dragFrom = g; m_drag = {}; return; }
    }
    select(0, -1);
}
void PerfboardController::dragTo(std::optional<GridPt> g) {
    if (!m_dragFrom || !g || m_selKind == 0) return;
    const GridPt off{g->c - m_dragFrom->c, g->r - m_dragFrom->r};
    if (off == m_drag) return;
    m_drag = off;
    emit ghostChanged();
}
void PerfboardController::release() {
    const GridPt off = m_drag;
    m_dragFrom.reset();
    m_drag = {};
    if (off.c || off.r) moveSelected(off.c, off.r);
    else emit ghostChanged();
}
void PerfboardController::escape() {
    if (m_wireStart) { m_wireStart.reset(); setGhost({}); emit toolChanged(); return; }
    if (m_tool != QLatin1String("select")) { setTool(QStringLiteral("select")); return; }
    select(0, -1);
}

// ---- Assistant ----

void PerfboardController::startAssist() {
    if (m_design.parts.empty()) return;
    m_done.assign(m_design.parts.size(), false);
    m_assist = 0;
    emit assistChanged();
    emit ghostChanged();
}
void PerfboardController::assistGo(int step) {
    if (m_assist < 0) return;
    if (step >= int(m_design.parts.size())) {
        m_assist = -1;
        Toast::instance()->show(QStringLiteral("Alle Bauteile bestückt. Vor dem Einschalten Lötstellen und Polarität prüfen."), QStringLiteral("ok"));
    } else m_assist = std::max(0, step);
    emit assistChanged();
    emit ghostChanged();
}
void PerfboardController::stopAssist() { m_assist = -1; emit assistChanged(); emit ghostChanged(); }
void PerfboardController::toggleDone(int step) {
    if (step < 0 || step >= int(m_done.size())) return;
    m_done[size_t(step)] = !m_done[size_t(step)];
    emit assistChanged();
}

// ---- Files ----

QString PerfboardController::suggestedName(const QString& ext) const {
    const QString base = m_path.isEmpty() ? QDir::homePath() + QLatin1Char('/') + m_design.title : QFileInfo(m_path).absolutePath() + QLatin1Char('/') + QFileInfo(m_path).completeBaseName();
    return base + QLatin1Char('.') + ext;
}
bool PerfboardController::save(const QString& pathIn) {
    QString path = localPath(pathIn);
    if (!path.endsWith(QLatin1String(".lumaraster"), Qt::CaseInsensitive)) path += QStringLiteral(".lumaraster");
    QSaveFile f(path);
    if (!f.open(QIODevice::WriteOnly) || f.write(pcb::perfToJson(m_design)) < 0 || !f.commit()) {
        Toast::instance()->show(QStringLiteral("Speichern ging nicht: %1. Anderen Ordner wählen.").arg(f.errorString()), QStringLiteral("bad"));
        return false;
    }
    m_path = path;
    m_dirty = false;
    emit changed();
    Toast::instance()->show(QStringLiteral("Gespeichert: %1").arg(QFileInfo(path).fileName()), QStringLiteral("ok"));
    return true;
}
bool PerfboardController::open(const QString& pathIn) {
    const QString path = localPath(pathIn);
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly)) { Toast::instance()->show(QStringLiteral("%1 lässt sich nicht öffnen.").arg(QFileInfo(path).fileName()), QStringLiteral("bad")); return false; }
    try {
        PerfDesign d = pcb::perfFromJson(f.readAll());
        edit([&](PerfDesign& x) { x = std::move(d); });
    } catch (const std::exception& e) {
        Toast::instance()->show(QString::fromUtf8(e.what()), QStringLiteral("bad"));
        return false;
    }
    m_path = path;
    m_dirty = false;
    m_selKind = 0;
    m_assist = -1;
    emit changed();
    emit selectionChanged();
    return true;
}
bool PerfboardController::exportTo(const QString& pathIn, const QString& format) {
    const QString path = localPath(pathIn);
    QByteArray data;
    if (format == QLatin1String("csv")) data = pcb::bomCsv(m_design);
    else if (format == QLatin1String("svg")) data = pcb::assemblySvg(m_design, m_viewBelow);
    else data = pcb::assemblyPng(m_design, 12, m_viewBelow);
    QSaveFile f(path);
    if (!f.open(QIODevice::WriteOnly) || f.write(data) < 0 || !f.commit()) {
        Toast::instance()->show(QStringLiteral("Export ging nicht: %1.").arg(f.errorString()), QStringLiteral("bad"));
        return false;
    }
    Toast::instance()->show(QStringLiteral("Exportiert: %1").arg(QFileInfo(path).fileName()), QStringLiteral("ok"));
    return true;
}

// ---- Into the project ----

void PerfboardController::toProject() {
    if (badCount() > 0) {
        Confirm::instance()->askNative({{"title", QStringLiteral("Trotz Problemen übernehmen?")},
                                        {"body", QStringLiteral("Die Prüfung meldet Probleme, etwa einen Kurzschluss oder ein doppelt belegtes Loch.")},
                                        {"okLabel", QStringLiteral("Trotzdem übernehmen")}},
                                       [this](bool yes) { if (yes) place(); });
        return;
    }
    place();
}
void PerfboardController::place() {
    auto* doc = Document::instance();
    const pcb::PerfMarks marks = pcb::buildMarks(m_design, m_opt);
    if (marks.component.empty() && marks.solder.empty()) {
        Toast::instance()->show(QStringLiteral("Es gibt noch nichts zu markieren. Erst Bauteile oder Verbindungen setzen."), QStringLiteral("warn"));
        return;
    }
    const auto onlyOurs = [doc](int p) {
        bool any = false;
        for (const Document::ElementPtr& e : doc->elements()) {
            if (e->plate != p) continue;
            if (e->kind != QLatin1String("Lochraster")) return false;
            any = true;
        }
        return any;
    };
    int top, bottom;
    if (m_plateTop >= 0 && m_plateBottom >= 0 && m_plateBottom < doc->plateCount() && onlyOurs(m_plateTop) && onlyOurs(m_plateBottom)) {
        top = m_plateTop;
        bottom = m_plateBottom;
    } else if (doc->empty()) {
        top = 0;
        bottom = 1;
    } else {
        top = doc->plateCount();
        bottom = top + 1;
    }
    QStringList ids;
    const lumacut::Pt centre{bedX(), bedY()};
    doc->commit([&](Document::State& s) {
        std::vector<lumacut::Element> els = pcb::perfElements(s.editLayers(), marks, m_design, top, bottom, centre, m_power, m_speed);
        auto& list = s.editElements();
        std::erase_if(list, [&](const Document::ElementPtr& e) { return (e->plate == top || e->plate == bottom) && e->kind == QLatin1String("Lochraster"); });
        for (lumacut::Element& e : els) { if (e.plate == top) ids << e.id; list.push_back(std::make_shared<const lumacut::Element>(std::move(e))); }
        s.plateCount = std::max(s.plateCount, bottom + 1);
        s.activePlate = top;
    });
    doc->select(ids);
    m_plateTop = top;
    m_plateBottom = bottom;
    Toast::instance()->show(QStringLiteral("Bestückungsseite auf Platte %1, Lötseite gespiegelt auf Platte %2. Nur markieren, nichts schneiden.").arg(top + 1).arg(bottom + 1),
                            QStringLiteral("ok"));
    Shell::instance()->navigate(QStringLiteral("start"));
}

QVariantMap PerfboardController::info() const {
    QStringList refs, checks;
    for (const pcb::Placed& p : m_design.parts) refs << p.ref;
    for (const QVariant& c : m_checks) checks << c.toMap().value("id").toString();
    QVariantMap m{{"parts", int(m_design.parts.size())}, {"wires", int(m_design.wires.size())}, {"labels", int(m_design.labels.size())},
                  {"refs", refs}, {"checks", checks}, {"bom", int(pcb::bom(m_design).size())}, {"revision", m_revision}, {"busy", m_running},
                  {"cols", m_design.board.cols}, {"rows", m_design.board.rows}, {"width", m_design.board.width}, {"height", m_design.board.height},
                  {"tool", m_tool}, {"viewBelow", m_viewBelow}, {"selKind", m_selKind}, {"selIndex", m_selIndex}, {"assist", m_assist}};
    if (m_marks) {
        m["componentLines"] = int(m_marks->component.size());
        m["solderLines"] = int(m_marks->solder.size());
        m["textLost"] = m_marks->textLostShare;
    }
    return m;
}
