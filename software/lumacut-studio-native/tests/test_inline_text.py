"""Text direkt auf der Arbeitsfläche tippen (LightBurn: mit dem Text-Werkzeug klicken und
lostippen, Doppelklick bearbeitet an Ort und Stelle; xTool: Text auf der Leinwand
bearbeiten) – Eingabefeld, Live-Vorschau, genau ein Undo-Schritt, Abbrechen, Touch."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QInputDialog

from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.inline_text import TOUCH_PX, InlineTextEditor
from lumacut_canvas.model import Geometry, Layer, Shape
from lumacut_canvas.tools import Tool

FAMILY = "DejaVu Sans"
NO = Qt.NoModifier


@pytest.fixture
def ed(qapp, monkeypatch):
    def boom(*a, **k):  # der Inline-Weg darf keinen Dialog öffnen
        raise AssertionError("Dialog geöffnet")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(boom))
    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(boom))
    e = CanvasEditor()
    e.set_touch_mode(False, persist=False)
    e.resize(1400, 800)
    e.show()
    qapp.processEvents()
    yield e
    e.inline_text.discard()
    e.undo_stack.setClean()
    e.close()


def _add(ed, text="Hallo", **kw):
    s = Shape("text", Geometry(40, 40, 40, 12), ed.document.active_layer_id, text=text,
              font_family=FAMILY, **kw)
    ed.document.add_shape(s)
    ed.set_selection([s.id])
    return ed.document.shape(s.id)


def _center(s):
    b = s.bounds()
    return QPointF(b.x + b.w / 2, b.y + b.h / 2)


def _type(ed, text):
    ed.inline_text.edit.setPlainText(text)


def _click_text_tool(ed, p):
    ed.set_tool(Tool.TEXT)
    ed.tools.press(p, NO)
    ed.tools.release(p, NO)


# --- Doppelklick: vorhandener Text --------------------------------------------------
def test_editor_has_inline_text_on_by_default(ed):
    assert isinstance(ed.inline_text, InlineTextEditor)
    assert ed.inline_text_editing is True and not ed.inline_text.active


def test_double_click_opens_field_on_the_canvas_with_the_text_selected(ed):
    t = _add(ed)
    ed.tools.double_click(_center(t))
    it = ed.inline_text
    assert it.active and it.shape_id == t.id and not it.is_new
    assert it.frame.parent() is ed.view.viewport() and it.frame.isVisible()
    assert it.edit.toPlainText() == "Hallo"
    assert it.edit.textCursor().selectedText() == "Hallo"   # Lostippen ersetzt den Text
    assert it.edit.font().family() == FAMILY


def test_field_sits_right_below_the_text_inside_the_view(ed):
    t = _add(ed)
    ed.tools.double_click(_center(t))
    f = ed.inline_text.frame.geometry()
    r = ed.view.mapFromScene(ed.inline_text._anchor_rect()).boundingRect()
    assert f.top() >= r.bottom() and f.top() - r.bottom() <= 12
    assert abs(f.left() - r.left()) <= 2
    vp = ed.view.viewport().rect()
    assert vp.contains(f)


def test_field_goes_above_when_there_is_no_room_below(ed):
    vp = ed.view.viewport()
    bottom = ed.view.mapToScene(200, vp.height() - 8)
    top = ed.view.mapToScene(200, vp.height() - 40)
    s = Shape("text", Geometry(bottom.x(), top.y(), 40, bottom.y() - top.y()),
              ed.document.active_layer_id, text="Unten", font_family=FAMILY)
    ed.document.add_shape(s)
    ed.inline_text.edit_shape(s.id)
    f = ed.inline_text.frame.geometry()
    r = ed.view.mapFromScene(ed.inline_text._anchor_rect()).boundingRect()
    assert vp.rect().contains(f)
    assert f.bottom() <= r.top() + 1                    # darüber statt darunter


def test_typing_shows_live_on_the_canvas(ed):
    t = _add(ed)
    w0 = t.geom.w
    ed.tools.double_click(_center(t))
    _type(ed, "Hallo Welt")
    s = ed.document.shape(t.id)
    assert s.text == "Hallo Welt" and s.geom.w > w0 * 1.5          # Box wächst mit
    assert s.geom.h == pytest.approx(t.geom.h)                      # Buchstaben gleich groß
    assert (s.geom.x, s.geom.y) == (pytest.approx(t.geom.x), pytest.approx(t.geom.y))


def test_enter_makes_a_new_line_and_the_field_grows(ed):
    t = _add(ed)
    ed.tools.double_click(_center(t))
    it = ed.inline_text
    h0 = it.frame.height()
    it.edit.moveCursor(it.edit.textCursor().MoveOperation.End)
    for _ in range(3):
        QTest.keyClick(it.edit, Qt.Key_Return)
        QTest.keyClicks(it.edit, "Zeile")
    assert it.active                                                # Enter beendet nicht
    s = ed.document.shape(t.id)
    assert s.text == "Hallo\nZeile\nZeile\nZeile" and s.geom.h > t.geom.h * 3
    assert it.frame.height() > h0


def test_ctrl_enter_commits_as_exactly_one_undo_step(ed):
    t = _add(ed)
    n0 = ed.undo_stack.count()
    ed.tools.double_click(_center(t))
    for word in ("H", "Ha", "Han", "Hans"):
        _type(ed, word)
    QTest.keyClick(ed.inline_text.edit, Qt.Key_Return, Qt.ControlModifier)
    assert not ed.inline_text.active
    assert ed.document.shape(t.id).text == "Hans"
    assert ed.undo_stack.count() == n0 + 1 and ed.undo_stack.undoText() == "Text ändern"
    ed.undo_stack.undo()
    s = ed.document.shape(t.id)
    assert s.text == "Hallo" and s.geom.w == pytest.approx(t.geom.w)
    ed.undo_stack.redo()
    assert ed.document.shape(t.id).text == "Hans"


def test_escape_restores_the_old_text_without_undo_step(ed):
    t = _add(ed)
    n0, i0 = ed.undo_stack.count(), ed.undo_stack.index()
    ed.tools.double_click(_center(t))
    _type(ed, "Etwas ganz anderes")
    QTest.keyClick(ed.inline_text.edit, Qt.Key_Escape)
    assert not ed.inline_text.active
    s = ed.document.shape(t.id)
    assert s.text == "Hallo" and s.geom.w == pytest.approx(t.geom.w)
    assert ed.undo_stack.index() == i0 and ed.undo_stack.undoText() != "Text ändern" or i0 == 0
    assert ed.undo_stack.index() == i0


def test_escape_after_another_command_still_restores_the_text(ed):
    t = _add(ed)
    ed.tools.double_click(_center(t))
    _type(ed, "Zwischen")
    other = Shape("rect", Geometry(100, 100, 10, 10), ed.document.active_layer_id)
    from lumacut_canvas.commands import AddShapesCommand
    ed.undo_stack.push(AddShapesCommand(ed.document, [other]))
    _type(ed, "Zwischendurch")
    ed.inline_text.cancel()
    assert ed.document.shape(t.id).text == "Hallo" and ed.document.has_shape(other.id)


def test_unchanged_or_emptied_text_gives_no_undo_step(ed):
    t = _add(ed)
    i0 = ed.undo_stack.index()
    ed.tools.double_click(_center(t))
    ed.inline_text.commit()
    assert ed.undo_stack.index() == i0
    ed.tools.double_click(_center(t))
    _type(ed, "Hallo!")
    _type(ed, "Hallo")                                   # zurückgetippt
    ed.inline_text.commit()
    assert ed.undo_stack.index() == i0 and ed.document.shape(t.id).text == "Hallo"
    ed.tools.double_click(_center(t))
    _type(ed, "  \n ")                                   # alles gelöscht: alter Text bleibt
    ed.inline_text.commit()
    assert ed.undo_stack.index() == i0 and ed.document.shape(t.id).text == "Hallo"


def test_buttons_commit_and_cancel_without_taking_focus(ed):
    t = _add(ed)
    ed.tools.double_click(_center(t))
    it = ed.inline_text
    assert it.ok_button.focusPolicy() == Qt.NoFocus and it.cancel_button.focusPolicy() == Qt.NoFocus
    _type(ed, "Neu")
    it.ok_button.click()
    assert not it.active and ed.document.shape(t.id).text == "Neu"
    ed.tools.double_click(_center(ed.document.shape(t.id)))
    _type(ed, "Weg")
    ed.inline_text.cancel_button.click()
    assert ed.document.shape(t.id).text == "Neu"


def test_focus_leaving_the_field_commits(ed, qapp):
    t = _add(ed)
    ed.tools.double_click(_center(t))
    _type(ed, "Fokus")
    ed.inline_text.edit.focusOutEvent(_focus_out(Qt.MouseFocusReason))
    assert not ed.inline_text.active and ed.document.shape(t.id).text == "Fokus"


def test_switching_windows_keeps_the_field_open(ed):
    t = _add(ed)
    ed.tools.double_click(_center(t))
    _type(ed, "Bleibt")
    ed.inline_text.edit.focusOutEvent(_focus_out(Qt.ActiveWindowFocusReason))
    assert ed.inline_text.active
    ed.inline_text.commit()
    assert ed.document.shape(t.id).text == "Bleibt"


def _focus_out(reason):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent
    return QFocusEvent(QEvent.FocusOut, reason)


def test_multiline_and_layout_survive_inline_editing(ed):
    t = _add(ed, "Ab\nCdef", text_align="right", line_spacing=150, letter_spacing=10)
    ed.tools.double_click(_center(t))
    assert ed.inline_text.edit.toPlainText() == "Ab\nCdef"
    _type(ed, "Ab\nCdefgh")
    ed.inline_text.commit()
    s = ed.document.shape(t.id)
    assert s.text == "Ab\nCdefgh" and s.text_align == "right"
    assert s.line_spacing == t.line_spacing and s.letter_spacing == t.letter_spacing
    assert s.geom.x + s.geom.w == pytest.approx(t.geom.x + t.geom.w, abs=1e-6)  # rechts fest


def test_style_layer_and_id_are_kept(ed):
    t = _add(ed, font_bold=True, text_case="upper")
    ed.tools.double_click(_center(t))
    _type(ed, "neu")
    ed.inline_text.commit()
    s = ed.document.shape(t.id)
    assert s.id == t.id and s.layer_id == t.layer_id and s.font_bold and s.text_case == "upper"
    assert s.font_family == FAMILY


def test_carriage_returns_are_normalized(ed):
    t = _add(ed)
    ed.tools.double_click(_center(t))
    _type(ed, "A\r\nB")
    ed.inline_text.commit()
    assert ed.document.shape(t.id).text == "A\nB"


def test_shape_deleted_while_typing_closes_the_field(ed):
    t = _add(ed)
    ed.tools.double_click(_center(t))
    ed.document.remove_shape(t.id)
    _type(ed, "x")
    assert not ed.inline_text.active


def test_old_dialog_path_when_switched_off(ed, monkeypatch):
    t = _add(ed)
    ed.inline_text_editing = False
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Dialog", True)))
    ed.tools.double_click(_center(t))
    assert not ed.inline_text.active and ed.document.shape(t.id).text == "Dialog"


def test_arc_text_and_images_keep_their_own_double_click(ed):
    t = _add(ed)
    called = []
    ed.document.shape(t.id).generator = {"kind": "arc_text", "spec": {}}
    ed.generated_edit_handler = lambda sid: called.append(sid) or True
    ed.tools.double_click(_center(t))
    assert called == [t.id] and not ed.inline_text.active


# --- Text-Werkzeug: neuer Text ----------------------------------------------------
def test_text_tool_click_opens_an_empty_field_without_object(ed):
    n = len(ed.document.shapes)
    i0 = ed.undo_stack.index()
    _click_text_tool(ed, QPointF(30, 50))
    it = ed.inline_text
    assert it.active and it.is_new and it.edit.toPlainText() == ""
    assert it.edit.placeholderText()
    assert len(ed.document.shapes) == n and ed.undo_stack.index() == i0


def test_new_text_appears_while_typing_and_commits_as_one_insert(ed):
    n0 = ed.undo_stack.count()
    _click_text_tool(ed, QPointF(30, 50))
    for word in ("L", "Lu", "Luma", "LumaCut"):
        _type(ed, word)
    s = ed.document.shapes[-1]
    assert s.kind == "text" and s.text == "LumaCut"
    assert (s.geom.x, s.geom.y) == (pytest.approx(30), pytest.approx(50))
    ed.inline_text.commit()
    s = ed.document.shapes[-1]
    assert s.text == "LumaCut" and ed.selection == [s.id]
    assert ed.undo_stack.count() == n0 + 1 and ed.undo_stack.undoText() == "Text einfügen"
    assert s.layer_id == ed.document.active_layer_id and s.font_family == ed.text_font_family
    ed.undo_stack.undo()
    assert not ed.document.has_shape(s.id)


def test_new_text_has_the_default_letter_height(ed):
    from lumacut_canvas.tools import DEFAULT_TEXT_HEIGHT_MM
    _click_text_tool(ed, QPointF(30, 50))
    _type(ed, "Ab")
    one = ed.document.shapes[-1].geom.h
    _type(ed, "Ab\nCd")
    two = ed.document.shapes[-1].geom.h
    assert one == pytest.approx(DEFAULT_TEXT_HEIGHT_MM, rel=0.35)
    assert two > one * 1.8                                   # Zeilen kommen dazu, nicht kleiner


def test_new_text_escape_or_empty_leaves_nothing(ed):
    n, i0 = len(ed.document.shapes), ed.undo_stack.index()
    _click_text_tool(ed, QPointF(30, 50))
    _type(ed, "Weg")
    QTest.keyClick(ed.inline_text.edit, Qt.Key_Escape)
    assert len(ed.document.shapes) == n and ed.undo_stack.index() == i0
    _click_text_tool(ed, QPointF(30, 50))
    ed.inline_text.commit()
    assert len(ed.document.shapes) == n and ed.undo_stack.index() == i0
    assert not ed.undo_stack.canRedo() or ed.undo_stack.index() == i0


def test_new_text_snaps_to_the_grid_or_objects_like_before(ed):
    from lumacut_canvas.tools import _clamp_point
    ed.set_tool(Tool.TEXT)
    p = QPointF(20.9, 51.0)
    expected = _clamp_point(ed.tools.snap_point(p))
    _click_text_tool(ed, p)
    g = ed.inline_text.base.geom
    assert (g.x, g.y) == (pytest.approx(expected.x()), pytest.approx(expected.y()))


def test_locked_layer_opens_no_field(ed):
    lay = Layer(name="zu", locked=True)
    ed.document.layers.append(lay)
    ed.document.active_layer_id = lay.id
    _click_text_tool(ed, QPointF(30, 50))
    assert not ed.inline_text.active


def test_switching_tool_commits_the_open_field(ed):
    _click_text_tool(ed, QPointF(30, 50))
    _type(ed, "Werkzeug")
    ed.set_tool(Tool.SELECT)
    assert not ed.inline_text.active and ed.document.shapes[-1].text == "Werkzeug"


def test_new_document_discards_the_field(ed, monkeypatch):
    _click_text_tool(ed, QPointF(30, 50))
    _type(ed, "x")
    monkeypatch.setattr(ed, "_confirm_discard", lambda: True)
    ed.new_document()
    assert not ed.inline_text.active and ed.undo_stack.count() == 0


def test_save_commits_first(ed, tmp_path):
    from lumacut_canvas.document_io import FILE_SUFFIX
    _click_text_tool(ed, QPointF(30, 50))
    _type(ed, "Gespeichert")
    p = ed.save_file(tmp_path / f"a{FILE_SUFFIX}")
    assert not ed.inline_text.active and "Gespeichert" in p.read_text(encoding="utf-8")
    assert ed.undo_stack.undoText() == "Text einfügen"


def test_other_command_while_typing_still_ends_in_the_typed_text(ed):
    t = _add(ed)
    ed.tools.double_click(_center(t))
    _type(ed, "Zwischen")
    other = Shape("rect", Geometry(100, 100, 10, 10), ed.document.active_layer_id)
    from lumacut_canvas.commands import AddShapesCommand
    ed.undo_stack.push(AddShapesCommand(ed.document, [other]))
    _type(ed, "Zwischendurch")
    ed.inline_text.commit()
    assert ed.document.shape(t.id).text == "Zwischendurch" and ed.document.has_shape(other.id)


def test_outline_matches_a_dialog_made_text(ed):
    _click_text_tool(ed, QPointF(30, 50))
    _type(ed, "GC")
    ed.inline_text.commit()
    inline = ed.document.shapes[-1]
    ref = Shape("text", inline.geom.copy(), inline.layer_id, text="GC", font_family=inline.font_family,
                font_bold=inline.font_bold, font_italic=inline.font_italic)
    from lumacut_canvas.shape_paths import shape_path
    assert shape_path(inline).boundingRect() == shape_path(ref).boundingRect()


# --- Touch ----------------------------------------------------------------------
def test_touch_mode_buttons_and_field_are_finger_sized(ed):
    ed.set_touch_mode(True, persist=False)
    t = _add(ed)
    ed.tools.double_click(_center(t))
    it = ed.inline_text
    assert it.ok_button.width() >= TOUCH_PX and it.ok_button.height() >= TOUCH_PX
    assert it.cancel_button.height() >= TOUCH_PX and it.frame.height() >= TOUCH_PX
    assert it.edit.font().pixelSize() >= 20


def test_field_follows_zoom_and_scroll(ed):
    t = _add(ed)
    ed.tools.double_click(_center(t))
    before = ed.inline_text.frame.geometry()
    ed.view.zoom_by(1.5)
    ed.view.horizontalScrollBar().setValue(ed.view.horizontalScrollBar().value() + 40)
    after = ed.inline_text.frame.geometry()
    r = ed.view.mapFromScene(ed.inline_text._anchor_rect()).boundingRect()
    assert after != before and abs(after.left() - max(6, r.left())) <= 2
