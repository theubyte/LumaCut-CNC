"""Material test with a chosen parameter per axis (LightBurn Material Test X / Y
parameter, Interval Test): power, speed, line interval or passes."""

import hashlib

import pytest

from _pi_guard import pi_check
from lumacut_canvas.document_io import load_document, save_document
from lumacut_canvas.gcode import document_to_gcode
from lumacut_canvas.model import Document
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM
from lumacut_job.estimate import estimate_gcode
from lumacut_job.material_test import (TEST_PARAMS, MaterialTestSpec, add_material_test,
                                       build_material_test)
from lumacut_job.planner import optimized_document_gcode


def _cells(layers):
    return [l for l in layers if l.name.startswith("Test P")]


def _cell_grid(spec):
    """Cell layers in grid order (row by row from the top-left)."""
    layers, shapes = build_material_test(spec)
    cells = list(reversed(_cells(layers)))
    return cells, layers, shapes


def _hatch_rows(shape):
    """Number of distinct y values of a serpentine cell (= rows of the hatch)."""
    return len({round(p[1], 6) for p in shape.points})


# --- spec ---------------------------------------------------------------------------------

def test_defaults_are_the_classic_power_by_speed_grid():
    s = MaterialTestSpec()
    assert (s.column_param, s.row_param) == ("power", "speed")
    assert s.column_values() == s.powers() and s.row_values() == s.speeds()
    assert s.cell_settings(1, 2) == {"power": s.powers()[2], "speed": s.speeds()[1],
                                     "interval": 0.2, "passes": 1}
    assert s.label_width() == s.label_mm + 2


def test_param_values_for_every_parameter():
    s = MaterialTestSpec(line_interval_mm=0.05, interval_max=0.25, passes=1, passes_max=4)
    assert s.param_values("interval", 5) == [0.05, 0.1, 0.15, 0.2, 0.25]
    assert s.param_values("passes", 4) == [1, 2, 3, 4]
    assert s.param_values("passes", 3) == [1, 2, 4]          # 2.5 -> 2 (banker's), ints only
    assert all(isinstance(v, int) for v in s.param_values("passes", 6))
    assert s.param_values("interval", 1) == [0.05]
    with pytest.raises(ValueError):
        s.param_values("frequency", 3)


def test_off_axis_parameters_take_their_fixed_value():
    s = MaterialTestSpec(column_param="interval", row_param="passes", power_min=35,
                         power_max=90, speed_min=1200, speed_max=3000, columns=3, rows=2,
                         line_interval_mm=0.1, interval_max=0.3, passes=1, passes_max=2)
    assert s.cell_settings(0, 0) == {"power": 35, "speed": 1200, "interval": 0.1, "passes": 1}
    assert s.cell_settings(1, 2) == {"power": 35, "speed": 1200, "interval": 0.3, "passes": 2}


@pytest.mark.parametrize("kw, msg", [
    (dict(column_param="speed", row_param="speed"), "verschiedene"),
    (dict(column_param="focus"), "Unbekannt"),
    (dict(column_param="interval", line_interval_mm=0), "Füllen"),
    (dict(row_param="interval", interval_max=3.0), "Linienabstand"),
    (dict(row_param="passes", passes_max=31), "Durchgänge"),
    (dict(row_param="passes", passes_max=0), "Durchgänge"),
])
def test_validation_of_axis_parameters(kw, msg):
    with pytest.raises(ValueError, match=msg):
        build_material_test(MaterialTestSpec(**kw))


def test_off_axis_maximum_is_not_validated():
    # interval_max / passes_max only matter on an axis (outline grids keep working).
    build_material_test(MaterialTestSpec(line_interval_mm=0, interval_max=99, passes_max=99,
                                         columns=2, rows=2))


# --- grid ---------------------------------------------------------------------------------

