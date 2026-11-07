#include "PerfboardStage.h"

#include <QHoverEvent>
#include <QKeyEvent>
#include <QMouseEvent>
#include "PerfboardController.h"
#include "Shell.h"

namespace pcb = lumacut::pcb;

namespace {

constexpr double kMargin = 6;   // mm of sheet around the board
enum LayerId { Board, Pads, Holes, Bodies, WiresSolder, WiresComp, MarksActive, MarksOther, Selection, Ghost, Assist };

std::vector<std::vector<QPointF>> toPaths(const pcb::Polys& polys, bool close) {
    std::vector<std::vector<QPointF>> out;
    out.reserve(polys.size());
    for (const lumacut::Poly& p : polys) {
        std::vector<QPointF> q;
        q.reserve(p.size() + 1);
        for (const lumacut::Pt& v : p) q.emplace_back(v.x, v.y);
        if (close && !q.empty() && q.front() != q.back()) q.push_back(q.front());
        out.push_back(std::move(q));
    }
    return out;
}
void partLines(const pcb::Placed& p, const pcb::PartDef& def, const pcb::PerfBoard& b, pcb::Polys& out) {
    for (lumacut::Poly& q : pcb::partOutline(p, def, b)) out.push_back(std::move(q));
    // Pin 1 ring, so orientation reads in the editor even where the marking falls on pads.
    const lumacut::Pt h = b.hole(pcb::pinsOf(p, def).front());
    out.push_back(pcb::closed(pcb::circle(h.x, h.y, b.padDia / 2 + 0.3, 0.02)));
}

}  // namespace

PerfboardStage::PerfboardStage(QQuickItem* parent) : StageItem(parent) {
    setProperty("interactive", true);
    setProperty("showGrid", false);
    setProperty("parkWidth", 0);
    setProperty("parkHeight", 0);
    setAcceptedMouseButtons(Qt::AllButtons);
    setAcceptHoverEvents(true);
    setFlag(QQuickItem::ItemIsFocusScope, true);
    setActiveFocusOnTab(true);
    auto* c = PerfboardController::instance();
    connect(c, &PerfboardController::changed, this, [this] { rebuildStatic(); rebuildDynamic(); });
    connect(c, &PerfboardController::marksChanged, this, &PerfboardStage::rebuildDynamic);
    connect(c, &PerfboardController::selectionChanged, this, &PerfboardStage::rebuildDynamic);
    connect(c, &PerfboardController::ghostChanged, this, &PerfboardStage::rebuildDynamic);
    connect(c, &PerfboardController::assistChanged, this, &PerfboardStage::rebuildDynamic);
    connect(c, &PerfboardController::viewChanged, this, [this] { m_w = 0; rebuildStatic(); rebuildDynamic(); restyle(); });
    connect(this, &PerfboardStage::colorsChanged, this, &PerfboardStage::restyle);
    connect(this, &GpuViewItem::viewChanged, this, [this] { ++m_viewRev; emit viewRevisionChanged(); });
    restyle();
    rebuildStatic();
    rebuildDynamic();
}

QTransform PerfboardStage::boardTransform() const {
    const auto& b = PerfboardController::instance()->design().board;
    if (PerfboardController::instance()->viewBelow()) return QTransform(-1, 0, 0, 1, kMargin + b.width, kMargin);
    return QTransform::fromTranslate(kMargin, kMargin);
}

void PerfboardStage::restyle() {
    auto* c = PerfboardController::instance();
    const auto layer = [](int id, QColor color, bool fill, float opacity = 1.0f, bool visible = true) {
        StageLayer l;
        l.id = id;
        l.color = color;
        l.fill = fill;
        l.fillOpacity = 1.0f;
        l.opacity = opacity;
        l.visible = visible;
        return l;
    };
    const bool marks = c->showMarks();
    setLayers({layer(Board, m_board, true), layer(Pads, m_pad, true), layer(Holes, m_hole, true),
               layer(Bodies, m_body, false, marks ? 0.35f : 0.9f), layer(WiresSolder, m_solder, false, 0.55f), layer(WiresComp, m_wire, false, 0.55f),
               layer(MarksActive, m_laser, false, 1.0f, marks), layer(MarksOther, m_laser, false, 0.3f, marks),
               layer(Selection, m_accent, false), layer(Ghost, m_accent, false, 0.7f), layer(Assist, m_warn, false)});
}

