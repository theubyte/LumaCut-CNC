"""Material test image cells with the remaining image settings (sharpen, black /
white point, tone curve, dot width correction, scan angle / angle increment,
bidirectional, overscan): every image cell gets them, the dialog shows them under
„Weitere Bildoptionen“ and emits only changed values. Default (no options) keeps
the image cells byte-identical."""

import re

import pytest

from _pi_guard import pi_check
from lumacut_canvas.model import Document, ImageSettings
from lumacut_job.material_test import (IMAGE_EXTRA_OPTIONS, IMAGE_OPTION_KEYS,
                                       IMAGE_OPTION_RANGES, MaterialTestSpec, add_material_test,
                                       build_material_test)
from lumacut_job.planner import optimized_document_gcode

S_CURVE = ((0, 0), (64, 44), (192, 212), (255, 255))


def _cells(spec):
    return [s for s in build_material_test(spec)[1] if s.kind == "image"]


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
    kw.setdefault("image_mode", "floyd")
    return MaterialTestSpec(**kw)


# --- engine -------------------------------------------------------------------------------

def test_extra_options_are_image_settings_fields_with_ranges():
    names = set(ImageSettings.__dataclass_fields__)
    assert set(IMAGE_EXTRA_OPTIONS) <= names
    assert set(IMAGE_EXTRA_OPTIONS) <= set(IMAGE_OPTION_KEYS)
    assert set(IMAGE_EXTRA_OPTIONS) - {"curve", "bidirectional"} <= set(IMAGE_OPTION_RANGES)


@pytest.mark.parametrize("mode", ["floyd", "grayscale", "threshold", "halftone", "depth3d"])
def test_default_valued_extra_options_keep_cells_byte_identical(qapp, mode):
    d = ImageSettings()
    same = {k: getattr(d, k) for k in IMAGE_EXTRA_OPTIONS}
    assert _gcode(_base(image_mode=mode, image_options=same)) == _gcode(_base(image_mode=mode))


@pytest.mark.parametrize("opts", [
    {"sharpen": 120.0, "sharpen_radius": 2.0},
    {"black_point": 30, "white_point": 220},
    {"curve": S_CURVE},
    {"dot_width_mm": 0.1},
    {"scan_angle": 45.0},
    {"bidirectional": False},
    {"overscan_mm": 1.0},
])
def test_each_extra_option_reaches_every_cell_and_changes_gcode(qapp, opts):
    spec = _base(image_options=opts)
    for c in _cells(spec):
        st = c.image.settings
        for k, v in opts.items():
            assert getattr(st, k) == v, k
    g = _gcode(spec)
    pi_check(g)
    assert g != _gcode(_base())


@pytest.mark.parametrize("mode", ["grayscale", "halftone", "depth3d"])
def test_extra_options_apply_to_every_mode(qapp, mode):
    opts = {"black_point": 20, "curve": S_CURVE, "scan_angle": 30.0, "overscan_mm": 2.0}
    spec = _base(image_mode=mode, columns=1, image_options=opts)
    st = _cells(spec)[0].image.settings
    assert (st.black_point, st.curve, st.scan_angle, st.overscan_mm) == (20, S_CURVE, 30.0, 2.0)
    pi_check(_gcode(spec))


def test_scan_angle_gives_oblique_rows(qapp):
    g = _gcode(_base(columns=1, image_options={"scan_angle": 90.0}))
    # 90°: rows along Y -> lit G1 moves change Y, not X.
    lit = [ln for ln in g.splitlines() if ln.startswith("G1") and re.search(r" S[1-9]", ln)]
    assert lit and all("Y" in ln for ln in lit)


