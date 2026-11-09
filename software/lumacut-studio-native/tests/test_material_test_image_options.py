"""Material test image cells with the image mode's extra parameters (threshold,
halftone cells / angle, 3D levels / Z step, brightness / contrast / gamma /
negative): the dialog exposes them per mode and every image cell gets them.
Default (no options) keeps the image cells byte-identical."""

import hashlib
import re

import pytest

from _pi_guard import pi_check
from lumacut_canvas.model import Document, ImageSettings
from lumacut_job.material_test import (IMAGE_ADJUST_OPTIONS, IMAGE_MODE_OPTIONS,
                                       IMAGE_OPTION_KEYS, MaterialTestSpec, add_material_test,
                                       build_material_test)
from lumacut_job.planner import optimized_document_gcode


def _cells(spec):
    return [s for s in build_material_test(spec)[1] if s.kind == "image"]


def _gcode(spec):
    doc = Document()
    add_material_test(doc, spec)
    # Shape ids are random per build: normalise the "; IMAGE <id>" comments.
    return re.sub(r"^; IMAGE \w+", "; IMAGE id", optimized_document_gcode(doc, scan_offsets=None),
                  flags=re.M)


def _base(**kw):
    kw.setdefault("columns", 2)
    kw.setdefault("rows", 1)
    kw.setdefault("labels", False)
    kw.setdefault("line_interval_mm", 0.25)
    return MaterialTestSpec(**kw)


# --- engine -------------------------------------------------------------------------------

def test_option_tables_cover_image_settings_fields():
    names = set(ImageSettings.__dataclass_fields__)
    assert set(IMAGE_OPTION_KEYS) <= names
    for keys in IMAGE_MODE_OPTIONS.values():
        assert set(keys) <= set(IMAGE_OPTION_KEYS)
    assert set(IMAGE_ADJUST_OPTIONS) <= set(IMAGE_OPTION_KEYS)


@pytest.mark.parametrize("mode", ["floyd", "grayscale", "threshold", "halftone", "depth3d"])
def test_no_or_empty_options_keep_cells_byte_identical(qapp, mode):
    plain = _gcode(_base(image_mode=mode))
    assert _gcode(_base(image_mode=mode, image_options={})) == plain
    assert _gcode(_base(image_mode=mode, image_options=None)) == plain
    # Default-valued options are also identical.
    d = ImageSettings()
    same = {k: getattr(d, k) for k in IMAGE_OPTION_KEYS}
    assert _gcode(_base(image_mode=mode, image_options=same)) == plain
    assert all(c.image.settings == _cells(_base(image_mode=mode))[i].image.settings
               for i, c in enumerate(_cells(_base(image_mode=mode, image_options=same))))


def test_default_floyd_ramp_grid_sha_is_unchanged(qapp):
    # Guard for the round-38 default image grid: options default to None.
    g = _gcode(MaterialTestSpec(image_mode="floyd", columns=3, rows=2, labels=False))
    g2 = _gcode(MaterialTestSpec(image_mode="floyd", columns=3, rows=2, labels=False,
                                 image_options=None))
    assert hashlib.sha256(g.encode()).hexdigest() == hashlib.sha256(g2.encode()).hexdigest()


def test_threshold_option_goes_into_every_cell_and_changes_gcode(qapp):
    spec = _base(image_mode="threshold", image_options={"threshold": 60})
    assert {c.image.settings.threshold for c in _cells(spec)} == {60}
    assert _gcode(spec) != _gcode(_base(image_mode="threshold"))
    # Lower threshold = fewer dark pixels -> shorter lit length on a ramp.
    assert _lit_mm(_gcode(spec)) < _lit_mm(_gcode(_base(image_mode="threshold")))


def _lit_mm(g):
    """Total X length of lit G0/G1 moves (S > 0)."""
    total, x = 0.0, None
    for line in g.splitlines():
        m = re.search(r"X(-?[\d.]+)", line)
        if not line.startswith(("G0", "G1")) or not m:
            continue
        nx = float(m.group(1))
        s = re.search(r" S(\d+)", line)
        if line.startswith("G1") and s and int(s.group(1)) > 0 and x is not None:
            total += abs(nx - x)
        x = nx
    return total


