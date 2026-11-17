"""Werkzeug „Passmarken“ (Alt+Umschalt+M) – Design an zwei Marken auf das echte
Werkstück legen wie LightBurns *Print and Cut* („Drucken und Schneiden“).

Ablauf (Maus oder Finger, je ein Tippen):

1. **Soll 1** – Marke im Design antippen (fängt an Mitten, Ecken, Knoten anderer
   Objekte, wenn „An Objekten fangen“ an ist; sonst die genaue Stelle, kein Raster),
2. **Ist 1** – dieselbe Marke dort antippen, wo sie wirklich liegt – auf dem
   Kamerascan als Hintergrund (genaue Stelle, ohne Raster- und Objektfang),
3. **Soll 2**, 4. **Ist 2** – zweite Marke, möglichst weit von der ersten entfernt.

Nach dem vierten Tippen werden die ausgewählten Objekte (ohne Auswahl: alle
Objekte entsperrter, sichtbarer Ebenen) in **einem** Undo-Schritt verschoben und
gedreht (:mod:`marks`); Eingabe nach dem zweiten Tippen verschiebt nur. Bis dahin
zeigt die Zeichenfläche die Punkte (blau = Soll, orange = Ist), die Pfeile
Soll → Ist und gestrichelt, wohin das Design käme. Ziehen statt Tippen setzt den
Punkt beim Loslassen (feines Nachführen mit dem Finger). Rücktaste nimmt den
letzten Punkt zurück, Esc löscht alle.

„Passmarken als Zahlen …“ (Menü „Anordnen“ / Kontextmenü des Werkzeugs) nimmt
die Punkte als X/Y in Anzeige-Koordinaten (Nullpunkt oben rechts) – z. B. mit
dem Lineal gemessen –, vorbelegt mit den angetippten Punkten. „Maßstab
angleichen“ (Vorgabe aus, gilt für die Sitzung) skaliert zusätzlich, damit beide
Marken genau treffen; sonst bleibt das Design maßhaltig.

Ausgerichtet wird in absoluten Koordinaten; steht die Startposition am Pi auf
„Kopfposition“ / „Benutzer-Ursprung“, nennt die Meldung das (der Pi würde den
Auftrag wieder verschieben). Ein Ergebnis, das über die Arbeitsfläche hinausragt,
wird abgelehnt statt (wie sonst) in die Fläche geschoben – sonst passten die
Marken nicht mehr.

Kein neuer Projekt-Schlüssel, nichts gespeichert; G-Code ändert sich nur durch
die bewegten Objekte selbst.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QGraphicsItem,
                               QGridLayout, QLabel, QVBoxLayout)

from . import marks
from .commands import SetGeometryCommand
from .workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, screen_to_user, user_to_screen

SOLL_COLOR = "#4fc3f7"
IST_COLOR = "#ff9f43"
GHOST_COLOR = "#ffffff"
Z_VALUE = 2.04e9
TAP_PX = 6.0
STEPS = ("Soll 1", "Ist 1", "Soll 2", "Ist 2")
STEP_HINTS = (
    "Marke 1 im Design antippen (fängt an Objekten)",
    "Marke 1 dort antippen, wo sie wirklich liegt (Kamerascan, genaue Stelle)",
    "Marke 2 im Design antippen – oder Eingabe = nur verschieben",
    "Marke 2 dort antippen, wo sie wirklich liegt",
)


def placement_hint() -> str:
    """Hinweis, wenn der Pi den Auftrag gerade verschiebt (Kopfposition / Benutzer-Ursprung).

    Passmarken richten in absoluten Koordinaten aus; „Aktuelle Position“ oder
    „Benutzer-Ursprung“ am Pi würden den ausgerichteten Auftrag wieder verschieben.
    """
    try:
        from lumacut_job.park_corner import ORIGIN_NAMES
        from lumacut_job.park_routine import active_start
        origin = active_start().origin
    except Exception:  # pragma: no cover - ohne Job-Paket kein Hinweis
        return ""
    if origin == "absolute":
        return ""
    name = ORIGIN_NAMES.get(origin, origin)
    return (f" – Hinweis: Startposition am Pi ist „{name}“ und verschiebt den Auftrag; "
            "für Passmarken „Absolut“ wählen")


def _touch(ed) -> bool:
    return bool(getattr(ed, "touch_mode", False))


class MarksOverlay(QGraphicsItem):
    """Soll- / Ist-Punkte, Pfeile und das bewegte Design (Umriss) in Szenen-mm."""

    def __init__(self, ed) -> None:
        super().__init__()
        self.ed = ed
        self.points: list[tuple[float, float]] = []
        self.hover: tuple[float, float] | None = None
        self.ghost: list[list[tuple[float, float]]] = []
        self.setZValue(Z_VALUE)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setVisible(False)

    def set_state(self, points, hover, ghost) -> None:
        self.points = list(points)
        self.hover = hover
        self.ghost = [list(g) for g in ghost or []]
        self.setVisible(bool(self.points) or self.hover is not None)
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt API
        return QRectF(-60, -60, WORK_WIDTH_MM + 120, WORK_HEIGHT_MM + 120)

    def paint(self, p: QPainter, option, widget=None) -> None:
        ppm = max(float(getattr(self.ed.view, "px_per_mm", 1.0)), 1e-6)
        touch = _touch(self.ed)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(Qt.NoBrush)
        if self.ghost:
            pen = QPen(QColor(GHOST_COLOR), 1.0, Qt.DashLine)
            pen.setCosmetic(True)
            p.setPen(pen)
            for poly in self.ghost:
                p.drawPolygon(QPolygonF([QPointF(*q) for q in poly]))
        pts = list(self.points)
        if self.hover is not None and len(pts) < 4:
            pts.append(self.hover)
        for i in range(0, len(pts) - 1, 2):       # Pfeil Soll → Ist
            a, b = QPointF(*pts[i]), QPointF(*pts[i + 1])
            pen = QPen(QColor(IST_COLOR), 1.5, Qt.DashLine)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.drawLine(a, b)
        r = (8.0 if touch else 5.5) / ppm
        font = QFont()
        font.setPointSizeF(12.0 if touch else 9.0)
        font.setBold(True)
        for i, q in enumerate(pts):
            soll = i % 2 == 0
            color = QColor(SOLL_COLOR if soll else IST_COLOR)
            if i >= len(self.points):
                color.setAlpha(150)               # folgt noch der Maus
            pen = QPen(color, 2.0 if touch else 1.5)
            pen.setCosmetic(True)
            p.setPen(pen)
            c = QPointF(*q)
            if soll:
                p.drawEllipse(c, r, r)
            else:
                path = QPainterPath()
                path.moveTo(c.x() - r * 1.4, c.y())
                path.lineTo(c.x() + r * 1.4, c.y())
                path.moveTo(c.x(), c.y() - r * 1.4)
                path.lineTo(c.x(), c.y() + r * 1.4)
                p.drawPath(path)
                p.drawRect(QRectF(c.x() - r * 0.6, c.y() - r * 0.6, r * 1.2, r * 1.2))
            p.save()
            p.translate(c)
            p.scale(1.0 / ppm, 1.0 / ppm)
            p.setFont(font)
            p.drawText(QPointF(r * ppm + 3, -r * ppm - 2), str(i // 2 + 1))
            p.restore()


class MarksTool:
    """Zustand und Bedienung des Passmarken-Werkzeugs (von ToolController gerufen)."""

    def __init__(self, editor) -> None:
        self.ed = editor
        self.points: list[tuple[float, float]] = []   # Soll 1, Ist 1, Soll 2, Ist 2
        self.scale = False
        self._press: QPointF | None = None
        self._hover: tuple[float, float] | None = None
        self.item = MarksOverlay(editor)
        editor.scene.addItem(self.item)

    @property
    def doc(self):
        return self.ed.document

    @property
    def ctl(self):
        return self.ed.tools

    @property
    def step(self) -> int:
        """Index des nächsten Punkts (0 … 3)."""
        return len(self.points)

    @property
    def active(self) -> bool:
        return bool(self.points) or self._press is not None

    # --- Ziel und Punkte ----------------------------------------------------
    def target_ids(self) -> tuple[list[str], bool]:
        """(Objekte, die bewegt werden, ob es die Auswahl ist)."""
        doc = self.doc
        sel = [i for i in self.ed.selection if doc.has_shape(i) and doc.is_editable(i)]
        if sel:
            return sel, True
        return [s.id for s in doc.shapes if doc.is_editable(s.id)], False

    def _snap_soll(self, pos: QPointF) -> tuple[float, float]:
        osnap = self.ctl.object_snap
        if osnap is not None:
            if osnap.targets is None:
                osnap.begin(())
            s = osnap.point(pos.x(), pos.y())
            if s is not None and s.snapped_x and s.snapped_y and s.point is not None:
                return (float(s.point[0]), float(s.point[1]))
        return (pos.x(), pos.y())

    def _raw(self, pos: QPointF) -> tuple[float, float]:
        osnap = self.ctl.object_snap
        if osnap is not None and osnap.targets is not None:
            osnap.end()                              # Ist-Punkt: genau dort, kein Fang
        return (pos.x(), pos.y())

    def point_for(self, pos: QPointF) -> tuple[float, float]:
        return self._snap_soll(pos) if self.step % 2 == 0 else self._raw(pos)

    def fit(self, points=None) -> marks.MarkFit:
        pts = list(self.points if points is None else points)
        return marks.fit_marks(pts[0::2], pts[1::2], self.scale)

    def _ghost(self, pts) -> list[list[tuple[float, float]]]:
        if len(pts) < 2:
            return []
        try:
            f = self.fit(pts[: 4 if len(pts) >= 4 else 2])
        except marks.MarkError:
            return []
        ids, _ = self.target_ids()
        out = []
        for i in ids[:200]:
            g = f.map_geometry(self.doc.shape(i).geom)
            out.append(g.corner_points())
        return out

    def refresh(self) -> None:
        pts = list(self.points)
        if self._hover is not None and len(pts) < 4:
            pts.append(self._hover)
        self.item.set_state(self.points, self._hover if len(self.points) < 4 else None,
                            self._ghost(pts))

    def _prompt(self) -> None:
        i = min(self.step, 3)
        ids, is_sel = self.target_ids()
        what = (f"{len(ids)} ausgewählte Objekt(e)" if is_sel
                else f"alle {len(ids)} Objekt(e)")
        self.ed.notify(f"Passmarken ({what}): {STEPS[i]} – {STEP_HINTS[i]} "
                       "(Rücktaste = letzter Punkt zurück, Esc = neu)")

    # --- Aktion -------------------------------------------------------------
    def apply(self, soll, ist, scale: bool | None = None) -> bool:
        """Ziele mit den Passmarken bewegen (ein Undo-Schritt); True wenn bewegt."""
        if scale is not None:
            self.scale = bool(scale)
        ids, is_sel = self.target_ids()
        if not ids:
            self.ed.notify("Passmarken: keine bewegbaren Objekte (Ebenen gesperrt oder ausgeblendet)")
            return False
        try:
            f = marks.fit_marks(soll, ist, self.scale)
        except marks.MarkError as e:
            self.ed.notify(str(e))
            return False
        if f.is_identity:
            self.ed.notify("Passmarken: Soll und Ist stimmen schon überein – nichts bewegt")
            return False
        doc = self.doc
        old = {i: doc.shape(i).geom.copy() for i in ids}
        new = marks.map_geometries(old, f)
        if not marks.inside_work_area(new.values()):
            # Das Dokument würde die Objekte in die Fläche schieben – dann passen die Marken nicht.
            self.ed.notify("Passmarken: das Design läge danach teils außerhalb der Arbeitsfläche – "
                           "nicht ausgerichtet (Werkstück weiter innen auflegen oder Punkte prüfen)")
            return False
        self.ed.undo_stack.push(SetGeometryCommand(doc, old, new, "Passmarken ausrichten"))
        if not is_sel:
            self.ed.set_selection(ids)
        text = f"Passmarken: {len(ids)} Objekt(e) ausgerichtet – {marks.summary(f)}"
        if f.error_mm > marks.WARN_ERROR_MM:
            text += " – Abweichung groß: Punkte prüfen oder „Maßstab angleichen“"
        hint = placement_hint()
        self.ed.notify(text + hint + " – Strg+Z holt es zurück")
        return True

    def apply_points(self) -> bool:
        pts = list(self.points)
        n = 4 if len(pts) >= 4 else 2
        if len(pts) < 2:
            self.ed.notify("Passmarken: erst Soll 1 und Ist 1 antippen")
            return False
        ok = self.apply(pts[0:n:2], pts[1:n:2])
        if ok:
            self.clear()
        return ok

    # --- Eingaben (Szenen-mm) ---------------------------------------------
    def hover(self, pos: QPointF) -> None:
        if not self.points and self._press is None:
            self._hover = None
            if self.item.isVisible():
                self.refresh()
            return
        self._hover = self.point_for(pos) if len(self.points) < 4 else None
        self.refresh()

    def press(self, pos: QPointF) -> None:
        self._press = QPointF(pos)
        self._hover = self.point_for(pos)
        self.refresh()

    def move(self, pos: QPointF) -> None:
        if self._press is None:
            return
        self._hover = self.point_for(pos)
        self.refresh()

    def release(self, pos: QPointF) -> None:
        if self._press is None:
            return
        self._press = None
        p = self.point_for(pos)
        osnap = self.ctl.object_snap
        if osnap is not None:
            osnap.end()
        self._hover = None
        self.points.append(p)
        if len(self.points) == 4:
            if not self.apply_points():
                self.points.pop()                    # letzten Ist-Punkt neu setzen
                self.refresh()
            return
        self.refresh()
        self._prompt()

    def undo_point(self) -> bool:
        if not self.points:
            return False
        self.points.pop()
        self._hover = None
        self.refresh()
        self._prompt()
        return True

    def clear(self) -> bool:
        had = bool(self.points)
        self.points = []
        self._press = None
        self._hover = None
        self.item.set_state([], None, [])
        return had

    def cancel(self) -> None:
        """Werkzeugwechsel / Abbruch: Punkte verwerfen."""
        self.clear()

    def abort(self) -> None:
        """Zweiter Finger (Zoomen): nur den laufenden Zug verwerfen, Punkte bleiben."""
        self._press = None
        self._hover = None
        self.refresh()

    def key_press(self, event: QKeyEvent) -> bool:
        k = event.key()
        if k == Qt.Key_Escape and self.clear():
            self.ed.notify("Passmarken gelöscht")
            return True
        if k == Qt.Key_Backspace and self.undo_point():
            return True
        if k in (Qt.Key_Return, Qt.Key_Enter) and len(self.points) >= 2:
            self.apply_points()
            return True
        return False

    def set_scale(self, on: bool) -> None:
        self.scale = bool(on)
        a = self.ed.actions_by_name.get("marks_scale")
        if a is not None and a.isChecked() != self.scale:
            a.blockSignals(True)
            a.setChecked(self.scale)
            a.blockSignals(False)
        self.refresh()
        self.ed.notify("Passmarken: Maßstab angleichen " + ("an" if self.scale else "aus (maßhaltig)"))

    def numeric_dialog(self) -> bool:
        dlg = MarksDialog(self, self.ed)
        if dlg.exec() != QDialog.Accepted:
            return False
        return dlg.apply()


class MarksDialog(QDialog):
    """„Passmarken als Zahlen …“ – Soll / Ist in Anzeige-Koordinaten (Nullpunkt oben rechts)."""

    def __init__(self, tool: MarksTool, parent=None) -> None:
        super().__init__(parent)
        self.tool = tool
        self.setWindowTitle("Passmarken ausrichten")
        lay = QVBoxLayout(self)
        intro = QLabel("Soll = Lage der Marke im Design, Ist = gemessene Lage auf dem Bett "
                       "(Anzeige-Koordinaten in mm, Nullpunkt oben rechts).")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        grid = QGridLayout()
        grid.addWidget(QLabel("X"), 0, 1)
        grid.addWidget(QLabel("Y"), 0, 2)
        self.spins: list[tuple[QDoubleSpinBox, QDoubleSpinBox]] = []
        for i, name in enumerate(STEPS):
            grid.addWidget(QLabel(name), i + 1, 0)
            pair = []
            for col in (1, 2):
                sp = QDoubleSpinBox()
                sp.setRange(-1000.0, 1000.0)
                sp.setDecimals(2)
                sp.setSingleStep(0.1)
                sp.setSuffix(" mm")
                sp.valueChanged.connect(self.update_info)
                grid.addWidget(sp, i + 1, col)
                pair.append(sp)
            self.spins.append((pair[0], pair[1]))
        lay.addLayout(grid)
        self.second = QCheckBox("Zweites Paar verwenden (drehen)")
        self.second.setChecked(True)
        self.second.toggled.connect(self.update_info)
        self.scale = QCheckBox("Maßstab angleichen (sonst maßhaltig)")
        self.scale.setChecked(tool.scale)
        self.scale.toggled.connect(self.update_info)
        lay.addWidget(self.second)
        lay.addWidget(self.scale)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Ausrichten")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self._prefill()
        self.update_info()

    def _prefill(self) -> None:
        pts = list(self.tool.points)
        ids, _ = self.tool.target_ids()
        b = self.tool.doc.selection_bounds(ids) if ids else None
        corners = ([(b.x, b.y), (b.x, b.y), (b.right, b.bottom), (b.right, b.bottom)] if b is not None
                   else [(0.0, 0.0)] * 4)
        for i in range(4):
            if i < len(pts):
                x, y = pts[i]
            elif i % 2 == 1 and i - 1 < len(pts):
                x, y = pts[i - 1]                    # Ist beginnt beim Soll-Punkt
            else:
                x, y = corners[i]
            for sp, val in zip(self.spins[i], screen_to_user(x, y)):
                sp.blockSignals(True)
                sp.setValue(round(val, 2))
                sp.blockSignals(False)
        self.second.setChecked(len(pts) != 2 and len(pts) != 3)

    def set_point(self, i: int, u: float, v: float) -> None:
        """Punkt ``i`` (0 … 3) in Anzeige-Koordinaten setzen (für Tests / Skripte)."""
        self.spins[i][0].setValue(u)
        self.spins[i][1].setValue(v)

    def screen_points(self) -> list[tuple[float, float]]:
        n = 4 if self.second.isChecked() else 2
        return [user_to_screen(sx.value(), sy.value()) for sx, sy in self.spins[:n]]

    def update_info(self, *_a) -> None:
        for sx, sy in self.spins[2:]:
            sx.setEnabled(self.second.isChecked())
            sy.setEnabled(self.second.isChecked())
        pts = self.screen_points()
        ok = True
        try:
            f = marks.fit_marks(pts[0::2], pts[1::2], self.scale.isChecked())
            text = marks.summary(f)
        except marks.MarkError as e:
            text, ok = str(e), False
        self.info.setText(text)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)

    def apply(self) -> bool:
        pts = self.screen_points()
        ok = self.tool.apply(pts[0::2], pts[1::2], self.scale.isChecked())
        if ok:
            self.tool.clear()
        return ok


MENU_ACTIONS = ["tool_marks", "marks_numeric"]


def add_to_menu(editor, menu) -> None:
    """Kontextmenü im Werkzeug: Zahlen-Dialog, Maßstab, Punkte löschen."""
    a = editor.actions_by_name
    menu.addAction(a["marks_numeric"])
    menu.addAction(a["marks_scale"])
    if editor.marks_tool.points:
        menu.addAction(a["marks_clear"])


def install(editor) -> MarksTool:
    tool = MarksTool(editor)
    n = editor._act("marks_numeric", "Passmarken als Zahlen …", lambda: tool.numeric_dialog())
    n.setToolTip("Design an zwei gemessenen Marken ausrichten: Soll- und Ist-Punkte als X/Y eingeben "
                 "(wie LightBurns Print and Cut)")
    s = editor._act("marks_scale", "Passmarken: Maßstab angleichen",
                    lambda on: tool.set_scale(on), checkable=True)
    s.setToolTip("Aus (Vorgabe): Design bleibt maßhaltig, nur verschieben / drehen. An: zusätzlich "
                 "gleichmäßig skalieren, damit beide Marken genau treffen")
    editor._act("marks_clear", "Passmarken löschen",
                lambda: tool.clear() and editor.notify("Passmarken gelöscht"))
    return tool


__all__ = ["MENU_ACTIONS", "MarksDialog", "MarksOverlay", "MarksTool", "add_to_menu", "install"]
