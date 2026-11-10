"""Material test dialog: draw own tone curves (review round 54).

Until round 53 a curve axis / the grid-wide curve offered the presets and the
curves of a reopened spec only. Now „Kurve zeichnen…“ opens the image dialog's
curve editor over the test image's histogram (templates: presets and the
curves of the document's images), drawn curves are checked on the axis or
chosen for all cells, own curves can be edited / removed, the curves of the
document's images (selected first) are listed, and the drawn curve reaches
every cell and the G-code. Untouched dialogs give the same spec as before."""

import re

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox

from _pi_guard import pi_check
from lumacut_canvas.model import (Document, Geometry, ImageSettings, RasterImage, Shape,
                                  normalize_curve)
from lumacut_job.material_test import (CURVE_AXIS_PRESETS, MaterialTestSpec,
                                       add_material_test, build_material_test, ramp_png)
from lumacut_job.planner import optimized_document_gcode
from lumacut_job.raster import CURVE_PRESETS

S_CURVE = normalize_curve(CURVE_PRESETS["Kontrast verstärken (S-Kurve)"])
DRAWN = ((0, 0), (70, 40), (180, 200), (255, 255))
DRAWN2 = ((0, 10), (128, 90), (255, 255))
PHOTO = ((0, 0), (60, 110), (255, 255))


def _dialog(spec=None, curves=None, mode="grayscale"):
    from lumacut_job.qt_tools import CELL_IMAGE, MaterialTestDialog
    dlg = MaterialTestDialog(None, spec, image_curves=curves)
    if spec is None:
        dlg.mode.setCurrentIndex(CELL_IMAGE)
        dlg.image_mode.setCurrentIndex(dlg.image_mode.findData(mode))
    return dlg


class _Drawer:
    """Replaces CurveDrawDialog.exec: records the start curve / templates / histogram
    and „draws“ the next curve (None = cancel)."""

    def __init__(self, monkeypatch, *curves):
        from lumacut_job import material_test_curve_qt as m
        self.curves = list(curves)
        self.seen = []
        drawer = self

        def fake_exec(dlg):
            drawer.seen.append({"start": dlg.curve(), "templates": dlg.template_names(),
                                "hist": dlg.editor._hist, "title": dlg.windowTitle()})
            nxt = drawer.curves.pop(0)
            if nxt is None:
                return QDialog.Rejected
            dlg.set_curve(nxt)
            return QDialog.Accepted

        monkeypatch.setattr(m.CurveDrawDialog, "exec", fake_exec)


def _texts(dlg):
    return [dlg.axis_curves.item(i).text() for i in range(dlg.axis_curves.count())]


def _gcode(spec):
    doc = Document()
    add_material_test(doc, spec)
    return re.sub(r"^; IMAGE \w+", "; IMAGE id", optimized_document_gcode(doc, scan_offsets=None),
                  flags=re.M)


# --- curve draw dialog ----------------------------------------------------------------------

def test_draw_dialog_templates_editor_and_histogram(qapp):
    from lumacut_job.material_test_curve_qt import CurveDrawDialog, grid_image_histogram
    hist = grid_image_histogram(MaterialTestSpec(image_mode="grayscale"))
    assert hist.shape == (256,) and hist.sum() == 256 * 16          # ramp 256 × 16 px
    dlg = CurveDrawDialog(S_CURVE, templates=[("Bild 1", PHOTO), ("Bild 2", S_CURVE)],
                          histogram=hist)
    names = dlg.template_names()
    assert names[:len(CURVE_PRESETS)] == list(CURVE_PRESETS)
    assert names[len(CURVE_PRESETS):] == ["Bild 1"]                 # S already a preset
    assert dlg.template.currentText() == "Kontrast verstärken (S-Kurve)"
    assert np.array_equal(dlg.editor._hist, hist)
    dlg.template.setCurrentIndex(len(CURVE_PRESETS))
    dlg.template.activated.emit(len(CURVE_PRESETS))
    assert dlg.curve() == PHOTO
    # Editing a point leaves the template on „Benutzerdefiniert“.
    dlg.editor.move_point(1, 60, 150)
    assert dlg.curve() == ((0, 0), (60, 150), (255, 255))
    assert dlg.template.currentText() == "Benutzerdefiniert"
    dlg.template.activated.emit(0)                                   # Linear
    assert dlg.curve() == ()
    dlg.deleteLater()


