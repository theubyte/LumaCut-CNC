"""Material test image cells with an image option on an axis (threshold, halftone
cells / screen angle, brightness, contrast, gamma, sharpen, scan angle): every cell
gets its swept value on top of the grid-wide image options, labels and layer names
show it, validation checks range and image mode, and the dialog offers the axis only
for image cells. Grids without an image axis stay byte-identical."""

import re

import pytest

from _pi_guard import pi_check
from lumacut_canvas.model import Document, ImageSettings
from lumacut_job.material_test import (AXIS_PARAMS, IMAGE_AXIS_DEFAULT_RANGES,
                                       IMAGE_AXIS_PARAMS, IMAGE_OPTION_KEYS,
                                       IMAGE_OPTION_RANGES, TEST_PARAMS, MaterialTestSpec,
                                       add_material_test, build_material_test,
                                       image_axis_mode)
from lumacut_job.planner import optimized_document_gcode


def _cells(spec):
    return [s for s in build_material_test(spec)[1] if s.kind == "image"]


def _cell_layers(spec):
    return [l for l in build_material_test(spec)[0] if l.name != "Test Beschriftung"]


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
    kw.setdefault("image_mode", "floyd")
    return MaterialTestSpec(**kw)


# --- engine -------------------------------------------------------------------------------

def test_axis_params_are_numeric_image_options_with_ranges():
    assert AXIS_PARAMS[:len(TEST_PARAMS)] == TEST_PARAMS
    names = set(ImageSettings.__dataclass_fields__)
    assert set(IMAGE_AXIS_PARAMS) <= names & set(IMAGE_OPTION_KEYS) & set(IMAGE_OPTION_RANGES)
    for k, (lo, hi) in IMAGE_AXIS_DEFAULT_RANGES.items():
        rlo, rhi = IMAGE_OPTION_RANGES[k]
        assert rlo <= lo < hi <= rhi, k
    assert image_axis_mode("threshold") == "threshold"
    assert image_axis_mode("halftone_angle") == "halftone"
    assert image_axis_mode("gamma") == ""


@pytest.mark.parametrize("param, mode, rng, attr_vals", [
    ("threshold", "threshold", (64, 192), [64, 128, 192]),
    ("halftone_cpi", "halftone", (20, 60), [20.0, 40.0, 60.0]),
    ("halftone_angle", "halftone", (0, 45), [0.0, 22.5, 45.0]),
    ("brightness", "grayscale", (-30, 30), [-30.0, 0.0, 30.0]),
    ("contrast", "floyd", (0, 40), [0.0, 20.0, 40.0]),
    ("gamma", "floyd", (0.6, 1.8), [0.6, 1.2, 1.8]),
    ("sharpen", "floyd", (0, 200), [0.0, 100.0, 200.0]),
    ("scan_angle", "grayscale", (0, 90), [0.0, 45.0, 90.0]),
])
def test_column_axis_sweeps_the_image_option(qapp, param, mode, rng, attr_vals):
    spec = _base(image_mode=mode, column_param=param, image_axis_ranges={param: rng})
    spec.validate()
    assert [getattr(c.image.settings, param) for c in _cells(spec)] == attr_vals
    g = _gcode(spec)
    pi_check(g)
    fixed = _base(image_mode=mode, column_param="power")
    assert g != _gcode(fixed)


def test_threshold_values_are_integers():
    spec = _base(image_mode="threshold", column_param="threshold", columns=4,
                 image_axis_ranges={"threshold": (50, 101)})
    vals = spec.column_values()
    assert vals == [50, 67, 84, 101] and all(isinstance(v, int) for v in vals)


def test_default_range_without_explicit_ranges():
    spec = _base(column_param="gamma")
    assert spec.column_values() == [0.6, 1.2, 1.8]


