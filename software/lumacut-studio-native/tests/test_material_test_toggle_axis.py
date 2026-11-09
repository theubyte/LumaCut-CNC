"""Material test image cells with the angle increment or an on / off image option
(negative, bidirectional) on a column / row axis (review round 48): the swept value
reaches every cell and the G-code, an on / off axis has exactly two columns / rows
(aus, an) and no range, an angle-increment axis needs more than one pass, layer
names and labels carry the value, the dialog fixes the count of an on / off axis,
and grids without these axes stay byte-identical."""

import re

import pytest

from _pi_guard import pi_check
from lumacut_canvas.model import Document
from lumacut_job.images import pass_angles
from lumacut_job.material_test import (AXIS_PARAMS, IMAGE_ALL_AXIS_PARAMS,
                                       IMAGE_AXIS_DEFAULT_RANGES, IMAGE_AXIS_PARAMS,
                                       IMAGE_BOOL_AXIS_PARAMS, MaterialTestSpec,
                                       add_material_test, build_material_test)
from lumacut_job.planner import optimized_document_gcode


def _cells(spec):
    return [s for s in build_material_test(spec)[1] if s.kind == "image"]


def _names(spec):
    return [l.name for l in build_material_test(spec)[0] if l.name.startswith("Test P")]


def _gcode(spec):
    doc = Document()
    add_material_test(doc, spec)
    return re.sub(r"^; IMAGE \w+", "; IMAGE id", optimized_document_gcode(doc, scan_offsets=None),
                  flags=re.M)


def _base(**kw):
    kw.setdefault("columns", 2)
    kw.setdefault("rows", 1)
    kw.setdefault("labels", False)
    kw.setdefault("line_interval_mm", 0.25)
    kw.setdefault("image_mode", "grayscale")
    return MaterialTestSpec(**kw)


# --- engine -------------------------------------------------------------------------------

def test_new_axes_are_offered():
    assert "angle_increment" in IMAGE_AXIS_PARAMS
    assert IMAGE_AXIS_DEFAULT_RANGES["angle_increment"] == (0.0, 90.0)
    assert IMAGE_BOOL_AXIS_PARAMS == ("negative", "bidirectional")
    assert not set(IMAGE_BOOL_AXIS_PARAMS) & set(IMAGE_AXIS_PARAMS)
    assert set(IMAGE_ALL_AXIS_PARAMS) <= set(AXIS_PARAMS)
    spec = _base(column_param="angle_increment", columns=3, passes=2)
    assert spec.column_values() == [0.0, 45.0, 90.0]
    assert _base(column_param="negative").column_values() == [False, True]


@pytest.mark.parametrize("param", IMAGE_BOOL_AXIS_PARAMS)
def test_on_off_axis_reaches_the_cells_and_gcode(qapp, param):
    spec = _base(column_param=param)
    spec.validate()
    assert [getattr(c.image.settings, param) for c in _cells(spec)] == [False, True]
    g = _gcode(spec)
    pi_check(g)
    assert g != _gcode(_base(column_param="power"))
    # Each cell engraves like a plain grid with that option grid-wide.
    for value in (False, True):
        one = _base(columns=1, image_options={param: value})
        assert [getattr(c.image.settings, param) for c in _cells(one)] == [value]


def test_on_off_axis_overrides_grid_wide_value(qapp):
    spec = _base(column_param="bidirectional", image_options={"bidirectional": False,
                                                              "negative": True})
    sts = [c.image.settings for c in _cells(spec)]
    assert [s.bidirectional for s in sts] == [False, True]
    assert {s.negative for s in sts} == {True}


def test_negative_by_bidirectional_two_by_two(qapp):
    spec = _base(column_param="bidirectional", row_param="negative", rows=2, labels=True)
    spec.validate()
    pairs = [(c.image.settings.bidirectional, c.image.settings.negative) for c in _cells(spec)]
    assert pairs == [(False, False), (True, False), (False, True), (True, True)]
    names = _names(spec)
    assert len(set(names)) == 4
    assert "Test P20% F600 Bidirektional aus Negativ an" in names
    assert spec.label_texts() == (["aus", "an"], ["aus", "an"])
    texts = {s.text for s in build_material_test(spec)[1] if s.kind == "text"}
    assert {"aus", "an"} <= texts
    pi_check(_gcode(spec))