def test_histogram_follows_photo_and_black_white_point(qapp):
    from lumacut_job.material_test_curve_qt import grid_image_histogram
    from lumacut_job.material_test import wedge_png
    spec = MaterialTestSpec(image_mode="grayscale", image_source="photo",
                            image_png=wedge_png())
    h = grid_image_histogram(spec)
    assert np.count_nonzero(h) == 16                                  # 16 grey bands
    lv = grid_image_histogram(MaterialTestSpec(
        image_mode="grayscale", image_options={"black_point": 64, "white_point": 192}))
    assert lv.sum() == 256 * 16 and lv[0] >= 65 * 16 and lv[255] >= 64 * 16
    assert grid_image_histogram(None) is None
    assert grid_image_histogram(MaterialTestSpec(image_mode="grayscale",
                                                 image_source="photo")) is None


def test_document_image_curves_selected_first_and_once(qapp):
    from lumacut_job.material_test_curve_qt import document_image_curves
    doc = Document()
    png = ramp_png()
    ids = []
    for curve in (PHOTO, (), S_CURVE, PHOTO):
        s = doc.add_shape(Shape("image", Geometry(0, 0, 10, 10), doc.active_layer_id,
                                image=RasterImage(png, 256, 16, ImageSettings(curve=curve))))
        ids.append(s.id)
    doc.add_shape(Shape("rect", Geometry(0, 0, 5, 5), doc.active_layer_id))
    assert document_image_curves(doc) == [("Bild 1", PHOTO), ("Bild 3", S_CURVE)]
    assert document_image_curves(doc, [ids[2]]) == [("Bild 3", S_CURVE), ("Bild 1", PHOTO)]
    assert document_image_curves(doc, [ids[3]]) == [("Bild 4", PHOTO), ("Bild 3", S_CURVE)]
    assert document_image_curves(None) == [] and document_image_curves(Document()) == []


# --- curve axis -----------------------------------------------------------------------------

def test_untouched_dialog_unchanged(qapp):
    dlg = _dialog()
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("curve"))
    assert _texts(dlg)[:len(CURVE_AXIS_PRESETS)] == list(CURVE_PRESETS)
    assert dlg.axis_curves.count() == len(CURVE_AXIS_PRESETS)
    assert dlg.spec().image_axis_curves == CURVE_AXIS_PRESETS[:5]
    assert not dlg.axis_curve_buttons.isHidden()
    assert not dlg.axis_curve_remove.isEnabled()
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("power"))
    assert dlg.axis_curve_buttons.isHidden() and dlg.axis_curves.isHidden()
    dlg.deleteLater()


def test_draw_new_axis_curve_is_checked_and_reaches_the_gcode(qapp, monkeypatch):
    drawer = _Drawer(monkeypatch, DRAWN)
    dlg = _dialog()
    dlg.cols.setValue(2)
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("curve"))
    assert dlg.axis_curves_checked() == CURVE_AXIS_PRESETS[:2]
    dlg.axis_curves.setCurrentRow(1)                                 # start from S
    dlg.axis_curve_new.click()
    assert drawer.seen[0]["start"] == S_CURVE
    assert drawer.seen[0]["hist"] is not None and drawer.seen[0]["hist"].sum() == 256 * 16
    assert _texts(dlg)[-1] == "Benutzerdefiniert 1"
    assert dlg.axis_curves.currentRow() == dlg.axis_curves.count() - 1
    assert dlg.axis_curves_checked() == ((), S_CURVE, DRAWN)
    assert dlg.cols.value() == 3 and dlg.bb.button(QDialogButtonBox.Ok).isEnabled()
    assert dlg.axis_curve_remove.isEnabled()
    spec = dlg.spec()
    spec.validate()
    assert spec.image_axis_curves == ((), S_CURVE, DRAWN)
    assert spec.label_texts()[0] == ["Linear", "S", "Eigene 1"]
    cells = [s for s in build_material_test(spec)[1] if s.kind == "image"]
    assert sorted({s.image.settings.curve for s in cells}) == sorted({(), S_CURVE, DRAWN})
    g = _gcode(spec)
    pi_check(g)
    # The drawn curve's column differs from a linear one.
    lin = _gcode(MaterialTestSpec(**{**spec.__dict__, "image_axis_curves": ((), S_CURVE,
                                                                           CURVE_AXIS_PRESETS[2])}))
    assert g != lin
    dlg.deleteLater()


