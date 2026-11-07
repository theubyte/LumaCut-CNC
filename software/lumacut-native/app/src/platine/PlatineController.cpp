#include "PlatineController.h"

#include <QFile>
#include <QFileInfo>
#include <QFutureWatcher>
#include <QUrl>
#include <QtConcurrent/QtConcurrentRun>
#include <algorithm>
#include "Shell.h"
#include "Toast.h"
#include "core/parallel.h"
#include "core/toolpath.h"
#include "doc/Document.h"

namespace pcb = lumacut::pcb;
using pcb::LayerKind;
using pcb::ProcessKey;
using pcb::ResistMethod;
using pcb::Side;
using pcb::Stage;

namespace {

const char* kProcessKeys[pcb::kProcessCount] = {"resist", "drill", "fiducial", "outline", "mask", "silk"};
int processIndex(const QString& key) {
    for (int i = 0; i < pcb::kProcessCount; ++i) if (key == QLatin1String(kProcessKeys[i])) return i;
    return -1;
}
QString de(double v, int digits) { return QString::number(v, 'f', digits).replace(QLatin1Char('.'), QLatin1Char(',')); }
QString stageKey(Stage s) { return s == Stage::Mask ? QStringLiteral("mask") : s == Stage::Silk ? QStringLiteral("silk") : QStringLiteral("resist"); }
QString methodKey(ResistMethod m) { return m == ResistMethod::Isolation ? QStringLiteral("isolation") : m == ResistMethod::Expose ? QStringLiteral("expose") : QStringLiteral("raster"); }
QString toneKey(pcb::Tone t) { return t == pcb::Tone::Bad ? QStringLiteral("bad") : t == pcb::Tone::Warn ? QStringLiteral("warn") : QStringLiteral("ok"); }

QString fileSummary(const pcb::PcbFile& f) {
    if (f.pending) return QStringLiteral("wird gelesen …");
    if (!f.error.isEmpty()) return QStringLiteral("Nicht lesbar");
    if (f.kind == LayerKind::Other) return QStringLiteral("–");
    if (f.drill) {
        const int n = int(f.drill->hits.size()), t = int(f.drill->tools.size());
        QString s = QStringLiteral("%1 Löcher, %2 Werkzeuge").arg(n).arg(t);
        if (!f.drill->slotHoles.empty()) s += QStringLiteral(", %1 Schlitze").arg(f.drill->slotHoles.size());
        return s;
    }
    if (f.gerber) {
        if (f.kind == LayerKind::Outline) return f.gerber->strokes.size() == 1 ? QStringLiteral("1 Linienzug") : QStringLiteral("%1 Linienzüge").arg(f.gerber->strokes.size());
        QString s = QStringLiteral("%1 mm²").arg(de(f.gerber->area, 0));
        if (!f.gerber->flashes.empty()) s += QStringLiteral(", %1 Pads").arg(f.gerber->flashes.size());
        return s;
    }
    return QStringLiteral("…");
}

}  // namespace

/** One worker run: what went in, what came out. */
struct PlatineController::Result {
    quint64 generation = 0;
    quint64 filesGeneration = 0;
    bool filesRun = false;
    std::vector<pcb::PcbFile> files;
    std::shared_ptr<const pcb::Board> board;
    std::shared_ptr<const pcb::Plan> plan;
    std::shared_ptr<const pcb::DesignFacts> facts;
    std::vector<double> secondsAtUnitSpeed;   // per plan layer, estimate * speed
};

static quint64 g_filesGeneration = 0;

PlatineController::PlatineController(QObject* parent) : QObject(parent) {
    m_debounce.setSingleShot(true);
    connect(&m_debounce, &QTimer::timeout, this, &PlatineController::run);
}

// ---- Properties ----

