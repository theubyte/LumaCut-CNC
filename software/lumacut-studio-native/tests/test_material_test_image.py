"""Material test with image cells (LightBurn Interval Test "Dithered Image"):
every cell is a white-to-black grey ramp engraved in the chosen image mode with
the cell's power / speed / line interval / passes."""

import hashlib

import numpy as np
import pytest

from _pi_guard import pi_check
from lumacut_canvas.document_io import load_document, save_document
from lumacut_canvas.gcode import document_to_gcode
from lumacut_canvas.model import IMAGE_MODES, Document
from lumacut_job.estimate import estimate_gcode
from lumacut_job.material_test import (RAMP_PX, TEST_IMAGE_MODES, MaterialTestSpec,
                                       add_material_test, build_material_test, ramp_png)
from lumacut_job.planner import optimized_document_gcode
from lumacut_materials import testgrid


def _image_cells(shapes):
    return [s for s in shapes if s.kind == "image"]


def _gcode(spec):
    doc = Document()
    add_material_test(doc, spec)
    return doc, optimized_document_gcode(doc, scan_offsets=None)


# --- ramp image ---------------------------------------------------------------------------

def test_ramp_png_is_a_white_to_black_grey_png(qapp):
    from lumacut_import.image_preview import gray_from_png
    png = ramp_png()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    gray = gray_from_png(png)
    assert gray.shape == (RAMP_PX[1], RAMP_PX[0])
    assert gray[0, 0] == 255 and gray[0, -1] == 0
    assert np.all(np.diff(gray[0].astype(int)) <= 0)        # monotonic white -> black
    assert np.all(gray == gray[0])                            # every row the same
    assert ramp_png() == png                                  # deterministic


# --- spec / build -------------------------------------------------------------------------

def test_default_spec_has_vector_cells():
    s = MaterialTestSpec()
    assert s.image_mode == "" and s.image_min_power == 0.0
    _, shapes = build_material_test(MaterialTestSpec(labels=False))
    assert not _image_cells(shapes)


def test_image_cells_carry_the_cell_settings():
    spec = MaterialTestSpec(image_mode="jarvis", columns=3, rows=2, power_min=20, power_max=60,
                            speed_min=1200, speed_max=2400, line_interval_mm=0.1, passes=2,
                            image_min_power=5, cell_mm=8, gap_mm=2)
    layers, shapes = build_material_test(spec)
    cells = _image_cells(shapes)
    assert len(cells) == 6 and len(shapes) == 6 + 3 + 2      # + labels
    by_layer = {l.id: l for l in layers}
    for s in cells:
        layer = by_layer[s.layer_id]
        st = s.image.settings
        assert st.mode == "jarvis" and st.line_interval_mm == 0.1 and st.min_power == 5
        assert (st.power, st.speed_mm_min, st.passes) == (layer.power, layer.speed, layer.passes)
        assert layer.name == f"Test P{layer.power:g}% F{layer.speed:g}"
        assert (s.geom.w, s.geom.h, s.geom.rot) == (8, 8, 0)
        assert (s.image.px_width, s.image.px_height) == RAMP_PX
    assert {(c.image.settings.power, c.image.settings.speed_mm_min) for c in cells} == {
        (p, f) for p in (20, 40, 60) for f in (1200, 2400)}
    # Same grid positions as the vector cells.
    _, vec = build_material_test(MaterialTestSpec(columns=3, rows=2, cell_mm=8, gap_mm=2,
                                                  power_min=20, power_max=60, speed_min=1200,
                                                  speed_max=2400, line_interval_mm=0.1))
    vec_boxes = sorted((round(s.geom.bounds().x, 6), round(s.geom.bounds().y, 6))
                       for s in vec if s.kind == "path")
    assert sorted((round(s.geom.x, 6), round(s.geom.y, 6)) for s in cells) == vec_boxes