void PerfboardStage::rebuildStatic() {
    const auto& b = PerfboardController::instance()->design().board;
    const QTransform t = boardTransform();
    pcb::Polys board{{{0, 0}, {b.width, 0}, {b.width, b.height}, {0, b.height}, {0, 0}}};
    pcb::Polys pads, holes;
    for (int r = 0; r < b.rows; ++r)
        for (int col = 0; col < b.cols; ++col) {
            pads.push_back(pcb::closed(b.padShape({col, r})));
            const lumacut::Pt h = b.hole(col, r);
            holes.push_back(pcb::closed(pcb::circle(h.x, h.y, b.holeDia / 2, 0.02)));
        }
    for (const lumacut::Pt& m : b.mountHoles()) holes.push_back(pcb::closed(pcb::circle(m.x, m.y, b.mountDia / 2, 0.02)));
    std::vector<StageElement> els(3);
    els[0] = {1, Board, toPaths(board, true), t, true};
    els[1] = {2, Pads, toPaths(pads, true), t, true};
    els[2] = {3, Holes, toPaths(holes, true), t, true};
    upsertElements(std::move(els));
    if (std::abs(b.width - m_w) > 1e-9 || std::abs(b.height - m_h) > 1e-9) {
        m_w = b.width;
        m_h = b.height;
        setProperty("bedWidth", b.width + 2 * kMargin);
        setProperty("bedHeight", b.height + 2 * kMargin);
        fit();
    }
}

void PerfboardStage::rebuildDynamic() {
    auto* c = PerfboardController::instance();
    const pcb::PerfDesign& d = c->design();
    const pcb::PerfBoard& b = d.board;
    const QTransform t = boardTransform();
    std::vector<StageElement> els;
    quint64 next = 10;
    const auto add = [&](int layer, const pcb::Polys& polys, bool close) {
        if (polys.empty()) return;
        els.push_back({next++, layer, toPaths(polys, close), t, true});
    };
    const pcb::GridPt drag = c->dragOffset();
    pcb::Polys bodies, sel, assist;
    const int assistPart = c->assistPart();
    for (size_t i = 0; i < d.parts.size(); ++i) {
        pcb::Placed p = d.parts[i];
        const pcb::PartDef* def = pcb::findPart(p.partId);
        if (!def) continue;
        const bool selected = c->selKind() == 1 && c->selIndex() == int(i);
        if (selected) p.at = {p.at.c + drag.c, p.at.r + drag.r};
        pcb::Polys lines;
        partLines(p, *def, b, lines);
        pcb::Polys& target = selected ? sel : int(i) == assistPart ? assist : bodies;
        target.insert(target.end(), lines.begin(), lines.end());
        if (selected || int(i) == assistPart)
            for (const pcb::GridPt& g : pcb::pinsOf(p, *def)) { const lumacut::Pt h = b.hole(g); target.push_back(pcb::closed(pcb::circle(h.x, h.y, b.padDia / 2 + 0.15, 0.02))); }
    }
    add(Bodies, bodies, true);
    pcb::Polys ws, wc;
    for (size_t i = 0; i < d.wires.size(); ++i) {
        lumacut::Poly line;
        const bool selected = c->selKind() == 2 && c->selIndex() == int(i);
        for (const pcb::GridPt& g : d.wires[i].pts) line.push_back(b.hole({g.c + (selected ? drag.c : 0), g.r + (selected ? drag.r : 0)}));
        (selected ? sel : d.wires[i].solder ? ws : wc).push_back(line);
    }
    add(WiresSolder, ws, false);
    add(WiresComp, wc, false);
    for (size_t i = 0; i < d.labels.size(); ++i)
        if (c->selKind() == 3 && c->selIndex() == int(i)) {
            const pcb::Label& l = d.labels[i];
            const double w = std::max(1.0, l.heightMm * 0.35 * l.text.size());
            sel.push_back({{l.at.x - w, l.at.y - l.heightMm}, {l.at.x + w, l.at.y - l.heightMm}, {l.at.x + w, l.at.y + l.heightMm}, {l.at.x - w, l.at.y + l.heightMm}, {l.at.x - w, l.at.y - l.heightMm}});
        }
    if (const auto m = c->marks()) {
        add(c->viewBelow() ? MarksActive : MarksOther, m->solder, false);
        add(c->viewBelow() ? MarksOther : MarksActive, m->component, false);
    }
    add(Selection, sel, false);
    add(Assist, assist, false);
    const auto& g = c->ghost();
    if (g.on) {
        pcb::Polys gl;
        if (g.wire) {
            lumacut::Poly line;
            for (const pcb::GridPt& q : g.route) line.push_back(b.hole(q));
            gl.push_back(line);
        } else if (const pcb::PartDef* def = pcb::findPart(g.partId)) {
            const pcb::Placed p{{}, g.partId, {}, {}, g.at, g.rot};
            partLines(p, *def, b, gl);
            for (const pcb::GridPt& q : pcb::pinsOf(p, *def)) { const lumacut::Pt h = b.hole(q); gl.push_back(pcb::closed(pcb::circle(h.x, h.y, b.padDia / 2 + 0.15, 0.02))); }
        }
        add(Ghost, gl, false);
    }
    std::vector<quint64> ids;
    for (const StageElement& e : els) ids.push_back(e.id);
    std::vector<quint64> gone;
    for (quint64 id : m_dynamicIds) if (std::find(ids.begin(), ids.end(), id) == ids.end()) gone.push_back(id);
    if (!gone.empty()) removeElements(std::move(gone));
    m_dynamicIds = ids;
    m_shown = 3 + int(els.size());
    upsertElements(std::move(els));
    ++m_viewRev;
    emit viewRevisionChanged();
}