QVariantList PlatineController::files() const {
    QVariantList out;
    for (const pcb::PcbFile& f : m_files) {
        const QStringList w = f.gerber ? f.gerber->warnings : f.drill ? f.drill->warnings : QStringList();
        out << QVariantMap{{"name", f.name}, {"kind", pcb::layerKey(f.kind)}, {"label", pcb::layerLabel(f.kind)},
                           {"summary", fileSummary(f)}, {"error", f.error}, {"warnings", w}};
    }
    return out;
}
QVariantList PlatineController::kinds() const {
    QVariantList out;
    for (int i = 0; i < pcb::kLayerKindCount; ++i) out << QVariantMap{{"key", pcb::layerKey(LayerKind(i))}, {"label", pcb::layerLabel(LayerKind(i))}};
    return out;
}
QVariantMap PlatineController::boardInfo() const {
    if (!m_board) return {};
    const pcb::Board& b = *m_board;
    const auto sides = [](const std::optional<pcb::SideArt>* a) {
        QStringList s;
        if (a[0]) s << QStringLiteral("oben");
        if (a[1]) s << QStringLiteral("unten");
        return s.isEmpty() ? QStringLiteral("fehlt") : s.join(QStringLiteral(", "));
    };
    QString drills = QString::number(b.drills.size());
    if (!b.slotHoles.empty()) drills += QStringLiteral(" + %1 Schlitze").arg(b.slotHoles.size());
    return {{"size", QStringLiteral("%1 × %2 mm").arg(de(b.bounds.width(), 1), de(b.bounds.height(), 1))},
            {"copper", sides(b.copper)}, {"mask", sides(b.mask)}, {"silk", sides(b.silk)}, {"drills", drills},
            {"outline", b.outlineFromFile ? QStringLiteral("aus Datei") : QStringLiteral("geschätzt")},
            {"hasBottom", bool(b.copper[1])}, {"hasTop", bool(b.copper[0])}, {"drillCount", int(b.drills.size())},
            {"hasMask", bool(b.mask[int(m_settings.side)])}, {"hasSilk", bool(b.silk[int(m_settings.side)])}};
}
QStringList PlatineController::warnings() const {
    QStringList out;
    if (m_board) out << m_board->warnings;
    for (const pcb::PcbFile& f : m_files) {
        const QStringList w = f.gerber ? f.gerber->warnings : f.drill ? f.drill->warnings : QStringList();
        for (const QString& s : w) out << f.name + QStringLiteral(": ") + s;
        if (!f.error.isEmpty()) out << f.name + QStringLiteral(": nicht lesbar (") + f.error + QStringLiteral("). Neu exportieren.");
    }
    if (m_plan) out << m_plan->warnings;
    out.removeDuplicates();
    return out;
}
QVariantMap PlatineController::settings() const {
    const pcb::JobSettings& s = m_settings;
    return {{"side", s.side == Side::Bottom ? "bottom" : "top"}, {"mirror", s.mirror}, {"beamMm", s.beamMm}, {"overlapPct", s.overlapPct},
            {"resist", s.resist}, {"method", methodKey(s.method)}, {"passes", s.passes}, {"passSpacingMm", pcb::passSpacing(s)},
            {"isolationOffsetMm", s.isolationOffsetMm}, {"removeRest", s.removeRest}, {"drillMarks", s.drillMarks},
            {"drillStyle", s.drillCross ? "cross" : "dot"}, {"drillMarkMm", s.drillMarkMm}, {"mask", s.mask}, {"silk", s.silk},
            {"fiducials", s.fiducials}, {"fiducialDiaMm", s.fiducialDiaMm}, {"fiducialOffsetMm", s.fiducialOffsetMm},
            {"outlineMark", s.outlineMark}};
}
double PlatineController::interval() const { return pcb::lineInterval(m_settings.beamMm, m_settings.overlapPct); }
QString PlatineController::stage() const { return stageKey(m_stage); }
QVariantList PlatineController::stages() const {
    QVariantList out;
    for (Stage st : {Stage::Resist, Stage::Mask, Stage::Silk}) {
        const bool present = m_plan && std::any_of(m_plan->layers.begin(), m_plan->layers.end(), [st](const pcb::PlanLayer& l) { return l.stage == st; });
        if (present || st == Stage::Resist) out << QVariantMap{{"value", stageKey(st)}, {"label", pcb::stageLabel(st)}};
    }
    return out;
}
QVariantList PlatineController::jobLayers() const {
    QVariantList out;
    if (!m_plan) return out;
    QSet<int> seen;
    for (size_t i = 0; i < m_plan->layers.size(); ++i) {
        const pcb::PlanLayer& l = m_plan->layers[i];
        if (l.stage != m_stage || (l.key == ProcessKey::Outline && !m_settings.outlineMark)) continue;
        const int k = int(l.key);
        const double speed = m_settings.speed[k];
        const double secs = i < m_secondsAtUnitSpeed.size() ? m_secondsAtUnitSpeed[i] / std::max(1.0, speed) : 0;
        out << QVariantMap{{"key", QString::fromLatin1(kProcessKeys[k])}, {"name", l.name.mid(8)}, {"process", l.process},
                           {"power", m_settings.power[k]}, {"speed", speed}, {"time", lumacut::formatDuration(secs)},
                           {"first", !seen.contains(k)}, {"color", QStringLiteral("#%1").arg(qulonglong(l.color) & 0xFFFFFF, 6, 16, QLatin1Char('0'))}};
        seen.insert(k);
    }
    return out;
}
QString PlatineController::jobTime() const {
    if (!m_plan) return {};
    double total = 0;
    for (size_t i = 0; i < m_plan->layers.size() && i < m_secondsAtUnitSpeed.size(); ++i) {
        const pcb::PlanLayer& l = m_plan->layers[i];
        if (l.stage != m_stage || (l.key == ProcessKey::Outline && !m_settings.outlineMark)) continue;
        total += m_secondsAtUnitSpeed[i] / std::max(1.0, m_settings.speed[int(l.key)]);
    }
    return lumacut::formatDuration(total);
}
int PlatineController::badCount() const {
    int n = 0;
    for (const QVariant& c : m_checks) if (c.toMap().value("tone") == QLatin1String("bad")) ++n;
    return n;
}
QString PlatineController::jobSize() const {
    if (!m_plan) return {};
    return QStringLiteral("%1 × %2 mm").arg(de(m_plan->bounds.width(), 1), de(m_plan->bounds.height(), 1));
}
QVariantList PlatineController::viewLayers() const {
    QVariantList out;
    if (!m_board) return out;
    const auto has = [this](ProcessKey k) { return m_plan && std::any_of(m_plan->layers.begin(), m_plan->layers.end(), [k](const pcb::PlanLayer& l) { return l.key == k; }); };
    const auto row = [&](const char* key, const char* label, const char* color, bool present) {
        if (present) out << QVariantMap{{"key", key}, {"label", QString::fromUtf8(label)}, {"color", color}, {"shown", layerShown(QLatin1String(key))}};
    };
    row("copper", "Kupfer", "copper", bool(m_board->copperOf(m_settings.side)));
    row("resist", "Laserbahnen", "laser", has(ProcessKey::Resist));
    row("holes", "Bohrungen", "drill", !m_board->drills.empty());
    row("marks", "Bohrmarken", "mark", has(ProcessKey::Drill));
    row("fiducial", "Passmarken", "mark", has(ProcessKey::Fiducial));
    row("mask", "Lötstopp-Öffnungen", "mask", has(ProcessKey::Mask));
    row("silk", "Bestückungsdruck", "silk", has(ProcessKey::Silk));
    row("outline", "Umriss", "edge", true);
    return out;
}
QVariantList PlatineController::workflow() const {
    const bool film = m_settings.method == ResistMethod::Expose;
    QVariantList out;
    const auto step = [&](const QString& title, const QString& text, bool laser = false) { out << QVariantMap{{"title", title}, {"text", text}, {"laser", laser}}; };
    step(QStringLiteral("Zuschneiden"), QStringLiteral("Platine mit Zugabe sägen, nicht mit dem Laser. Die Passmarken liegen außerhalb des Umrisses."));
    step(QStringLiteral("Reinigen"), QStringLiteral("Kupfer mit Schleifvlies blank machen, mit Isopropanol entfetten, danach nicht mehr mit den Fingern berühren."));
    if (film) {
        step(QStringLiteral("Film auflaminieren"), QStringLiteral("Bei gedämpftem Licht ohne Blauanteil, nach Herstellerangabe."));
    } else {
        step(QStringLiteral("Lackieren"), QStringLiteral("Mehrere dünne Schichten matt schwarz, im Freien oder unter Absaugung. Trocknen lassen, eher länger: weicher Lack schmiert unter dem Strahl."));
    }
    step(QStringLiteral("Materialtest"), QStringLiteral("Auf einem Probestück mit demselben Lack. Leistung und Tempo hier eintragen."), true);
    step(QStringLiteral("Lasern"), QStringLiteral("Flach auflegen und fixieren, neu scannen, Höhe abtasten. Unter Starten mit der Go-Abfrage beginnen."), true);
    if (film) step(QStringLiteral("Entwickeln"), QStringLiteral("In Sodalösung nach Herstellerangabe, bis die unbelichteten Stellen ganz weg sind."));
    else step(QStringLiteral("Prüfen"), QStringLiteral("Mit der Lupe: wo der Lack weg ist, muss das Kupfer blank sein. Ruß vorsichtig abtupfen."));
    step(QStringLiteral("Ätzen"), QStringLiteral("Natriumpersulfat oder Eisen(III)-chlorid nach Herstellerangabe. Regelmäßig nachsehen, zu langes Ätzen frisst die Leiter von der Seite an."));
    step(QStringLiteral("Lack entfernen"), film ? QStringLiteral("Film nach Herstellerangabe strippen.") : QStringLiteral("Lack mit Aceton abwaschen."));
    step(QStringLiteral("Bohren"), QStringLiteral("An den geätzten Marken bohren. Der Laser bohrt nicht. Für eine zweite Seite die Passmarken durchbohren."));
    if (m_settings.mask) step(QStringLiteral("Lötstopp"), QStringLiteral("UV-Lack auftragen und aushärten, dann Arbeitsgang Lötstopp: legt die Pads frei. Vorher Probestück, neu scannen."), true);
    if (m_settings.silk) step(QStringLiteral("Bestückungsdruck"), QStringLiteral("Mit wenig Leistung in den Lack markieren. Vorher Probestück, Lage prüfen, neu scannen."), true);
    return out;
}
std::optional<pcb::Clearance> PlatineController::marker() const {
    if (!m_facts || !m_facts->clearance || m_facts->clearance->mm >= m_settings.beamMm * 1.5) return std::nullopt;
    return m_facts->clearance;
}

