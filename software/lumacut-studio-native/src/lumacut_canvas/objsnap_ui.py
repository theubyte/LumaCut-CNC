"""„An Objekten fangen“ (Alt+Umschalt+S) – Objektfang mit Hilfslinien wie LightBurns
*Snap to Objects* und xTools Ausrichtungslinien.

* Schalter in der Aktionsleiste neben „Am Raster fangen“, Vorgabe an; die Wahl
  wird in QSettings (``canvas/object_snap``) gespeichert.
* Wirkt beim Zeichnen (Rechteck, Ellipse, Linie, Polygon, Vieleck / Stern, Text),
  beim Ziehen eines Skalier-Griffs (ungedrehter Rahmen), beim Verschieben von
  Knoten und beim Verschieben der Auswahl (Kanten / Mitten der Box). Wo der
  Objektfang greift, hat er Vorrang vor dem 1-mm-Raster; sonst gilt das Raster.
* Gedrückte Alt-Taste setzt den Objektfang während eines Zugs aus.
* Magentafarbene Hilfslinien und eine Marke am getroffenen Punkt zeigen, worauf
  eingerastet wurde; die Statusleiste nennt die Art („Fang: Knoten“).

Rechnen in :mod:`objsnap` (Qt-frei).
"""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem

from . import objsnap
from .objsnap import Snap, SnapTargets
from .workarea import Rect

SETTINGS_KEY = "canvas/object_snap"
GUIDE_COLOR = "#ff4fd8"
MARKER_PX = 5.0  # halbe Kantenlänge der Fangmarke


def load_setting(settings) -> bool | None:
    if settings is None or not settings.contains(SETTINGS_KEY):
        return None
    v = settings.value(SETTINGS_KEY)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def save_setting(settings, on: bool) -> None:
    if settings is not None:
        settings.setValue(SETTINGS_KEY, bool(on))
        settings.sync()


class SnapGuides(QGraphicsPathItem):
    """Hilfslinien und Fangmarke (kosmetischer Stift, über allem)."""

    def __init__(self) -> None:
        super().__init__()
        pen = QPen(QColor(GUIDE_COLOR), 1.0, Qt.DashLine)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setZValue(2.1e9)
        self.setVisible(False)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def show_snaps(self, snaps: Iterable[Snap | None], px_per_mm: float) -> None:
        snaps = [s for s in snaps if s is not None and s.snapped]
        if not snaps:
            self.setVisible(False)
            return
        path = QPainterPath()
        r = MARKER_PX / max(px_per_mm, 1e-9)
        for snap in snaps:
            for x1, y1, x2, y2 in snap.guides:
                path.moveTo(x1, y1)
                path.lineTo(x2, y2)
            if snap.point is not None:
                path.addRect(QRectF(snap.point[0] - r, snap.point[1] - r, 2 * r, 2 * r))
        self.setPath(path)
        self.setVisible(True)


class ObjectSnap:
    """Zustand des Objektfangs eines Editors (Ziele je Zug, Hilfslinien)."""

    def __init__(self, editor) -> None:
        self.ed = editor
        self.enabled = True  # gespeicherte Wahl: apply_saved()
        self.targets: SnapTargets | None = None
        self.suspended = False  # Alt gedrückt
        self.last: Snap | None = None
        # Fang des Startpunkts beim Zeichnen: bleibt während des Zugs sichtbar.
        self.anchor: Snap | None = None
        self._label = ""
        self.guides = SnapGuides()
        editor.scene.addItem(self.guides)

    # --- Schalter ------------------------------------------------------------
    def set_enabled(self, on: bool, persist: bool = True) -> None:
        on = bool(on)
        self.enabled = on
        if persist:
            save_setting(getattr(self.ed, "_settings", None), on)
        act = self.ed.actions_by_name.get("object_snap")
        if act is not None and act.isChecked() != on:
            act.blockSignals(True)
            act.setChecked(on)
            act.blockSignals(False)
        if not on:
            self.end()
        self.ed.notify("An Objekten fangen: an" if on else "An Objekten fangen: aus")

    def apply_saved(self, settings) -> None:
        """Gespeicherte Wahl übernehmen (ohne Meldung / erneutes Speichern)."""
        saved = load_setting(settings)
        if saved is not None and saved != self.enabled:
            self.enabled = saved
            act = self.ed.actions_by_name.get("object_snap")
            if act is not None:
                act.blockSignals(True)
                act.setChecked(saved)
                act.blockSignals(False)

    # --- Zug ---------------------------------------------------------------
    def begin(self, exclude: Iterable[str] = ()) -> None:
        """Ziele für einen Zug sammeln (``exclude``: gezogene Objekte / Vorschau)."""
        self.last = None
        self.anchor = None
        self.targets = SnapTargets.from_document(self.ed.document, exclude) if self.enabled else None

    def end(self) -> None:
        self.targets = None
        self.last = None
        self.anchor = None
        self._label = ""
        self.suspended = False
        self.guides.setVisible(False)

    def keep_anchor(self) -> None:
        """Den letzten Fang (Startpunkt) bis zum Ende des Zugs mit anzeigen."""
        self.anchor = self.last

    @property
    def active(self) -> bool:
        return self.enabled and self.targets is not None and not self.suspended

    def tolerance(self) -> float:
        return objsnap.tolerance_mm(self.ed.view.px_per_mm, bool(getattr(self.ed, "touch_mode", False)))

    def point(self, x: float, y: float) -> Snap | None:
        if not self.active:
            self._show(None)
            return None
        s = self.targets.snap_point(x, y, self.tolerance())
        self._show(s)
        return s

    def box(self, box: Rect, axes: tuple[bool, bool] = (True, True)) -> tuple[float, float, Snap] | None:
        if not self.active:
            self._show(None)
            return None
        ddx, ddy, s = self.targets.snap_box(box, self.tolerance(), axes)
        self._show(s)
        return ddx, ddy, s

    def _show(self, snap: Snap | None) -> None:
        self.last = snap if snap is not None and snap.snapped else None
        self.guides.show_snaps((self.anchor, self.last), self.ed.view.px_per_mm)
        label = self.last.label if self.last is not None else ""
        if label and label != self._label:
            self.ed.notify(f"Fang: {label}")
        self._label = label


def install(editor) -> ObjectSnap:
    snap = ObjectSnap(editor)
    a = editor._act("object_snap", "An Objekten fangen", lambda on: snap.set_enabled(on),
                    "Alt+Shift+S", "objsnap", checkable=True)
    a.setToolTip("An Objekten fangen – Knoten, Ecken, Mitten, Kanten anderer Objekte; "
                 "Alt beim Ziehen setzt aus  (Alt+Umschalt+S)")
    a.setChecked(snap.enabled)
    return snap


__all__ = ["ObjectSnap", "SnapGuides", "install", "SETTINGS_KEY"]
