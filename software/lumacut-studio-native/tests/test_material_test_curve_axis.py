"""Material test image cells with the tone curve or the 3D-depth options on a column /
row axis (review round 51): a curve axis gives every column / row one curve (presets
by default, an explicit list incl. custom curves otherwise), 3D levels / Z step sweep
like the other numeric image axes with the focus drop checked per cell, the swept
value reaches every cell and the G-code, layer names and labels carry the curve's
short name, the dialog offers a checkable / reorderable curve list, and grids without
these axes stay byte-identical."""

import re

import pytest

from _pi_guard import pi_check
from lumacut_canvas.model import Document, normalize_curve
from lumacut_job.material_test import (AXIS_PARAMS, CURVE_AXIS_PRESETS,
                                       IMAGE_ALL_AXIS_PARAMS, IMAGE_AXIS_DEFAULT_RANGES,
                                       IMAGE_AXIS_PARAMS, IMAGE_CHOICE_AXIS_PARAMS,
                                       MaterialTestSpec, add_material_test,
                                       build_material_test, curve_label)
from lumacut_job.planner import optimized_document_gcode
from lumacut_job.raster import CURVE_PRESETS, CURVE_SHORT_LABELS

S_CURVE = normalize_curve(CURVE_PRESETS["Kontrast verstärken (S-Kurve)"])
SHADOWS = normalize_curve(CURVE_PRESETS["Schatten aufhellen (dunkle Holzstellen)"])
CUSTOM = ((0, 0), (100, 60), (255, 255))


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
    assert IMAGE_CHOICE_AXIS_PARAMS == ("curve",)
    assert {"depth_levels", "z_step_mm"} <= set(IMAGE_AXIS_PARAMS)
    assert set(IMAGE_ALL_AXIS_PARAMS) <= set(AXIS_PARAMS) and "curve" in AXIS_PARAMS
    assert IMAGE_AXIS_DEFAULT_RANGES["depth_levels"] == (4, 16)
    assert IMAGE_AXIS_DEFAULT_RANGES["z_step_mm"] == (0.0, 0.2)
    assert CURVE_AXIS_PRESETS[0] == () and CURVE_AXIS_PRESETS[1] == S_CURVE
    assert len(CURVE_AXIS_PRESETS) == len(CURVE_PRESETS) == len(CURVE_SHORT_LABELS)


def test_presets_shared_with_the_image_dialog(qapp):
    from lumacut_import import curve_widget
    assert curve_widget.CURVE_PRESETS is CURVE_PRESETS


def test_curve_axis_defaults_to_the_first_presets(qapp):
    spec = _base(column_param="curve", columns=4)
    spec.validate()
    assert spec.column_values() == list(CURVE_AXIS_PRESETS[:4])
    assert [c.image.settings.curve for c in _cells(spec)] == list(CURVE_AXIS_PRESETS[:4])
    assert spec.label_texts()[0] == ["Linear", "S", "S+", "Flach"]
    assert "Test P20% F600 Kurve S+" in _names(spec)


def test_curve_axis_reaches_the_gcode(qapp):
    spec = _base(column_param="curve", image_axis_curves=((), S_CURVE))
    spec.validate()
    g = _gcode(spec)
    pi_check(g)
    assert g != _gcode(_base(column_param="power"))
    # Each cell engraves like a one-cell grid with that curve grid-wide.
    for curve in ((), S_CURVE):
        one = _base(columns=1, image_options={"curve": curve})
        assert [c.image.settings.curve for c in _cells(one)] == [curve]
    # Powers per image block: the Linear cell lasers like an untouched image, the
    # S-curve cell differently.
    blocks = [re.findall(r" S(\d+)", b) for b in g.split("; IMAGE id")[1:]]
    plain = [re.findall(r" S(\d+)", b) for b in _gcode(_base(columns=1)).split("; IMAGE id")[1:]]
    assert len(blocks) == 2 and len(plain) == 1
    assert plain[0] in blocks and blocks[0] != blocks[1]


def test_curve_axis_overrides_grid_wide_curve_and_keeps_other_options(qapp):
    spec = _base(column_param="curve", image_axis_curves=(SHADOWS, ()),
                 image_options={"curve": S_CURVE, "gamma": 1.4})
    sts = [c.image.settings for c in _cells(spec)]
    assert [s.curve for s in sts] == [SHADOWS, ()]
    assert {s.gamma for s in sts} == {1.4}