// ---- Actions ----

void PlatineController::setBusy(const QString& text) {
    if (text == m_busyText) return;
    m_busyText = text;
    emit busyChanged();
}

void PlatineController::loadExample() {
    m_files.clear();
    addFiles(pcb::exampleBoardFiles());
}

QStringList PlatineController::fileFilters() const {
    return {QStringLiteral("Gerber und Bohrdaten (*.zip *.gbr *.ger *.pho *.art *.gtl *.gbl *.gts *.gbs *.gto *.gbo *.gtp *.gbp *.gko *.gm1 *.gm2 *.gml *.drl *.xln *.exc *.txt *.nc *.cmp *.sol *.stc *.sts *.plc *.pls *.dim)"),
            QStringLiteral("Alle Dateien (*)")};
}

void PlatineController::loadPaths(const QStringList& paths) {
    QStringList local;
    for (const QString& p : paths) {
        const QUrl u(p);
        local << (u.isLocalFile() ? u.toLocalFile() : p);
    }
    if (local.isEmpty()) return;
    setBusy(QStringLiteral("Dateien werden gelesen …"));
    using Read = std::pair<std::vector<std::pair<QString, QByteArray>>, QString>;
    auto* watcher = new QFutureWatcher<Read>(this);
    connect(watcher, &QFutureWatcherBase::finished, this, [this, watcher] {
        Read r = watcher->result();
        watcher->deleteLater();
        setBusy({});
        if (!r.second.isEmpty()) { Toast::instance()->show(r.second, QStringLiteral("bad")); return; }
        if (r.first.empty()) { Toast::instance()->show(QStringLiteral("Darin sind keine Gerber- oder Bohrdateien. Andere Dateien wählen."), QStringLiteral("warn")); return; }
        addFiles(std::move(r.first));
    });
    watcher->setFuture(QtConcurrent::run([local]() -> Read {
        std::vector<std::pair<QString, QByteArray>> picked;
        for (const QString& p : local) {
            QFile f(p);
            if (!f.open(QIODevice::ReadOnly)) return {{}, QStringLiteral("%1 lässt sich nicht öffnen.").arg(QFileInfo(p).fileName())};
            if (f.size() > 200LL * 1024 * 1024) return {{}, QStringLiteral("%1 ist zu groß für eine Platine.").arg(QFileInfo(p).fileName())};
            picked.emplace_back(QFileInfo(p).fileName(), f.readAll());
        }
        try {
            return {pcb::unpackPcbInputs(picked), {}};
        } catch (const std::exception& e) {
            return {{}, QString::fromUtf8(e.what()) + QStringLiteral(" Datei neu exportieren.")};
        }
    }));
}

