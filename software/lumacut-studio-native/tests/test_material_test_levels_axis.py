"""Material test image cells with black point, white point, dot width correction or
overscan on a column / row axis (review round 46): the swept value reaches every
cell, coupled options are checked per cell (black < white point, dot width ≤ the
cell's line interval) in the engine and the dialog, layer names carry the value,
and grids without these axes stay byte-identical."""

import re

import pytest

from _pi_guard import pi_check
from lumacut_canvas.model import Document
from lumacut_job.material_test import (IMAGE_AXIS_DEFAULT_RANGES, IMAGE_AXIS_PARAMS,
                                       MaterialTestSpec, add_material_test,
                                       build_material_test)
from lumacut_job.planner import optimized_document_gcode

NEW_AXES = ("black_point", "white_point", "dot_width_mm", "overscan_mm")


def _cells(spec):
    return [s for s in build_material_test(spec)[1] if s.kind == "image"]


def _gcode(spec):
    doc = Document()
    add_material_test(doc, spec)
    return re.sub(r"^; IMAGE \w+", "; IMAGE id", optimized_document_gcode(doc, scan_offsets=None),
                  flags=re.M)


def _base(**kw):
    kw.setdefault("columns", 3)
    kw.setdefault("rows", 1)
    kw.setdefault("labels", False)
    kw.setdefault("line_interval_mm", 0.25)
    kw.setdefault("image_mode", "grayscale")
    return MaterialTestSpec(**kw)


# --- engine -------------------------------------------------------------------------------

def test_new_axes_are_offered_with_default_ranges():
    assert set(NEW_AXES) <= set(IMAGE_AXIS_PARAMS)
    spec = _base(column_param="black_point", columns=5)
    assert spec.column_values() == [0, 16, 32, 48, 64]
    assert all(isinstance(v, int) for v in spec.column_values())
    spec = _base(column_param="white_point", columns=2)
    assert spec.column_values() == [192, 255]
    assert _base(column_param="dot_width_mm", columns=5).column_values() == [
        0.0, 0.025, 0.05, 0.075, 0.1]
    assert _base(column_param="overscan_mm", columns=3).column_values() == [0.0, 2.5, 5.0]
    assert IMAGE_AXIS_DEFAULT_RANGES["overscan_mm"] == (0.0, 5.0)


@pytest.mark.parametrize("param, mode, rng, vals", [
    ("black_point", "grayscale", (0, 60), [0, 30, 60]),
    ("white_point", "floyd", (180, 240), [180, 210, 240]),
    ("dot_width_mm", "floyd", (0.0, 0.1), [0.0, 0.05, 0.1]),
    ("overscan_mm", "grayscale", (0.0, 4.0), [0.0, 2.0, 4.0]),
])
def test_column_axis_reaches_the_cells_and_gcode(qapp, param, mode, rng, vals):
    spec = _base(image_mode=mode, column_param=param, image_axis_ranges={param: rng})
    spec.validate()
    assert [getattr(c.image.settings, param) for c in _cells(spec)] == vals
    g = _gcode(spec)
    pi_check(g)
    assert g != _gcode(_base(image_mode=mode, column_param="power"))


def test_layer_names_carry_the_swept_value():
    spec = _base(column_param="dot_width_mm", row_param="black_point", rows=2,
                 image_axis_ranges={"dot_width_mm": (0.0, 0.1), "black_point": (0, 40)})
    names = [l.name for l in build_material_test(spec)[0] if l.name.startswith("Test P")]
    assert len(set(names)) == 6
    assert "Test P20% F600 Punktbreitenkorrektur 0.05mm Schwarzpunkt 40" in names
    spec = _base(column_param="overscan_mm", image_axis_ranges={"overscan_mm": (1, 3)})
    names = {l.name for l in build_material_test(spec)[0]}
    assert "Test P20% F600 Overscan 2mm" in names


def test_black_axis_checked_against_grid_wide_white_point():
    spec = _base(column_param="black_point", image_axis_ranges={"black_point": (0, 100)},
                 image_options={"white_point": 80})
    with pytest.raises(ValueError, match="Schwarzpunkt 100 muss kleiner als der Weißpunkt 80"):
        spec.validate()
    spec.image_options = {"white_point": 101}
    spec.validate()
    assert [c.image.settings.white_point for c in _cells(spec)] == [101] * 3


def test_white_axis_checked_against_black_axis_per_cell():
    spec = _base(column_param="black_point", row_param="white_point", rows=2,
                 image_axis_ranges={"black_point": (0, 120), "white_point": (100, 255)})
    with pytest.raises(ValueError, match="in jeder Testzelle"):
        spec.validate()
    spec.image_axis_ranges = {"black_point": (0, 120), "white_point": (121, 255)}
    spec.validate()
    pairs = [(c.image.settings.black_point, c.image.settings.white_point) for c in _cells(spec)]
    assert pairs == [(0, 121), (60, 121), (120, 121), (0, 255), (60, 255), (120, 255)]


def test_swept_white_point_ignores_grid_wide_white_point():
    # The axis value wins, so a conflicting grid-wide white point does not block the grid.
    spec = _base(column_param="white_point", image_axis_ranges={"white_point": (200, 250)},
                 image_options={"black_point": 50, "white_point": 40})
    spec.validate()
    assert [c.image.settings.white_point for c in _cells(spec)] == [200, 225, 250]


