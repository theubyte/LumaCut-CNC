"""Import-Einstellungen (LightBurn *Auto-close tolerance* / SVG-Pfade mit Löchern als eine
Form): Duplikate löschen, offene Pfade verbinden, Löcher kombinieren – gleich beim Import,
standardmäßig aus."""

from __future__ import annotations

import pytest
from _pi_guard import pi_check

from lumacut_canvas import pathops
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_import import cleanup
from lumacut_import.cleanup import CleanupResult, ImportOptions, clean_import

ALL = ImportOptions(delete_duplicates=True, auto_join=True, combine_holes=True)


def seg(a, b, lid="L1", groups=("g",)):
    s = Shape.from_points("path", [a, b], lid)
    s.groups = groups
    return s


def poly(pts, lid="L1", groups=("g",)):
    s = Shape.from_points("polygon", pts, lid)
    s.groups = groups
    return s


def sq(x, y, w, h=None):
    h = w if h is None else h
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def square_segments(x, y, w, gap=0.0, lid="L1"):
    p = sq(x, y, w)
    return [seg(p[0], p[1], lid), seg(p[2], p[1], lid), seg(p[2], p[3], lid),
            seg(p[3], (x + gap, y), lid)]


def area(s):
    return pathops.shape_area(s).area


# ---------------------------------------------------------------- Optionen
def test_defaults_are_all_off_and_return_the_same_objects():
    o = ImportOptions()
    assert not o.active and o.describe() == "aus"
    assert o.join_tolerance_mm == pytest.approx(0.05)
    parts = square_segments(0, 0, 10) + [poly(sq(20, 0, 10)), poly(sq(22, 2, 2))]
    for opts in (None, o, ImportOptions(join_tolerance_mm=1.0)):
        res = clean_import(parts, opts)
        assert [id(s) for s in res.shapes] == [id(s) for s in parts]
        assert not res.changed and res.note() == ""


def test_normalized_clamps_tolerance_and_describe():
    assert ImportOptions(auto_join=True, join_tolerance_mm=99).normalized().join_tolerance_mm == 2.0
    assert ImportOptions(join_tolerance_mm=0).normalized().join_tolerance_mm == 0.001
    assert ImportOptions(join_tolerance_mm=float("nan")).normalized().join_tolerance_mm == 0.05
    assert ImportOptions(join_tolerance_mm="x").normalized().join_tolerance_mm == 0.05
    assert ALL.describe() == "Duplikate löschen, verbinden ≤ 0.05 mm, Löcher kombinieren"
    assert ImportOptions(auto_join=True, join_tolerance_mm=0.2).describe() == "verbinden ≤ 0.2 mm"