void PlatineController::addFiles(std::vector<std::pair<QString, QByteArray>> entries) {
    for (auto& [name, text] : entries) {
        std::erase_if(m_files, [&](const pcb::PcbFile& f) { return f.name == name; });
        pcb::PcbFile f;
        f.name = name;
        f.text = std::move(text);
        f.kind = LayerKind::Other;
        f.pending = 1;   // classified and parsed on the worker
        m_files.push_back(std::move(f));
    }
    emit filesChanged();
    schedule(true);
}

void PlatineController::removeFile(int index) {
    if (index < 0 || index >= int(m_files.size())) return;
    m_files.erase(m_files.begin() + index);
    emit filesChanged();
    schedule(true);
}

void PlatineController::setKind(int index, const QString& key) {
    if (index < 0 || index >= int(m_files.size())) return;
    pcb::PcbFile& f = m_files[size_t(index)];
    const LayerKind k = pcb::layerFromKey(key);
    if (k == f.kind && !f.pending) return;
    // Gerber stays parsed between Gerber kinds; a drill file parses differently.
    const bool keep = (k == LayerKind::Drill) == (f.kind == LayerKind::Drill) && k != LayerKind::Other && f.kind != LayerKind::Other
                      && f.error.isEmpty() && (f.gerber || f.drill);
    f.kind = k;
    if (!keep) { f.gerber.reset(); f.drill.reset(); f.error.clear(); f.pending = 2; }
    emit filesChanged();
    schedule(true);
}