def test_dot_width_axis_checked_against_each_cell_interval():
    spec = _base(column_param="dot_width_mm", image_axis_ranges={"dot_width_mm": (0.0, 0.3)})
    with pytest.raises(ValueError, match="Punktbreitenkorrektur 0.3 mm > Linienabstand 0.25"):
        spec.validate()
    # Interval on the other axis: every cell compared with its own interval.
    spec = _base(column_param="dot_width_mm", row_param="interval", rows=2,
                 line_interval_mm=0.1, interval_max=0.3,
                 image_axis_ranges={"dot_width_mm": (0.0, 0.1)})
    spec.validate()
    spec.image_axis_ranges = {"dot_width_mm": (0.0, 0.2)}
    with pytest.raises(ValueError, match="Linienabstand 0.1 mm der Testzelle"):
        spec.validate()


def test_overscan_axis_range_validated():
    spec = _base(column_param="overscan_mm", image_axis_ranges={"overscan_mm": (0, 25)})
    with pytest.raises(ValueError, match="Overscan außerhalb 0..20"):
        spec.validate()


def test_grid_wide_checks_unchanged_without_axis():
    with pytest.raises(ValueError, match="Schwarzpunkt muss kleiner"):
        _base(image_options={"black_point": 90, "white_point": 90}).validate()
    with pytest.raises(ValueError, match="kleinster Linienabstand"):
        _base(image_options={"dot_width_mm": 0.3}).validate()
    assert _base().image_cell_problem() == ""


def test_save_load_round_trip(qapp, tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    spec = _base(column_param="white_point", row_param="overscan_mm", rows=2,
                 image_axis_ranges={"white_point": (200, 240), "overscan_mm": (0.5, 2.5)})
    doc = Document()
    add_material_test(doc, spec)
    back = load_document(save_document(doc, tmp_path / "t.lumacut.json"))
    sts = sorted((s.image.settings.white_point, s.image.settings.overscan_mm)
                 for s in back.shapes if s.kind == "image")
    assert sts == [(200, 0.5), (200, 2.5), (220, 0.5), (220, 2.5), (240, 0.5), (240, 2.5)]
    assert [l.name for l in back.layers] == [l.name for l in doc.layers]
    assert optimized_document_gcode(back, scan_offsets=None) == optimized_document_gcode(
        doc, scan_offsets=None)


# --- dialog -------------------------------------------------------------------------------

def _dialog(mode="grayscale"):
    from lumacut_job.qt_tools import CELL_IMAGE, MaterialTestDialog
    dlg = MaterialTestDialog(None)
    dlg.mode.setCurrentIndex(CELL_IMAGE)
    dlg.image_mode.setCurrentIndex(dlg.image_mode.findData(mode))
    return dlg


def test_dialog_offers_new_axes_with_spins(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    dlg = _dialog()
    for key in NEW_AXES:
        assert dlg.col_param.model().item(dlg.col_param.findData(key)).isEnabled()
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("dot_width_mm"))
    lo, hi = dlg.axis_from[0], dlg.axis_to[0]
    assert dlg._rows["c_from"].text() == "Punktbreitenkorrektur von"
    assert lo.decimals() == 3 and lo.suffix() == " mm" and lo.singleStep() == 0.01
    assert (lo.value(), hi.value()) == (0.0, 0.1)
    dlg.opt_more.setChecked(True)
    assert dlg.opt_dot_width.isHidden() and not dlg.opt_black.isHidden()
    dlg.row_param.setCurrentIndex(dlg.row_param.findData("black_point"))
    assert dlg.axis_from[1].decimals() == 0 and dlg.opt_black.isHidden()
    dlg.axis_to[1].setValue(48)
    out = dlg.spec()
    assert out.image_axis_ranges == {"dot_width_mm": (0.0, 0.1), "black_point": (0, 48)}
    assert out.image_options is None or "black_point" not in out.image_options
    out.validate()
    assert dlg.bb.button(QDialogButtonBox.Ok).isEnabled()
    dlg.deleteLater()


def test_dialog_blocks_black_point_above_white_point(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    dlg = _dialog()
    ok = dlg.bb.button(QDialogButtonBox.Ok)
    dlg.opt_more.setChecked(True)
    dlg.opt_white.setValue(100)
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("black_point"))
    dlg.axis_to[0].setValue(120)
    assert not ok.isEnabled() and "Schwarzpunkt 120" in dlg.hint.text()
    assert "Weißpunkt 100" in dlg.hint.text()
    dlg.axis_to[0].setValue(90)
    assert ok.isEnabled()
    # Grid-wide black point above the grid-wide white point is no longer a problem
    # once the black point is swept (its hidden widget is not emitted).
    dlg.opt_black.setValue(200)
    assert ok.isEnabled()
    dlg.deleteLater()


def test_dialog_blocks_dot_width_above_cell_interval(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    dlg = _dialog("floyd")
    ok = dlg.bb.button(QDialogButtonBox.Ok)
    dlg.interval.setValue(0.1)
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("dot_width_mm"))
    assert ok.isEnabled()
    dlg.axis_to[0].setValue(0.15)
    assert not ok.isEnabled() and "Linienabstand 0.1 mm der Testzelle" in dlg.hint.text()
    dlg.axis_to[0].setValue(0.08)
    assert ok.isEnabled()
    dlg.deleteLater()


def test_dialog_reopens_overscan_axis(qapp):
    from lumacut_job.qt_tools import MaterialTestDialog
    spec = MaterialTestSpec(image_mode="grayscale", column_param="overscan_mm",
                            image_axis_ranges={"overscan_mm": (0.5, 4.5)})
    dlg = MaterialTestDialog(None, spec)
    assert (dlg.axis_from[0].value(), dlg.axis_to[0].value()) == (0.5, 4.5)
    assert dlg.spec() == spec
    dlg.deleteLater()
