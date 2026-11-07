#include "core/pcb/job.h"

#include "core/parallel.h"
#include <algorithm>
#include <cmath>

namespace lumacut::pcb {
namespace {

struct Meta { const char* name; Stage stage; qint64 color; };
const Meta kMeta[kProcessCount] = {
    {"Platine Ätzresist", Stage::Resist, 0xFFE0824ALL},
    {"Platine Bohrmarken", Stage::Resist, 0xFF6CB6FFLL},
    {"Platine Passmarken", Stage::Resist, 0xFFB08CFFLL},
    {"Platine Umriss", Stage::Resist, 0xFF8A93A8LL},
    {"Platine Lötstopp", Stage::Mask, 0xFF4FD8B4LL},
    {"Platine Beschriftung", Stage::Silk, 0xFFF2C14ELL},
};
const Meta& meta(ProcessKey k) { return kMeta[int(k)]; }

Poly rect(double x0, double y0, double x1, double y1) { return {{x0, y0}, {x1, y0}, {x1, y1}, {x0, y1}}; }
QString mm(double v) { return QString::number(v, 'f', 2).replace(QLatin1Char('.'), QLatin1Char(',')); }

}  // namespace

JobSettings defaultSettings() { return {}; }

double lineInterval(double beamMm, double overlapPct) { return std::max(0.03, beamMm * (1 - overlapPct / 100)); }
double passSpacing(const JobSettings& s) { return s.passSpacingMm > 0 ? s.passSpacingMm : lineInterval(s.beamMm, s.overlapPct); }

std::vector<Pt> fiducialPoints(const Box& b, int count, double off) {
    const double cx = (b.minX + b.maxX) / 2;
    if (count == 2) return {{cx, b.maxY + off}, {cx, b.minY - off}};
    if (count == 4) return {{b.minX - off, b.maxY + off}, {b.maxX + off, b.maxY + off}, {b.maxX + off, b.minY - off}, {b.minX - off, b.minY - off}};
    return {};
}

Polys drillMarkPolys(const Board& board, const JobSettings& s) {
    Polys out;
    for (const DrillHit& h : board.drills) {
        const double size = std::min(s.drillMarkMm, h.dia > 0 ? h.dia * 0.8 : s.drillMarkMm);
        if (!s.drillCross) out.push_back(circle(h.x, h.y, size / 2));
        else {
            const double t = std::max(s.beamMm, 0.1), l = std::max(size, 2 * t);
            for (Poly& p : unionPolys({rect(h.x - l / 2, h.y - t / 2, h.x + l / 2, h.y + t / 2), rect(h.x - t / 2, h.y - l / 2, h.x + t / 2, h.y + l / 2)}))
                out.push_back(std::move(p));
        }
    }
    return unionPolys(out);
}

Plan buildPlan(const Board& board, const JobSettings& s) {
    Plan plan;
    const double beam = s.beamMm, interval = lineInterval(s.beamMm, s.overlapPct);
    const auto add = [&](ProcessKey key, LayerMode mode, Polys polys, bool output = true, const QString& suffix = {}) {
        if (polys.empty()) return;
        const Meta& m = meta(key);
        PlanLayer l;
        l.key = key;
        l.name = QString::fromUtf8(m.name) + suffix;
        l.stage = m.stage;
        l.mode = mode;
        l.process = mode == LayerMode::Fill ? QStringLiteral("Gravieren") : QStringLiteral("Markieren");
        l.color = m.color;
        l.polys = std::move(polys);
        l.intervalMm = interval;
        l.powerPct = s.power[int(key)];
        l.speed = s.speed[int(key)];
        l.output = output;
        plan.layers.push_back(std::move(l));
    };
    static const Polys none;
    const Polys& copper = board.copperOf(s.side) ? board.copperOf(s.side)->polys : none;
    const Polys edge = offsetPolys({board.outline.front()}, 0.5);
    const std::vector<Pt> marks = fiducialPoints(board.bounds, s.fiducials, s.fiducialOffsetMm);

    if (s.resist) {
        if (copper.empty()) plan.warnings << QStringLiteral("Für diese Seite gibt es keine Kupferlage: kein Ätzresist möglich.");
        else if (s.method == ResistMethod::Raster) {
            add(ProcessKey::Resist, LayerMode::Fill, subtractPolys(edge, offsetPolys(copper, beam / 2)));
        } else if (s.method == ResistMethod::Isolation) {
            const int passes = std::clamp(s.passes, 1, 50);
            const double step = passSpacing(s), first = beam / 2 + std::max(0.0, s.isolationOffsetMm);
            std::vector<Polys> rings(static_cast<size_t>(passes));
            parallelFor(passes, [&](std::ptrdiff_t k) { rings[size_t(k)] = offsetPolys(copper, first + double(k) * step); });
            Polys lines;
            for (Polys& r : rings) lines.insert(lines.end(), std::make_move_iterator(r.begin()), std::make_move_iterator(r.end()));
            add(ProcessKey::Resist, LayerMode::Line, clipLines(lines, edge));
            if (s.removeRest)
                add(ProcessKey::Resist, LayerMode::Fill, subtractPolys(edge, offsetPolys(copper, first + passes * step)), true, QStringLiteral(" Rest"));
        } else {
            // Negative film: light hardens what stays. Copper is exposed, drill centres stay dark and etch free.
            Polys shrunk = offsetPolys(copper, -beam / 2);
            add(ProcessKey::Resist, LayerMode::Fill, s.drillMarks ? subtractPolys(shrunk, drillMarkPolys(board, s)) : shrunk);
        }
        if (!copper.empty() && s.method != ResistMethod::Expose && s.drillMarks) add(ProcessKey::Drill, LayerMode::Fill, drillMarkPolys(board, s));
        if (!copper.empty() && !marks.empty()) {
            const double d = s.fiducialDiaMm;
            Polys shape;
            // Removing resist etches a dot. With negative film a ring of copper stays instead, the dot free inside it.
            for (const Pt& m : marks) {
                if (s.method == ResistMethod::Expose)
                    for (Poly& p : subtractPolys({circle(m.x, m.y, d / 2 + 1)}, {circle(m.x, m.y, d / 2)})) shape.push_back(std::move(p));
                else shape.push_back(closed(circle(m.x, m.y, d / 2)));
            }
            add(ProcessKey::Fiducial, LayerMode::Fill, shape);
        }
        add(ProcessKey::Outline, LayerMode::Line, board.outline, s.outlineMark);
    }
    if (s.mask) {
        const Polys& m = board.maskOf(s.side) ? board.maskOf(s.side)->polys : none;
        if (m.empty()) plan.warnings << QStringLiteral("Für diese Seite gibt es keine Lötstopp-Datei.");
        add(ProcessKey::Mask, LayerMode::Fill, offsetPolys(m, -beam / 2));
    }
    if (s.silk) {
        const Polys& sk = board.silkOf(s.side) ? board.silkOf(s.side)->polys : none;
        if (sk.empty()) plan.warnings << QStringLiteral("Für diese Seite gibt es keinen Bestückungsdruck.");
        // Text on a pad would burn the opening; fabs clip it the same way.
        add(ProcessKey::Silk, LayerMode::Fill, subtractPolys(sk, board.maskOf(s.side) ? board.maskOf(s.side)->polys : none));
    }
    plan.fiducials = marks;
    plan.bounds = board.bounds;
    const double r = s.fiducialDiaMm / 2 + (s.method == ResistMethod::Expose ? 1 : 0);
    for (const Pt& f : marks) plan.bounds = plan.bounds.united({f.x - r, f.y - r, f.x + r, f.y + r});
    return plan;
}

Pt toJob(Pt p, const Box& b, bool mirror) { return {mirror ? b.maxX - p.x : p.x - b.minX, b.maxY - p.y}; }

Pt centeredOnBed(const Plan& plan) {
    const Pt c = Work::center();
    return {std::round(std::max(0.0, c.x - plan.bounds.width() / 2)), std::round(std::max(0.0, c.y - plan.bounds.height() / 2))};
}

DesignFacts designFacts(const Board& board, Side side) {
    DesignFacts f;
    if (const auto& c = board.copperOf(side)) {
        f.minTrace = c->minStroke;
        f.clearance = minClearance(c->polys);
        f.copperArea = c->area;
    }
    return f;
}

std::vector<DesignCheck> designChecks(const DesignFacts& f, const JobSettings& s, const Plan& plan, Pt origin) {
    std::vector<DesignCheck> out;
    if (f.clearance) {
        const double c = f.clearance->mm;
        const QString title = QStringLiteral("Kleinster Abstand %1 mm").arg(mm(c));
        if (c < s.beamMm)
            out.push_back({"clearance", Tone::Bad, title, QStringLiteral("Enger als der Strahl (%1 mm). Dort bleibt Lack stehen, nach dem Ätzen eine Brücke. Die Stelle ist in der Vorschau markiert.").arg(mm(s.beamMm))});
        else if (c < s.beamMm * 1.5)
            out.push_back({"clearance", Tone::Warn, title, QStringLiteral("Knapp über der Strahlbreite. Mit dem Materialtest prüfen, ob der Lack dort sauber frei wird.")});
        else out.push_back({"clearance", Tone::Ok, title, QStringLiteral("Passt zur Strahlbreite %1 mm.").arg(mm(s.beamMm))});
    } else if (f.copperArea > 0) {
        out.push_back({"clearance", Tone::Ok, QStringLiteral("Kleinster Abstand über 2 mm"), QStringLiteral("Unkritisch für den Strahl.")});
    }
    if (f.minTrace) {
        const double t = *f.minTrace;
        const QString title = QStringLiteral("Kleinste Leiterbreite %1 mm").arg(mm(t));
        if (t < s.beamMm) out.push_back({"trace", Tone::Bad, title, QStringLiteral("Schmaler als der Strahl (%1 mm). Diese Leiter bleibt nicht zuverlässig stehen.").arg(mm(s.beamMm))});
        else if (t < std::max(0.3, s.beamMm * 2)) out.push_back({"trace", Tone::Warn, title, QStringLiteral("Das Ätzbad greift die Leiter auch von der Seite an. Dünne Bahnen vorab auf einem Reststück testen.")});
        else out.push_back({"trace", Tone::Ok, title, QStringLiteral("Aus den Zeichenbefehlen der Datei, ohne Flächen.")});
    }
    const Box placed{origin.x, origin.y, origin.x + plan.bounds.width(), origin.y + plan.bounds.height()};
    if (!Work::contains(placed)) out.push_back({"bed", Tone::Bad, QStringLiteral("Größer als die Arbeitsfläche"), QStringLiteral("Die Platine passt so nicht auf die Maschine.")});
    else if (Work::touchesPark(placed)) out.push_back({"bed", Tone::Bad, QStringLiteral("Berührt die %1").arg(Work::parkName()), QStringLiteral("Im Motiv verschieben, die %1 bleibt frei.").arg(Work::parkName())});
    if (s.side == Side::Bottom && !s.mirror)
        out.push_back({"mirror", Tone::Warn, QStringLiteral("Unterseite nicht gespiegelt"), QStringLiteral("Gerber zeigt die Unterseite von oben durch die Platine. Ungespiegelt passt sie nicht zu den Bohrungen der Oberseite.")});
    if (s.side == Side::Top && s.mirror)
        out.push_back({"mirror", Tone::Warn, QStringLiteral("Oberseite gespiegelt"), QStringLiteral("Die Oberseite wird normalerweise nicht gespiegelt.")});
    return out;
}

double estimateSeconds(const PlanLayer& layer, double overscanMm) {
    const double perMm = 60 / std::max(1.0, layer.speed);
    if (layer.mode == LayerMode::Line) {
        double len = 0;
        for (const Poly& p : layer.polys) for (size_t i = 1; i < p.size(); ++i) len += std::hypot(p[i].x - p[i - 1].x, p[i].y - p[i - 1].y);
        return len * perMm;
    }
    const auto b = boundsOfPolys(layer.polys);
    if (!b) return 0;
    const double iv = std::max(0.01, layer.intervalMm);
    const std::ptrdiff_t rows = std::ptrdiff_t(std::floor((b->height() - iv / 2) / iv)) + 1;
    std::vector<double> burn(size_t(std::max<std::ptrdiff_t>(rows, 0))), runs(burn.size());
    parallelBlocks(std::ptrdiff_t(burn.size()), 64, [&](std::ptrdiff_t from, std::ptrdiff_t to) {
        std::vector<double> xs;
        for (std::ptrdiff_t r = from; r < to; ++r) {
            const double y = b->minY + iv / 2 + double(r) * iv;
            xs.clear();
            for (const Poly& p : layer.polys)
                for (size_t i = 1; i < p.size(); ++i) {
                    const Pt u = p[i - 1], v = p[i];
                    if ((u.y <= y && v.y > y) || (v.y <= y && u.y > y)) xs.push_back(u.x + (y - u.y) * (v.x - u.x) / (v.y - u.y));
                }
            std::sort(xs.begin(), xs.end());
            for (size_t i = 0; i + 1 < xs.size(); i += 2) { burn[size_t(r)] += xs[i + 1] - xs[i]; runs[size_t(r)] += 1; }
        }
    });
    double total = 0;
    for (size_t i = 0; i < burn.size(); ++i) total += burn[i] + runs[i] * 2 * overscanMm;
    return total * perMm;
}

QString stageLabel(Stage s) {
    switch (s) {
    case Stage::Resist: return QStringLiteral("Ätzresist");
    case Stage::Mask: return QStringLiteral("Lötstopp");
    case Stage::Silk: return QStringLiteral("Bestückungsdruck");
    }
    return {};
}
QString processLabel(ProcessKey k) {
    switch (k) {
    case ProcessKey::Resist: return QStringLiteral("Ätzresist");
    case ProcessKey::Drill: return QStringLiteral("Bohrmarken");
    case ProcessKey::Fiducial: return QStringLiteral("Passmarken");
    case ProcessKey::Outline: return QStringLiteral("Umriss");
    case ProcessKey::Mask: return QStringLiteral("Lötstopp");
    case ProcessKey::Silk: return QStringLiteral("Beschriftung");
    }
    return {};
}
QStringList platineLayerNames() {
    QStringList out;
    for (const Meta& m : kMeta) out << QString::fromUtf8(m.name);
    out << QString::fromUtf8(kMeta[0].name) + QStringLiteral(" Rest");
    return out;
}

std::vector<Element> planElements(std::vector<Layer>& layers, const Plan& plan, const JobSettings& s, Stage stage, int plate, Pt origin) {
    const QString groupId = newId();
    std::vector<Element> out;
    for (const PlanLayer& pl : plan.layers) {
        auto it = std::find_if(layers.begin(), layers.end(), [&](const Layer& l) { return l.name == pl.name; });
        if (it == layers.end()) { layers.push_back(newLayer(pl.name, pl.color, pl.mode)); it = layers.end() - 1; }
        Layer& l = *it;
        l.mode = pl.mode;
        l.color = pl.color;
        l.powerPct = pl.powerPct;
        l.speed = pl.speed;
        l.intervalMm = pl.intervalMm;
        l.passes = 1;
        l.zStepMm = 0;
        l.output = pl.stage == stage && pl.output;
        l.visible = true;
        l.extra.insert(QStringLiteral("process"), pl.process);
        Element e = newElement(l.id, QStringLiteral("Platine"));
        e.groupId = groupId;
        e.plate = plate;
        e.transform.x = origin.x;
        e.transform.y = origin.y;
        e.paths.reserve(pl.polys.size(), 0);
        Poly buf;
        for (const Poly& p : pl.polys) {
            buf.clear();
            for (const Pt& q : p) buf.push_back(toJob(q, plan.bounds, s.mirror));
            e.paths.add(buf);
        }
        out.push_back(std::move(e));
    }
    return out;
}

QStringList applyPlanToDoc(Document& doc, const Plan& plan, const JobSettings& s, Stage stage, int plate, Pt origin) {
    std::vector<Element> els = planElements(doc.layers, plan, s, stage, plate, origin);
    std::erase_if(doc.elements, [plate](const Element& e) { return e.plate == plate && e.kind == QLatin1String("Platine"); });
    if (plate >= doc.plateCount) doc.plateCount = plate + 1;
    QStringList ids;
    for (Element& e : els) { ids << e.id; doc.elements.push_back(std::move(e)); }
    return ids;
}

}  // namespace lumacut::pcb