void PlatineController::clear() {
    m_files.clear();
    m_board.reset();
    m_plan.reset();
    m_facts.reset();
    m_secondsAtUnitSpeed.clear();
    m_checks.clear();
    ++m_generation;
    ++g_filesGeneration;
    emit filesChanged();
    emit boardChanged();
    emit planChanged();
    emit viewChanged();
}

void PlatineController::set(const QString& key, const QVariant& v) {
    pcb::JobSettings& s = m_settings;
    bool geometry = true;
    if (key == QLatin1String("side")) {
        const Side side = v.toString() == QLatin1String("bottom") ? Side::Bottom : Side::Top;
        if (side == s.side) return;
        s.side = side;
        s.mirror = side == Side::Bottom;   // the side decides the mirroring, unless changed afterwards by hand
    }
    else if (key == QLatin1String("mirror")) { s.mirror = v.toBool(); geometry = false; }
    else if (key == QLatin1String("beamMm")) s.beamMm = std::clamp(v.toDouble(), 0.03, 1.0);
    else if (key == QLatin1String("overlapPct")) s.overlapPct = std::clamp(v.toDouble(), 0.0, 80.0);
    else if (key == QLatin1String("resist")) s.resist = v.toBool();
    else if (key == QLatin1String("method")) {
        const QString m = v.toString();
        s.method = m == QLatin1String("isolation") ? ResistMethod::Isolation : m == QLatin1String("expose") ? ResistMethod::Expose : ResistMethod::Raster;
    }
    else if (key == QLatin1String("passes")) s.passes = std::clamp(v.toInt(), 1, 20);
    else if (key == QLatin1String("passSpacingMm")) s.passSpacingMm = std::clamp(v.toDouble(), 0.03, 2.0);
    else if (key == QLatin1String("isolationOffsetMm")) s.isolationOffsetMm = std::clamp(v.toDouble(), 0.0, 2.0);
    else if (key == QLatin1String("removeRest")) s.removeRest = v.toBool();
    else if (key == QLatin1String("drillMarks")) s.drillMarks = v.toBool();
    else if (key == QLatin1String("drillStyle")) s.drillCross = v.toString() == QLatin1String("cross");
    else if (key == QLatin1String("drillMarkMm")) s.drillMarkMm = std::clamp(v.toDouble(), 0.1, 2.0);
    else if (key == QLatin1String("mask")) s.mask = v.toBool();
    else if (key == QLatin1String("silk")) s.silk = v.toBool();
    else if (key == QLatin1String("fiducials")) { const int n = v.toInt(); s.fiducials = n >= 4 ? 4 : n >= 2 ? 2 : 0; }
    else if (key == QLatin1String("fiducialDiaMm")) s.fiducialDiaMm = std::clamp(v.toDouble(), 0.3, 3.0);
    else if (key == QLatin1String("fiducialOffsetMm")) s.fiducialOffsetMm = std::clamp(v.toDouble(), 1.0, 20.0);
    else if (key == QLatin1String("outlineMark")) { s.outlineMark = v.toBool(); geometry = false; }
    else return;
    emit settingsChanged();
    if (geometry) schedule(false);
    else { refreshChecks(); emit planChanged(); emit viewChanged(); }
}