def test_interval_by_power_grid():
    spec = MaterialTestSpec(column_param="interval", row_param="power", columns=4, rows=3,
                            line_interval_mm=0.1, interval_max=0.4, power_min=20,
                            power_max=60, speed_min=2400, cell_mm=8)
    cells, layers, shapes = _cell_grid(spec)
    assert len(cells) == 12
    by_id = {s.layer_id: s for s in shapes if s.kind == "path"}
    for r, power in enumerate([20, 40, 60]):
        for c, interval in enumerate([0.1, 0.2, 0.3, 0.4]):
            layer = cells[r * 4 + c]
            assert (layer.power, layer.speed, layer.passes) == (power, 2400, 1)
            assert layer.line_interval_mm == interval and layer.fill_mode == "none"
            assert _hatch_rows(by_id[layer.id]) == round(8 / interval) + 1


def test_passes_by_speed_grid():
    spec = MaterialTestSpec(column_param="passes", row_param="speed", columns=3, rows=2,
                            passes=1, passes_max=5, speed_min=600, speed_max=1200,
                            power_min=80, line_interval_mm=0)
    cells, _, shapes = _cell_grid(spec)
    assert [(l.passes, l.speed, l.power) for l in cells] == [
        (1, 600, 80), (3, 600, 80), (5, 600, 80), (1, 1200, 80), (3, 1200, 80), (5, 1200, 80)]
    assert {s.kind for s in shapes if s.layer_id in {l.id for l in cells}} == {"rect"}
    # Line interval stays the layer default when it is not tested.
    assert {l.line_interval_mm for l in cells} == {cells[0].__class__.line_interval_mm}


def test_swapped_axes_speed_columns_power_rows():
    spec = MaterialTestSpec(column_param="speed", row_param="power", columns=2, rows=3,
                            speed_min=600, speed_max=1800, power_min=30, power_max=90)
    cells, _, _ = _cell_grid(spec)
    assert [(l.speed, l.power) for l in cells] == [(600, 30), (1800, 30), (600, 60),
                                                   (1800, 60), (600, 90), (1800, 90)]
    assert {l.line_interval_mm for l in cells} == {cells[0].__class__.line_interval_mm}


def test_layer_order_bottom_runs_first_and_names_stay_parsable():
    from lumacut_materials.testgrid import find_test_cells
    spec = MaterialTestSpec(column_param="interval", row_param="passes", columns=3, rows=2,
                            line_interval_mm=0.1, interval_max=0.3, passes_max=3)
    doc = Document()
    layers = add_material_test(doc, spec)
    assert layers[0].name == "Test Beschriftung"
    # Top-left cell is the bottom layer (runs first).
    assert layers[-1].line_interval_mm == 0.1 and layers[-1].passes == 1
    assert len(find_test_cells(doc)) == 6


def test_cells_are_recognized_by_the_material_library_with_layer_passes():
    from lumacut_materials import load_db
    from lumacut_materials.testgrid import find_test_cells, preset_from_test_cell
    doc = Document()
    add_material_test(doc, MaterialTestSpec(column_param="passes", row_param="power", columns=3,
                                            rows=2, passes_max=3, line_interval_mm=0))
    cell = [l for l in find_test_cells(doc) if l.passes == 3][0]
    p = preset_from_test_cell(load_db(), cell, "basswood_plywood", "cut", 3.0)
    assert (p.power_pct, p.speed_mm_min, p.passes) == (cell.power, cell.speed, 3)


# --- labels -------------------------------------------------------------------------------

def test_labels_show_the_axis_values(qapp):
    spec = MaterialTestSpec(column_param="interval", row_param="passes", columns=3, rows=3,
                            line_interval_mm=0.1, interval_max=0.2, passes_max=3)
    _, layers, shapes = _cell_grid(spec)
    label_id = layers[0].id
    texts = [s.text for s in shapes if s.kind == "text" and s.layer_id == label_id]
    assert texts == ["0.1", "0.15", "0.2", "1x", "2x", "3x"]
    assert spec.label_texts() == (["0.1", "0.15", "0.2"], ["1x", "2x", "3x"])


