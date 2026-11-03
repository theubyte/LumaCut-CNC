"""Schraffur-Vorschau auf der Arbeitsfläche.

Zeigt die Füllung (Schraffur/Kreuzschraffur) gefüllter Ebenen als dünne
Linien in der Ebenenfarbe unter den Objekten – dieselbe Geometrie wie im
G-Code (``export.layer_fill_blocks``, auch „Objekte zusammen füllen“). Läuft über den Overlay-Hook des
Editors, berechnet erst nach kurzer Ruhe neu (Ziehen bleibt flüssig) und
ändert weder Dokument noch Export.

Mit aktivem Scan-Versatz (``lumacut_job.scan_offset``) zeigt sie die Linien so,
wie sie gebrannt werden – um den halben Versatz entgegen ihrer Fahrtrichtung
verschoben, in Planer-Reihenfolge (``scan_offset.preview_fill_lines``); ohne
Versatz bleibt es bei der reinen Füllgeometrie.
"""

from __future__ import annotations

from PySide6.QtCore import QLineF, QObject, QRectF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen

from .export import layer_fill_blocks

OVERLAY_KEY = "fill_preview"
DEBOUNCE_MS = 120
MAX_PREVIEW_LINES = 200_000   # darüber wird nicht mehr gezeichnet (nur der G-Code zählt)


def _shifted_lines(doc):
    """Gebrannte Füllstrecken mit Scan-Versatz je Ebene, ``None`` = ohne Versatz."""
    try:
        from lumacut_job.scan_offset import preview_fill_lines
    except Exception:  # pragma: no cover - lumacut_job ist Teil der App
        return None
    try:
        return preview_fill_lines(doc)
    except ValueError:              # z. B. zu viele Linien: dann die reine Geometrie
        return None


class FillPreview(QObject):
    """Overlay mit ``visible``/``opacity``/``paint`` für ``editor.add_overlay``."""

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.editor = editor
        self.visible = True
        self.opacity = 0.75
        self.lines: list[tuple[QColor, list[QLineF]]] = []
        self.truncated = False
        self.scan_offset_applied = False   # zuletzt mit Scan-Versatz gezeichnet
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
        shifted = _shifted_lines(doc)
        self.scan_offset_applied = shifted is not None
        for layer in doc.layers:
            if not layer.visible or layer.fill_mode == "none":
                continue
            lines: list[QLineF] = []
            try:
                if shifted is not None:
                    blocks = [shifted.get(layer.id, [])]
                else:
                    blocks = [segs for _ids, segs in layer_fill_blocks(doc, layer)]
            except ValueError:          # zu viele Linien: Hinweis kommt beim Export
                self.truncated = True
                blocks = []
            for segs in blocks:
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