QPointF PerfboardStage::toBoard(QPointF itemPos) const {
    const QPointF mm = itemToMm(itemPos);
    return boardTransform().inverted().map(mm);
}
QPointF PerfboardStage::boardToItem(double x, double y) const { return mmToItem(boardTransform().map(QPointF(x, y))); }
QPointF PerfboardStage::holeItemPos(int c, int r) const {
    const lumacut::Pt h = PerfboardController::instance()->design().board.hole(c, r);
    return boardToItem(h.x, h.y);
}
void PerfboardStage::fitBoard() { fit(); }

void PerfboardStage::mousePressEvent(QMouseEvent* e) {
    forceActiveFocus(Qt::MouseFocusReason);
    if (e->button() != Qt::LeftButton) {
        if (e->button() == Qt::RightButton) PerfboardController::instance()->escape();
        m_panning = true;
        GpuViewItem::mousePressEvent(e);
        return;
    }
    const QPointF p = toBoard(e->position());
    const lumacut::Pt bp{p.x(), p.y()};
    auto* c = PerfboardController::instance();
    m_editing = true;
    c->press(c->design().board.holeAt(bp), bp, e->modifiers() & Qt::ShiftModifier);
    e->accept();
}
void PerfboardStage::mouseMoveEvent(QMouseEvent* e) {
    if (m_panning) { GpuViewItem::mouseMoveEvent(e); return; }
    const QPointF p = toBoard(e->position());
    const lumacut::Pt bp{p.x(), p.y()};
    auto* c = PerfboardController::instance();
    if (m_editing) c->dragTo(c->design().board.holeAt(bp));
    else c->hover(c->design().board.holeAt(bp), bp, e->modifiers() & Qt::ShiftModifier);
    e->accept();
}
void PerfboardStage::mouseReleaseEvent(QMouseEvent* e) {
    if (m_panning) { m_panning = false; GpuViewItem::mouseReleaseEvent(e); return; }
    if (m_editing) { m_editing = false; PerfboardController::instance()->release(); }
    e->accept();
}
void PerfboardStage::hoverMoveEvent(QHoverEvent* e) {
    const QPointF p = toBoard(e->position());
    const lumacut::Pt bp{p.x(), p.y()};
    auto* c = PerfboardController::instance();
    c->hover(c->design().board.holeAt(bp), bp, e->modifiers() & Qt::ShiftModifier);
}
void PerfboardStage::keyPressEvent(QKeyEvent* e) {
    auto* c = PerfboardController::instance();
    const bool ctrl = e->modifiers() & Qt::ControlModifier;
    switch (e->key()) {
    case Qt::Key_Delete: case Qt::Key_Backspace: c->deleteSelected(); break;
    case Qt::Key_R: if (ctrl) return QQuickItem::keyPressEvent(e); c->rotateGhostOrSelection(); break;
    case Qt::Key_Escape: c->escape(); break;
    case Qt::Key_Z: if (!ctrl) return QQuickItem::keyPressEvent(e); if (e->modifiers() & Qt::ShiftModifier) c->redo(); else c->undo(); break;
    case Qt::Key_Y: if (!ctrl) return QQuickItem::keyPressEvent(e); c->redo(); break;
    case Qt::Key_V: if (ctrl) return QQuickItem::keyPressEvent(e); c->setTool(QStringLiteral("select")); break;
    case Qt::Key_W: if (ctrl) return QQuickItem::keyPressEvent(e); c->setTool(QStringLiteral("wire")); break;
    case Qt::Key_T: if (ctrl) return QQuickItem::keyPressEvent(e); c->setTool(QStringLiteral("text")); break;
    case Qt::Key_Left: c->moveSelected(c->viewBelow() ? 1 : -1, 0); break;
    case Qt::Key_Right: c->moveSelected(c->viewBelow() ? -1 : 1, 0); break;
    case Qt::Key_Up: c->moveSelected(0, -1); break;
    case Qt::Key_Down: c->moveSelected(0, 1); break;
    default: QQuickItem::keyPressEvent(e); return;
    }
    e->accept();
}