def test_settings_round_trip(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    st = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    assert cleanup.load_options(st) == ImportOptions()
    assert cleanup.load_options(None) == ImportOptions()
    cleanup.save_options(st, ImportOptions(True, True, 0.125, False))
    again = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    assert cleanup.load_options(again) == ImportOptions(True, True, 0.125, False)
    again.setValue("import/join_tolerance_mm", "kaputt")
    again.setValue("import/combine_holes", "true")
    assert cleanup.load_options(again) == ImportOptions(True, True, 0.05, True)
    cleanup.save_options(None, ALL)   # ohne QSettings: nichts passiert


# ---------------------------------------------------------------- Duplikate
def test_duplicates_deleted_keeping_the_first():
    a = poly(sq(0, 0, 10))
    b = poly(list(reversed(sq(0, 0, 10))))           # gleiche Kontur rückwärts
    line = seg((0, 20), (30, 20))
    line2 = seg((30, 20), (0, 20))
    other = poly(sq(0, 0, 10), lid="L2")             # andere Ebene bleibt
    res = clean_import([a, b, line, line2, other], ImportOptions(delete_duplicates=True))
    assert res.shapes == [a, line, other]
    assert res.duplicates == 2 and res.changed
    assert res.note() == " · beim Import: 2 Duplikat(e) gelöscht"


def test_duplicates_go_before_joining_so_a_doubled_edge_does_not_chain():
    parts = square_segments(0, 0, 20)
    doubled = parts + [seg((20, 0), (20, 20))]      # zweite Kante rechts doppelt
    res = clean_import(doubled, ImportOptions(delete_duplicates=True, auto_join=True))
    (sq_poly,) = res.shapes
    assert sq_poly.kind == "polygon" and area(sq_poly) == pytest.approx(400)
    assert res.duplicates == 1 and res.joined_pieces == 4 and res.joined_closed == 1
    only_join = clean_import(doubled, ImportOptions(auto_join=True))
    assert len(only_join.shapes) == 2              # die doppelte Strecke bleibt übrig


# ---------------------------------------------------------------- Verbinden
def test_auto_join_closes_segment_soup_and_keeps_group_and_layer():
    parts = square_segments(10, 10, 30) + [seg((100, 0), (120, 0))]
    res = clean_import(parts, ImportOptions(auto_join=True))
    sq_poly, lone = res.shapes
    assert sq_poly.kind == "polygon" and area(sq_poly) == pytest.approx(900)
    assert sq_poly.groups == ("g",) and sq_poly.layer_id == "L1"
    assert lone is parts[-1]                      # nicht verbindbar: unverändert
    assert (res.joined_pieces, res.joined_closed, res.joined_open) == (4, 1, 0)
    assert res.note() == " · beim Import: 4 offene Form(en) verbunden → 1 geschlossen"


def test_auto_join_tolerance():
    gap = square_segments(0, 0, 20, gap=0.3)
    assert clean_import(gap, ImportOptions(auto_join=True)).shapes[0].kind == "path"
    res = clean_import(gap, ImportOptions(auto_join=True, join_tolerance_mm=0.5))
    (closed,) = res.shapes
    assert closed.kind == "polygon" and area(closed) == pytest.approx(400, rel=0.02)


def test_auto_join_open_chain_and_nested_rings():
    chain = [seg((0, 50), (10, 50)), seg((10, 50), (20, 55))]
    outer = square_segments(0, 0, 40)
    inner = square_segments(10, 10, 10)
    res = clean_import(chain + outer + inner, ImportOptions(auto_join=True))
    kinds = sorted(s.kind for s in res.shapes)
    assert kinds == ["path", "polygon"]
    plate = next(s for s in res.shapes if s.kind == "polygon")
    assert len(plate.ring_ranges()) == 2 and area(plate) == pytest.approx(1600 - 100)
    assert res.joined_open == 1 and res.joined_closed == 1
    assert "→ 1 geschlossen, 1 offen" in res.note()


def test_auto_join_keeps_document_order_of_untouched_shapes():
    before = poly(sq(100, 100, 5))
    after = poly(sq(200, 100, 5))
    parts = [before] + square_segments(0, 0, 20) + [after]
    res = clean_import(parts, ImportOptions(auto_join=True))
    assert res.shapes[0] is before and res.shapes[-1] is after and len(res.shapes) == 3


# ---------------------------------------------------------------- Löcher
def test_combine_holes_outer_with_holes_and_islands():
    plate = poly(sq(0, 0, 100))
    hole1 = poly(sq(10, 10, 30))
    island = poly(sq(15, 15, 10))                   # Insel im Loch: eigenes Teil
    hole2 = poly(sq(60, 60, 20))
    other = poly(sq(200, 0, 20))
    res = clean_import([plate, hole1, island, hole2, other], ImportOptions(combine_holes=True))
    combined, isl, oth = res.shapes
    assert combined.kind == "polygon" and len(combined.ring_ranges()) == 3
    assert area(combined) == pytest.approx(10000 - 900 - 400)
    assert combined.groups == ("g",)
    assert isl is island and oth is other
    assert res.holes == 2
    assert res.note() == " · beim Import: 2 Loch-Kontur(en) mit Außenkontur kombiniert"


def test_combine_holes_letter_o_and_order():
    o_outer = poly(sq(0, 0, 10, 14))
    o_inner = poly(sq(3, 3, 4, 8))
    i_bar = poly(sq(12, 0, 2, 14))
    res = clean_import([o_inner, i_bar, o_outer], ImportOptions(combine_holes=True))
    first, second = res.shapes
    assert len(first.ring_ranges()) == 2 and area(first) == pytest.approx(140 - 32)
    assert second is i_bar
    a, b = first.ring_ranges()[0]
    ring0 = first.abs_points()[a:b]
    assert max(x for x, _ in ring0) == pytest.approx(10)   # Außenkontur zuerst


def test_combine_holes_per_layer_and_skips_others():
    plate = poly(sq(0, 0, 50))
    hole_other_layer = poly(sq(10, 10, 10), lid="L2")
    rect = Shape("rect", Geometry(20, 20, 5, 5), "L1")     # kein Polygon: bleibt
    code = poly(sq(30, 30, 5))
    code.generator = {"kind": "qr", "text": "x"}
    already = Shape.from_points("polygon", sq(60, 0, 30) + sq(65, 5, 5), "L1", rings=[4])
    inside_already = poly(sq(70, 20, 3))
    shapes = [plate, hole_other_layer, rect, code, already, inside_already]
    res = clean_import(shapes, ImportOptions(combine_holes=True))
    assert res.shapes == shapes and not res.changed


def test_combine_holes_rotated_part_uses_world_outline():
    plate = poly(sq(0, 0, 40, 10))
    plate.geom.rot = 90.0                     # steht jetzt hochkant um (20, 5)
    hole = poly(sq(18, -10, 4, 4))            # nur in der gedrehten Platte
    res = clean_import([plate, hole], ImportOptions(combine_holes=True))
    (combined,) = res.shapes
    assert area(combined) == pytest.approx(400 - 16)
    miss = poly(sq(30, 2, 4, 4))              # in der ungedrehten Box, nicht in der gedrehten
    res = clean_import([plate, miss], ImportOptions(combine_holes=True))
    assert len(res.shapes) == 2


def test_combine_holes_limit(monkeypatch):
    monkeypatch.setattr(cleanup, "COMBINE_MAX", 2)
    shapes = [poly(sq(0, 0, 50)), poly(sq(10, 10, 5)), poly(sq(30, 30, 5))]
    res = clean_import(shapes, ImportOptions(combine_holes=True))
    assert res.shapes == shapes and res.combine_skipped
    assert res.note() == " · beim Import: über 2 Konturen – Löcher nicht kombiniert"


def test_join_then_combine_holes():
    plate = poly(sq(0, 0, 60))
    hole_segments = square_segments(20, 20, 10)
    res = clean_import([plate] + hole_segments, ALL)
    (combined,) = res.shapes
    assert len(combined.ring_ranges()) == 2 and area(combined) == pytest.approx(3600 - 100)
    assert res.joined_closed == 1 and res.holes == 1
    assert res.note() == (" · beim Import: 4 offene Form(en) verbunden → 1 geschlossen, "
                          "1 Loch-Kontur(en) mit Außenkontur kombiniert")


def test_images_and_empty_lists_untouched():
    img = Shape("image", Geometry(0, 0, 10, 10), "L1")
    res = clean_import([img], ALL)
    assert res.shapes == [img] and not res.changed
    assert clean_import([], ALL).shapes == []
    assert CleanupResult().note() == ""


# ---------------------------------------------------------------- Dateien
def _dxf(tmp_path, doubled=False):
    ezdxf = pytest.importorskip("ezdxf")
    d = ezdxf.new()
    d.header["$INSUNITS"] = 4                    # mm
    msp = d.modelspace()
    lines = [((0, 0), (40, 0)), ((40, 0), (40, 30)), ((40, 30), (0, 30)), ((0, 30), (0, 0)),
             ((10, 10), (20, 10)), ((20, 10), (20, 20)), ((20, 20), (10, 20)), ((10, 20), (10, 10)),
             ((100, 0), (120, 0))]
    if doubled:
        lines.append(((40, 0), (40, 30)))
    for a, b in lines:
        msp.add_line(a, b)
    p = tmp_path / "plate.dxf"
    d.saveas(p)
    return p


def test_dxf_segment_soup_becomes_plate_with_hole(tmp_path):
    from lumacut_import.placement import import_file
    res = import_file(_dxf(tmp_path, doubled=True), "L1")
    assert len(res.shapes) == 10
    out = clean_import(res.shapes, ALL)
    plate, lone = out.shapes
    assert plate.kind == "polygon" and len(plate.ring_ranges()) == 2
    b = plate.bounds()
    assert (b.w, b.h) == pytest.approx((40, 30))
    assert area(plate) == pytest.approx(1200 - 100)
    assert lone.kind == "path"
    assert out.duplicates == 1 and out.joined_pieces == 8


def test_svg_letter_with_hole(tmp_path):
    from lumacut_import.placement import import_file
    p = tmp_path / "o.svg"
    p.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="40mm" '
                 'viewBox="0 0 40 40"><path d="M0 0 H30 V30 H0 Z M10 10 V20 H20 V10 Z"/></svg>')
    res = import_file(p, "L1")
    assert len(res.shapes) == 2
    (o,) = clean_import(res.shapes, ImportOptions(combine_holes=True)).shapes
    assert area(o) == pytest.approx(900 - 100, rel=1e-5)