def test_halftone_cells_and_angle(qapp):
    spec = _base(image_mode="halftone",
                 image_options={"halftone_cpi": 12.0, "halftone_angle": 15.0})
    sts = [c.image.settings for c in _cells(spec)]
    assert {(s.halftone_cpi, s.halftone_angle) for s in sts} == {(12.0, 15.0)}
    g = _gcode(spec)
    pi_check(g)
    assert g != _gcode(_base(image_mode="halftone"))


def test_depth3d_levels_and_z_step(qapp):
    spec = _base(image_mode="depth3d", columns=1,
                 image_options={"depth_levels": 4, "z_step_mm": 0.2})
    st = _cells(spec)[0].image.settings
    assert (st.depth_levels, st.z_step_mm) == (4, 0.2)
    g = _gcode(spec)
    pi_check(g)
    assert g != _gcode(_base(image_mode="depth3d", columns=1))
    assert "G0 Z" in g        # focus follows the slices


def test_adjustments_apply_to_all_modes(qapp):
    opts = {"brightness": 20.0, "contrast": -10.0, "gamma": 1.5, "negative": True}
    spec = _base(image_mode="jarvis", image_options=opts)
    for c in _cells(spec):
        st = c.image.settings
        assert (st.brightness, st.contrast, st.gamma, st.negative) == (20.0, -10.0, 1.5, True)
    assert _gcode(spec) != _gcode(_base(image_mode="jarvis"))


def test_options_of_other_modes_are_ignored(qapp):
    # A threshold / halftone value does not leak into a Floyd grid (stored settings stay clean).
    spec = _base(image_mode="floyd", image_options={"threshold": 10, "halftone_cpi": 9.0,
                                                    "depth_levels": 3})
    assert spec.image_overrides() == {}
    assert _gcode(spec) == _gcode(_base(image_mode="floyd"))
    assert _cells(spec)[0].image.settings == _cells(_base(image_mode="floyd"))[0].image.settings


def test_vector_grid_ignores_options():
    spec = MaterialTestSpec(labels=False, image_options={"threshold": 10})
    assert spec.image_overrides() == {}
    assert not _cells(spec)


@pytest.mark.parametrize("opts, msg", [
    ({"nope": 1}, "Unbekannte Bildoption"),
    ({"threshold": 300}, "Schwellwert außerhalb"),
    ({"halftone_cpi": 2}, "Halbton-Zellen außerhalb"),
    ({"halftone_angle": 120}, "Rasterwinkel außerhalb"),
    ({"gamma": 0.1}, "Gamma außerhalb"),
    ({"brightness": "x"}, "keine Zahl"),
])
def test_option_validation(opts, msg):
    with pytest.raises(ValueError, match=msg):
        _base(image_mode="halftone", image_options=opts).validate()


def test_depth3d_drop_limit():
    ok = _base(image_mode="depth3d", image_options={"depth_levels": 7, "z_step_mm": 0.5})
    ok.validate()                                    # 6 × 0.5 = 3 mm
    with pytest.raises(ValueError, match="Fokus-Absenkung"):
        _base(image_mode="depth3d",
              image_options={"depth_levels": 8, "z_step_mm": 0.5}).validate()