def test_wide_row_labels_widen_the_label_column_and_never_overlap(qapp):
    spec = MaterialTestSpec(column_param="power", row_param="interval", columns=2, rows=3,
                            line_interval_mm=0.05, interval_max=0.125, label_mm=3)
    assert spec.label_width() > spec.label_mm + 2
    _, layers, shapes = _cell_grid(spec)
    label_id = layers[0].id
    row_labels = [s for s in shapes if s.kind == "text" and s.layer_id == label_id
                  and s.geom.x == spec.x]
    cells = [s for s in shapes if s.kind == "path"]
    left = min(s.geom.x for s in cells)
    assert len(row_labels) == 3
    assert all(s.geom.x + s.geom.w < left for s in row_labels)
    w, h = spec.size()
    right = max(s.geom.x + s.geom.w for s in cells)
    assert right == pytest.approx(spec.x + w)


def test_size_checks_the_work_area_with_the_wider_labels():
    spec = MaterialTestSpec(column_param="power", row_param="interval", columns=12, rows=2,
                            line_interval_mm=0.05, interval_max=0.125, cell_mm=25, gap_mm=4)
    w, _ = spec.size()
    spec.x = WORK_WIDTH_MM - w + 0.5
    with pytest.raises(ValueError, match="Arbeitsfläche"):
        build_material_test(spec)
    spec.x = WORK_WIDTH_MM - w
    build_material_test(spec)
    assert spec.y + spec.size()[1] <= WORK_HEIGHT_MM


# --- G-code -------------------------------------------------------------------------------

# SHA-256 of the round-34 output (before axis parameters), labels off (no font dependency).
_OLD_SHA = {
    "default": "da24487e6cc23ef0e427690c5764de502c4e7dcf370d7cd854b2aec86463b8c0",
    "outline": "d243491f4504394081cd79abccb420f59a11544774e699b003ec8fbfb204b0d0",
}


@pytest.mark.parametrize("name, kw", [
    ("default", dict(labels=False)),
    ("outline", dict(labels=False, line_interval_mm=0, columns=3, rows=4, passes=2)),
])
def test_old_grids_are_byte_identical(qapp, name, kw):
    doc = Document()
    add_material_test(doc, MaterialTestSpec(**kw))
    assert hashlib.sha256(document_to_gcode(doc).encode()).hexdigest() == _OLD_SHA[name]


def test_old_grid_with_labels_unchanged_geometry(qapp):
    # Label boxes of the classic grid are exactly the old ones.
    spec = MaterialTestSpec(columns=3, rows=2, speed_min=600, speed_max=1200)
    layers, shapes = build_material_test(spec)
    texts = [(s.text, s.geom.x, s.geom.y, s.geom.w, s.geom.h)
             for s in shapes if s.kind == "text"]
    th, lab, pitch = 3.0, 5.0, 14.0
    assert texts == [("20", 25.0, 20.0, th * 2.4, th), ("60", 39.0, 20.0, th * 2.4, th),
                     ("100", 53.0, 20.0, th * 2.4, th),
                     ("10", 20.0, 25.0 + 3.5, th, th * 0.9), ("20", 20.0, 25.0 + pitch + 3.5, th, th)]
    assert lab == spec.label_width()


@pytest.mark.parametrize("cp, rp", [("interval", "power"), ("passes", "speed"),
                                    ("speed", "interval"), ("passes", "interval")])
def test_all_axis_combinations_are_pi_safe(qapp, cp, rp):
    doc = Document()
    spec = MaterialTestSpec(column_param=cp, row_param=rp, columns=3, rows=2,
                            line_interval_mm=0.1, interval_max=0.3, passes_max=3)
    add_material_test(doc, spec)
    for g in (document_to_gcode(doc), optimized_document_gcode(doc)):
        pi_check(g)
        assert g.count("; LAYER Test P") == 6
    assert estimate_gcode(optimized_document_gcode(doc)).total_time_s > 0


def test_passes_and_interval_change_the_burnt_length(qapp):
    def cut_length(**kw):
        doc = Document()
        add_material_test(doc, MaterialTestSpec(labels=False, columns=3, rows=1, **kw))
        return estimate_gcode(document_to_gcode(doc)).cut_length_mm
    base = cut_length(line_interval_mm=0.2)
    assert cut_length(column_param="passes", row_param="speed", passes_max=3,
                      line_interval_mm=0.2) == pytest.approx(base * 2, rel=1e-6)   # 1+2+3 vs 3x1
    dense = cut_length(column_param="interval", row_param="speed", line_interval_mm=0.1,
                       interval_max=0.1)
    assert dense == pytest.approx(base * 2, rel=0.03)