def test_custom_curves_and_row_axis_labels(qapp):
    other = ((0, 0), (200, 120), (255, 255))
    spec = _base(row_param="curve", column_param="power", rows=3, labels=True,
                 image_axis_curves=(CUSTOM, S_CURVE, other))
    spec.validate()
    assert spec.label_texts()[1] == ["Eigene 1", "S", "Eigene 2"]
    assert [c.image.settings.curve for c in _cells(spec)][::2] == [CUSTOM, S_CURVE, other]
    names = _names(spec)
    assert len(set(names)) == 6 and "Test P100% F600 Kurve Eigene 2" in names
    texts = {s.text for s in build_material_test(spec)[1] if s.kind == "text"}
    assert {"Eigene 1", "S", "Eigene 2"} <= texts
    assert spec.label_width() > spec.label_mm + 2      # wide row labels widen the column
    assert curve_label(CUSTOM, 3) == "Eigene 3" and curve_label(()) == "Linear"


def test_curve_by_power_grid(qapp):
    spec = _base(column_param="curve", row_param="power", rows=2, power_max=60,
                 image_axis_curves=([[0, 0], [64, 30], [255, 255]], ()))   # lists (JSON) are fine
    spec.validate()
    got = [(c.image.settings.power, c.image.settings.curve) for c in _cells(spec)]
    assert got == [(20.0, ((0, 0), (64, 30), (255, 255))), (20.0, ()),
                   (60.0, ((0, 0), (64, 30), (255, 255))), (60.0, ())]
    pi_check(_gcode(spec))


def test_depth_axes_sweep_levels_and_z_step(qapp):
    spec = _base(image_mode="depth3d", column_param="z_step_mm", columns=3,
                 row_param="depth_levels", rows=2,
                 image_axis_ranges={"depth_levels": (4, 8), "z_step_mm": (0.0, 0.2)})
    spec.validate()
    got = [(c.image.settings.depth_levels, c.image.settings.z_step_mm) for c in _cells(spec)]
    assert got == [(4, 0.0), (4, 0.1), (4, 0.2), (8, 0.0), (8, 0.1), (8, 0.2)]
    assert "Test P20% F600 Z-Schritt 0.1mm 3D-Stufen 8" in _names(spec)
    assert spec.label_texts() == (["0", "0.1", "0.2"], ["4", "8"])
    g = _gcode(spec)
    pi_check(g)
    assert g != _gcode(_base(image_mode="depth3d", columns=3, rows=2))


def test_depth_axis_checks_the_focus_drop_per_cell(qapp):
    # 16 levels × 0.2 mm = 3.0 mm is the limit; 0.25 mm in the last column breaks it.
    ok = _base(image_mode="depth3d", column_param="depth_levels",
               image_axis_ranges={"depth_levels": (4, 16)}, image_options={"z_step_mm": 0.2})
    ok.validate()
    bad = _base(image_mode="depth3d", column_param="depth_levels",
                image_axis_ranges={"depth_levels": (4, 16)}, image_options={"z_step_mm": 0.25})
    with pytest.raises(ValueError, match="Fokus-Absenkung 3.75 mm > 3 mm .* in einer Testzelle"):
        bad.validate()
    # A swept Z step is checked against the grid-wide levels.
    bad2 = _base(image_mode="depth3d", column_param="z_step_mm",
                 image_axis_ranges={"z_step_mm": (0.1, 0.5)}, image_options={"depth_levels": 8})
    with pytest.raises(ValueError, match="Fokus-Absenkung 3.50 mm"):
        bad2.validate()


@pytest.mark.parametrize("kw, msg", [
    (dict(column_param="curve", columns=1), "Kurven-Achse braucht mindestens 2 Spalten"),
    (dict(column_param="curve", columns=9), "höchstens 8 Vorlagen"),
    (dict(row_param="curve", rows=3, image_axis_curves=((), S_CURVE)),
     "2 Kurven für 3 Zeilen"),
    (dict(column_param="curve", image_axis_curves=(S_CURVE, S_CURVE)), "jede Kurve nur einmal"),
    (dict(column_param="curve", image_axis_curves=((), ((0, 0), (0, 9), (255, 255))))
     , "Eingänge aufsteigend"),
    (dict(column_param="curve", image_axis_curves=5), "Liste von Kurven"),
    (dict(image_mode="", column_param="curve"), "Kurve als Achse nur mit Bild-Testzellen"),
    (dict(column_param="depth_levels"), "3D-Stufen-Achse nur im Bildmodus 3D-Tiefe"),
    (dict(image_mode="depth3d", column_param="depth_levels",
          image_axis_ranges={"depth_levels": (1, 8)}), "3D-Stufen außerhalb 2..64"),
    (dict(image_mode="depth3d", column_param="z_step_mm",
          image_axis_ranges={"z_step_mm": (0.1, 0.1)}), "von und bis müssen verschieden"),
    (dict(image_axis_ranges={"curve": (0, 1)}), "Unbekannte Bild-Achse: curve"),
])
def test_validation(kw, msg):
    with pytest.raises(ValueError, match=msg):
        _base(**kw).validate()