def test_interval_and_passes_axes_go_into_the_image_settings():
    spec = MaterialTestSpec(image_mode="floyd", column_param="interval", row_param="passes",
                            columns=3, rows=2, line_interval_mm=0.1, interval_max=0.3,
                            passes=1, passes_max=2, labels=False)
    layers, shapes = build_material_test(spec)
    got = sorted((s.image.settings.line_interval_mm, s.image.settings.passes)
                 for s in _image_cells(shapes))
    assert got == [(0.1, 1), (0.1, 2), (0.2, 1), (0.2, 2), (0.3, 1), (0.3, 2)]
    # The material library still sees the interval / passes axes on the cell layers.
    doc = Document()
    add_material_test(doc, spec)
    assert testgrid.tested_axes(testgrid.find_test_cells(doc)) == {"interval", "passes"}


@pytest.mark.parametrize("kw, msg", [
    (dict(image_mode="sketch"), "Bildmodus"),
    (dict(image_mode="nope"), "Bildmodus"),
    (dict(image_mode="floyd", line_interval_mm=0), "Linienabstand"),
    (dict(image_mode="floyd", power_min=10, image_min_power=20), "Min.-Leistung"),
])
def test_validation_of_image_cells(kw, msg):
    with pytest.raises(ValueError, match=msg):
        MaterialTestSpec(**kw).validate()


def test_image_modes_offered():
    assert "sketch" not in TEST_IMAGE_MODES
    assert set(TEST_IMAGE_MODES) == set(IMAGE_MODES) - {"sketch"}


# --- G-code -------------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["floyd", "grayscale", "threshold", "halftone", "jarvis"])
def test_image_grid_is_pi_safe_and_runs_cells_before_labels(qapp, mode):
    spec = MaterialTestSpec(image_mode=mode, columns=3, rows=2, line_interval_mm=0.2,
                            power_min=20, power_max=80)
    doc, g = _gcode(spec)
    pi_check(g)
    lines = g.splitlines()
    images = [i for i, l in enumerate(lines) if l.startswith("; IMAGE ")]
    assert len(images) == 6
    label = next(i for i, l in enumerate(lines) if l.startswith("; LAYER Test Beschriftung"))
    assert max(images) < label
    # Top-left cell (bottom layer) runs first.
    first = lines[images[0]].split()[2]
    top_left = min(_image_cells(doc.shapes), key=lambda s: (s.geom.y, s.geom.x))
    assert first == top_left.id
    assert estimate_gcode(g).total_time_s > 0


def test_ramp_power_rises_from_white_to_black_and_tops_at_the_cell_power(qapp):
    spec = MaterialTestSpec(image_mode="grayscale", columns=2, rows=1, power_min=40,
                            power_max=80, line_interval_mm=0.25, labels=False,
                            image_min_power=10)
    _, g = _gcode(spec)
    blocks = g.split("; IMAGE ")[1:]
    assert len(blocks) == 2
    peaks = []
    for block in blocks:
        s = [int(l.rsplit("S", 1)[1]) for l in block.splitlines()
             if l.startswith("G1") and " S" in l]
        lit = [v for v in s if v > 0]
        peaks.append(max(lit))
        assert min(lit) < max(lit) / 2            # a ramp, not a solid block
    # Max S follows the cell power (S0..255 scale on the Pi -> 80 % > 40 %).
    assert peaks[1] > peaks[0] * 1.7


def test_more_power_and_slower_speed_in_the_image_cells_changes_the_gcode(qapp):
    def body(**kw):
        return _gcode(MaterialTestSpec(image_mode="floyd", columns=1, rows=1, labels=False,
                                       line_interval_mm=0.2, **kw))[1]
    a = body(power_min=30, speed_min=1200)
    b = body(power_min=60, speed_min=1200)
    c = body(power_min=30, speed_min=2400)
    assert a != b and a != c
    assert " F1200 " in a and " F2400 " in c


