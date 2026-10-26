"""Materialbibliothek → Bild-Modus depth3d (raster.sliced_depth_gcode)."""

import re

import pytest

from _pi_guard import pi_check
from lumacut_canvas.model import Document, Geometry, ImageSettings, Layer, RasterImage, Shape
from lumacut_job.raster import MAX_DEPTH_DROP_MM
from lumacut_materials import load_db
from lumacut_materials.db import MaterialError
from lumacut_materials.depth3d import apply_to_image_settings, depth3d_image_settings
from lumacut_materials.planner import plan_relief


@pytest.fixture(scope="module")
def db():
    return load_db()


@pytest.mark.parametrize("mid,depth", [("basswood_plywood", 1.5), ("mdf", 2.0), ("slate", 0.3)])
def test_settings_match_relief_plan(db, mid, depth):
    m = db.material(mid)
    if not m.can_relief:
        with pytest.raises(MaterialError):
            depth3d_image_settings(db, mid, depth)
        return
    f = depth3d_image_settings(db, mid, depth)
    p = plan_relief(db, mid, depth)
    s = apply_to_image_settings(ImageSettings(), f)
    assert s.mode == "depth3d" and s.depth_levels == p.passes and s.passes == 1
    assert s.power == p.power_pct and s.speed_mm_min == p.speed_mm_min
    assert s.z_step_mm * (s.depth_levels - 1) <= MAX_DEPTH_DROP_MM + 1e-9
    # Gesamttiefe: Stufen × Schichttiefe = Zieltiefe
    assert s.depth_levels * p.layer_depth_mm == pytest.approx(depth, abs=0.01)


def _image(qapp, doc):
    from PySide6.QtGui import QColor, QImage
    from lumacut_import.image import grayscale_png
    img = QImage(30, 12, QImage.Format_RGB32)
    for x in range(30):
        for y in range(12):
            v = int(255 * x / 29)
            img.setPixelColor(x, y, QColor(v, v, v))
    png, pw, ph = grayscale_png(img)
    sh = Shape("image", Geometry(60, 60, 15, 6, 0), doc.active_layer_id,
               image=RasterImage(png, pw, ph, ImageSettings()))
    doc.add_shape(sh)
    return sh


def test_apply_to_image_one_undo_step_and_pi_safe_gcode(qapp, db):
    from PySide6.QtGui import QUndoStack
    from lumacut_job.images import image_job, raster_settings, render_gray
    from lumacut_job.raster import sliced_depth_gcode
    from lumacut_canvas.workarea import to_machine
    from lumacut_materials.dialog import apply_depth3d

    class Ed:
        pass
    ed = Ed()
    ed.document = Document()
    ed.document.add_layer(Layer("Ebene 1"))
    ed.undo_stack = QUndoStack()
    sh = _image(qapp, ed.document)
    ed.selection = [sh.id, "fehlt"]
    f = depth3d_image_settings(db, "basswood_plywood", 1.5)
    assert apply_depth3d(ed, f) == [sh.id]
    st = ed.document.shape(sh.id).image.settings
    assert st.mode == "depth3d" and st.depth_levels == f["depth_levels"]
    assert ed.undo_stack.count() == 1
    assert image_job(ed.document.shape(sh.id)).lines
    shape = ed.document.shape(sh.id)
    gray, (cx, cy) = render_gray(shape, st.line_interval_mm)
    ox, oy = to_machine(cx, cy)
    text = sliced_depth_gcode(gray, (ox, oy), gray.shape[1] * st.line_interval_mm,
                              gray.shape[0] * st.line_interval_mm, raster_settings(shape, 0.0),
                              levels=st.depth_levels, z_step_mm=st.z_step_mm)
    pi_check(text)
    assert not re.search(r"\bM4\b", text)
    ed.undo_stack.undo()
    assert ed.document.shape(sh.id).image.settings == ImageSettings()
