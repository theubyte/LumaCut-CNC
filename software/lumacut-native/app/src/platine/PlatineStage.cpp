#include "PlatineStage.h"

#include "PlatineController.h"

namespace pcb = lumacut::pcb;

namespace {

constexpr double kMargin = 4;   // mm of sheet around the job
enum LayerId { Board, Copper, ResistFill, ResistLine, Holes, Marks, Fiducial, Mask, Silk, Outline, Marker, LayerCount };

}  // namespace

PlatineStage::PlatineStage(QQuickItem* parent) : StageItem(parent) {
    setProperty("interactive", true);
    setProperty("showGrid", false);
    setProperty("parkWidth", 0);
    setProperty("parkHeight", 0);
    auto* c = PlatineController::instance();
    connect(c, &PlatineController::planChanged, this, &PlatineStage::rebuild);
    connect(c, &PlatineController::boardChanged, this, &PlatineStage::rebuild);
    connect(c, &PlatineController::viewChanged, this, &PlatineStage::restyle);
    connect(this, &PlatineStage::colorsChanged, this, &PlatineStage::restyle);
    restyle();
    rebuild();
}

void PlatineStage::restyle() {
    auto* c = PlatineController::instance();
    const auto layer = [&](int id, QColor color, bool fill, const char* key, float fillOpacity = 1.0f) {
        StageLayer l;
        l.id = id;
        l.color = color;
        l.fill = fill;
        l.fillOpacity = fillOpacity;
        l.visible = key == nullptr || c->layerShown(QLatin1String(key));
        return l;
    };
    std::vector<StageLayer> layers{
        layer(Board, m_board, true, nullptr),
        layer(Copper, m_copper, true, "copper", 0.95f),
        layer(ResistFill, m_laser, true, "resist", 0.5f),
        layer(ResistLine, m_laser, false, "resist"),
        layer(Holes, m_drill, true, "holes"),
        layer(Marks, m_mark, true, "marks", 0.9f),
        layer(Fiducial, m_mark, true, "fiducial", 0.9f),
        layer(Mask, m_mask, true, "mask", 0.6f),
        layer(Silk, m_silk, true, "silk", 0.85f),
        layer(Outline, m_edgeLine, false, "outline"),
        layer(Marker, m_bad, false, nullptr),
    };
    setLayers(std::move(layers));
}

void PlatineStage::rebuild() {
    auto* c = PlatineController::instance();
    const auto board = c->board();
    const auto plan = c->plan();
    const pcb::JobSettings& s = c->jobSettings();
    if (plan == m_lastPlan && board == m_lastBoard && s.mirror == m_lastMirror && int(s.side) == m_lastSide) return;
    m_lastPlan = plan;
    m_lastBoard = board;
    m_lastMirror = s.mirror;
    m_lastSide = int(s.side);

    std::vector<StageElement> els;
    if (board && plan) {
        const lumacut::Box& b = plan->bounds;
        const QTransform t = QTransform::fromTranslate(kMargin, kMargin);
        quint64 next = 1;
        const auto add = [&](int layer, const pcb::Polys& polys, bool close) {
            if (polys.empty()) return;
            StageElement e;
            e.id = next++;
            e.layer = layer;
            e.transform = t;
            e.paths.reserve(polys.size());
            for (const lumacut::Poly& p : polys) {
                std::vector<QPointF> q;
                q.reserve(p.size() + 1);
                for (const lumacut::Pt& v : p) { const lumacut::Pt j = pcb::toJob(v, b, s.mirror); q.emplace_back(j.x, j.y); }
                if (close && !q.empty() && q.front() != q.back()) q.push_back(q.front());
                e.paths.push_back(std::move(q));
            }
            els.push_back(std::move(e));
        };
        add(Board, {board->outline.front()}, true);
        if (const auto& cu = board->copperOf(s.side)) add(Copper, cu->polys, true);
        pcb::Polys holes;
        for (const pcb::DrillHit& h : board->drills) holes.push_back(pcb::closed(pcb::circle(h.x, h.y, std::max(0.05, h.dia / 2), 0.01)));
        for (const pcb::DrillSlot& sl : board->slotHoles) for (lumacut::Poly& p : pcb::strokePolyline({sl.a, sl.b}, std::max(0.1, sl.dia))) holes.push_back(std::move(p));
        add(Holes, holes, true);
        for (const pcb::PlanLayer& l : plan->layers) {
            switch (l.key) {
            case pcb::ProcessKey::Resist: add(l.mode == lumacut::LayerMode::Fill ? ResistFill : ResistLine, l.polys, l.mode == lumacut::LayerMode::Fill); break;
            case pcb::ProcessKey::Drill: add(Marks, l.polys, true); break;
            case pcb::ProcessKey::Fiducial: add(Fiducial, l.polys, true); break;
            case pcb::ProcessKey::Mask: add(Mask, l.polys, true); break;
            case pcb::ProcessKey::Silk: add(Silk, l.polys, true); break;
            case pcb::ProcessKey::Outline: break;
            }
        }
        add(Outline, board->outline, true);
        if (const auto m = c->marker()) {
            pcb::Polys ring{pcb::closed(pcb::circle(m->at.x, m->at.y, 1.2, 0.01)), pcb::closed(pcb::circle(m->at.x, m->at.y, 1.5, 0.01))};
            add(Marker, ring, true);
        }
        const double w = b.width() + 2 * kMargin, h = b.height() + 2 * kMargin;
        if (std::abs(w - m_lastW) > 1e-6 || std::abs(h - m_lastH) > 1e-6) {
            setProperty("bedWidth", w);
            setProperty("bedHeight", h);
            m_lastW = w;
            m_lastH = h;
            fit();
        }
    }
    m_shown = int(els.size());
    setElements(std::move(els));
    emit contentChanged();
}