def test_axis_value_overrides_grid_wide_option_others_kept(qapp):
    spec = _base(image_mode="halftone", column_param="halftone_angle", row_param="speed",
                 rows=2, image_axis_ranges={"halftone_angle": (0, 30)},
                 image_options={"halftone_angle": 75.0, "halftone_cpi": 30.0, "gamma": 1.5})
    sts = [c.image.settings for c in _cells(spec)]
    assert [s.halftone_angle for s in sts] == [0.0, 15.0, 30.0] * 2
    assert {s.halftone_cpi for s in sts} == {30.0} and {s.gamma for s in sts} == {1.5}
    assert sorted({s.speed_mm_min for s in sts}) == [600.0, 3000.0]


def test_two_image_axes_sweep_both(qapp):
    spec = _base(image_mode="threshold", column_param="threshold", row_param="gamma",
                 rows=2, image_axis_ranges={"threshold": (100, 200), "gamma": (0.8, 1.6)})
    pairs = [(c.image.settings.threshold, c.image.settings.gamma) for c in _cells(spec)]
    assert pairs == [(100, 0.8), (150, 0.8), (200, 0.8), (100, 1.6), (150, 1.6), (200, 1.6)]
    pi_check(_gcode(spec))


def test_layer_names_and_labels_show_the_swept_value():
    spec = _base(image_mode="grayscale", column_param="brightness", row_param="scan_angle",
                 rows=2, labels=True, image_axis_ranges={"brightness": (-20, 20),
                                                         "scan_angle": (0, 90)})
    names = [l.name for l in _cell_layers(spec)]
    assert len(set(names)) == len(names) == 6
    assert "Test P20% F600 Helligkeit -20% Scan-Winkel 0°" in names
    assert "Test P20% F600 Helligkeit +20% Scan-Winkel 90°" in names
    assert spec.label_texts() == (["-20", "+0", "+20"], ["0", "90"])
    texts = {s.text for s in build_material_test(spec)[1] if s.kind == "text"}
    assert {"-20", "+0", "+20", "0", "90"} <= texts


def test_mixed_axis_keeps_power_speed_in_name():
    spec = _base(image_mode="threshold", column_param="power", row_param="threshold",
                 rows=2, image_axis_ranges={"threshold": (80, 160)})
    names = [l.name for l in _cell_layers(spec)]
    assert "Test P100% F600 Schwellwert 160" in names
    assert all(re.match(r"^Test P\d+(\.\d+)?% F\d+(\.\d+)? Schwellwert \d+$", n) for n in names)


@pytest.mark.parametrize("kw, msg", [
    (dict(image_mode="", column_param="gamma"), "Gamma als Achse nur mit Bild-Testzellen"),
    (dict(image_mode="floyd", column_param="threshold"),
     "Schwellwert-Achse nur im Bildmodus Schwellwert"),
    (dict(image_mode="threshold", column_param="halftone_cpi"),
     "Halbton-Zellen-Achse nur im Bildmodus Halbton"),
    (dict(image_mode="floyd", column_param="gamma", image_axis_ranges={"gamma": (0.1, 2)}),
     "Gamma außerhalb 0.2..5"),
    (dict(image_mode="floyd", column_param="scan_angle",
          image_axis_ranges={"scan_angle": (0, 120)}), "Scan-Winkel außerhalb -90..90"),
    (dict(image_mode="floyd", column_param="gamma", image_axis_ranges={"gamma": (1, 1)}),
     "Gamma von und bis müssen verschieden sein"),
    (dict(image_mode="threshold", column_param="threshold", columns=5,
          image_axis_ranges={"threshold": (100, 102)}),
     "Schwellwert von und bis müssen verschieden sein"),
    (dict(image_mode="floyd", image_axis_ranges={"negative": (0, 1)}),
     "Unbekannte Bild-Achse: negative"),
    (dict(image_mode="floyd", column_param="gamma", image_axis_ranges={"gamma": "x"}),
     "Gamma: von/bis-Zahlen erwartet"),
    (dict(column_param="gamma", row_param="gamma"), "verschiedene Parameter"),
    (dict(column_param="bogus"), "Unbekannter Testparameter"),
])
def test_image_axis_validation(kw, msg):
    with pytest.raises(ValueError, match=msg):
        _base(**kw).validate()