void PlatineController::setStage(const QString& st) {
    const Stage s = st == QLatin1String("mask") ? Stage::Mask : st == QLatin1String("silk") ? Stage::Silk : Stage::Resist;
    if (s == m_stage) return;
    m_stage = s;
    emit settingsChanged();
    emit planChanged();
}

void PlatineController::setProcessValue(const QString& process, const QString& field, double value) {
    const int k = processIndex(process);
    if (k < 0) return;
    if (field == QLatin1String("power")) m_settings.power[k] = std::clamp(value, lumacut::Limits::MIN_RELIABLE_POWER_PCT, lumacut::Limits::POWER_MAX);
    else if (field == QLatin1String("speed")) m_settings.speed[k] = std::clamp(value, 100.0, 12000.0);
    else return;
    emit settingsChanged();
    emit planChanged();
}

void PlatineController::toggleLayer(const QString& key) {
    if (m_hidden.contains(key)) m_hidden.remove(key);
    else m_hidden.insert(key);
    emit viewChanged();
}

// ---- Worker ----

void PlatineController::schedule(bool files) {
    ++m_generation;
    if (files) { m_filesDirty = true; ++g_filesGeneration; }
    if (m_running) { m_again = true; return; }
    m_debounce.start(files ? 0 : 120);
}