def test_angle_increment_axis_turns_later_passes(qapp):
    spec = _base(column_param="angle_increment", columns=3, passes=2,
                 image_options={"scan_angle": 0.0})
    spec.validate()
    sts = [c.image.settings for c in _cells(spec)]
    assert [s.angle_increment for s in sts] == [0.0, 45.0, 90.0]
    assert [pass_angles(s) for s in sts] == [[0.0, 0.0], [0.0, 45.0], [0.0, 90.0]]
    assert "Test P20% F600 Winkel-Schritt 45°" in _names(spec)
    g = _gcode(spec)
    pi_check(g)
    assert g != _gcode(_base(column_param="power", columns=3, passes=2))


def test_angle_increment_with_scan_angle_and_passes_axis(qapp):
    spec = _base(column_param="angle_increment", row_param="passes", rows=2, passes=1,
                 passes_max=3, image_axis_ranges={"angle_increment": (30, 60)},
                 image_options={"scan_angle": 45.0})
    spec.validate()
    got = [(c.image.settings.passes, c.image.settings.angle_increment) for c in _cells(spec)]
    assert got == [(1, 30.0), (1, 60.0), (3, 30.0), (3, 60.0)]
    assert pass_angles(_cells(spec)[3].image.settings) == [45.0, -75.0, -15.0]


@pytest.mark.parametrize("kw, msg", [
    (dict(column_param="negative", columns=3), "Negativ-Achse braucht genau 2 Spalten"),
    (dict(row_param="bidirectional", rows=1), "Bidirektional-Achse braucht genau 2 Zeilen"),
    (dict(image_mode="", column_param="negative"), "Negativ als Achse nur mit Bild-Testzellen"),
    (dict(column_param="angle_increment", columns=3), "braucht mehr als einen Durchgang"),
    (dict(column_param="angle_increment", row_param="passes", passes=1, passes_max=1),
     "braucht mehr als einen Durchgang"),
    (dict(column_param="angle_increment", passes=2,
          image_axis_ranges={"angle_increment": (0, 120)}), "Winkel-Schritt außerhalb -90..90"),
    (dict(column_param="angle_increment", passes=2,
          image_axis_ranges={"angle_increment": (15, 15)}), "von und bis müssen verschieden"),
    (dict(image_axis_ranges={"bidirectional": (0, 1)}), "Unbekannte Bild-Achse: bidirectional"),
])
def test_validation(kw, msg):
    with pytest.raises(ValueError, match=msg):
        _base(**kw).validate()


def test_grids_without_new_axes_keep_names(qapp):
    spec = _base(columns=3, passes=2, image_options={"negative": True, "bidirectional": False,
                                                     "angle_increment": 90.0})
    assert all(re.match(r"^Test P\d+(\.\d+)?% F\d+(\.\d+)?$", n) for n in _names(spec))
    assert {c.image.settings.angle_increment for c in _cells(spec)} == {90.0}