def test_ranges_for_options_not_on_an_axis_are_ignored(qapp):
    plain = _base()
    spare = _base(image_axis_ranges={"gamma": (0.5, 2.0)})
    spare.validate()
    assert _gcode(spare) == _gcode(plain)
    assert [l.name for l in _cell_layers(spare)] == [l.name for l in _cell_layers(plain)]


@pytest.mark.parametrize("kw", [
    dict(image_mode=""), dict(image_mode="", line_interval_mm=0.0),
    dict(image_mode="floyd"), dict(image_mode="threshold", image_options={"threshold": 90}),
    dict(image_mode="halftone", column_param="focus"),
])
def test_grids_without_image_axis_keep_classic_names(kw):
    names = [l.name for l in _cell_layers(_base(**kw))]
    assert all(re.match(r"^Test P\d+(\.\d+)?% F\d+(\.\d+)?$", n) for n in names)


def test_image_axis_survives_save_and_load(qapp, tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    spec = _base(image_mode="halftone", column_param="halftone_cpi", row_param="scan_angle",
                 rows=2, image_axis_ranges={"halftone_cpi": (15, 45), "scan_angle": (0, 45)})
    doc = Document()
    add_material_test(doc, spec)
    back = load_document(save_document(doc, tmp_path / "t.lumacut.json"))
    get = lambda d: sorted((s.image.settings.halftone_cpi, s.image.settings.scan_angle)
                           for s in d.shapes if s.kind == "image")
    assert get(back) == get(doc) and len(set(get(back))) == 6
    assert [l.name for l in back.layers] == [l.name for l in doc.layers]
    assert optimized_document_gcode(back, scan_offsets=None) == optimized_document_gcode(
        doc, scan_offsets=None)


# --- dialog -------------------------------------------------------------------------------

def _enabled(combo, key):
    return combo.model().item(combo.findData(key)).isEnabled()


def test_dialog_offers_image_axes_only_for_image_cells(qapp):
    from lumacut_job.qt_tools import CELL_FILL, CELL_IMAGE, MaterialTestDialog
    dlg = MaterialTestDialog(None)
    for key in IMAGE_AXIS_PARAMS:
        assert dlg.col_param.findData(key) >= 0 and not _enabled(dlg.col_param, key)
    assert all(_enabled(dlg.col_param, k) for k in TEST_PARAMS)
    assert dlg.axis_from[0].isHidden() and dlg.axis_to[1].isHidden()
    dlg.mode.setCurrentIndex(CELL_IMAGE)
    dlg.image_mode.setCurrentIndex(dlg.image_mode.findData("floyd"))
    assert _enabled(dlg.row_param, "gamma") and _enabled(dlg.row_param, "scan_angle")
    assert not _enabled(dlg.row_param, "threshold")
    assert not _enabled(dlg.row_param, "halftone_angle")
    dlg.image_mode.setCurrentIndex(dlg.image_mode.findData("halftone"))
    assert _enabled(dlg.row_param, "halftone_angle") and not _enabled(dlg.row_param, "threshold")
    dlg.mode.setCurrentIndex(CELL_FILL)
    assert not _enabled(dlg.row_param, "gamma")
    dlg.deleteLater()


def test_dialog_image_axis_spins_and_spec(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    from lumacut_job.qt_tools import CELL_IMAGE, MaterialTestDialog
    dlg = MaterialTestDialog(None)
    dlg.mode.setCurrentIndex(CELL_IMAGE)
    dlg.image_mode.setCurrentIndex(dlg.image_mode.findData("threshold"))
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("threshold"))
    lo, hi = dlg.axis_from[0], dlg.axis_to[0]
    assert not lo.isHidden() and not hi.isHidden()
    assert dlg._rows["c_from"].text() == "Schwellwert von"
    assert dlg._rows["cols"].text() == "Spalten (Schwellwert)"
    assert (lo.minimum(), lo.maximum(), lo.decimals()) == (0, 255, 0)
    assert (lo.value(), hi.value()) == IMAGE_AXIS_DEFAULT_RANGES["threshold"]
    assert lo.toolTip()
    # The grid-wide threshold widget is replaced by the axis.
    assert dlg.opt_threshold.isHidden() and not dlg.opt_gamma.isHidden()
    lo.setValue(90)
    hi.setValue(170)
    dlg.opt_threshold.setValue(10)               # hidden: not emitted
    dlg.opt_gamma.setValue(1.4)
    out = dlg.spec()
    assert out.column_param == "threshold"
    assert out.image_axis_ranges == {"threshold": (90, 170)}
    assert out.image_options == {"gamma": 1.4}
    out.validate()
    assert dlg.bb.button(QDialogButtonBox.Ok).isEnabled()
    assert [c.image.settings.threshold for c in _cells(out)][:5] == [90, 110, 130, 150, 170]
    # Switching the axis away and back keeps the entered range.
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("power"))
    assert lo.isHidden() and dlg.spec().image_axis_ranges is None
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("threshold"))
    assert (lo.value(), hi.value()) == (90, 170)
    dlg.deleteLater()


