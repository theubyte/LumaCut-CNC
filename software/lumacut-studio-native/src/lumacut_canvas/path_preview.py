"""Pfadvorschau: zeigt die Laserbahn genau so, wie sie gesendet wird.

Die Vorschau erzeugt den G-Code mit demselben Generator wie der Sendepfad
(``lumacut_job.planner.optimized_document_gcode`` – Planer-Reihenfolge,
Füllung/Schraffur, Bild-Gravuren; ohne ``lumacut_job`` der reine
Canvas-Generator ``gcode.document_to_gcode``) und liest ihn mit
:func:`toolpath.parse_gcode` zurück. Sie ändert daher weder Dokument noch
G-Code – sie *liest* nur, was ohnehin rausgehen würde.

Darstellung (über den Objekten, Vordergrund-Hook der View):

* Schnitte in der Ebenenfarbe, Leerfahrten grau gestrichelt
* Start jedes Laufs als Punkt mit Reihenfolgenummer, Pfeil für die Richtung
* Leiste mit Schnitt-/Leerfahrtlänge und Zeit (``lumacut_job.estimate``),
  Ebenenfilter und Schieberegler zum Abspielen (zeigt die ersten *n*
  Bewegungen; die Spitze ist markiert)

Neu gerechnet wird gebündelt nach kurzer Ruhe (``DEBOUNCE_MS``) und nur,
solange die Vorschau eingeschaltet ist.
"""

from __future__ import annotations

import logging
import math
from typing import Callable

from PySide6.QtCore import QLineF, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSlider, QWidget

from . import theme
from .gcode import _comment
from .toolpath import CUT, Move, Toolpath, parse_gcode
from .workarea import from_machine

_log = logging.getLogger(__name__)

FOREGROUND_KEY = "path_preview"
DEBOUNCE_MS = 250
MAX_LABELS = 400          # höchstens so viele Nummern (große Raster-Jobs)
LABEL_CELL_PX = 22        # Nummern nicht dichter als dieses Raster
ARROW_MIN_PX = 16         # Pfeil nur auf Segmenten, die so lang dargestellt werden
RAPID_COLOR = "#8a94a3"
IMAGE_COLOR = "#e0b354"   # Bild-Gravur ohne bekannte Ebenenfarbe
ALL = ""                  # Filter: alle Quellen

Generator = Callable[[object], str]


def default_generator() -> Generator:
    """Derselbe Generator wie ``_send_canvas_job`` (mit Planer), sonst der Canvas-Export."""
    try:
        from lumacut_job.planner import optimized_document_gcode
        return optimized_document_gcode
    except Exception:  # pragma: no cover - lumacut_job ist Teil der App
        from .gcode import document_to_gcode
        return document_to_gcode


def _estimate(gcode: str):
    try:
        from lumacut_job.estimate import estimate_gcode
    except Exception:  # pragma: no cover
        return None
    try:
        return estimate_gcode(gcode)
    except Exception:
        _log.exception("Zeitschätzung fehlgeschlagen")
        return None


def format_mm(mm: float) -> str:
    return f"{mm / 1000:.2f} m" if mm >= 1000 else f"{mm:.0f} mm"


def format_time(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h} h {m:02d} min" if h else (f"{m} min {sec:02d} s" if m else f"{sec} s")