def test_drawing_an_existing_curve_checks_it_and_cancel_changes_nothing(qapp, monkeypatch):
    _Drawer(monkeypatch, None, CURVE_AXIS_PRESETS[3])
    dlg = _dialog()
    dlg.rows.setValue(2)
    dlg.row_param.setCurrentIndex(dlg.row_param.findData("curve"))
    before = (_texts(dlg), dlg.axis_curves_checked())
    assert dlg.new_axis_curve() == -1
    assert (_texts(dlg), dlg.axis_curves_checked()) == before
    row = dlg.new_axis_curve()                                       # = preset 4: no copy
    assert row == 3 and dlg.axis_curves.count() == len(CURVE_AXIS_PRESETS)
    assert CURVE_AXIS_PRESETS[3] in dlg.axis_curves_checked()
    dlg.deleteLater()


def test_edit_own_curve_in_place_preset_stays(qapp, monkeypatch):
    _Drawer(monkeypatch, DRAWN, DRAWN2, PHOTO)
    dlg = _dialog()
    dlg.cols.setValue(2)
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("curve"))
    dlg.axis_curves.setCurrentRow(0)
    dlg.new_axis_curve()                                             # Benutzerdefiniert 1
    own = dlg.axis_curves.count() - 1
    # Move it to the front (like a drag) and edit it: replaced in place, same label.
    item = dlg.axis_curves.takeItem(own)
    dlg.axis_curves.insertItem(0, item)
    dlg.axis_curves.setCurrentRow(0)
    assert dlg.edit_axis_curve() == 0
    assert _texts(dlg)[0] == "Benutzerdefiniert 1"
    assert dlg.axis_curves_checked()[0] == DRAWN2
    assert DRAWN not in dlg.axis_curves_checked()
    # Editing a preset (S): the preset stays, the result is a new own curve.
    s_row = _texts(dlg).index("Kontrast verstärken (S-Kurve)")
    dlg.axis_curves.setCurrentRow(s_row)
    assert not dlg.axis_curve_remove.isEnabled()
    row = dlg.edit_axis_curve()
    assert _texts(dlg)[row] == "Benutzerdefiniert 2"
    assert _texts(dlg)[s_row] == "Kontrast verstärken (S-Kurve)"
    assert dlg.axis_curves_checked() == (DRAWN2, (), S_CURVE, PHOTO)
    dlg.spec().validate()
    dlg.deleteLater()


def test_edit_to_an_existing_curve_merges_and_remove(qapp, monkeypatch):
    _Drawer(monkeypatch, DRAWN, S_CURVE)
    dlg = _dialog()
    dlg.cols.setValue(2)
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("curve"))
    dlg.new_axis_curve()
    n = dlg.axis_curves.count()
    dlg.axis_curves.setCurrentRow(n - 1)
    dlg.edit_axis_curve()                                            # own → equals S
    assert dlg.axis_curves.count() == n - 1
    assert dlg.axis_curves_checked() == ((), S_CURVE)
    # Remove: presets cannot be removed, own curves can.
    dlg.axis_curves.setCurrentRow(1)
    assert not dlg.remove_axis_curve() and dlg.axis_curves.count() == n - 1
    dlg.deleteLater()

    _Drawer(monkeypatch, DRAWN)
    dlg = _dialog()
    dlg.cols.setValue(2)
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("curve"))
    dlg.new_axis_curve()
    assert dlg.cols.value() == 3
    dlg.axis_curve_remove.click()
    assert dlg.axis_curves.count() == len(CURVE_AXIS_PRESETS)
    assert dlg.axis_curves_checked() == CURVE_AXIS_PRESETS[:2] and dlg.cols.value() == 2
    assert dlg.axis_curve_edit.isEnabled() == (dlg.axis_curves.currentItem() is not None)
    assert not dlg.axis_curve_remove.isEnabled()                    # a preset is current now
    dlg.deleteLater()