void PlatineController::run() {
    if (m_running) { m_again = true; return; }
    if (m_files.empty()) { clear(); return; }
    if (!m_filesDirty && !m_board) return;
    m_running = true;
    m_again = false;
    setBusy(m_filesDirty ? QStringLiteral("Platine wird gelesen …") : QStringLiteral("Bahnen werden gerechnet …"));
    auto in = std::make_shared<Result>();
    in->generation = m_generation;
    in->filesGeneration = g_filesGeneration;
    in->filesRun = m_filesDirty;
    in->files = m_files;
    in->board = m_filesDirty ? nullptr : m_board;
    const bool sameSide = m_facts && m_plan && !m_filesDirty && m_factsSide == m_settings.side;
    in->facts = sameSide ? m_facts : nullptr;
    m_filesDirty = false;
    const pcb::JobSettings s = m_settings;
    auto* watcher = new QFutureWatcher<std::shared_ptr<Result>>(this);
    connect(watcher, &QFutureWatcherBase::finished, this, [this, watcher] {
        auto r = watcher->result();
        watcher->deleteLater();
        finished(std::move(r));
    });
    watcher->setFuture(QtConcurrent::run([in, s]() -> std::shared_ptr<Result> {
        if (in->filesRun) {
            // Classify and parse what is new, all files at once on all cores.
            lumacut::parallelFor(std::ptrdiff_t(in->files.size()), [&](std::ptrdiff_t i) {
                pcb::PcbFile& f = in->files[size_t(i)];
                if (f.pending == 1) f = pcb::readPcbFile(f.name, f.text);
                else if (f.pending == 2) f = pcb::parseAs(f, f.kind);
            });
            auto b = pcb::buildBoard(in->files);
            in->board = b ? std::make_shared<const pcb::Board>(std::move(*b)) : nullptr;
        }
        if (in->board) {
            in->plan = std::make_shared<const pcb::Plan>(pcb::buildPlan(*in->board, s));
            if (!in->facts) in->facts = std::make_shared<const pcb::DesignFacts>(pcb::designFacts(*in->board, s.side));
            in->secondsAtUnitSpeed.resize(in->plan->layers.size());
            lumacut::parallelFor(std::ptrdiff_t(in->plan->layers.size()), [&](std::ptrdiff_t i) {
                const pcb::PlanLayer& l = in->plan->layers[size_t(i)];
                in->secondsAtUnitSpeed[size_t(i)] = pcb::estimateSeconds(l) * std::max(1.0, l.speed);
            });
        }
        return in;
    }));
}

void PlatineController::finished(std::shared_ptr<Result> r) {
    m_running = false;
    const bool filesCurrent = r->filesGeneration == g_filesGeneration;
    if (r->filesRun && filesCurrent) {
        m_files = std::move(r->files);
        m_board = r->board;
        emit filesChanged();
        emit boardChanged();
    }
    if (filesCurrent && r->generation == m_generation) {
        if (r->filesRun || r->board == m_board) {
            m_plan = r->plan;
            m_facts = r->facts;
            m_factsSide = m_settings.side;
            m_secondsAtUnitSpeed = std::move(r->secondsAtUnitSpeed);
            ++m_revision;
            refreshChecks();
            emit boardChanged();
            emit planChanged();
            emit viewChanged();
        }
        setBusy({});
        if (!m_board && !m_files.empty()) Toast::instance()->show(QStringLiteral("Keine Lage erkannt. Rechts neben der Datei die Lage wählen."), QStringLiteral("warn"));
        return;
    }
    // Something changed meanwhile: run again with the newest input.
    m_again = false;
    m_debounce.start(0);
}

void PlatineController::refreshChecks() {
    m_checks.clear();
    if (!m_plan || !m_facts) return;
    for (const pcb::DesignCheck& c : pcb::designChecks(*m_facts, m_settings, *m_plan, pcb::centeredOnBed(*m_plan)))
        m_checks << QVariantMap{{"id", c.id}, {"tone", toneKey(c.tone)}, {"title", c.title}, {"text", c.text}};
}