def test_unidirectional_and_overscan_change_the_moves(qapp):
    def directions(g):
        """Signs of the X steps of lit G1 moves."""
        signs, x = set(), None
        for ln in g.splitlines():
            m = re.search(r"X(-?[\d.]+)", ln)
            if not ln.startswith(("G0", "G1")) or not m:
                continue
            nx = float(m.group(1))
            if ln.startswith("G1") and re.search(r" S[1-9]", ln) and x is not None and nx != x:
                signs.add(nx > x)
            x = nx
        return signs
    bi = _gcode(_base(columns=1))
    uni = _gcode(_base(columns=1, image_options={"bidirectional": False}))
    assert directions(bi) == {True, False}
    assert len(directions(uni)) == 1                    # every row in the same direction
    no_os = _gcode(_base(columns=1, image_options={"overscan_mm": 0.0}))
    assert len(no_os.splitlines()) < len(bi.splitlines())


def test_curve_lists_are_normalised():
    spec = _base(image_options={"curve": [[0, 0], [128, 168], [255, 255]]})
    assert spec.image_overrides()["curve"] == ((0, 0), (128, 168), (255, 255))
    linear = _base(image_options={"curve": [[0, 0], [255, 255]]})
    assert linear.image_overrides()["curve"] == ()


@pytest.mark.parametrize("opts, msg", [
    ({"sharpen": 600}, "Schärfen außerhalb"),
    ({"sharpen_radius": 0.1}, "Schärferadius außerhalb"),
    ({"black_point": 255}, "Schwarzpunkt außerhalb"),
    ({"white_point": 0}, "Weißpunkt außerhalb"),
    ({"black_point": 200, "white_point": 100}, "Schwarzpunkt muss kleiner"),
    ({"scan_angle": 95}, "Scan-Winkel außerhalb"),
    ({"angle_increment": -91}, "Winkel-Schritt außerhalb"),
    ({"overscan_mm": 25}, "Overscan außerhalb"),
    ({"dot_width_mm": 0.3}, "Punktbreitenkorrektur 0.3 mm > kleinster Linienabstand 0.25"),
    ({"curve": [[0, 0], [300, 10]]}, "Kurve: Punkte 0..255"),
    ({"curve": [[0, 0]]}, "Kurve: 2.."),
    ({"curve": [[100, 0], [50, 10]]}, "Eingänge aufsteigend"),
    ({"curve": "abc"}, "Kurve: Punkte"),
])
def test_extra_option_validation(opts, msg):
    with pytest.raises(ValueError, match=msg):
        _base(image_options=opts).validate()


def test_dot_width_checked_against_the_smallest_interval_on_an_axis():
    spec = _base(column_param="interval", line_interval_mm=0.3, interval_max=0.1,
                 image_options={"dot_width_mm": 0.15})
    assert spec.min_interval() == pytest.approx(0.1)
    with pytest.raises(ValueError, match="Punktbreitenkorrektur"):
        spec.validate()
    _base(column_param="interval", line_interval_mm=0.3, interval_max=0.2,
          image_options={"dot_width_mm": 0.15}).validate()