def test_grids_without_new_axes_unchanged(qapp):
    spec = _base(columns=3, image_options={"curve": S_CURVE},
                 image_axis_curves=((), S_CURVE))      # ignored without a curve axis
    spec.validate()
    assert all(re.match(r"^Test P\d+(\.\d+)?% F\d+(\.\d+)?$", n) for n in _names(spec))
    assert {c.image.settings.curve for c in _cells(spec)} == {S_CURVE}
    assert _gcode(spec) == _gcode(_base(columns=3, image_options={"curve": S_CURVE}))
    d3 = _base(image_mode="depth3d", image_options={"z_step_mm": 0.3, "depth_levels": 11})
    d3.validate()
    with pytest.raises(ValueError, match="Fokus-Absenkung 3.30 mm"):
        _base(image_mode="depth3d", image_options={"z_step_mm": 0.3,
                                                   "depth_levels": 12}).validate()


def test_save_load_round_trip(qapp, tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    spec = _base(column_param="curve", row_param="power", rows=2,
                 image_axis_curves=(CUSTOM, SHADOWS))
    doc = Document()
    add_material_test(doc, spec)
    back = load_document(save_document(doc, tmp_path / "t.lumacut.json"))
    curves = sorted(s.image.settings.curve for s in back.shapes if s.kind == "image")
    assert curves == sorted([CUSTOM, CUSTOM, SHADOWS, SHADOWS])
    assert [l.name for l in back.layers] == [l.name for l in doc.layers]
    assert optimized_document_gcode(back, scan_offsets=None) == optimized_document_gcode(
        doc, scan_offsets=None)


# --- dialog -------------------------------------------------------------------------------

def _dialog(mode="grayscale", spec=None):
    from lumacut_job.qt_tools import CELL_IMAGE, MaterialTestDialog
    dlg = MaterialTestDialog(None, spec)
    if spec is None:
        dlg.mode.setCurrentIndex(CELL_IMAGE)
        dlg.image_mode.setCurrentIndex(dlg.image_mode.findData(mode))
    return dlg


def _enabled(combo, key):
    return combo.model().item(combo.findData(key)).isEnabled()


def _check(dlg, row, on):
    from PySide6.QtCore import Qt
    dlg.axis_curves.item(row).setCheckState(Qt.Checked if on else Qt.Unchecked)


def test_dialog_offers_curve_and_depth_axes(qapp):
    from lumacut_job.qt_tools import CELL_FILL, MaterialTestDialog
    dlg = MaterialTestDialog(None)
    for key in ("curve", "depth_levels", "z_step_mm"):
        i = dlg.col_param.findData(key)
        assert i >= 0 and dlg.col_param.itemText(i).endswith("(Bild)")
        assert not _enabled(dlg.col_param, key)
    assert dlg.axis_curves.isHidden()
    dlg.deleteLater()
    dlg = _dialog()
    assert _enabled(dlg.col_param, "curve") and not _enabled(dlg.col_param, "z_step_mm")
    dlg.image_mode.setCurrentIndex(dlg.image_mode.findData("depth3d"))
    assert _enabled(dlg.row_param, "depth_levels") and _enabled(dlg.row_param, "z_step_mm")
    dlg.mode.setCurrentIndex(CELL_FILL)
    assert not _enabled(dlg.row_param, "curve")
    dlg.deleteLater()


def test_dialog_curve_axis_list_sets_the_count(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    dlg = _dialog()
    ok = dlg.bb.button(QDialogButtonBox.Ok)
    dlg.cols.setValue(3)
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("curve"))
    assert not dlg.axis_curves.isHidden() and dlg._rows["axis_curves"].text() == "Kurven (Spalten)"
    assert dlg.axis_curves.count() == len(CURVE_AXIS_PRESETS)
    assert dlg.axis_curves.item(1).text() == "Kontrast verstärken (S-Kurve)"
    assert dlg.axis_curves_checked() == CURVE_AXIS_PRESETS[:3]
    assert dlg.cols.value() == 3 and not dlg.cols.isEnabled()
    assert dlg.axis_from[0].isHidden() and dlg.axis_to[0].isHidden()
    dlg.opt_more.setChecked(True)
    assert dlg.opt_curve.isHidden() and not dlg.opt_sharpen.isHidden()
    # Shadows lifted instead of S+: 3 columns stay, the order follows the list.
    _check(dlg, 2, False)
    _check(dlg, 6, True)
    assert dlg.cols.value() == 3
    out = dlg.spec()
    assert out.column_param == "curve" and out.columns == 3
    assert out.image_axis_curves == ((), S_CURVE, SHADOWS)
    assert not out.image_options or "curve" not in out.image_options
    out.validate()
    assert ok.isEnabled()
    # Fewer than two curves: OK blocked with a hint.
    _check(dlg, 0, False)
    _check(dlg, 1, False)
    assert not ok.isEnabled() and "mindestens 2 Kurven" in dlg.hint.text()
    _check(dlg, 4, True)
    assert ok.isEnabled() and dlg.cols.value() == 2
    # Back to power: count editable, no curve list in the spec.
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("power"))
    assert dlg.cols.isEnabled() and dlg.axis_curves.isHidden()
    assert dlg.spec().image_axis_curves is None
    dlg.deleteLater()