class PathPreview(QObject):
    """Vordergrund-Objekt (``visible``/``opacity``/``paint``) plus Rechenlogik."""

    changed = Signal()

    def __init__(self, editor, generator: Generator | None = None) -> None:
        super().__init__(editor)
        self.editor = editor
        self.visible = False
        self.opacity = 0.95
        self._generator = generator
        self.gcode = ""
        self.error = ""
        self.toolpath = Toolpath()
        self.estimate = None
        self.source_filter = ALL
        self.limit: int | None = None      # Schieberegler: erste n Bewegungen
        self._colors: dict[tuple[str, str], QColor] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self.rebuild)
        self._dirty = True
        # Quelle des Vorschau-Dokuments: Standard ganzes Design; main.py hängt
        # JobTools.job_document ein, damit „Nur Auswahl“ hier genauso wirkt wie
        # beim Senden (REVIEW_GAP_ANALYSIS §9, Vorschau = Auftrag).
        self._document_provider: Callable[[], object] | None = None
        self._selection_only: Callable[[], bool] | None = None
        editor.document.add_listener(self.schedule)
        sig = getattr(editor, "selectionChanged", None)
        if sig is not None:
            sig.connect(self._selection_changed)

    # --- Steuerung -------------------------------------------------------
    @property
    def generator(self) -> Generator:
        if self._generator is None:
            self._generator = default_generator()
        return self._generator

    def set_generator(self, gen: Generator | None) -> None:
        self._generator = gen
        self._dirty = True
        if self.visible:
            self.rebuild()

    def set_document_source(self, provider: Callable[[], object] | None,
                            selection_only: Callable[[], bool] | None = None) -> None:
        """Dokument-Quelle setzen (``None`` = ganzes Design).

        ``selection_only`` meldet, ob die Quelle von der Auswahl abhängt; dann
        wird bei jeder Auswahländerung neu gerechnet.
        """
        self._document_provider = provider
        self._selection_only = selection_only
        self.schedule()

    @property
    def selection_only(self) -> bool:
        try:
            return bool(self._selection_only and self._selection_only())
        except Exception:
            return False

    def _selection_changed(self, *_args) -> None:
        if self.selection_only:
            self.schedule()

    def set_visible(self, on: bool) -> None:
        on = bool(on)
        if on == self.visible:
            return
        self.visible = on
        view = self.editor.view
        if on:
            view.add_foreground(FOREGROUND_KEY, self)
            if self._dirty:
                self.rebuild()
        else:
            self._timer.stop()
            view.remove_foreground(FOREGROUND_KEY)
        self.changed.emit()

    def schedule(self) -> None:
        self._dirty = True
        if self.visible:
            self._timer.start()

    def pending(self) -> bool:
        return self._timer.isActive()

    def set_filter(self, source: str) -> None:
        self.source_filter = source or ALL
        self._update_view()

    def set_limit(self, n: int | None) -> None:
        total = len(self.toolpath.moves)
        self.limit = None if n is None or n >= total else max(0, int(n))
        self._update_view()

    # --- Rechnen ---------------------------------------------------------
    def rebuild(self) -> None:
        self._timer.stop()
        self._dirty = False
        self.error = ""
        try:
            doc = (self._document_provider() if self._document_provider is not None
                   else self.editor.document)
            self.gcode = self.generator(doc)
        except ValueError as exc:            # z. B. „Keine sichtbaren Objekte“
            self.gcode, self.error = "", str(exc)
        except Exception as exc:             # Vorschau darf den Editor nie stören
            _log.exception("Pfadvorschau: G-Code konnte nicht erzeugt werden")
            self.gcode, self.error = "", f"Vorschau nicht möglich: {exc}"
        self.toolpath = self._to_work(parse_gcode(self.gcode)) if self.gcode else Toolpath()
        self.estimate = _estimate(self.gcode) if self.gcode else None
        self._colors = self._source_colors()
        if self.source_filter not in {self.key(s) for s in self.toolpath.sources()}:
            self.source_filter = ALL
        self.limit = None
        self._update_view()

    @staticmethod
    def _to_work(tp: Toolpath) -> Toolpath:
        out = Toolpath(runs=list(tp.runs), cut_length_mm=tp.cut_length_mm,
                       rapid_length_mm=tp.rapid_length_mm)
        for m in tp.moves:
            x0, y0 = from_machine(m.x0, m.y0)
            x1, y1 = from_machine(m.x1, m.y1)
            out.moves.append(Move(m.kind, x0, y0, x1, y1, m.source, m.power, m.feed))
        return out

    @staticmethod
    def key(source: tuple[str, str]) -> str:
        return f"{source[0]}:{source[1]}"

    def _source_colors(self) -> dict[tuple[str, str], QColor]:
        doc = self.editor.document
        by_name = {_comment(l.name): QColor(l.color) for l in doc.layers}
        out: dict[tuple[str, str], QColor] = {}
        for src in self.toolpath.sources():
            kind, ident = src
            color = None
            if kind == "layer":
                color = by_name.get(ident)
            elif kind == "image":
                for s in doc.shapes:
                    if s.id == ident:
                        try:
                            color = QColor(doc.layer(s.layer_id).color)
                        except KeyError:
                            pass
                        break
                color = color or QColor(IMAGE_COLOR)
            out[src] = color or QColor(theme.ACCENT)
        return out

    def source_label(self, source: tuple[str, str]) -> str:
        kind, ident = source
        if kind == "layer":
            return f"Ebene {ident}"
        if kind == "image":
            return f"Bild {ident[:8]}"
        return "Sonstiges"

    def color(self, source: tuple[str, str]) -> QColor:
        return self._colors.get(source, QColor(theme.ACCENT))

    def shown_count(self) -> int:
        n = len(self.toolpath.moves)
        return n if self.limit is None else min(self.limit, n)

    def _passes(self, m: Move) -> bool:
        return self.source_filter == ALL or self.key(m.source) == self.source_filter

    def visible_moves(self) -> list[tuple[int, Move]]:
        return [(i, m) for i, m in enumerate(self.toolpath.moves[:self.shown_count()])
                if self._passes(m)]

    def visible_runs(self) -> list[tuple[int, int, int]]:
        """(Nummer, Start, Ende) der sichtbaren Läufe; Nummer = Gesamtreihenfolge."""
        n = self.shown_count()
        out = []
        for k, (s, e) in enumerate(self.toolpath.runs):
            if s >= n:
                break
            if self._passes(self.toolpath.moves[s]):
                out.append((k + 1, s, min(e, n)))
        return out

    def readout(self) -> str:
        if self.error:
            return self.error
        tp = self.toolpath
        if not tp.moves:
            return "Keine Laserbahn"
        cut, rapid = tp.cut_length_mm, tp.rapid_length_mm
        text = f"Schneiden {format_mm(cut)} · Leerfahrt {format_mm(rapid)}"
        if self.estimate is not None:
            text += f" · ca. {format_time(self.estimate.total_time_s)}"
        text += f" · {len(tp.runs)} Läufe"
        if self.selection_only:
            text = "Nur Auswahl · " + text
        if self.limit is not None:
            c, r = tp.lengths_until(self.limit)
            text += f"  |  bis Schritt {self.limit}: {format_mm(c)} / {format_mm(r)}"
        return text

    def _update_view(self) -> None:
        if self.visible:
            self.editor.view.viewport().update()
        self.changed.emit()

    # --- Zeichnen --------------------------------------------------------
    def paint(self, p: QPainter, work: QRectF) -> None:
        moves = self.visible_moves()
        if not moves:
            return
        p.setRenderHint(QPainter.Antialiasing, True)
        rapid: list[QLineF] = []
        cuts: dict[tuple[str, str], list[QLineF]] = {}
        for _, m in moves:
            line = QLineF(m.x0, m.y0, m.x1, m.y1)
            if m.kind == CUT:
                cuts.setdefault(m.source, []).append(line)
            elif m.source[0] != "image":     # Raster-Zeilenwechsel nicht als Gewirr zeigen
                rapid.append(line)
        pen = QPen(QColor(RAPID_COLOR), 0, Qt.DashLine)
        p.setPen(pen)
        p.drawLines(rapid)
        for src, lines in cuts.items():
            p.setPen(QPen(self.color(src), 0))
            p.drawLines(lines)
        self._paint_markers(p)

    def _paint_markers(self, p: QPainter) -> None:
        t = p.transform()
        tp = self.toolpath
        runs = self.visible_runs()
        p.save()
        p.resetTransform()
        font = QFont(p.font())
        font.setPixelSize(10)
        font.setBold(True)
        p.setFont(font)
        used: set[tuple[int, int]] = set()
        labels = 0
        for num, s, e in runs:
            first = tp.moves[s]
            if first.source[0] == "image":
                continue                      # Rasterzeilen: keine Einzelmarken
            a = t.map(QPointF(first.x0, first.y0))
            color = self.color(first.source)
            # Pfeil auf dem (dargestellt) längsten Segment des Laufs
            best, best_len = None, ARROW_MIN_PX
            for m in tp.moves[s:e]:
                q0, q1 = t.map(QPointF(m.x0, m.y0)), t.map(QPointF(m.x1, m.y1))
                ln = math.hypot(q1.x() - q0.x(), q1.y() - q0.y())
                if ln > best_len:
                    best, best_len = (q0, q1), ln
            if best is not None:
                _arrow(p, best[0], best[1], color)
            p.setPen(QPen(QColor(theme.BG), 1))
            p.setBrush(QBrush(color))
            p.drawEllipse(a, 3.5, 3.5)
            cell = (int(a.x() // LABEL_CELL_PX), int(a.y() // LABEL_CELL_PX))
            if labels < MAX_LABELS and cell not in used:
                used.add(cell)
                labels += 1
                r = QRectF(a.x() + 4, a.y() - 15, 30, 13)
                p.setPen(QPen(QColor(theme.BG), 1))
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):   # Kontur für Lesbarkeit
                    p.drawText(r.translated(dx, dy), Qt.AlignLeft | Qt.AlignVCenter, str(num))
                p.setPen(QPen(QColor(theme.TEXT), 1))
                p.drawText(r, Qt.AlignLeft | Qt.AlignVCenter, str(num))
        if self.limit is not None and self.limit > 0:     # Spitze beim Abspielen
            m = tp.moves[self.limit - 1]
            h = t.map(QPointF(m.x1, m.y1))
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(h, 7, 7)
        p.restore()


def _arrow(p: QPainter, a: QPointF, b: QPointF, color: QColor) -> None:
    mx, my = (a.x() + b.x()) / 2, (a.y() + b.y()) / 2
    ang = math.atan2(b.y() - a.y(), b.x() - a.x())
    size = 6.0
    pts = [QPointF(mx + math.cos(ang) * size, my + math.sin(ang) * size),
           QPointF(mx + math.cos(ang + 2.5) * size, my + math.sin(ang + 2.5) * size),
           QPointF(mx + math.cos(ang - 2.5) * size, my + math.sin(ang - 2.5) * size)]
    p.setPen(QPen(QColor(theme.BG), 1))
    p.setBrush(QBrush(color))
    p.drawPolygon(QPolygonF(pts))


class PathPreviewBar(QWidget):
    """Leiste unter der Eigenschaftenleiste: Werte, Ebenenfilter, Abspielen."""

    def __init__(self, preview: PathPreview, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PathPreviewBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.preview = preview
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(8)
        title = QLabel("Pfadvorschau")
        title.setStyleSheet(f"color: {theme.ACCENT}; font-weight: 600;")
        self.readout = QLabel()
        self.readout.setObjectName("PathReadout")
        self.readout.setStyleSheet(f"color: {theme.TEXT_DIM};")
        self.filter = QComboBox()
        self.filter.setObjectName("PathFilter")
        self.filter.setToolTip("Nur eine Ebene bzw. ein Bild zeigen (Nummern bleiben die Gesamtreihenfolge)")
        self.filter.currentIndexChanged.connect(self._filter_changed)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setObjectName("PathScrub")
        self.slider.setToolTip("Abspielen: zeigt die ersten n Bewegungen in Sendereihenfolge")
        self.slider.setMinimumWidth(120)
        self.slider.valueChanged.connect(self._scrub)
        lay.addWidget(title)
        lay.addWidget(self.readout, 1)
        lay.addWidget(self.filter)
        lay.addWidget(self.slider, 1)
        preview.changed.connect(self.sync)
        self.setVisible(preview.visible)
        self.sync()

    def sync(self) -> None:
        pv = self.preview
        self.setVisible(pv.visible)
        self.readout.setText(pv.readout())
        keys = [ALL] + [pv.key(s) for s in pv.toolpath.sources()]
        current = [self.filter.itemData(i) for i in range(self.filter.count())]
        if keys != current:
            self.filter.blockSignals(True)
            self.filter.clear()
            self.filter.addItem("Alle Ebenen", ALL)
            for s in pv.toolpath.sources():
                self.filter.addItem(pv.source_label(s), pv.key(s))
            self.filter.blockSignals(False)
        idx = self.filter.findData(pv.source_filter)
        if idx >= 0 and idx != self.filter.currentIndex():
            self.filter.blockSignals(True)
            self.filter.setCurrentIndex(idx)
            self.filter.blockSignals(False)
        total = len(pv.toolpath.moves)
        self.slider.blockSignals(True)
        self.slider.setRange(0, total)
        self.slider.setValue(pv.shown_count())
        self.slider.setEnabled(total > 0)
        self.slider.blockSignals(False)

    def _filter_changed(self, _i: int) -> None:
        self.preview.set_filter(self.filter.currentData() or ALL)

    def _scrub(self, value: int) -> None:
        self.preview.set_limit(value)
