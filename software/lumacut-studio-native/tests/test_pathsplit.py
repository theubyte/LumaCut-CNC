"""Zerlegen / Kombinieren (LightBurn *Break Apart* / *Combine*): Teilpfade als eigene
Objekte, mehrere Objekte als ein Objekt mit Ringen."""

from __future__ import annotations

import math

import pytest
from _pi_guard import pi_check

from lumacut_canvas import pathops, pathsplit
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Document, Geometry, Layer, Shape
from lumacut_canvas.shape_paths import shape_polygons
from lumacut_job.planner import optimized_document_gcode


@pytest.fixture
def doc(qapp):
    return Document()


def sq(x, y, w, h=None):
    h = w if h is None else h
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def multi(lid, *rings, kind="polygon", curves=()):
    pts, starts = [], []
    for r in rings:
        if pts:
            starts.append(len(pts))
        pts.extend(r)
    return Shape.from_points(kind, pts, lid, rings=starts, curves=curves)


def area(s):
    return pathops.shape_area(s).area


def region(shapes):
    from shapely.ops import unary_union
    return unary_union([pathops.shape_area(s) for s in shapes])


def canon(polys, nd=4):
    """Ringe als Mengen gerundeter Punkte (Startpunkt / Schlusspunkt egal)."""
    return sorted(tuple(sorted({(round(x, nd), round(y, nd)) for x, y in p})) for p in polys)


def world_rings(shapes):
    return canon([p for s in shapes for p in shape_polygons(s)])


def plate(lid):
    """Platte mit Loch, daneben ein Quadrat, im Loch eine Insel (4 Ringe, 3 Teile)."""
    return multi(lid, sq(0, 0, 40), sq(10, 10, 20), sq(60, 0, 20), sq(15, 15, 5))


# ---------------------------------------------------------------- Zerlegen (Engine)
def test_break_keeps_holes_with_their_outer_contour_and_islands_separate(doc):
    s = plate(doc.active_layer_id)
    parts = pathsplit.break_shape(s)
    assert [p.kind for p in parts] == ["polygon"] * 3
    assert [len(p.ring_ranges()) for p in parts] == [2, 1, 1]       # Platte+Loch, Quadrat, Insel
    assert [(p.bounds().x, p.bounds().y, p.bounds().w, p.bounds().h) for p in parts] == \
        [(0, 0, 40, 40), (60, 0, 20, 20), (15, 15, 5, 5)]
    assert area(parts[0]) == pytest.approx(1600 - 400)
    assert sum(area(p) for p in parts) == pytest.approx(area(s))
    assert region(parts).symmetric_difference(pathops.shape_area(s)).area == pytest.approx(0, abs=1e-6)
    assert all(p.id != s.id for p in parts) and len({p.id for p in parts}) == 3


def test_break_every_subpath_separately(doc):
    s = plate(doc.active_layer_id)
    parts = pathsplit.break_shape(s, keep_holes=False)
    assert len(parts) == 4 and all(len(p.ring_ranges()) == 1 for p in parts)
    assert world_rings(parts) == world_rings([s])
    assert pathsplit.break_preview([s]) == (3, 4)


def test_break_keeps_rotation_layer_groups_and_world_position(doc):
    lid = doc.active_layer_id
    s = plate(lid)
    s.geom.rot = 30.0
    s.groups = ("g1", "g2")
    parts = pathsplit.break_shape(s)
    assert all(p.geom.rot == pytest.approx(30.0) for p in parts)
    assert all(p.layer_id == lid and p.groups == ("g1", "g2") for p in parts)
    assert world_rings(parts) == world_rings([s])
    # Teile sind in ihrem eigenen (gedrehten) Rahmen achsparallel: 4 Punkte, Box = Kantenlänge
    assert (parts[1].geom.w, parts[1].geom.h) == (pytest.approx(20), pytest.approx(20))


def test_break_keeps_curve_segments_on_the_right_ring(doc):
    lid = doc.active_layer_id
    a = [(0, 0), (20, 0), (20, 20), (0, 20)]
    b = [(40, 0), (60, 0), (60, 20), (40, 20)]
    s = multi(lid, a, b, curves=[1, 4, 6])
    parts = pathsplit.break_shape(s)
    assert [p.curves for p in parts] == [(1,), (0, 2)]
    assert world_rings(parts) == world_rings([s])
    s.geom.rot = 45.0
    parts = pathsplit.break_shape(s)
    assert canon([p for q in parts for p in shape_polygons(q)], 2) == canon(shape_polygons(s), 2)


