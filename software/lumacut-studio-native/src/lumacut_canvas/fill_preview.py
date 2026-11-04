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

Den Planer dafür rechnet ein Hintergrund-Thread (``FillPreviewJob.run``, nur
reine Python-Daten, keine Qt-Objekte): bis er fertig ist, zeigt die Vorschau
die reine Füllgeometrie (``scan_offset_pending``), danach die verschobenen
Linien. Jede neue Änderung bricht einen laufenden Lauf ab (``should_stop`` im
Planer) und verwirft sein Ergebnis – es wird nie eine veraltete Planung
gezeichnet. Ergebnisse holt ein Timer im GUI-Thread ab.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QLineF, QObject, QRectF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen

from .export import layer_fill_blocks

OVERLAY_KEY = "fill_preview"
DEBOUNCE_MS = 120
POLL_MS = 25                  # Abholen des Hintergrund-Ergebnisses
MAX_PREVIEW_LINES = 200_000   # darüber wird nicht mehr gezeichnet (nur der G-Code zählt)
BACKGROUND = True             # Planer im Hintergrund (False: synchron, z. B. für Skripte)


def _shift_request(doc):
    """``None`` (ohne Versatz), fertige Linien (dict) oder ein ``FillPreviewJob``."""
    try:
        from lumacut_job.scan_offset import preview_fill_request
    except Exception:  # pragma: no cover - lumacut_job ist Teil der App
        return None
    try:
        return preview_fill_request(doc)
    except ValueError:              # z. B. zu viele Linien: dann die reine Geometrie
        return None


def _run_job(job, should_stop=None):
    """Ergebnis eines ``FillPreviewJob``; ``None`` bei Fehler (reine Geometrie)."""
    try:
        return job.run(should_stop)
    except ValueError:
        return None


class _Worker:
    """Ein Planerlauf in einem Daemon-Thread – hält keine Qt-Objekte."""

    def __init__(self, job, generation: int) -> None:
        self.generation = generation
        self.stop = threading.Event()
        self.result = None
        self.cancelled = False
        self.error: BaseException | None = None
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(job,), daemon=True,
                                       name="lumacut-fill-preview")
        self.thread.start()

    def _run(self, job) -> None:
        from lumacut_job.planner import PlanCancelled
        try:
            self.result = _run_job(job, self.stop.is_set)
        except PlanCancelled:
            self.cancelled = True
        except Exception as exc:     # nie den Thread mit Ausnahme beenden
            self.error = exc
        finally:
            self.done.set()


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
        self.scan_offset_pending = False   # Planer läuft noch, gezeichnet ist die reine Geometrie
        self.background_runs = 0           # gestartete Hintergrund-Läufe (Diagnose/Tests)
        self._generation = 0
        self._worker: _Worker | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self.rebuild)
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._collect)
        self._installed = False
        editor.document.add_listener(self.schedule)
        self.rebuild()

    def schedule(self) -> None:
        # Ein laufender Planer rechnet für einen alten Stand: sofort abbrechen
        # (beim Ziehen wird so keine Rechenzeit verschwendet) und sein Ergebnis
        # nicht mehr zeichnen.
        if self._worker is not None:
            self._generation += 1
            self._cancel()
        self._timer.start()

    def busy(self) -> bool:
        """Läuft gerade ein Planer für die Vorschau?"""
        return self._worker is not None

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.stop.set()       # der Thread endet beim nächsten Prüfpunkt
            self._worker = None
        self._poll.stop()
        self.scan_offset_pending = False

    def rebuild(self) -> None:
        self._timer.stop()
        self._generation += 1
        self._cancel()
        doc = self.editor.document
        req = _shift_request(doc)
        if req is None or isinstance(req, dict):
            self._draw(doc, req)
        elif not BACKGROUND:
            self._draw(doc, _run_job(req))
        else:
            # Erst die reine Geometrie zeichnen, dann den Thread starten – sonst
            # teilen sich beide den GIL und der GUI-Thread wartet länger.
            self._draw(doc, None)
            self._worker = _Worker(req, self._generation)
            self.background_runs += 1
            self.scan_offset_pending = True
            self._poll.start()

    def wait(self, timeout: float = 30.0) -> bool:
        """Auf einen laufenden Hintergrund-Lauf warten und ihn übernehmen
        (Tests, Export-Hooks). ``True``, wenn danach nichts mehr läuft."""
        w = self._worker
        if w is None:
            return True
        if not w.done.wait(timeout):
            return False
        self._collect()
        return self._worker is None

    def _collect(self) -> None:
        w = self._worker
        if w is None:
            self._poll.stop()
            return
        if not w.done.is_set():
            return
        self._worker = None
        self._poll.stop()
        self.scan_offset_pending = False
        if w.generation != self._generation or w.cancelled:
            return                        # veraltet: eine neuere Planung folgt
        # Fehler/zu viele Linien: die reine Geometrie ist schon gezeichnet.
        if w.error is None and w.result is not None:
            self._draw(self.editor.document, w.result)

    def _draw(self, doc, shifted) -> None:
        out: list[tuple[QColor, list[QLineF]]] = []
        total = 0
        self.truncated = False
        self.scan_offset_applied = shifted is not None
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