def test_save_load_round_trip(qapp, tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    spec = _base(column_param="negative", row_param="angle_increment", rows=2, passes=2,
                 image_axis_ranges={"angle_increment": (0, 90)})
    doc = Document()
    add_material_test(doc, spec)
    back = load_document(save_document(doc, tmp_path / "t.lumacut.json"))
    sts = sorted((s.image.settings.negative, s.image.settings.angle_increment)
                 for s in back.shapes if s.kind == "image")
    assert sts == [(False, 0.0), (False, 90.0), (True, 0.0), (True, 90.0)]
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


def _enabled(combo, key):
    return combo.model().item(combo.findData(key)).isEnabled()


def test_dialog_offers_new_axes_only_for_image_cells(qapp):
    from lumacut_job.qt_tools import CELL_FILL, MaterialTestDialog
    dlg = MaterialTestDialog(None)
    for key in ("angle_increment",) + IMAGE_BOOL_AXIS_PARAMS:
        i = dlg.col_param.findData(key)
        assert i >= 0 and dlg.col_param.itemText(i).endswith("(Bild)")
        assert not _enabled(dlg.col_param, key)
    dlg.deleteLater()
    dlg = _dialog()
    for key in ("angle_increment",) + IMAGE_BOOL_AXIS_PARAMS:
        assert _enabled(dlg.col_param, key) and _enabled(dlg.row_param, key)
    dlg.mode.setCurrentIndex(CELL_FILL)
    assert not _enabled(dlg.row_param, "negative")
    dlg.deleteLater()


def test_dialog_on_off_axis_fixes_two_columns(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    dlg = _dialog()
    ok = dlg.bb.button(QDialogButtonBox.Ok)
    dlg.cols.setValue(5)
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("bidirectional"))
    assert dlg.cols.value() == 2 and not dlg.cols.isEnabled()
    assert dlg._rows["cols"].text() == "Spalten (Bidirektional)"
    assert dlg.axis_from[0].isHidden() and dlg.axis_to[0].isHidden()
    dlg.opt_more.setChecked(True)
    assert dlg.opt_bidirectional.isHidden() and not dlg.opt_overscan.isHidden()
    dlg.opt_bidirectional.setChecked(False)       # hidden: not emitted
    out = dlg.spec()
    assert out.column_param == "bidirectional" and out.columns == 2
    assert out.image_axis_ranges is None
    assert not out.image_options or "bidirectional" not in out.image_options
    out.validate()
    assert ok.isEnabled()
    # Negativ on the rows as well; the grid-wide checkbox disappears.
    dlg.row_param.setCurrentIndex(dlg.row_param.findData("negative"))
    assert dlg.rows.value() == 2 and not dlg.rows.isEnabled() and dlg.opt_negative.isHidden()
    dlg.spec().validate()
    # Back to power: the count can be changed again.
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("power"))
    assert dlg.cols.isEnabled() and dlg.cols.value() == 2
    dlg.deleteLater()


def test_dialog_angle_increment_axis_needs_passes(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    dlg = _dialog("floyd")
    ok = dlg.bb.button(QDialogButtonBox.Ok)
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("angle_increment"))
    lo, hi = dlg.axis_from[0], dlg.axis_to[0]
    assert dlg._rows["c_from"].text() == "Winkel-Schritt von"
    assert (lo.value(), hi.value()) == (0.0, 90.0)
    assert lo.suffix() == " °" and lo.singleStep() == 15
    assert not ok.isEnabled() and "mehr als einen Durchgang" in dlg.hint.text()
    dlg.passes.setValue(2)
    assert ok.isEnabled()
    dlg.opt_more.setChecked(True)
    assert dlg.opt_angle_increment.isHidden() and not dlg.opt_scan_angle.isHidden()
    out = dlg.spec()
    assert out.image_axis_ranges == {"angle_increment": (0.0, 90.0)}
    out.validate()
    # A passes axis up to 3 also allows it with one fixed pass.
    dlg.passes.setValue(1)
    assert not ok.isEnabled()
    dlg.row_param.setCurrentIndex(dlg.row_param.findData("passes"))
    dlg.passes_max.setValue(3)
    assert ok.isEnabled()
    dlg.spec().validate()
    dlg.deleteLater()


def test_dialog_reopens_toggle_and_increment_axes(qapp):
    from lumacut_job.qt_tools import MaterialTestDialog
    spec = MaterialTestSpec(image_mode="grayscale", column_param="negative", columns=2,
                            row_param="angle_increment", rows=3, passes=2,
                            image_axis_ranges={"angle_increment": (15.0, 75.0)})
    dlg = MaterialTestDialog(None, spec)
    assert not dlg.cols.isEnabled() and dlg.cols.value() == 2
    assert (dlg.axis_from[1].value(), dlg.axis_to[1].value()) == (15.0, 75.0)
    assert dlg.spec() == spec
    dlg.deleteLater()