def test_interval_on_layer_survives_save_and_load(tmp_path):
    doc = Document()
    add_material_test(doc, MaterialTestSpec(column_param="interval", row_param="speed",
                                            columns=2, rows=1, line_interval_mm=0.1,
                                            interval_max=0.3, labels=False))
    path = save_document(doc, tmp_path / "t.lumacut.json")
    back = load_document(path)
    assert sorted(l.line_interval_mm for l in back.layers if l.name.startswith("Test P")) == [0.1, 0.3]
    assert document_to_gcode(back) == document_to_gcode(doc)


def test_test_params_constant():
    assert TEST_PARAMS == ("power", "speed", "interval", "passes")


# --- dialog -------------------------------------------------------------------------------

def test_dialog_round_trip_and_field_enabling(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    from lumacut_job.qt_tools import MaterialTestDialog
    spec = MaterialTestSpec(column_param="interval", row_param="passes", line_interval_mm=0.1,
                            interval_max=0.4, passes=2, passes_max=6, columns=4, rows=3)
    dlg = MaterialTestDialog(None, spec)
    out = dlg.spec()
    assert (out.column_param, out.row_param) == ("interval", "passes")
    assert (out.line_interval_mm, out.interval_max, out.passes, out.passes_max) == (0.1, 0.4, 2, 6)
    assert dlg.interval_max.isEnabled() and dlg.passes_max.isEnabled()
    assert not dlg.p_max.isEnabled() and not dlg.s_max.isEnabled()
    assert dlg._rows["p_min"].text() == "Leistung" and dlg._rows["interval"].text() == "Linienabstand von"
    assert dlg._rows["cols"].text() == "Spalten (Linienabstand)"
    ok = dlg.bb.button(QDialogButtonBox.Ok)
    assert ok.isEnabled() and dlg.hint.isHidden()
    # Same parameter on both axes -> OK disabled with a hint.
    dlg.row_param.setCurrentIndex(dlg.row_param.findData("interval"))
    assert not ok.isEnabled() and "verschiedene" in dlg.hint.text()
    # Interval test with outline mode -> refused.
    dlg.row_param.setCurrentIndex(dlg.row_param.findData("power"))
    assert ok.isEnabled()
    dlg.mode.setCurrentIndex(1)
    assert not ok.isEnabled() and "Füllen" in dlg.hint.text()
    assert not dlg.interval.isEnabled()
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("speed"))
    assert ok.isEnabled() and dlg.s_max.isEnabled() and dlg.p_max.isEnabled()
    assert dlg.spec().line_interval_mm == 0.0
    dlg.deleteLater()


def test_dialog_defaults_are_the_classic_grid(qapp):
    from lumacut_job.qt_tools import MaterialTestDialog
    dlg = MaterialTestDialog(None)
    assert dlg.spec() == MaterialTestSpec()
    outline = MaterialTestDialog(None, MaterialTestSpec(line_interval_mm=0))
    assert outline.mode.currentIndex() == 1 and outline.spec().line_interval_mm == 0
    dlg.deleteLater()
    outline.deleteLater()


def test_job_tools_insert_interval_test_as_one_undo_step(qapp):
    from lumacut_canvas.editor import CanvasEditor
    from lumacut_job.qt_tools import insert_material_test
    ed = CanvasEditor()
    n0 = len(ed.document.layers)
    n = insert_material_test(ed, MaterialTestSpec(column_param="interval", row_param="power",
                                                  columns=3, rows=2, line_interval_mm=0.1,
                                                  interval_max=0.3))
    assert n == 7 and len(ed.document.layers) == n0 + 7
    ed.undo_stack.undo()
    assert len(ed.document.layers) == n0 and not ed.document.shapes
    ed.undo_stack.setClean()
    ed.deleteLater()