def test_extra_options_survive_save_and_load(qapp, tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    opts = {"curve": S_CURVE, "scan_angle": 30.0, "angle_increment": 90.0, "sharpen": 50.0,
            "black_point": 15, "white_point": 230, "dot_width_mm": 0.05,
            "bidirectional": False, "overscan_mm": 1.5}
    spec = _base(passes=2, image_options=opts)
    doc = Document()
    add_material_test(doc, spec)
    back = load_document(save_document(doc, tmp_path / "t.lumacut.json"))
    sts = [s.image.settings for s in back.shapes if s.kind == "image"]
    assert sts and all(getattr(st, k) == v for st in sts for k, v in opts.items())
    assert optimized_document_gcode(back, scan_offsets=None) == optimized_document_gcode(
        doc, scan_offsets=None)


# --- dialog -------------------------------------------------------------------------------

def _visible(dlg):
    return {k for k, w in dlg._opt_widgets.items() if not w.isHidden()}


def test_dialog_more_checkbox_shows_extra_rows(qapp):
    from lumacut_job.qt_tools import CELL_FILL, CELL_IMAGE, MaterialTestDialog
    dlg = MaterialTestDialog(None)
    assert dlg.opt_more.isHidden() and not dlg.opt_more.isChecked()
    dlg.mode.setCurrentIndex(CELL_IMAGE)
    assert not dlg.opt_more.isHidden()
    assert not _visible(dlg) & set(IMAGE_EXTRA_OPTIONS)
    dlg.opt_more.setChecked(True)
    assert set(IMAGE_EXTRA_OPTIONS) <= _visible(dlg)
    assert all(not dlg._rows[dlg._opt_rows[k]].isHidden() for k in IMAGE_EXTRA_OPTIONS)
    assert not dlg.opt_sharpen_radius.isEnabled()     # sharpen 0 -> radius off
    dlg.opt_sharpen.setValue(50)
    assert dlg.opt_sharpen_radius.isEnabled()
    assert dlg.spec().image_options == {"sharpen": 50.0}
    dlg.mode.setCurrentIndex(CELL_FILL)
    assert dlg.opt_more.isHidden() and not _visible(dlg)
    assert all(dlg._opt_widgets[k].toolTip() for k in IMAGE_EXTRA_OPTIONS)
    assert dlg.opt_more.toolTip()
    dlg.deleteLater()


def test_dialog_round_trips_changed_extra_options_only(qapp):
    from lumacut_job.qt_tools import CELL_IMAGE, MaterialTestDialog
    dlg = MaterialTestDialog(None)
    dlg.mode.setCurrentIndex(CELL_IMAGE)
    dlg.opt_more.setChecked(True)
    assert dlg.spec().image_options is None           # untouched -> None
    dlg.opt_scan_angle.setValue(45)
    dlg.opt_bidirectional.setChecked(False)
    dlg.opt_curve.setCurrentIndex(1)                  # S-Kurve
    dlg.opt_black.setValue(10)
    out = dlg.spec()
    assert out.image_options == {"scan_angle": 45.0, "bidirectional": False,
                                 "curve": S_CURVE, "black_point": 10}
    out.validate()
    assert {c.image.settings.scan_angle for c in _cells(out)} == {45.0}
    # Off again: the extra values are not applied.
    dlg.opt_more.setChecked(False)
    assert dlg.spec().image_options is None
    # A spec with extra options reopens with the checkbox on and the values set.
    custom = ((0, 10), (128, 100), (255, 250))
    spec = MaterialTestSpec(image_mode="grayscale",
                            image_options={"curve": custom, "overscan_mm": 1.5,
                                           "dot_width_mm": 0.05, "white_point": 240,
                                           "contrast": 10.0})
    again = MaterialTestDialog(None, spec)
    assert again.opt_more.isChecked()
    assert again.opt_curve.currentText() == "Benutzerdefiniert"
    assert (again.opt_overscan.value(), again.opt_dot_width.value(),
            again.opt_white.value()) == (1.5, 0.05, 240)
    assert again.spec() == spec
    dlg.deleteLater()
    again.deleteLater()


def test_dialog_blocks_bad_levels_and_dot_width(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    from lumacut_job.qt_tools import CELL_IMAGE, MaterialTestDialog
    dlg = MaterialTestDialog(None)
    dlg.mode.setCurrentIndex(CELL_IMAGE)
    ok = dlg.bb.button(QDialogButtonBox.Ok)
    dlg.opt_white.setValue(100)
    dlg.opt_black.setValue(150)
    assert ok.isEnabled()                             # hidden (checkbox off): not applied
    dlg.opt_more.setChecked(True)
    assert not ok.isEnabled() and "Schwarzpunkt" in dlg.hint.text()
    dlg.opt_black.setValue(50)
    assert ok.isEnabled()
    dlg.interval.setValue(0.1)
    dlg.opt_dot_width.setValue(0.15)
    assert not ok.isEnabled() and "Punktbreitenkorrektur" in dlg.hint.text()
    dlg.interval.setValue(0.2)
    assert ok.isEnabled()
    dlg.deleteLater()