def test_old_vector_grids_stay_byte_identical(qapp):
    # Same SHA as the round-34 grid (test_material_test_params._OLD_SHA["default"]).
    doc = Document()
    add_material_test(doc, MaterialTestSpec(labels=False, image_mode=""))
    assert hashlib.sha256(document_to_gcode(doc).encode()).hexdigest() == (
        "da24487e6cc23ef0e427690c5764de502c4e7dcf370d7cd854b2aec86463b8c0")


def test_image_grid_survives_save_and_load(qapp, tmp_path):
    spec = MaterialTestSpec(image_mode="stucki", columns=2, rows=2, line_interval_mm=0.2,
                            labels=False)
    doc, g = _gcode(spec)
    back = load_document(save_document(doc, tmp_path / "t.lumacut.json"))
    assert [s.image.settings for s in _image_cells(back.shapes)] == [
        s.image.settings for s in _image_cells(doc.shapes)]
    assert optimized_document_gcode(back, scan_offsets=None) == g


# --- dialog -------------------------------------------------------------------------------

def test_dialog_image_cells_round_trip_and_fields(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    from lumacut_job.qt_tools import CELL_FILL, CELL_IMAGE, CELL_OUTLINE, MaterialTestDialog
    dlg = MaterialTestDialog(None)
    assert dlg.mode.currentIndex() == CELL_FILL
    assert dlg.image_mode.isHidden() and dlg._rows["image_min"].isHidden()
    dlg.mode.setCurrentIndex(CELL_IMAGE)
    assert not dlg.image_mode.isHidden() and not dlg.image_min.isHidden()
    assert dlg.interval.isEnabled()
    assert dlg.image_mode.currentData() == "floyd"
    assert dlg.image_mode.findData("sketch") == -1
    dlg.image_mode.setCurrentIndex(dlg.image_mode.findData("grayscale"))
    dlg.image_min.setValue(5)
    out = dlg.spec()
    assert (out.image_mode, out.image_min_power, out.line_interval_mm) == ("grayscale", 5, 0.2)
    ok = dlg.bb.button(QDialogButtonBox.Ok)
    assert ok.isEnabled()
    dlg.image_min.setValue(dlg.p_min.value() + 1)
    assert not ok.isEnabled() and "Min.-Leistung" in dlg.hint.text()
    dlg.image_min.setValue(0)
    assert ok.isEnabled()
    # Interval test with image cells is allowed.
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("interval"))
    assert ok.isEnabled()
    # Back to fill / outline -> no image cells in the spec.
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("power"))
    dlg.mode.setCurrentIndex(CELL_OUTLINE)
    assert dlg.spec().image_mode == "" and dlg.spec().line_interval_mm == 0
    assert dlg.image_mode.isHidden()
    dlg.mode.setCurrentIndex(CELL_FILL)
    assert dlg.spec().image_mode == "" and dlg.spec().image_min_power == 0
    # A spec with image cells opens in image mode.
    again = MaterialTestDialog(None, MaterialTestSpec(image_mode="halftone", image_min_power=3))
    assert again.mode.currentIndex() == CELL_IMAGE
    assert again.spec() == MaterialTestSpec(image_mode="halftone", image_min_power=3)
    dlg.deleteLater()
    again.deleteLater()


def test_job_tools_insert_image_grid_as_one_undo_step(qapp):
    from lumacut_canvas.editor import CanvasEditor
    from lumacut_job.qt_tools import insert_material_test
    ed = CanvasEditor()
    n0 = len(ed.document.layers)
    n = insert_material_test(ed, MaterialTestSpec(image_mode="floyd", columns=2, rows=2))
    assert n == 5 and len(_image_cells(ed.document.shapes)) == 4
    ed.undo_stack.undo()
    assert len(ed.document.layers) == n0 and not ed.document.shapes
    ed.undo_stack.setClean()
    ed.deleteLater()