def test_too_many_checked_curves_block_ok(qapp, monkeypatch):
    curves = [((0, 0), (128, 20 + 10 * i), (255, 255)) for i in range(5)]
    _Drawer(monkeypatch, *curves)
    dlg = _dialog()
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("curve"))
    for row in range(dlg.axis_curves.count()):
        dlg.axis_curves.item(row).setCheckState(Qt.Checked)
    for _ in curves:
        dlg.new_axis_curve()
    assert len(dlg.axis_curves_checked()) == len(CURVE_AXIS_PRESETS) + 5 > 12
    assert not dlg.bb.button(QDialogButtonBox.Ok).isEnabled()
    assert "höchstens 12 Kurven" in dlg.hint.text()
    dlg.axis_curves.item(0).setCheckState(Qt.Unchecked)
    assert dlg.bb.button(QDialogButtonBox.Ok).isEnabled() and dlg.cols.value() == 12
    dlg.spec().validate()
    dlg.deleteLater()


def test_document_curves_listed_and_offered_as_templates(qapp, monkeypatch):
    drawer = _Drawer(monkeypatch, None)
    dlg = _dialog(curves=[("Bild 2", PHOTO), ("Bild 1", S_CURVE), ("Bild 3", PHOTO)])
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("curve"))
    assert _texts(dlg)[-1] == "Bild 2"                               # S stays the preset
    assert dlg.axis_curves.count() == len(CURVE_AXIS_PRESETS) + 1
    assert PHOTO not in dlg.axis_curves_checked()
    dlg.axis_curves.item(dlg.axis_curves.count() - 1).setCheckState(Qt.Checked)
    assert dlg.spec().image_axis_curves[-1] == PHOTO
    dlg.axis_curves.setCurrentRow(dlg.axis_curves.count() - 1)
    assert not dlg.axis_curve_remove.isEnabled()
    dlg.new_axis_curve()
    assert drawer.seen[0]["start"] == PHOTO
    assert drawer.seen[0]["templates"][-1] == "Bild 2"
    # Grid-wide curve combo offers the image curve too.
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("power"))
    dlg.opt_more.setChecked(True)
    i = dlg.opt_curve.findText("Bild 2")
    assert i == len(CURVE_PRESETS)
    dlg.opt_curve.setCurrentIndex(i)
    assert dlg.spec().image_options["curve"] == PHOTO
    dlg.deleteLater()


def test_reopened_spec_with_custom_curve_and_document_curve(qapp):
    spec = MaterialTestSpec(image_mode="floyd", column_param="curve", columns=2,
                            image_axis_curves=(DRAWN, PHOTO))
    dlg = _dialog(spec, curves=[("Bild 1", PHOTO)])
    assert _texts(dlg)[:2] == ["Benutzerdefiniert 1", "Bild 1"]
    assert dlg.axis_curves.count() == len(CURVE_AXIS_PRESETS) + 2
    assert dlg.spec() == spec
    dlg.deleteLater()


# --- grid-wide curve ------------------------------------------------------------------------