def test_break_curved_nesting_uses_the_flattened_rings(doc):
    lid = doc.active_layer_id
    # Kreisförmiger Außenring aus 4 Kurvenknoten: die Knoten-Polylinie (Raute) enthält das
    # kleine Quadrat bei (13, 2) nicht, die Kurve schon → es ist ein Loch.
    outer = [(10, 0), (20, 10), (10, 20), (0, 10)]
    s = multi(lid, outer, sq(13.5, 4.0, 1.0), curves=[0, 1, 2, 3])
    assert pathsplit.break_shape(s) is None                    # Ring mit Loch = ein Teil
    assert len(pathsplit.break_shape(s, keep_holes=False)) == 2


def test_break_open_path_into_its_subpaths(doc):
    lid = doc.active_layer_id
    s = multi(lid, [(0, 0), (10, 0), (10, 5)], [(20, 0), (30, 0)], [(0, 20), (5, 25)], kind="path")
    parts = pathsplit.break_shape(s)
    assert [p.kind for p in parts] == ["path"] * 3
    assert [p.abs_points()[0] for p in parts] == [(0, 0), (20, 0), (0, 20)]
    assert [p.abs_points()[-1] for p in parts] == [(10, 5), (30, 0), (5, 25)]
    assert pathsplit.break_shape(s, keep_holes=False)[2].abs_points() == [(0, 20), (5, 25)]


def test_break_skips_single_parts_codes_images_and_basic_shapes(doc):
    lid = doc.active_layer_id
    ring_with_hole = multi(lid, sq(0, 0, 20), sq(5, 5, 5))             # wie ein „O“
    single = Shape.from_points("polygon", sq(0, 0, 5), lid)
    code = multi(lid, sq(0, 0, 5), sq(10, 0, 5))
    code.generator = {"type": "qr"}
    rect = Shape("rect", Geometry(0, 0, 5, 5), lid)
    res = pathsplit.break_apart([ring_with_hole, single, code, rect])
    assert not res.changed and res.skipped == 2
    assert res.summary() == "Zerlegen: nichts zu zerlegen – jedes Objekt besteht aus einem Teil"
    assert len(pathsplit.break_shape(ring_with_hole, keep_holes=False)) == 2
    assert not pathsplit.can_break(code) and not pathsplit.can_break(rect)
    res = pathsplit.break_apart([plate(lid), single])
    assert res.summary() == "Zerlegen: 1 Objekt(e) → 3 Teil(e) · 1 Objekt(e) bestehen aus einem Teil"


def test_break_text_outline_into_letters(doc):
    t = Shape("text", Geometry(0, 0, 60, 20), doc.active_layer_id, text="Hi O")
    outline = pathops.text_to_outline(t)
    parts = pathsplit.break_shape(outline)
    assert len(parts) == 4                                    # H, i-Strich, i-Punkt, O (mit Loch)
    assert sorted(len(p.ring_ranges()) for p in parts) == [1, 1, 1, 2]
    assert sum(area(p) for p in parts) == pytest.approx(area(outline), rel=1e-6)


# ---------------------------------------------------------------- Kombinieren (Engine)
def test_combine_closed_shapes_into_one_polygon_with_a_hole(doc):
    lid = doc.active_layer_id
    r = Shape("rect", Geometry(0, 0, 40, 30), lid)
    e = Shape("ellipse", Geometry(10, 5, 20, 20), lid)
    res = pathsplit.combine([r, e])
    (new,) = res.add
    assert new.kind == "polygon" and len(new.ring_ranges()) == 2 and res.remove == [r.id, e.id]
    assert area(new) == pytest.approx(1200 - math.pi * 100, rel=1e-3)   # Kreis wird Loch
    assert res.overlaps == 0 and res.summary() == "Kombinieren: 2 Objekt(e) → 1 Objekt(e)"
    assert world_rings([new]) == world_rings([r, e])


def test_combine_open_paths_and_lines_into_one_path(doc):
    lid = doc.active_layer_id
    p = Shape.from_points("path", [(0, 0), (10, 0), (10, 10)], lid)
    ln = Shape("line", Geometry(20, 20, 10, -5), lid)
    (new,) = pathsplit.combine([p, ln]).add
    assert new.kind == "path" and len(new.ring_ranges()) == 2
    pieces = [new.abs_points()[a:b] for a, b in new.ring_ranges()]
    assert pieces == [[(0, 0), (10, 0), (10, 10)], [(20, 20), (30, 15)]]


