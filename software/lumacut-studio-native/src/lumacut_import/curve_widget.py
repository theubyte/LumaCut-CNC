"""Gradationskurve im Bildeinstellungs-Dialog (wie „Kurven“ in Bildbearbeitungen).

:class:`CurveWidget` zeigt die Kurve über dem Histogramm des Bildes: links
Schwarz, rechts Weiß, unten Schwarz, oben Weiß. Bedienung (Maus, Stift und
Touch – große Fangradien):

* Ziehen eines Punktes verschiebt ihn (Eingang zwischen den Nachbarn);
* Klicken / Tippen neben die Punkte setzt einen neuen Punkt auf der Kurve
  und zieht ihn gleich weiter;
* Doppelklick oder Rechtsklick auf einen inneren Punkt löscht ihn; ein
  Endpunkt wird dabei auf seine Ecke zurückgesetzt;
* Entf / Rücktaste löscht den zuletzt gewählten Punkt.

:data:`CURVE_PRESETS` sind die üblichen Kurven (S-Kurve usw.) für das
Vorlagen-Menü. Die Kurve wird als Stützpunkte ``((ein, aus), ...)``
(Grauwerte) in :class:`lumacut_canvas.model.ImageSettings` gespeichert und
im Auftrag von :func:`lumacut_job.raster.adjust_gray` angewandt – nach dem
Schwarz-/Weißpunkt, vor Helligkeit, Kontrast und Gamma.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from lumacut_canvas.model import CURVE_MAX_POINTS, normalize_curve
from lumacut_job.raster import curve_lut

LINEAR = ((0, 0), (255, 255))

#: Vorlagen (Name → Stützpunkte); „Linear“ = keine Kurve.
CURVE_PRESETS: dict[str, tuple] = {
    "Linear": (),
    "Kontrast verstärken (S-Kurve)": ((0, 0), (64, 44), (192, 212), (255, 255)),
    "Kontrast stark verstärken": ((0, 0), (64, 28), (192, 228), (255, 255)),
    "Kontrast verringern": ((0, 0), (64, 84), (192, 172), (255, 255)),
    "Mitteltöne aufhellen": ((0, 0), (128, 168), (255, 255)),
    "Mitteltöne abdunkeln": ((0, 0), (128, 88), (255, 255)),
    "Schatten aufhellen (dunkle Holzstellen)": ((0, 0), (48, 88), (128, 150), (255, 255)),
    "Lichter abdunkeln (helle Flächen gravieren)": ((0, 0), (128, 110), (208, 176), (255, 255)),
}
CUSTOM_LABEL = "Benutzerdefiniert"

GRAB_RADIUS_PX = 12      # Fangradius für Punkte (fingertauglich)
MARGIN_PX = 6


def preset_name(curve) -> str:
    """Name der Vorlage zu ``curve`` oder :data:`CUSTOM_LABEL`."""
    c = normalize_curve(curve)
    for name, pts in CURVE_PRESETS.items():
        if normalize_curve(pts) == c:
            return name
    return CUSTOM_LABEL


class CurveWidget(QWidget):
    """Bearbeitbare Gradationskurve; ``curve_changed`` liefert die
    normalisierten Stützpunkte (``()`` = linear)."""

    curve_changed = Signal(tuple)

    def __init__(self, curve=(), parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("image_curve")
        self.setMinimumSize(160, 160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_AcceptTouchEvents, False)  # Touch kommt als Maus an
        self.setToolTip("Gradationskurve: Punkt ziehen; neben die Kurve klicken = neuer Punkt; "
                        "Doppel-/Rechtsklick auf einen Punkt = löschen. Links Schwarz, "
                        "rechts Weiß; nach oben = heller (weniger lasern).")
        self._points: list[tuple[int, int]] = list(normalize_curve(curve) or LINEAR)
        self._drag: int | None = None
        self._selected: int | None = None
        self._hist: np.ndarray | None = None

    # -- Daten -----------------------------------------------------------
    def sizeHint(self) -> QSize:
        return QSize(220, 180)

    def curve(self) -> tuple:
        """Normalisierte Stützpunkte (``()`` = linear)."""
        return normalize_curve(self._points)

    def points(self) -> list[tuple[int, int]]:
        return list(self._points)

    def set_curve(self, curve, emit: bool = False) -> None:
        new = list(normalize_curve(curve) or LINEAR)
        if new == self._points:
            return
        self._points = new
        self._drag = self._selected = None
        self.update()
        if emit:
            self.curve_changed.emit(self.curve())

    def set_histogram(self, hist) -> None:
        """Histogramm (256 Werte) des Bildes als Hintergrund."""
        self._hist = None if hist is None else np.asarray(hist, dtype=float)
        self.update()

    # -- Koordinaten ------------------------------------------------------
    def _plot(self) -> QRectF:
        m = MARGIN_PX
        return QRectF(m, m, max(1, self.width() - 2 * m), max(1, self.height() - 2 * m))

    def to_widget(self, x: float, y: float) -> QPointF:
        r = self._plot()
        return QPointF(r.left() + x / 255.0 * r.width(), r.bottom() - y / 255.0 * r.height())

    def to_value(self, pos: QPointF) -> tuple[int, int]:
        r = self._plot()
        x = (pos.x() - r.left()) / r.width() * 255.0
        y = (r.bottom() - pos.y()) / r.height() * 255.0
        return int(round(min(255, max(0, x)))), int(round(min(255, max(0, y))))

    def point_at(self, pos: QPointF) -> int | None:
        best, best_d = None, GRAB_RADIUS_PX ** 2
        for i, (x, y) in enumerate(self._points):
            p = self.to_widget(x, y)
            d = (p.x() - pos.x()) ** 2 + (p.y() - pos.y()) ** 2
            if d <= best_d:
                best, best_d = i, d
        return best

    # -- Bearbeiten ---------------------------------------------------------
    def _changed(self) -> None:
        self.update()
        self.curve_changed.emit(self.curve())

    def add_point(self, x: int, y: int | None = None) -> int | None:
        """Punkt bei Eingang ``x`` (Ausgang ``y`` oder auf der Kurve)
        einfügen; Index oder None (Eingang belegt / zu viele Punkte)."""
        x = int(min(255, max(0, x)))
        if any(px == x for px, _ in self._points) or len(self._points) >= CURVE_MAX_POINTS:
            return None
        if y is None:
            y = int(round(float(curve_lut(self._points, 256)[x]) * 255.0))
        self._points.append((x, int(min(255, max(0, y)))))
        self._points.sort()
        i = [p[0] for p in self._points].index(x)
        self._selected = i
        self._changed()
        return i

    def move_point(self, i: int, x: int, y: int) -> None:
        """Punkt ``i`` verschieben; der Eingang bleibt zwischen den Nachbarn."""
        lo = self._points[i - 1][0] + 1 if i > 0 else 0
        hi = self._points[i + 1][0] - 1 if i < len(self._points) - 1 else 255
        new = (int(min(hi, max(lo, x))), int(min(255, max(0, y))))
        if new != self._points[i]:
            self._points[i] = new
            self._changed()

    def remove_point(self, i: int) -> None:
        """Inneren Punkt löschen; Endpunkt auf seine Ecke zurücksetzen."""
        if not 0 <= i < len(self._points):
            return
        if 0 < i < len(self._points) - 1:
            del self._points[i]
        else:
            corner = (0, 0) if i == 0 else (255, 255)
            others = [p[0] for j, p in enumerate(self._points) if j != i]
            if corner[0] in others:
                return
            self._points[i] = corner
            self._points.sort()
        self._selected = None
        self._changed()

    # -- Ereignisse -------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        pos = event.position()
        i = self.point_at(pos)
        if event.button() == Qt.RightButton:
            if i is not None:
                self.remove_point(i)
            return
        if event.button() != Qt.LeftButton:
            return
        if i is None:
            x, _ = self.to_value(pos)
            i = self.add_point(x)
        self._drag = self._selected = i
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None:
            x, y = self.to_value(event.position())
            self.move_point(self._drag, x, y)

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None

    def mouseDoubleClickEvent(self, event) -> None:
        i = self.point_at(event.position())
        if i is not None:
            self._drag = None
            self.remove_point(i)

    def event(self, event) -> bool:
        # Delete/Backspace remove the selected point even where an application
        # shortcut (e.g. "delete object") uses the same key.
        if (event.type() == QEvent.ShortcutOverride
                and event.key() in (Qt.Key_Delete, Qt.Key_Backspace)
                and self._selected is not None):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self._selected is not None:
            self.remove_point(self._selected)
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot()
        p.fillRect(self.rect(), QColor(250, 250, 250))
        if self._hist is not None and self._hist.size == 256 and self._hist.max() > 0:
            vals = np.sqrt(self._hist / self._hist.max())
            p.setPen(QColor(215, 215, 215))
            for i in range(256):
                if vals[i] > 0:
                    x = r.left() + (i + 0.5) / 256.0 * r.width()
                    p.drawLine(QPointF(x, r.bottom()), QPointF(x, r.bottom() - vals[i] * r.height()))
        p.setPen(QPen(QColor(200, 200, 200), 1, Qt.DotLine))
        for k in (1, 2, 3):
            x = r.left() + r.width() * k / 4
            y = r.top() + r.height() * k / 4
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        p.setPen(QPen(QColor(170, 170, 170), 1, Qt.DashLine))
        p.drawLine(QPointF(r.left(), r.bottom()), QPointF(r.right(), r.top()))
        p.setPen(QColor(150, 150, 150))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r)
        lut = curve_lut(self._points, 256)
        path = QPainterPath()
        for i in range(256):
            pt = self.to_widget(i, float(lut[i]) * 255.0)
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        p.setPen(QPen(QColor(30, 30, 30), 2))
        p.drawPath(path)
        for i, (x, y) in enumerate(self._points):
            pt = self.to_widget(x, y)
            sel = i == self._selected
            p.setPen(QPen(QColor(30, 90, 200), 2))
            p.setBrush(QColor(30, 90, 200) if sel else QColor(255, 255, 255))
            p.drawEllipse(pt, 5, 5)
        p.end()
