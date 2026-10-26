"""Schriftart, Größe, Fett und Kursiv für Textobjekte (PropertyBar, Undo, Datei)."""

import json

import pytest

from lumacut_canvas import text_ui
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Geometry, Shape
from lumacut_canvas.pathops import shape_area
from lumacut_canvas.shape_paths import shape_path


@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1200, 700)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


def _text(ed, txt="Hallo", **kw):
    from PySide6.QtCore import QPointF
    s = ed.tools.add_text(txt, QPointF(20, 20), **kw)
    return ed.document.shape(s.id)


def test_controls_visible_only_for_text(ed):
    bar = ed.property_bar.text_style
    t = _text(ed)
    assert not bar.isHidden()
    rid = ed.document.add_shape(Shape("rect", Geometry(100, 100, 10, 10), ed.document.active_layer_id)).id
    ed.set_selection([rid])
    assert bar.isHidden()
    ed.set_selection([t.id, rid])
    assert bar.isHidden()
    ed.set_selection([t.id])
    assert not bar.isHidden()


def test_bold_italic_change_outline_keep_height_and_undo(ed):
    t = _text(ed)
    h, w = t.geom.h, t.geom.w
    plain = shape_area(t).area
    bar = ed.property_bar.text_style
    bar.bold.setChecked(True)
    b = ed.document.shape(t.id)
    assert b.font_bold and b.geom.h == pytest.approx(h)
    if shape_area(text_ui.with_style(t, bold=True)).area == pytest.approx(plain):
        pytest.skip("Keine echten Schriften auf diesem System (Ersatzkästen statt Glyphen)")
    assert shape_area(b).area > plain * 1.05          # fetter Strich = mehr Fläche
    bar.italic.setChecked(True)
    bi = ed.document.shape(t.id)
    assert bi.font_italic and bi.font_bold
    d = json.loads(json.dumps(bi.to_dict()))
    assert d["bold"] is True and d["italic"] is True
    back = Shape.from_dict(d)
    assert shape_path(back).boundingRect() == shape_path(bi).boundingRect()
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    t0 = ed.document.shape(t.id)
    assert not t0.font_bold and not t0.font_italic and t0.geom.w == pytest.approx(w)
    assert ed.text_font_bold is True                  # neue Texte übernehmen die Wahl
    t2 = _text(ed, "Neu")
    assert t2.font_bold and t2.font_italic


def test_size_pt_scales_box_uniformly(ed):
    t = _text(ed)
    pt = text_ui.size_pt(t)
    assert pt > 0
    bar = ed.property_bar.text_style
    assert bar.size.value() == pytest.approx(pt, abs=0.05)
    bar.size.setValue(round(pt * 2, 1))
    t2 = ed.document.shape(t.id)
    assert t2.geom.h == pytest.approx(t.geom.h * round(pt * 2, 1) / pt, rel=1e-3)
    assert t2.geom.w / t2.geom.h == pytest.approx(t.geom.w / t.geom.h, rel=1e-6)
    assert (t2.geom.x, t2.geom.y) == (t.geom.x, t.geom.y)
    assert text_ui.size_pt(t2) == pytest.approx(round(pt * 2, 1), rel=1e-3)
    ed.undo_stack.undo()
    assert ed.document.shape(t.id).geom.h == pytest.approx(t.geom.h)


def test_family_change_and_text_to_path_button(ed):
    t = _text(ed)
    bar = ed.property_bar.text_style
    other = next(f for f in ("DejaVu Serif", "Times New Roman", "Courier New", "DejaVu Sans Mono")
                 if f != bar.family.currentFont().family())
    from PySide6.QtGui import QFont
    bar.family.setCurrentFont(QFont(other))
    assert ed.document.shape(t.id).font_family == bar.family.currentFont().family()
    bar.outline.click()
    assert not ed.document.has_shape(t.id)
    assert ed.document.shape(ed.selection[0]).kind == "polygon"