def test_combine_buckets_by_layer_and_closed_open_and_counts_loners(doc):
    lid = doc.active_layer_id
    other = doc.add_layer(Layer(name="Gravur", color="#0000ff")).id
    a = Shape("rect", Geometry(0, 0, 5, 5), lid)
    b = Shape("rect", Geometry(10, 0, 5, 5), lid)
    c = Shape.from_points("path", [(0, 10), (5, 10)], lid)
    d = Shape.from_points("path", [(0, 20), (5, 20)], lid)
    e = Shape("rect", Geometry(0, 30, 5, 5), other)                 # allein auf seiner Ebene
    img = Shape("image", Geometry(0, 40, 5, 5), lid)
    res = pathsplit.combine([a, c, b, e, d, img])
    assert [(ids, s.kind, s.layer_id) for ids, s in res.groups] == \
        [([a.id, b.id], "polygon", lid), ([c.id, d.id], "path", lid)]
    assert res.skipped == 1
    assert res.summary() == "Kombinieren: 4 Objekt(e) → 2 Objekt(e) · 1 ohne Partner übrig"
    assert not pathsplit.combine([a]).changed
    assert pathsplit.combine([a]).summary().startswith("Kombinieren: nichts zu kombinieren")


def test_combine_rotation_kept_when_equal_else_zero(doc):
    lid = doc.active_layer_id
    a = Shape("rect", Geometry(0, 0, 10, 5), lid)
    b = Shape("rect", Geometry(20, 0, 10, 5), lid)
    a.geom.rot = b.geom.rot = 15.0
    (new,) = pathsplit.combine([a, b]).add
    assert new.geom.rot == pytest.approx(15.0)
    assert world_rings([new]) == world_rings([a, b])
    b.geom.rot = 40.0
    (new,) = pathsplit.combine([a, b]).add
    assert new.geom.rot == 0.0
    assert world_rings([new]) == world_rings([a, b])


def test_combine_counts_crossing_outlines_but_not_nested_ones(doc):
    lid = doc.active_layer_id
    a = Shape("rect", Geometry(0, 0, 10, 10), lid)
    b = Shape("rect", Geometry(5, 5, 10, 10), lid)
    c = Shape("rect", Geometry(2, 2, 2, 2), lid)                   # in a, kreuzt nichts
    res = pathsplit.combine([a, b, c])
    assert res.overlaps == 1
    assert "Achtung: 1 Überlappung(en)" in res.summary() and "Vereinigen" in res.summary()
    assert area(res.add[0]) == pytest.approx(100 + 100 - 2 * 25 - 4)


def test_combine_keeps_curves_and_converts_text(doc):
    lid = doc.active_layer_id
    curvy = Shape.from_points("polygon", [(0, 0), (20, 0), (20, 20), (0, 20)], lid, curves=[0, 2])
    t = Shape("text", Geometry(40, 0, 30, 10), lid, text="AB")
    res = pathsplit.combine([curvy, t])
    (new,) = res.add
    assert new.curves == (0, 2) and res.text_converted == 1
    assert "1 Text(e) in Pfade umgewandelt" in res.summary()
    assert area(new) == pytest.approx(area(curvy) + area(t), rel=1e-3)


def test_combine_then_break_is_lossless_and_file_round_trips(doc):
    lid = doc.active_layer_id
    shapes = [Shape.from_points("polygon", sq(30 * k, 0, 20), lid) for k in range(3)]
    (new,) = pathsplit.combine(shapes).add
    back = pathsplit.break_shape(new)
    assert world_rings(back) == world_rings(shapes)
    again = Shape.from_dict(new.to_dict())
    assert again.rings == new.rings and world_rings([again]) == world_rings([new])


def test_gcode_same_burn_after_break_and_combine_and_passes_pi_guard(doc):
    lid = doc.active_layer_id
    s = plate(lid)
    doc.add_shape(s)
    before = optimized_document_gcode(doc)

    def burned(g):
        cut, x, y = 0.0, 0.0, 0.0
        for ln in g.splitlines():
            w = ln.split()
            if not w or w[0] not in ("G0", "G1"):
                continue
            nx = next((float(t[1:]) for t in w if t[0] == "X"), x)
            ny = next((float(t[1:]) for t in w if t[0] == "Y"), y)
            if w[0] == "G1" and any(t[0] == "S" and float(t[1:]) > 0 for t in w):
                cut += math.hypot(nx - x, ny - y)
            x, y = nx, ny
        return cut

    parts = pathsplit.break_shape(s)
    doc.remove_shape(s.id)
    for p in parts:
        doc.add_shape(p)
    after = optimized_document_gcode(doc)
    pi_check(after)
    assert burned(after) == pytest.approx(burned(before), rel=1e-6)
    (combined,) = pathsplit.combine(list(doc.shapes)).add
    for p in parts:
        doc.remove_shape(p.id)
    doc.add_shape(combined)
    again = optimized_document_gcode(doc)
    pi_check(again)
    assert burned(again) == pytest.approx(burned(before), rel=1e-6)
    assert not any(ln.split()[0] in ("G2", "G3") for ln in again.splitlines() if ln.strip())