def test_draw_grid_wide_curve(qapp, monkeypatch):
    drawer = _Drawer(monkeypatch, DRAWN, None, DRAWN2, S_CURVE)
    dlg = _dialog()
    assert dlg.opt_curve_draw.isHidden()
    dlg.opt_more.setChecked(True)
    assert not dlg.opt_curve_draw.isHidden() and not dlg._rows["opt_curve_draw"].isHidden()
    dlg.opt_curve_draw.click()
    assert drawer.seen[0]["start"] == ()
    assert dlg.opt_curve.currentText() == "Benutzerdefiniert"
    spec = dlg.spec()
    assert spec.image_options == {"curve": DRAWN}
    cells = [s for s in build_material_test(spec)[1] if s.kind == "image"]
    assert cells and all(s.image.settings.curve == DRAWN for s in cells)
    pi_check(_gcode(spec))
    n = dlg.opt_curve.count()
    assert dlg.draw_option_curve() == -1 and dlg.opt_curve.count() == n
    dlg.draw_option_curve()
    assert drawer.seen[-1]["start"] == DRAWN
    assert dlg.opt_curve.currentText() == "Benutzerdefiniert 2"
    assert dlg.spec().image_options == {"curve": DRAWN2}
    dlg.draw_option_curve()                                          # = S preset: chosen
    assert dlg.opt_curve.count() == n + 1
    assert dlg.opt_curve.currentText() == "Kontrast verstärken (S-Kurve)"
    # Curve on an axis: the grid-wide row incl. the button is hidden.
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("curve"))
    assert dlg.opt_curve.isHidden() and dlg.opt_curve_draw.isHidden()
    dlg.deleteLater()


def test_draw_uses_the_real_dialog_and_cancel(qapp, monkeypatch):
    """The real CurveDrawDialog is built (title, histogram of the photo); cancel = None."""
    from lumacut_job import material_test_curve_qt as m
    built = []
    orig_init = m.CurveDrawDialog.__init__

    def spy_init(self, *a, **kw):
        orig_init(self, *a, **kw)
        built.append(self)

    monkeypatch.setattr(m.CurveDrawDialog, "__init__", spy_init)
    monkeypatch.setattr(m.CurveDrawDialog, "exec", lambda self: QDialog.Rejected)
    dlg = _dialog()
    dlg.col_param.setCurrentIndex(dlg.col_param.findData("curve"))
    assert dlg.new_axis_curve() == -1
    assert built and built[0].windowTitle() == "Kurve für die Achse zeichnen"
    assert built[0].editor.objectName() == "material_test_curve_editor"
    dlg.deleteLater()


# --- main window ----------------------------------------------------------------------------

@pytest.fixture
def win(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    yield w
    w.canvas.undo_stack.setClean()
    w.close()
    w.deleteLater()
    qapp.processEvents()


def test_window_material_test_offers_the_selected_image_curve(win, monkeypatch):
    from lumacut_job import qt_tools
    doc = win.canvas.document
    png = ramp_png()
    a = doc.add_shape(Shape("image", Geometry(0, 0, 10, 10), doc.active_layer_id,
                            image=RasterImage(png, 256, 16, ImageSettings(curve=S_CURVE))))
    b = doc.add_shape(Shape("image", Geometry(20, 0, 10, 10), doc.active_layer_id,
                            image=RasterImage(png, 256, 16, ImageSettings(curve=PHOTO))))
    win.canvas.set_selection([b.id])
    seen = {}

    def fake_exec(dlg):
        seen["curves"] = list(dlg._doc_curves)
        dlg.mode.setCurrentIndex(qt_tools.CELL_IMAGE)
        dlg.cols.setValue(2)
        dlg.col_param.setCurrentIndex(dlg.col_param.findData("curve"))
        dlg.axis_curves.item(dlg.axis_curves.count() - 1).setCheckState(Qt.Checked)
        dlg.axis_curves.item(1).setCheckState(Qt.Unchecked)
        return QDialog.Accepted

    monkeypatch.setattr(qt_tools.MaterialTestDialog, "exec", fake_exec)
    n = win.job_tools.material_test()
    assert seen["curves"] == [("Bild 2", PHOTO), ("Bild 1", S_CURVE)]
    assert n > 0
    curves = {s.image.settings.curve for s in doc.shapes
              if s.kind == "image" and s.id not in (a.id, b.id)}
    assert curves == {(), PHOTO}