def test_dialog_blocks_bad_image_axes(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    from lumacut_job.qt_tools import CELL_FILL, CELL_IMAGE, MaterialTestDialog
    dlg = MaterialTestDialog(None)
    ok = dlg.bb.button(QDialogButtonBox.Ok)
    dlg.mode.setCurrentIndex(CELL_IMAGE)
    dlg.image_mode.setCurrentIndex(dlg.image_mode.findData("halftone"))
    dlg.row_param.setCurrentIndex(dlg.row_param.findData("halftone_angle"))
    assert ok.isEnabled()
    dlg.image_mode.setCurrentIndex(dlg.image_mode.findData("floyd"))
    assert not ok.isEnabled() and "nur im Bildmodus „Halbton“" in dlg.hint.text()
    dlg.image_mode.setCurrentIndex(dlg.image_mode.findData("halftone"))
    dlg.axis_to[1].setValue(dlg.axis_from[1].value())
    assert not ok.isEnabled() and "von und bis müssen verschieden" in dlg.hint.text()
    dlg.axis_to[1].setValue(30)
    assert ok.isEnabled()
    dlg.mode.setCurrentIndex(CELL_FILL)
    assert not ok.isEnabled() and "nur mit Art „Bild“" in dlg.hint.text()
    dlg.deleteLater()


def test_dialog_reopens_spec_with_image_axis(qapp):
    from lumacut_job.qt_tools import MaterialTestDialog
    spec = MaterialTestSpec(image_mode="grayscale", column_param="gamma", row_param="contrast",
                            columns=4, rows=3,
                            image_axis_ranges={"gamma": (0.5, 2.0), "contrast": (-30.0, 30.0)},
                            image_options={"brightness": 10.0})
    dlg = MaterialTestDialog(None, spec)
    assert (dlg.axis_from[0].value(), dlg.axis_to[0].value()) == (0.5, 2.0)
    assert dlg.axis_from[0].decimals() == 2
    assert (dlg.axis_from[1].value(), dlg.axis_to[1].value()) == (-30.0, 30.0)
    assert dlg.spec() == spec
    dlg.deleteLater()


def test_dialog_untouched_spec_has_no_image_axis(qapp):
    from lumacut_job.qt_tools import CELL_IMAGE, MaterialTestDialog
    dlg = MaterialTestDialog(None)
    assert dlg.spec().image_axis_ranges is None
    dlg.mode.setCurrentIndex(CELL_IMAGE)
    assert dlg.spec().image_axis_ranges is None
    assert dlg.spec() == MaterialTestSpec(image_mode="floyd")
    dlg.deleteLater()