// ---- Into the project ----

void PlatineController::toProject() {
    if (!m_plan || m_plan->layers.empty() || busy()) return;
    if (badCount() > 0) {
        Confirm::instance()->askNative({{"title", QStringLiteral("Trotz Problemen übernehmen?")},
                                        {"body", QStringLiteral("Die Prüfung meldet Probleme, die das Ergebnis verderben können.")},
                                        {"okLabel", QStringLiteral("Trotzdem übernehmen")}},
                                       [this](bool yes) { if (yes) place(); });
        return;
    }
    place();
}

void PlatineController::place() {
    if (!m_plan) return;
    auto* doc = Document::instance();
    const int side = int(m_settings.side);
    const auto onlyPlatine = [doc](int p) {
        bool any = false;
        for (const Document::ElementPtr& e : doc->elements()) {
            if (e->plate != p) continue;
            if (e->kind != QLatin1String("Platine")) return false;
            any = true;
        }
        return any;
    };
    int target;
    if (m_plate[side] >= 0 && m_plate[side] < doc->plateCount() && onlyPlatine(m_plate[side])) target = m_plate[side];
    else if (doc->empty()) target = 0;
    else if (doc->plateSize(doc->activePlate()) == 0) target = doc->activePlate();
    else target = doc->plateCount();

    pcb::Plan plan = *m_plan;
    for (pcb::PlanLayer& l : plan.layers) { l.powerPct = m_settings.power[int(l.key)]; l.speed = m_settings.speed[int(l.key)]; }
    const lumacut::Pt origin = pcb::centeredOnBed(plan);
    QStringList ids;
    doc->commit([&](Document::State& s) {
        std::vector<lumacut::Element> els = pcb::planElements(s.editLayers(), plan, m_settings, m_stage, target, origin);
        auto& list = s.editElements();
        std::erase_if(list, [target](const Document::ElementPtr& e) { return e->plate == target && e->kind == QLatin1String("Platine"); });
        for (lumacut::Element& e : els) { ids << e.id; list.push_back(std::make_shared<const lumacut::Element>(std::move(e))); }
        s.plateCount = std::max(s.plateCount, target + 1);
        s.activePlate = target;
    });
    doc->select(ids);
    m_plate[side] = target;
    Toast::instance()->show(QStringLiteral("Platine liegt auf Platte %1. Ausgabe: %2.").arg(target + 1).arg(pcb::stageLabel(m_stage)), QStringLiteral("ok"));
    emit placed(target);
    Shell::instance()->navigate(QStringLiteral("start"));
}

QVariantMap PlatineController::info() const {
    QVariantMap m{{"files", int(m_files.size())}, {"busy", busy()}, {"revision", m_revision}, {"hasBoard", hasBoard()}};
    QStringList kinds;
    for (const pcb::PcbFile& f : m_files) kinds << pcb::layerKey(f.kind);
    m["kinds"] = kinds;
    if (m_board) {
        m["drills"] = int(m_board->drills.size());
        m["boardW"] = m_board->bounds.width();
        m["boardH"] = m_board->bounds.height();
        m["copperTop"] = m_board->copper[0] ? m_board->copper[0]->area : 0.0;
        m["copperBottom"] = m_board->copper[1] ? m_board->copper[1]->area : 0.0;
    }
    if (m_plan) {
        QVariantList layers;
        for (const pcb::PlanLayer& l : m_plan->layers)
            layers << QVariantMap{{"name", l.name}, {"process", l.process}, {"paths", int(l.polys.size())}, {"area", l.mode == lumacut::LayerMode::Fill ? pcb::polysArea(l.polys) : 0.0}};
        m["layers"] = layers;
        m["jobW"] = m_plan->bounds.width();
        m["jobH"] = m_plan->bounds.height();
    }
    return m;
}
