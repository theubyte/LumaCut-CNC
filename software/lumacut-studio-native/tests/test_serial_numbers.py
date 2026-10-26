"""Seriennummern: Vorlage → Raster nummerierter Textkopien (ein Undo-Schritt)."""

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_canvas.model import Geometry, Shape  # noqa: E402
from lumacut_job.serial import (MAX_COUNT, SerialSpec, default_template, format_serial,
                                has_counter, serial_shapes)


def _aspect(text, family, bold, italic):  # 0.5 mm Breite je Zeichen bei 1 mm Höhe
    return 0.5 * max(1, len(text))


def test_format_tokens():
    day = dt.date(2026, 10, 26)
    assert format_serial("Nr. {n}", 7) == "Nr. 7"
    assert format_serial("{n:3}-{n:1}", 7) == "007-7"
    assert format_serial("{n:3}", -7) == "-007"
    assert format_serial("{{n}} {n} {date}", 12, day) == "{n} 12 26.10.2026"
    assert has_counter("A {n:2}") and not has_counter("A {{n}}") and not has_counter("{date}")
    assert default_template("Schild") == "Schild {n}"
    assert default_template("Nr {n:4}") == "Nr {n:4}"
    assert default_template("") == "{n}"


def test_spec_values_and_clamping():
    s = SerialSpec("{n}", start=10, step=-5, count=4)
    assert s.values() == [10, 5, 0, -5]
    assert s.texts() == ["10", "5", "0", "-5"]
    big = SerialSpec(count=10_000, columns=0, gap_x_mm=-3).normalized()
    assert big.count == MAX_COUNT and big.columns == 1 and big.gap_x_mm == 0


def test_grid_layout_widths_group_and_stretch():
    src = Shape("text", Geometry(10, 20, 6, 4), "L1", text="T{n}", groups=("outer",))
    # Streckung: Breite 6 bei Höhe 4 und Seitenverhältnis 0.5*4=2 → 6/(4*2) = 0.75
    shapes = serial_shapes(src, SerialSpec("T{n}", start=8, count=5, columns=2,
                                           gap_x_mm=1, gap_y_mm=2), _aspect)
    assert [s.text for s in shapes] == ["T8", "T9", "T10", "T11", "T12"]
    assert all(s.id != src.id for s in shapes) and len({s.id for s in shapes}) == 5
    assert all(s.layer_id == "L1" and s.kind == "text" for s in shapes)
    assert shapes[0].geom.w == pytest.approx(4 * 0.5 * 2 * 0.75)  # "T8"
    assert shapes[2].geom.w == pytest.approx(4 * 0.5 * 3 * 0.75)  # "T10"
    cell = max(s.geom.w for s in shapes)
    pos = [(round(s.geom.x, 6), round(s.geom.y, 6)) for s in shapes]
    assert pos == [(10, 20), (round(10 + cell + 1, 6), 20), (10, 26),
                   (round(10 + cell + 1, 6), 26), (10, 32)]
    assert all(s.geom.h == 4 for s in shapes)
    g = shapes[0].groups
    assert len(g) == 2 and g[1] == "outer" and all(s.groups == g for s in shapes)
    assert src.text == "T{n}" and src.geom.x == 10  # Vorlage unverändert


def test_errors():
    src = Shape("text", Geometry(10, 20, 6, 4), "L1", text="T")
    with pytest.raises(ValueError, match="Platzhalter"):
        serial_shapes(src, SerialSpec("ohne"), _aspect)
    with pytest.raises(ValueError, match="Textobjekt"):
        serial_shapes(Shape("rect", Geometry(0, 0, 5, 5), "L1"), SerialSpec(), _aspect)
    with pytest.raises(ValueError, match="Arbeitsfläche"):
        serial_shapes(src, SerialSpec("{n}", count=200, columns=1, gap_y_mm=5), _aspect)


def test_rotated_text_keeps_rotation():
    src = Shape("text", Geometry(50, 50, 10, 5), "L1", text="{n}")
    src.geom.rot = 90
    shapes = serial_shapes(src, SerialSpec("{n}", count=3, columns=3), _aspect)
    assert all(s.geom.rot == 90 for s in shapes)


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


def test_action_one_undo_step_and_gcode(win, monkeypatch):
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QMessageBox

    from lumacut_job.planner import optimized_document_gcode

    tools = win.job_tools
    a = tools.serial_action
    assert a.objectName() == "serial_numbers_action"
    assert a.shortcut() == QKeySequence("Alt+N")
    doc = win.canvas.document
    lid = doc.active_layer_id
    rect = doc.add_shape(Shape("rect", Geometry(10, 10, 20, 20), lid))
    txt = doc.add_shape(Shape("text", Geometry(40, 40, 20, 8), lid, text="Nr. {n:3}"))
    before = len(doc.shapes)
    win.canvas.set_selection([rect.id])
    assert tools.serial_numbers(SerialSpec("{n}")) == []
    assert "Textobjekt" in win.statusBar().currentMessage()
    win.canvas.set_selection([txt.id])
    ids = tools.serial_numbers(SerialSpec("Nr. {n:3}", start=1, count=6, columns=3))
    assert len(ids) == 6
    assert not doc.has_shape(txt.id)
    assert [doc.shape(i).text for i in ids] == [f"Nr. {i:03}" for i in range(1, 7)]
    assert len(doc.shapes) == before - 1 + 6
    assert sorted(win.canvas.selection) == sorted(ids)
    gcode = optimized_document_gcode(doc)
    assert gcode.count("G1 ") > 50
    win.canvas.undo_stack.undo()
    assert doc.has_shape(txt.id) and not any(doc.has_shape(i) for i in ids)
    assert len(doc.shapes) == before
    # Zu groß → Warnung, nichts verändert
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    win.canvas.set_selection([txt.id])
    assert tools.serial_numbers(SerialSpec("{n}", count=100, columns=1)) == []
    assert warned and "Arbeitsfläche" in warned[0] and len(doc.shapes) == before
    pi_check(gcode)


def test_dialog_preview(qapp):
    from lumacut_job.serial_qt import SerialDialog
    dlg = SerialDialog("Schild")
    assert dlg.template.text() == "Schild {n}"
    dlg.start.setValue(98)
    dlg.count.setValue(5)
    dlg.template.setText("S-{n:3}")
    assert dlg.preview.text() == "S-098, S-099, S-100, … S-102"
    assert dlg.ok_button.isEnabled()
    spec = dlg.spec()
    assert (spec.template, spec.start, spec.count) == ("S-{n:3}", 98, 5)
    dlg.template.setText("kein Platzhalter")
    assert not dlg.ok_button.isEnabled() and "fehlt" in dlg.preview.text()
    dlg.deleteLater()