def test_dialog_curve_list_can_be_reordered(qapp):
    dlg = _dialog()
    dlg.row_param.setCurrentIndex(dlg.row_param.findData("curve"))
    assert dlg._rows["axis_curves"].text() == "Kurven (Zeilen)"
    item = dlg.axis_curves.takeItem(0)               # Linear to the end (like a drag)
    dlg.axis_curves.insertItem(dlg.axis_curves.count(), item)
    dlg._update_fields()
    assert dlg.axis_curves_checked()[-1] == ()
    dlg.spec().validate()
    dlg.deleteLater()


def test_dialog_reopens_curve_axis_with_custom_curve(qapp):
    from lumacut_job.qt_tools import MaterialTestDialog
    spec = MaterialTestSpec(image_mode="floyd", column_param="curve", columns=3,
                            image_axis_curves=(SHADOWS, CUSTOM, ()))
    dlg = MaterialTestDialog(None, spec)
    assert [dlg.axis_curves.item(i).text() for i in range(3)] == [
        "Schatten aufhellen (dunkle Holzstellen)", "Benutzerdefiniert 1", "Linear"]
    assert dlg.axis_curves.count() == len(CURVE_AXIS_PRESETS) + 1
    assert not dlg.cols.isEnabled() and dlg.cols.value() == 3
    assert dlg.spec() == spec
    dlg.deleteLater()


def test_dialog_depth_axis_ranges_and_drop_hint(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    dlg = _dialog("depth3d")
    ok = dlg.bb.button(QDialogButtonBox.Ok)
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("depth_levels"))
    lo, hi = dlg.axis_from[0], dlg.axis_to[0]
    assert dlg._rows["c_from"].text() == "3D-Stufen von"
    assert (lo.value(), hi.value()) == (4, 16) and lo.decimals() == 0 and lo.singleStep() == 2
    assert dlg.opt_levels.isHidden() and not dlg.opt_zstep.isHidden()
    assert ok.isEnabled()
    dlg.opt_zstep.setValue(0.25)                      # 15 × 0.25 = 3.75 mm in the last column
    assert not ok.isEnabled() and "in einer Testzelle" in dlg.hint.text()
    hi.setValue(12)                                   # 11 × 0.25 = 2.75 mm
    assert ok.isEnabled()
    out = dlg.spec()
    assert out.image_axis_ranges == {"depth_levels": (4, 12)}
    assert out.image_options == {"z_step_mm": 0.25}
    out.validate()
    dlg.row_param.setCurrentIndex(dlg.row_param.findData("z_step_mm"))
    assert dlg._rows["r_from"].text() == "Z-Schritt von" and dlg.axis_to[1].suffix() == " mm"
    assert (dlg.axis_from[1].value(), dlg.axis_to[1].value()) == (0.0, 0.2)
    dlg.spec().validate()
    dlg.deleteLater()