def test_options_survive_save_and_load(qapp, tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    spec = _base(image_mode="halftone", image_options={"halftone_cpi": 20.0, "gamma": 0.8})
    doc = Document()
    add_material_test(doc, spec)
    back = load_document(save_document(doc, tmp_path / "t.lumacut.json"))
    sts = [s.image.settings for s in back.shapes if s.kind == "image"]
    assert {(s.halftone_cpi, s.gamma) for s in sts} == {(20.0, 0.8)}
    assert optimized_document_gcode(back, scan_offsets=None) == optimized_document_gcode(
        doc, scan_offsets=None)


# --- dialog -------------------------------------------------------------------------------

def _visible(dlg):
    return {k for k, w in dlg._opt_widgets.items() if not w.isHidden()}


def test_dialog_shows_parameters_of_the_chosen_mode(qapp):
    from lumacut_job.qt_tools import CELL_FILL, CELL_IMAGE, MaterialTestDialog
    dlg = MaterialTestDialog(None)
    assert _visible(dlg) == set()                     # fill cells: no image options
    dlg.mode.setCurrentIndex(CELL_IMAGE)
    adjust = set(IMAGE_ADJUST_OPTIONS)
    assert _visible(dlg) == adjust                    # floyd: adjustments only
    for mode, extra in (("threshold", {"threshold"}),
                        ("halftone", {"halftone_cpi", "halftone_angle"}),
                        ("depth3d", {"depth_levels", "z_step_mm"}),
                        ("grayscale", set()), ("newsprint", set())):
        dlg.image_mode.setCurrentIndex(dlg.image_mode.findData(mode))
        assert _visible(dlg) == adjust | extra, mode
        assert all(dlg._rows[dlg._opt_rows[k]].isHidden() is False for k in adjust | extra)
    # Untouched options -> None (spec identical to before this round).
    assert dlg.spec().image_options is None
    dlg.mode.setCurrentIndex(CELL_FILL)
    assert _visible(dlg) == set()
    # German tooltips on every option widget.
    assert all(w.toolTip() for w in dlg._opt_widgets.values())
    dlg.deleteLater()


def test_dialog_round_trips_changed_options_only(qapp):
    from lumacut_job.qt_tools import CELL_IMAGE, CELL_OUTLINE, MaterialTestDialog
    dlg = MaterialTestDialog(None)
    dlg.mode.setCurrentIndex(CELL_IMAGE)
    dlg.image_mode.setCurrentIndex(dlg.image_mode.findData("halftone"))
    dlg.opt_cpi.setValue(18)
    dlg.opt_angle.setValue(22.5)
    dlg.opt_contrast.setValue(15)
    dlg.opt_threshold.setValue(40)                    # not for halftone -> not emitted
    out = dlg.spec()
    assert out.image_options == {"halftone_cpi": 18.0, "halftone_angle": 22.5,
                                 "contrast": 15.0}
    out.validate()
    cells = _cells(out)
    assert {c.image.settings.halftone_cpi for c in cells} == {18.0}
    # Switching to threshold emits the threshold, drops the halftone values.
    dlg.image_mode.setCurrentIndex(dlg.image_mode.findData("threshold"))
    assert dlg.spec().image_options == {"threshold": 40, "contrast": 15.0}
    dlg.opt_negative.setChecked(True)
    assert dlg.spec().image_options["negative"] is True
    # Vector cells never carry options.
    dlg.mode.setCurrentIndex(CELL_OUTLINE)
    assert dlg.spec().image_options is None
    # A spec with options reopens with them.
    spec = MaterialTestSpec(image_mode="depth3d",
                            image_options={"depth_levels": 5, "z_step_mm": 0.3, "gamma": 1.2})
    again = MaterialTestDialog(None, spec)
    assert (again.opt_levels.value(), again.opt_zstep.value(), again.opt_gamma.value()) == (
        5, 0.3, 1.2)
    assert again.spec() == spec
    dlg.deleteLater()
    again.deleteLater()


def test_dialog_blocks_too_deep_3d_drop(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    from lumacut_job.qt_tools import CELL_IMAGE, MaterialTestDialog
    dlg = MaterialTestDialog(None)
    dlg.mode.setCurrentIndex(CELL_IMAGE)
    dlg.image_mode.setCurrentIndex(dlg.image_mode.findData("depth3d"))
    ok = dlg.bb.button(QDialogButtonBox.Ok)
    dlg.opt_levels.setValue(8)
    dlg.opt_zstep.setValue(0.5)                       # 7 × 0.5 = 3.5 mm
    assert not ok.isEnabled() and "Fokus-Absenkung" in dlg.hint.text()
    dlg.opt_zstep.setValue(0.4)                       # 2.8 mm
    assert ok.isEnabled()
    dlg.deleteLater()