def test_gcode_of_combined_plate_passes_the_pi_guard(tmp_path):
    from lumacut_import.placement import import_file
    from lumacut_job.planner import optimized_document_gcode
    res = import_file(_dxf(tmp_path), "L1")
    doc = Document()
    lid = doc.layers[0].id
    for s in clean_import(res.shapes, ALL).shapes:
        s.layer_id = lid
        doc.add_shape(s)
    gcode = optimized_document_gcode(doc)
    pi_check(gcode)
    assert not any(ln.split()[0] in ("G2", "G3") for ln in gcode.splitlines() if ln.strip())


# ---------------------------------------------------------------- Hauptfenster
@pytest.fixture()
def win(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    w.import_tools.settings = QSettings(str(tmp_path / "import.ini"), QSettings.IniFormat)
    w.import_tools.set_options(ImportOptions())
    yield w
    w.canvas.undo_stack.setClean()
    w.close()


def test_file_menu_entry_after_import(win):
    tools = win.import_tools
    texts = [a.text() for a in tools.menu.actions() if a.text()]
    i = texts.index("Importieren …")
    assert texts[i + 1] == "Import-Einstellungen …"
    assert tools.options_action.objectName() == "import_settings_action"
    assert tools.options_action.shortcut().isEmpty()
    assert "derzeit: aus" in tools.options_action.toolTip()


def test_import_without_settings_is_unchanged_and_byte_identical(win, tmp_path):
    from lumacut_import.placement import import_file
    from lumacut_job.planner import optimized_document_gcode
    p = _dxf(tmp_path)
    ids = win.import_tools.import_path(p)
    assert len(ids) == 9
    ed = win.canvas
    gcode = optimized_document_gcode(ed.document)
    ref = Document()
    ref.layers = ed.document.layers
    for s in import_file(p, ed.document.active_layer.id).shapes:
        ref.add_shape(s)
    assert optimized_document_gcode(ref) == gcode


def test_import_with_settings_one_undo_step_and_message(win, tmp_path):
    tools = win.import_tools
    tools.set_options(ALL)
    assert "derzeit: Duplikate löschen, verbinden ≤ 0.05 mm, Löcher kombinieren" in \
        tools.options_action.toolTip()
    msgs = []
    win.canvas.statusMessage.connect(msgs.append)
    ids = tools.import_path(_dxf(tmp_path, doubled=True))
    ed = win.canvas
    assert len(ids) == 2 and ed.selection == ids
    plate = ed.document.shape(ids[0])
    assert plate.kind == "polygon" and len(plate.ring_ranges()) == 2
    assert plate.groups and plate.groups == ed.document.shape(ids[1]).groups
    msg = next(m for m in msgs if m.startswith("Importiert: plate.dxf"))
    assert "· 2 Objekt(e)" in msg
    assert "beim Import: 1 Duplikat(e) gelöscht, 8 offene Form(en) verbunden → 1 geschlossen" in msg
    assert "verkleinert" not in msg
    assert "1 offene Kontur(en)" in msg and "Loch-Kontur(en) als eigene Objekte" not in msg
    assert ed.undo_stack.undoText() == "Importieren"
    ed.undo_stack.undo()
    assert not ed.document.shapes
    ed.undo_stack.redo()
    assert len(ed.document.shapes) == 2


def test_image_import_ignores_settings(win, tmp_path):
    from PySide6.QtGui import QColor, QImage
    win.import_tools.set_options(ALL)
    img = QImage(20, 10, QImage.Format_RGB32)
    img.fill(QColor(0, 0, 0))
    p = tmp_path / "b.png"
    img.save(str(p))
    (iid,) = win.import_tools.import_path(p)
    assert win.canvas.document.shape(iid).kind == "image"


def test_settings_dialog_and_persistence(win, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QDialogButtonBox
    from lumacut_import.cleanup_qt import ImportSettingsDialog
    dlg = ImportSettingsDialog(ImportOptions(auto_join=True, join_tolerance_mm=0.2))
    assert dlg.windowTitle() == "Import-Einstellungen"
    assert dlg.auto_join.isChecked() and dlg.tolerance.isEnabled()
    assert dlg.tolerance.value() == pytest.approx(0.2) and dlg.tolerance.suffix() == " mm"
    assert not dlg.combine_holes.isChecked() and not dlg.delete_duplicates.isChecked()
    dlg.auto_join.setChecked(False)
    assert not dlg.tolerance.isEnabled()
    dlg.combine_holes.setChecked(True)
    dlg.delete_duplicates.setChecked(True)
    assert dlg.options() == ImportOptions(True, False, 0.2, True)
    reset = dlg.buttons.button(QDialogButtonBox.RestoreDefaults)
    assert reset.text() == "Alles aus"
    reset.click()
    assert dlg.options() == ImportOptions()
    for w in (dlg.delete_duplicates, dlg.auto_join, dlg.tolerance, dlg.combine_holes):
        assert w.toolTip()

    tools = win.import_tools
    msgs = []
    win.canvas.statusMessage.connect(msgs.append)
    tools.ask_options = lambda o: None
    assert tools.edit_options() is False and tools.options == ImportOptions()
    tools.ask_options = lambda o: ImportOptions(auto_join=True, join_tolerance_mm=0.1)
    tools.options_action.trigger()
    assert tools.options == ImportOptions(auto_join=True, join_tolerance_mm=0.1)
    assert any("Import-Einstellungen: verbinden ≤ 0.1 mm – gilt ab dem nächsten Import" in m
               for m in msgs)
    stored = QSettings(str(tmp_path / "import.ini"), QSettings.IniFormat)
    assert cleanup.load_options(stored) == ImportOptions(auto_join=True, join_tolerance_mm=0.1)


def test_drop_uses_settings(win, tmp_path):
    win.import_tools.set_options(ImportOptions(auto_join=True))
    win.import_tools.drop_paths([_dxf(tmp_path)], (150.0, 150.0))
    shapes = win.canvas.document.shapes
    assert sorted(s.kind for s in shapes) == ["path", "polygon"]
    plate = next(s for s in shapes if s.kind == "polygon")
    assert len(plate.ring_ranges()) == 2
