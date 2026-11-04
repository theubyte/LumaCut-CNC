"""Live park-zone warning and the zone for placed jobs (lumacut_job.park_zone)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal

from lumacut_canvas.model import Document, Geometry, Layer, Shape
from lumacut_canvas.workarea import Rect, machine_to_screen, screen_to_machine
from lumacut_job import park_corner as pc
from lumacut_job import park_zone as pz

ZONE = pz.park_zone_rect()          # default: screen 312..360 / 0..5


class FakePanel(QObject):
    status_changed = Signal(object)

    def __init__(self, status=None, origin="absolute", anchor="tr"):
        super().__init__()
        self._status = status
        self.origin = origin
        self.anchor = anchor

    def job_origin(self):
        return self.origin, self.anchor


class FakeEditor(QObject):
    documentChanged = Signal()
    selectionChanged = Signal()

    def __init__(self, doc=None):
        super().__init__()
        self.document = doc or Document()
        self.selection = []
        self.refreshed = 0
        self.overlays = {}

    def add_overlay(self, key, ov, z=0.0):
        self.overlays[key] = ov

    def refresh_overlays(self):
        self.refreshed += 1


def _rect(doc, x, y, w, h, layer=None):
    return doc.add_shape(Shape("rect", Geometry(x, y, w, h), layer or doc.active_layer_id))


def _status(pos=None, user=None, corner=None):
    raw = {"park_corner_mm": {"x": corner[0], "y": corner[1]}} if corner else {}
    return SimpleNamespace(raw=raw, position=pos, origin=SimpleNamespace(user=user, supported=True),
                           coord_convention=pc.COORD_CONVENTION)


# --- geometry ------------------------------------------------------------------
def _mbox(*rects):
    from lumacut_job.park_zone import design_box
    return design_box(Shape("rect", Geometry(*r), "L") for r in rects)


def test_design_box_is_machine_extent():
    box = _mbox((300, 1, 30, 2))
    x0, y0 = screen_to_machine(330, 1)
    assert (box.xmin, box.ymin, box.xmax, box.ymax) == pytest.approx((x0, y0, x0 + 30, y0 + 2))
    assert _mbox() is None


def test_design_hits_zone_follows_pi_box_rule():
    corner = pc.PARK_CORNER_MM
    assert pz.design_hits_zone(_mbox((330, 1, 10, 10)), corner)
    assert not pz.design_hits_zone(_mbox((330, 5, 10, 10)), corner)   # touching the edge
    assert not pz.design_hits_zone(_mbox((200, 1, 100, 10)), corner)  # left of the zone
    # two objects, neither in the zone, but their common box is (Pi refuses that)
    two = _mbox((340, 100, 10, 10), (100, 1, 10, 3))
    assert pz.design_hits_zone(two, corner)
    assert not pz.design_hits_zone(None, corner)
    # placement with unknown target: not judged (the Pi decides)
    assert not pz.design_hits_zone(two, corner, "current", "tr", None)


def test_design_hits_zone_matches_check_job():
    for rects in (((330, 1, 10, 10),), ((330, 5, 10, 10),), ((340, 100, 10, 10), (100, 1, 10, 3)),
                  ((10, 10, 50, 50),)):
        shapes = [Shape("rect", Geometry(*r), "L") for r in rects]
        g = _gcode([_box_machine(sh) for sh in shapes])
        assert pz.design_hits_zone(pz.design_box(shapes), pc.PARK_CORNER_MM) == \
            (not pc.check_job(g).ok), rects


def test_placed_zone_absolute_equals_fixed_corner():
    assert pz.placed_zone_rect(pc.PARK_CORNER_MM, "absolute", "tr", None, None) == ZONE


def test_placed_zone_matches_send_time_check():
    """Whatever lies in the placed zone is what check_job refuses after placement."""
    corner = pc.PARK_CORNER_MM
    box = pc.Box(150.0, 100.0, 200.0, 140.0)          # design in machine mm
    target = (60.0, 40.0)                              # head position
    for anchor in ("tl", "tr", "bl", "br", "center"):
        try:
            z = pz.placed_zone_rect(corner, "current", anchor, target, box)
        except Exception as exc:                       # pragma: no cover
            raise AssertionError(anchor) from exc
        dx, dy = pc.placement_offset(box, "current", anchor, target)
        if z is None:
            continue
        # zone in machine mm = corner shifted back by the offset
        mx0, my0 = screen_to_machine(z.x, z.y)
        mx1, my1 = screen_to_machine(z.right, z.bottom)
        lo_x, hi_x = sorted((mx0, mx1))
        lo_y, hi_y = sorted((my0, my1))
        assert lo_x + dx >= -1e-6 and hi_x + dx <= corner[0] + 1e-6
        assert lo_y + dy >= -1e-6 and hi_y + dy <= corner[1] + 1e-6


def test_placed_zone_unknown_target_or_design():
    assert pz.placed_zone_rect((78, 35), "current", "tr", None, pc.Box(0, 0, 1, 1)) is None
    assert pz.placed_zone_rect((78, 35), "user", "tr", (10, 10), None) is None
    assert pz.placed_zone_rect((0, 35), "user", "tr", (10, 10), pc.Box(0, 0, 1, 1)) is None


def _gcode(doc_shapes_machine):
    lines = ["G90"]
    for (x0, y0, x1, y1) in doc_shapes_machine:
        lines += [f"G0 X{x0:.3f} Y{y0:.3f}", "M4 S0", f"G1 X{x1:.3f} Y{y1:.3f} F1500 S500", "M5"]
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("anchor", ["bl", "center", "tr"])
def test_sync_placed_zone_flags_what_check_job_refuses(qapp, anchor):
    """Placed job (Kopfposition): an object that lands in the corner is flagged
    live exactly when the send-time check refuses the same design."""
    doc = Document()
    ed = FakeEditor(doc)
    a = _rect(doc, 100, 100, 10, 10)
    target = (100.0, 60.0)
    mp = FakePanel(_status(pos=target), "current", anchor)
    msgs = []
    sync = pz.install_park_zone(ed, mp, report=msgs.append)
    assert sync.overlay.visible and sync.overlay.hits == ()
    b = _rect(doc, 0, 0, 2.0, 2.0)
    seen = set()
    for x in range(0, 358, 22):
        for y in range(0, 330, 22):
            doc.set_geometry(b.id, Geometry(float(x), float(y), 2.0, 2.0))
            ed.documentChanged.emit()
            g = _gcode([_box_machine(s) for s in doc.shapes])
            refused = not pc.check_job(g, origin="current", anchor=anchor, target=target).ok
            assert refused == sync.overlay.refused, (x, y)
            if sync.overlay.hits:
                assert refused
            seen.add(refused)
    if anchor == "tr":
        # head right of / below the corner, design hangs away from it: never refused
        assert seen == {False}
    else:
        assert seen == {True, False}
        assert any("Kopfposition" in m for m in msgs)


def _box_machine(shape):
    b = shape.bounds()
    x0, y0 = screen_to_machine(b.x, b.y)
    x1, y1 = screen_to_machine(b.right, b.bottom)
    return (x0, y0, x1, y1)


def test_sync_placed_zone_hidden_without_target(qapp):
    doc = Document()
    _rect(doc, 100, 100, 10, 10)
    mp = FakePanel(_status(pos=None), "current")
    sync = pz.install_park_zone(FakeEditor(doc), mp)
    assert not sync.overlay.visible
    mp._status = _status(pos=(50.0, 50.0))
    mp.status_changed.emit(mp._status)
    assert sync.overlay.visible and sync.overlay.placed is not None
    assert "Kopfposition" in sync.overlay.label()


# --- live warning ------------------------------------------------------------------
def test_live_warning_when_object_moved_into_zone(qapp):
    doc = Document()
    ed = FakeEditor(doc)
    s = _rect(doc, 200, 50, 10, 10)
    msgs = []
    sync = pz.install_park_zone(ed, FakePanel(), report=msgs.append)
    assert sync.overlay.hits == () and msgs == []
    n = ed.refreshed
    ed.documentChanged.emit()                       # nothing changed: no redraw / message
    assert ed.refreshed == n and msgs == []
    doc.set_geometry(s.id, Geometry(330, 1, 10, 10))
    ed.documentChanged.emit()
    assert sync.overlay.hits == (s.id,) and ed.refreshed == n + 1
    assert len(msgs) == 1 and "Park-Ecke" in msgs[0] and "1 Objekt liegt" in msgs[0]
    assert "darin" in sync.overlay.label()
    doc.set_geometry(s.id, Geometry(331, 1, 10, 10))  # still inside: no new message
    ed.documentChanged.emit()
    assert len(msgs) == 1
    doc.set_geometry(s.id, Geometry(200, 50, 10, 10))
    ed.documentChanged.emit()
    assert sync.overlay.hits == () and msgs[-1] == "Park-Ecke wieder frei."
    ed.documentChanged.emit()
    assert len(msgs) == 2


def test_live_warning_ignores_hidden_layers_and_follows_selection_only(qapp):
    doc = Document()
    ed = FakeEditor(doc)
    hidden = doc.add_layer(Layer("aus", visible=False))
    s1 = _rect(doc, 330, 1, 5, 2, hidden.id)
    s2 = _rect(doc, 320, 1, 5, 2, doc.layers[-1].id)
    only = [False]
    sync = pz.install_park_zone(ed, FakePanel(), selection_only=lambda: only[0])
    assert sync.overlay.hits == (s2.id,)
    only[0] = True
    ed.selection = [s1.id]
    ed.selectionChanged.emit()
    assert sync.overlay.hits == ()
    ed.selection = [s2.id]
    ed.selectionChanged.emit()
    assert sync.overlay.hits == (s2.id,)


def test_live_warning_whole_design_box(qapp):
    doc = Document()
    ed = FakeEditor(doc)
    _rect(doc, 340, 100, 10, 10)
    far = _rect(doc, 100, 50, 10, 3)
    msgs = []
    sync = pz.install_park_zone(ed, FakePanel(), report=msgs.append)
    assert not sync.overlay.refused
    doc.set_geometry(far.id, Geometry(100, 1, 10, 3))
    ed.documentChanged.emit()
    assert sync.overlay.refused and sync.overlay.hits == ()
    assert "Umriss" in msgs[-1] and "Umriss" in sync.overlay.label()


def test_live_warning_rotated_object_box(qapp):
    s = Shape("rect", Geometry(305, 6, 10, 3, rot=45.0), "L")
    assert pz.object_hits_zone_rect(s.bounds(), ZONE)          # rotated box reaches up
    assert not pz.object_hits_zone_rect(Shape("rect", Geometry(305, 6, 10, 3), "L").bounds(), ZONE)


def test_live_warning_on_real_canvas_drag(qapp):
    from PySide6.QtWidgets import QMainWindow
    from lumacut_canvas.editor import CanvasEditor
    from lumacut_job.qt_tools import JobTools
    from machine.panel import MachinePanel
    win = QMainWindow()
    ed = CanvasEditor()
    mp = MachinePanel()
    try:
        tools = JobTools(win, ed, mp, win.statusBar())
        doc = ed.document
        s = doc.add_shape(Shape("rect", Geometry(200, 50, 10, 10), doc.active_layer_id))
        qapp.processEvents()
        assert tools.park_zone.overlay.hits == ()
        doc.set_geometry(s.id, Geometry(330, 1, 10, 10))
        qapp.processEvents()
        assert tools.park_zone.overlay.hits == (s.id,)
        assert "Park-Ecke" in win.statusBar().currentMessage()
    finally:
        mp.shutdown() if hasattr(mp, "shutdown") else None
        ed.undo_stack.setClean()
        ed.close()
        win.close()
        ed.deleteLater()
        win.deleteLater()
        qapp.processEvents()
