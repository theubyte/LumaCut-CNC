"""Schraffur-Vorschau auf der Arbeitsfläche.

Zeigt die Füllung (Schraffur/Kreuzschraffur) gefüllter Ebenen als dünne
Linien in der Ebenenfarbe unter den Objekten – dieselbe Geometrie wie im
G-Code (``export.shape_fill_segments``). Läuft über den Overlay-Hook des
Editors, berechnet erst nach kurzer Ruhe neu (Ziehen bleibt flüssig) und
ändert weder Dokument noch Export.
"""

from __future__ import annotations

from PySide6.QtCore import QLineF, QObject, QRectF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen

from .export import shape_fill_segments

OVERLAY_KEY = "fill_preview"
DEBOUNCE_MS = 120
MAX_PREVIEW_LINES = 200_000   # darüber wird nicht mehr gezeichnet (nur der G-Code zählt)


class FillPreview(QObject):
    """Overlay mit ``visible``/``opacity``/``paint`` für ``editor.add_overlay``."""

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.editor = editor
        self.visible = True
        self.opacity = 0.75
        self.lines: list[tuple[QColor, list[QLineF]]] = []
        self.truncated = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self.rebuild)
        self._installed = False
        editor.document.add_listener(self.schedule)
        self.rebuild()

    def schedule(self) -> None:
        self._timer.start()

    def rebuild(self) -> None:
        doc = self.editor.document
        out: list[tuple[QColor, list[QLineF]]] = []
        total = 0
        self.truncated = False
        for layer in doc.layers:
            if not layer.visible or layer.fill_mode == "none":
                continue
            lines: list[QLineF] = []
            for s in doc.shapes_in_layer(layer.id):
                try:
                    segs = shape_fill_segments(s, layer)
                except ValueError:      # zu viele Linien: Hinweis kommt beim Export
                    self.truncated = True
                    continue
                total += len(segs)
                if total > MAX_PREVIEW_LINES:
                    self.truncated = True
                    break
                lines.extend(QLineF(a[0], a[1], b[0], b[1]) for a, b in segs)
            if lines:
                out.append((QColor(layer.color), lines))
            if total > MAX_PREVIEW_LINES:
                break
        self.lines = out
        # Nur angemeldet, solange es etwas zu zeigen gibt (andere Overlays unberührt).
        if out and not self._installed:
            self.editor.add_overlay(OVERLAY_KEY, self, z=50)
            self._installed = True
        elif not out and self._installed:
            self.editor.remove_overlay(OVERLAY_KEY)
            self._installed = False
        elif out:
            self.editor.refresh_overlays()

    def line_count(self) -> int:
        return sum(len(l) for _, l in self.lines)

    def paint(self, painter: QPainter, work: QRectF) -> None:
        for color, lines in self.lines:
            pen = QPen(color, 0)          # kosmetisch: 1 px bei jedem Zoom
            painter.setPen(pen)
            painter.drawLines(lines)