def test_import_hint_mentions_multi_part_objects(doc):
    from lumacut_import.qt import multipart_hint
    lid = doc.active_layer_id
    assert multipart_hint([plate(lid)]) == \
        " · 1 Objekt(e) aus mehreren Teilen (3 Teile) – Pfad › „Zerlegen“ (Strg+Alt+B)"
    assert multipart_hint([multi(lid, sq(0, 0, 20), sq(5, 5, 5))]) == ""      # Ring mit Loch
    assert multipart_hint([Shape("rect", Geometry(0, 0, 5, 5), lid)]) == ""


def test_import_hint_mentions_holes_imported_as_separate_objects(doc):
    from lumacut_import import qt as import_qt
    lid = doc.active_layer_id
    poly = lambda r: Shape.from_points("polygon", r, lid)                          # noqa: E731
    shapes = [poly(sq(0, 0, 40)), poly(sq(10, 10, 20)), poly(sq(15, 15, 5)), poly(sq(60, 0, 10)),
              Shape.from_points("path", [(0, 0), (5, 5)], lid)]
    assert import_qt.holes_hint(shapes) == (
        " · 1 Loch-Kontur(en) als eigene Objekte – „Jedes Objekt einzeln“ füllt sie mit; "
        "zum Füllen mit Loch Pfad › „Kombinieren“ (Strg+Alt+C)")
    assert import_qt.holes_hint(shapes[2:]) == ""
    other = doc.add_layer(Layer(name="B", color="#00ff00")).id
    assert import_qt.holes_hint([poly(sq(0, 0, 40)), Shape.from_points("polygon", sq(10, 10, 5), other)]) == ""
    many = [poly(sq(3 * (k % 50), 3 * (k // 50), 2)) for k in range(import_qt.HOLES_HINT_MAX)]
    assert import_qt.holes_hint(many + [poly(sq(-1, -1, 500))]) == ""            # zu viele: übersprungen
    (combined,) = pathsplit.combine(shapes[:2]).add
    assert area(combined) == pytest.approx(1200)


# ---------------------------------------------------------------- Editor / UI
@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, list(shapes)))
    return [s.id for s in shapes]


def test_editor_break_one_undo_step_keeps_stacking_and_selects_parts(ed):
    lid = ed.document.active_layer_id
    below = Shape("rect", Geometry(200, 200, 10, 10), lid)
    s = plate(lid)
    above = Shape("rect", Geometry(300, 200, 10, 10), lid)
    ids = _add(ed, [below, s, above])
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.set_selection([s.id])
    ed.actions_by_name["path_break"].trigger()
    shapes = ed.document.shapes
    assert [x.id for x in shapes][0] == below.id and shapes[-1].id == above.id
    assert len(shapes) == 5 and all(x.kind == "polygon" for x in shapes[1:4])
    assert sorted(ed.selection) == sorted(x.id for x in shapes[1:4])
    assert ed.undo_stack.undoText() == "Zerlegen"
    assert msgs[-1] == ("Zerlegen: 1 Objekt(e) → 3 Teil(e) – Löcher bleiben bei ihrer Außenkontur")
    ed.undo_stack.undo()
    assert [x.id for x in ed.document.shapes] == ids
    ed.undo_stack.redo()
    assert len(ed.document.shapes) == 5
    assert ed.actions_by_name["path_break"].shortcut().toString() == "Ctrl+Alt+B"


def test_editor_break_every_subpath_and_nothing_to_break(ed):
    lid = ed.document.active_layer_id
    s = plate(lid)
    o = multi(lid, sq(100, 0, 20), sq(105, 5, 5))
    _add(ed, [s, o])
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.set_selection([o.id])
    ed.actions_by_name["path_break"].trigger()
    assert ed.document.shape(o.id) is not None and ed.undo_stack.count() == 1
    assert msgs[-1].startswith("Zerlegen: nichts zu zerlegen") and "Löcher bleiben" in msgs[-1]
    ed.set_selection([s.id, o.id])
    ed.actions_by_name["path_break_all"].trigger()
    assert len(ed.document.shapes) == 6
    assert msgs[-1].startswith("Zerlegen: 2 Objekt(e) → 6 Teil(e)") and "Kombinieren" in msgs[-1]
    ed.undo_stack.undo()
    assert len(ed.document.shapes) == 2


def test_editor_combine_one_undo_step_per_layer_at_lowest_position(ed):
    lid = ed.document.active_layer_id
    a = Shape("rect", Geometry(0, 0, 40, 30), lid)
    mid = Shape("rect", Geometry(200, 0, 10, 10), lid)
    b = Shape("ellipse", Geometry(10, 5, 20, 20), lid)
    ids = _add(ed, [a, mid, b])
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.set_selection([a.id, b.id])
    ed.actions_by_name["path_combine"].trigger()
    shapes = ed.document.shapes
    assert [x.kind for x in shapes] == ["polygon", "rect"] and shapes[1].id == mid.id
    assert ed.selection == [shapes[0].id]
    assert ed.undo_stack.undoText() == "Kombinieren"
    assert msgs[-1] == "Kombinieren: 2 Objekt(e) → 1 Objekt(e)"
    ed.undo_stack.undo()
    assert [x.id for x in ed.document.shapes] == ids
    assert ed.actions_by_name["path_combine"].shortcut().toString() == "Ctrl+Alt+C"


def test_editor_split_actions_need_a_selection_and_respect_locked_layers(ed):
    lid = ed.document.active_layer_id
    s = plate(lid)
    r = Shape("rect", Geometry(100, 0, 5, 5), lid)
    _add(ed, [s, r])
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.set_selection([])
    ed.actions_by_name["path_break"].trigger()
    assert msgs[-1].startswith("Zerlegen: Objekte mit mehreren Teilen auswählen")
    ed.actions_by_name["path_combine"].trigger()
    assert msgs[-1].startswith("Kombinieren: nichts zu kombinieren")
    ed.set_selection([s.id, r.id])
    ed.document.update_layer(lid, locked=True)
    ed.actions_by_name["path_break"].trigger()
    ed.actions_by_name["path_combine"].trigger()
    assert [x.id for x in ed.document.shapes] == [s.id, r.id] and ed.undo_stack.count() == 1


def test_split_actions_in_path_menu_and_context_menu(ed):
    from PySide6.QtCore import QPointF
    _add(ed, [Shape("rect", Geometry(10, 10, 20, 10), ed.document.active_layer_id)])
    texts = [a.text() for a in ed.path_ops_button.menu().actions() if a.text()]
    for t in ("Zerlegen", "Zerlegen (jeder Teilpfad einzeln)", "Kombinieren"):
        assert t in texts
    assert "zerlegen / kombinieren" in ed.path_ops_button.toolTip()
    menu = ed.build_context_menu(QPointF(20, 15))
    sub = next(a.menu() for a in menu.actions() if a.menu() is not None
               and a.menu().objectName() == "PathOpsMenu")
    assert {"Zerlegen", "Kombinieren"} <= {a.text() for a in sub.actions()}


def test_main_window_shortcuts_unique_and_imported_svg_logo_breaks_apart(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction, QKeySequence
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    try:
        for key, text in (("Ctrl+Alt+B", "Zerlegen"), ("Ctrl+Alt+C", "Kombinieren")):
            owners = [a for a in w.findChildren(QAction) if a.shortcut() == QKeySequence(key)]
            assert [a.text() for a in owners] == [text]
        svg = tmp_path / "logo.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="50mm" '
                       'viewBox="0 0 100 50"><path d="M0 0 H40 V40 H0 Z M10 10 V30 H30 V10 Z '
                       'M60 0 H80 V20 H60 Z"/></svg>')
        msgs = []
        w.canvas.statusMessage.connect(msgs.append)
        ids = w.import_tools.import_path(svg)
        assert len(ids) == 3                       # SVG: jeder Teilpfad ein Objekt, das Loch auch
        assert any("1 Loch-Kontur(en) als eigene Objekte" in m and "Strg+Alt+C" in m for m in msgs)
        assert sum(area(w.canvas.document.shape(i)) for i in ids) == pytest.approx(2400, rel=1e-4)
        w.canvas.set_selection(ids)
        w.canvas.actions_by_name["path_combine"].trigger()
        (plate_,) = w.canvas.document.shapes
        assert len(plate_.ring_ranges()) == 3 and area(plate_) == pytest.approx(1600, rel=1e-4)   # Loch frei
        assert len(plate_.groups) == 1                   # Import-Gruppe bleibt
        w.canvas.set_selection([plate_.id])
        w.canvas.actions_by_name["path_break"].trigger()
        parts = w.canvas.document.shapes
        assert len(parts) == 2 and sorted(len(p.ring_ranges()) for p in parts) == [1, 2]
        assert sum(area(p) for p in parts) == pytest.approx(1600, rel=1e-4)
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
