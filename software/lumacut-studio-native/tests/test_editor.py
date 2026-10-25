"""Headless-Tests für Editor, Werkzeuge, Ebenen-Panel und Export."""

from PySide6.QtCore import QPointF, Qt

from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.export import export_png, export_svg, job_layers
from lumacut_canvas.layers_panel import LayersPanel, layer_summary
from lumacut_canvas.model import Geometry, Layer, Shape
from lumacut_canvas.tools import Tool, resize_bounds
from lumacut_canvas.workarea import Rect

NO = Qt.NoModifier
SHIFT = Qt.ShiftModifier


def drag(ed, a, b, mods=NO):
    t = ed.tools
    t.press(QPointF(*a), mods)
    t.move(QPointF((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), mods, True)
    t.move(QPointF(*b), mods, True)
    t.release(QPointF(*b), mods)


def editor(qapp):
    ed = CanvasEditor()
    ed.resize(1000, 700)
    ed.show()
    qapp.processEvents()
    return ed


def test_draw_rect_and_undo(qapp):
    ed = editor(qapp)
    ed.set_tool(Tool.RECT)
    drag(ed, (10, 10), (60, 40))
    assert len(ed.document.shapes) == 1
    s = ed.document.shapes[0]
    assert (s.kind, s.geom.as_tuple()) == ("rect", (10, 10, 50, 30))
    assert ed.selection == [s.id]
    assert ed.undo_stack.count() == 1  # Vorschau erzeugt keine Zusatzschritte
    ed.undo_stack.undo()
    assert ed.document.shapes == []


def test_shift_draws_circle_and_snaps(qapp):
    ed = editor(qapp)
    ed.set_tool(Tool.ELLIPSE)
    drag(ed, (10.2, 10.4), (40.3, 20.1), SHIFT)
    g = ed.document.shapes[0].geom
    assert g.w == g.h == 30


def test_draw_is_clamped_to_work_area(qapp):
    ed = editor(qapp)
    ed.set_tool(Tool.LINE)
    drag(ed, (300, 300), (500, 400))
    b = ed.document.shapes[0].bounds()
    assert b.right <= 360 and b.bottom <= 340


def test_move_with_select_tool_is_one_undo_step(qapp):
    ed = editor(qapp)
    ed.undo_stack.push(AddShapesCommand(ed.document, [Shape("rect", Geometry(10, 10, 20, 20), ed.document.active_layer_id)]))
    ed.set_tool(Tool.SELECT)
    drag(ed, (20, 20), (120, 70))
    g = ed.document.shapes[0].geom
    assert (g.x, g.y) == (110, 60)
    assert ed.undo_stack.count() == 2
    ed.undo_stack.undo()
    assert ed.document.shapes[0].geom.x == 10


def test_move_keeps_group_inside(qapp):
    ed = editor(qapp)
    lid = ed.document.active_layer_id
    ed.undo_stack.push(AddShapesCommand(ed.document, [Shape("rect", Geometry(10, 10, 20, 20), lid),
                                                      Shape("rect", Geometry(50, 10, 20, 20), lid)]))
    ed.select_all()
    drag(ed, (20, 20), (1000, 20))
    xs = sorted(s.geom.x for s in ed.document.shapes)
    assert xs == [300, 340]  # Abstand bleibt 40 mm, rechte Kante bei 360


def test_resize_handle_and_proportional(qapp):
    r = Rect(10, 10, 20, 10)
    assert resize_bounds(r, 4, QPointF(50, 50), False) == Rect(10, 10, 40, 40)
    assert resize_bounds(r, 4, QPointF(50, 15), True) == Rect(10, 10, 40, 20)
    ed = editor(qapp)
    ed.undo_stack.push(AddShapesCommand(ed.document, [Shape("rect", Geometry(10, 10, 20, 10), ed.document.active_layer_id)]))
    ed.select_all()
    drag(ed, (30, 20), (50, 15), SHIFT)  # Griff unten rechts
    assert ed.document.shapes[0].geom.as_tuple() == (10, 10, 40, 20)


def test_rubber_band_selection_skips_locked_layer(qapp):
    ed = editor(qapp)
    doc = ed.document
    a = Shape("rect", Geometry(10, 10, 10, 10), doc.active_layer_id)
    locked = doc.add_layer(Layer(name="Gesperrt", locked=True))
    b = Shape("rect", Geometry(30, 10, 10, 10), locked.id)
    ed.undo_stack.push(AddShapesCommand(doc, [a, b]))
    ed.set_selection([])
    drag(ed, (0, 0), (100, 100))
    assert ed.selection == [a.id]


def test_delete_duplicate_paste_and_nudge(qapp):
    ed = editor(qapp)
    ed.undo_stack.push(AddShapesCommand(ed.document, [Shape("ellipse", Geometry(10, 10, 10, 10), ed.document.active_layer_id)]))
    ed.select_all()
    ed.duplicate_selection()
    assert len(ed.document.shapes) == 2 and ed.document.shape(ed.selection[0]).geom.x == 15
    ed.copy_selection()
    ed.paste()
    assert len(ed.document.shapes) == 3
    ed.translate_selection(-1000, 0)
    assert ed.document.shape(ed.selection[0]).geom.x == 0
    ed.delete_selection()
    assert len(ed.document.shapes) == 2


def test_property_bar_sets_mm_geometry(qapp):
    ed = editor(qapp)
    ed.undo_stack.push(AddShapesCommand(ed.document, [Shape("rect", Geometry(10, 10, 20, 10), ed.document.active_layer_id)]))
    ed.select_all()
    pb = ed.property_bar
    pb.w.setValue(40)  # Seitenverhältnis gekoppelt
    assert ed.document.shapes[0].geom.as_tuple() == (10, 10, 40, 20)
    pb.x.setValue(100)
    assert ed.document.shapes[0].geom.x == 100


def test_text_tool_api(qapp):
    ed = editor(qapp)
    s = ed.tools.add_text("Hallo", QPointF(20, 20), 10)
    assert s.geom.h == 10 and s.geom.w > 10


def test_layers_panel_wiring(qapp):
    ed = editor(qapp)
    panel = LayersPanel(ed.document, ed.undo_stack)
    panel.add_layer()
    assert len(ed.document.layers) == 2 and panel.list.count() == 2
    new_id = ed.document.active_layer_id
    panel.power.setValue(42)
    panel.speed.setValue(2400)
    panel.passes.setValue(3)
    layer = ed.document.layer(new_id)
    assert (layer.power, layer.speed, layer.passes) == (42, 2400, 3)
    assert layer_summary(layer) == "42 % · 2400 mm/min · 3×"
    panel.name.setText("Gravur")
    panel._name_edited()
    assert layer.name == "Gravur"
    panel.toggle(new_id, "visible")
    assert not layer.visible
    panel.move_active(1)
    assert ed.document.layers[1].id == new_id
    panel.list.setCurrentRow(0)
    assert ed.document.active_layer_id != new_id
    panel.remove_active()
    assert len(ed.document.layers) == 1
    ed.undo_stack.undo()
    assert len(ed.document.layers) == 2


def test_hidden_layer_items_invisible(qapp):
    ed = editor(qapp)
    s = Shape("rect", Geometry(10, 10, 10, 10), ed.document.active_layer_id)
    ed.undo_stack.push(AddShapesCommand(ed.document, [s]))
    ed.select_all()
    ed.document.update_layer(s.layer_id, visible=False)
    assert not ed.scene.items_by_id[s.id].isVisible()
    assert ed.selection == []


def test_export_and_job_layers(qapp, tmp_path):
    ed = editor(qapp)
    doc = ed.document
    lid = doc.active_layer_id
    doc.add_shape(Shape("rect", Geometry(0, 0, 10, 10), lid))
    doc.add_shape(Shape("ellipse", Geometry(20, 20, 10, 10), lid))
    doc.add_shape(Shape("text", Geometry(50, 50, 30, 10), lid, text="A"))
    export_svg(doc, tmp_path / "a.svg")
    svg = (tmp_path / "a.svg").read_text(encoding="utf-8")
    assert 'viewBox="0 0 360 340"' in svg
    img = export_png(doc, tmp_path / "a.png", px_per_mm=2)
    assert (img.width(), img.height()) == (720, 680)
    jobs = job_layers(doc)
    assert len(jobs) == 1 and jobs[0].speed_mm_min == doc.layer(lid).speed
    first = jobs[0].polylines[0]
    assert min(p[0] for p in first) == 30 and min(p[1] for p in first) == 30  # Safezone-Versatz


def test_save_load_through_editor(qapp, tmp_path):
    ed = editor(qapp)
    ed.undo_stack.push(AddShapesCommand(ed.document, [Shape("rect", Geometry(1, 2, 3, 4), ed.document.active_layer_id)]))
    p = ed.save_file(tmp_path / "x.lumacut.json")
    assert ed.undo_stack.isClean()
    ed2 = editor(qapp)
    ed2.load_file(p)
    assert ed2.document.to_dict() == ed.document.to_dict()
    assert ed2.undo_stack.count() == 0


def test_canvas_demo_constructs(qapp):
    import canvas_demo
    w = canvas_demo.CanvasDemoWindow()
    w.show()
    qapp.processEvents()
    assert w.layers.list.count() == 1
    w.hide()


def test_all_icons_render(qapp):
    from lumacut_canvas import icons
    for name in icons.available():
        assert not icons.icon(name).pixmap(24, 24).isNull(), name
