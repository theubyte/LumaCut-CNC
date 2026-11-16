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
  Bewegungen; die Spitze ist markiert, dazu die Zeit bis dorthin)
* wie LightBurns Vorschau: „Abspielen“ lässt die Bahn in Sendereihenfolge
  ablaufen (Tempo als Vielfaches der geschätzten Echtzeit, Pause / Weiter,
  Ziehen am Regler hält an), „Leerfahrten“ blendet die grauen Leerfahrten aus
  („Show traversal moves“) und „Leistung“ schattiert jeden Schnitt nach seinem
  ``S``-Wert („Shade according to power“: schwach = blass, voll = kräftig).
  Alles nur Ansicht – Dokument und G-Code bleiben unverändert.

Neu gerechnet wird gebündelt nach kurzer Ruhe (``DEBOUNCE_MS``) und nur,
solange die Vorschau eingeschaltet ist.
"""

from __future__ import annotations

import logging
import math
from typing import Callable

from PySide6.QtCore import QLineF, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSlider, QToolButton, QWidget

from . import theme
from .gcode import PWM_MAX, _comment
from .toolpath import CUT, Move, Toolpath, count_until, parse_gcode
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
# Abspielen: Takt und Tempo als Vielfaches der geschätzten Echtzeit.
PLAY_TICK_MS = 40
PLAY_SPEEDS = (1, 10, 50, 200, 1000)
DEFAULT_PLAY_SPEED = 50
# Leistungs-Schattierung: Deckkraft von SHADE_MIN_ALPHA (kaum Leistung) bis 1 (S = PWM_MAX)
# in SHADE_LEVELS Stufen (wenige Stifte auch bei Bild-Gravuren mit vielen S-Werten).
SHADE_LEVELS = 16
SHADE_MIN_ALPHA = 0.15


def shade_level(power: float) -> int:
    """Stufe 1..SHADE_LEVELS für einen ``S``-Wert (0..PWM_MAX); jeder Schnitt bleibt sichtbar."""
    frac = max(0.0, min(1.0, float(power) / PWM_MAX))
    return max(1, min(SHADE_LEVELS, math.ceil(frac * SHADE_LEVELS - 1e-9)))


def shade_alpha(power: float) -> float:
    """Deckkraft eines Schnitts mit ``S`` = ``power`` bei „Leistung“ (Schattierung)."""
    return SHADE_MIN_ALPHA + (1.0 - SHADE_MIN_ALPHA) * shade_level(power) / SHADE_LEVELS

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
        # Ansicht wie LightBurns Vorschau (nur Darstellung, nicht gespeichert):
        self.show_rapids = True            # „Leerfahrten“ (Show traversal moves)
        self.shade_power = False           # „Leistung“ (Shade according to power)
        self.play_speed = DEFAULT_PLAY_SPEED
        self.playing = False
        self._play_t = 0.0                 # abgespielte Auftragszeit in s
        self._cum: list[float] = []        # Zeit am Ende jeder Bewegung (s)
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(PLAY_TICK_MS)
        self._play_timer.timeout.connect(self._tick)
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
            self._stop_play()
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
        """Erste ``n`` Bewegungen zeigen (``None`` = alle). Hält ein Abspielen an
        (Ziehen am Regler, wie in LightBurn)."""
        self._stop_play()
        self._set_limit(n)
        self._update_view()

    def _set_limit(self, n: int | None) -> None:
        total = len(self.toolpath.moves)
        self.limit = None if n is None or n >= total else max(0, int(n))

    def set_show_rapids(self, on: bool) -> None:
        """Leerfahrten zeigen (Standard) oder ausblenden – Längen / Zeit bleiben."""
        self.show_rapids = bool(on)
        self._update_view()

    def set_shade_power(self, on: bool) -> None:
        """Schnitte nach ihrer Leistung (``S``) schattieren."""
        self.shade_power = bool(on)
        self._update_view()

    # --- Abspielen -------------------------------------------------------
    def set_play_speed(self, factor: float) -> None:
        """Tempo als Vielfaches der geschätzten Echtzeit (z. B. 50 = 50× so schnell)."""
        self.play_speed = max(0.1, float(factor))
        self.changed.emit()

    def time_until(self, n: int) -> float:
        """Geschätzte Zeit (s) bis zum Ende der ersten ``n`` Bewegungen."""
        if n <= 0 or not self._cum:
            return 0.0
        return self._cum[min(n, len(self._cum)) - 1]

    @property
    def total_time_s(self) -> float:
        """Zeit der ganzen Bahn (die G-Code-Zeilen der Schätzung, ohne Anfahrt / Parken)."""
        return self._cum[-1] if self._cum else 0.0

    def play(self) -> None:
        """Abspielen ab der Reglerstellung; steht der Regler am Ende, von vorn."""
        total = len(self.toolpath.moves)
        if not total:
            return
        if self.limit is None or self.limit >= total:
            self._play_t = 0.0
            self._set_limit(0)
        else:
            self._play_t = self.time_until(self.limit)
        self.playing = True
        self._play_timer.start()
        self._update_view()

    def pause(self) -> None:
        if self.playing:
            self._stop_play()
            self._update_view()

    def toggle_play(self) -> None:
        self.pause() if self.playing else self.play()

    def _stop_play(self) -> None:
        self._play_timer.stop()
        self.playing = False

    def advance(self, seconds: float) -> None:
        """Abspielen um ``seconds`` Wanduhrzeit weiterführen (× Tempo); am Ende
        steht die ganze Bahn da und das Abspielen hält an."""
        if not self.playing:
            return
        self._play_t += max(0.0, seconds) * self.play_speed
        total = len(self.toolpath.moves)
        n = count_until(self._cum, self._play_t)
        if n >= total:
            self._stop_play()
            self._set_limit(None)
        else:
            self._set_limit(max(n, self.limit or 0))
        self._update_view()

    def _tick(self) -> None:
        self.advance(PLAY_TICK_MS / 1000.0)

    # --- Rechnen ---------------------------------------------------------
    def rebuild(self) -> None:
        self._timer.stop()
        self._stop_play()
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
        self._cum = self._cumulative()
        self._colors = self._source_colors()
        if self.source_filter not in {self.key(s) for s in self.toolpath.sources()}:
            self.source_filter = ALL
        self.limit = None
        self._update_view()

    def refresh_estimate(self) -> None:
        """Nur die Zeit neu schätzen (z. B. neue Bewegungsgrenzen vom Pi);
        der G-Code bleibt, wie er ist."""
        if not self.gcode:
            return
        self.estimate = _estimate(self.gcode)
        self._cum = self._cumulative()
        self._update_view()

    def _cumulative(self) -> list[float]:
        """Zeitachse fürs Abspielen: Anteile wie Länge / Vorschub, Summe wie die
        G-Code-Zeit der Schätzung (mit Beschleunigung, ohne Anfahrt / Parken)."""
        total = getattr(self.estimate, "program_time_s", None)
        motion = getattr(self.estimate, "motion", None)
        speed = getattr(motion, "speed", None)
        try:
            return self.toolpath.cumulative_times(total, max_speed=speed)
        except Exception:                      # Vorschau darf den Editor nie stören
            _log.exception("Pfadvorschau: Zeitachse nicht berechenbar")
            return []

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
            if self._cum:
                text += f" · nach ca. {format_time(self.time_until(self.limit))}"
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
        rapid, cuts = self.paint_lines(moves)
        if rapid:
            p.setPen(QPen(QColor(RAPID_COLOR), 0, Qt.DashLine))
            p.drawLines(rapid)
        for (src, level), lines in cuts.items():
            color = QColor(self.color(src))
            if level:
                color.setAlphaF(SHADE_MIN_ALPHA + (1.0 - SHADE_MIN_ALPHA) * level / SHADE_LEVELS)
            p.setPen(QPen(color, 0))
            p.drawLines(lines)
        self._paint_markers(p)

    def paint_lines(self, moves=None):
        """(Leerfahrt-Linien, {(Quelle, Schattierungsstufe): Schnitt-Linien}) wie gezeichnet;
        Stufe 0 = ohne Schattierung."""
        moves = self.visible_moves() if moves is None else moves
        rapid: list[QLineF] = []
        cuts: dict[tuple[tuple[str, str], int], list[QLineF]] = {}
        shade = self.shade_power
        for _, m in moves:
            line = QLineF(m.x0, m.y0, m.x1, m.y1)
            if m.kind == CUT:
                level = shade_level(m.power) if shade else 0
                cuts.setdefault((m.source, level), []).append(line)
            elif self.show_rapids and m.source[0] != "image":   # Raster-Zeilenwechsel nicht als Gewirr
                rapid.append(line)
        return rapid, cuts

    def cut_pens(self) -> dict[tuple[str, str], list[float]]:
        """Deckkräfte der Schnitt-Stifte je Quelle, wie :meth:`paint` sie wählt (Tests / Hilfe)."""
        out: dict[tuple[str, str], set[float]] = {}
        for _, m in self.visible_moves():
            if m.kind == CUT:
                a = shade_alpha(m.power) if self.shade_power else self.color(m.source).alphaF()
                out.setdefault(m.source, set()).add(round(a, 4))
        return {k: sorted(v) for k, v in out.items()}

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
        # Wie LightBurns Vorschau: Abspielen mit Tempo, Leerfahrten, Leistungs-Schattierung.
        self.play = QToolButton()
        self.play.setObjectName("PathPlay")
        self.play.setCheckable(True)
        self.play.clicked.connect(self._play_clicked)
        self.speed = QComboBox()
        self.speed.setObjectName("PathSpeed")
        self.speed.setToolTip("Abspieltempo als Vielfaches der geschätzten Echtzeit")
        for f in PLAY_SPEEDS:
            self.speed.addItem(f"{f}×", f)
        self.speed.setCurrentIndex(PLAY_SPEEDS.index(DEFAULT_PLAY_SPEED))
        self.speed.currentIndexChanged.connect(self._speed_changed)
        self.rapids = QToolButton()
        self.rapids.setObjectName("PathRapids")
        self.rapids.setText("Leerfahrten")
        self.rapids.setCheckable(True)
        self.rapids.setChecked(True)
        self.rapids.setToolTip("Leerfahrten (grau gestrichelt) zeigen oder ausblenden – "
                               "wie LightBurns „Show traversal moves“; Längen und Zeit bleiben")
        self.rapids.toggled.connect(preview.set_show_rapids)
        self.shade = QToolButton()
        self.shade.setObjectName("PathShade")
        self.shade.setText("Leistung")
        self.shade.setCheckable(True)
        self.shade.setToolTip("Schnitte nach ihrer Leistung schattieren: schwach = blass, "
                              "100 % = kräftig – wie LightBurns „Shade according to power“ "
                              "(zeigt Rampe, Steg-Pulse, Kontur-Leistung, Bild-Graustufen)")
        self.shade.toggled.connect(preview.set_shade_power)
        lay.addWidget(title)
        lay.addWidget(self.readout, 1)
        lay.addWidget(self.filter)
        lay.addWidget(self.rapids)
        lay.addWidget(self.shade)
        lay.addWidget(self.play)
        lay.addWidget(self.speed)
        lay.addWidget(self.slider, 1)
        preview.changed.connect(self.sync)
        self.setVisible(preview.visible)
        self.sync()

    def sync(self) -> None:
        pv = self.preview
        self.setVisible(pv.visible)
        self.readout.setText(pv.readout())
        note = getattr(pv.estimate, "motion_note", None)
        scope = getattr(pv.estimate, "scope_note", None)
        self.readout.setToolTip(
            (note() + " – Zeit " + (scope() if callable(scope) else "ohne Referenzfahrt/Fokus/Parken"))
            if callable(note) and note() else "")
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
        self.play.blockSignals(True)
        self.play.setChecked(pv.playing)
        self.play.blockSignals(False)
        self.play.setEnabled(total > 0)
        self.play.setText("❚❚ Pause" if pv.playing else "▶ Abspielen")
        self.play.setToolTip("Anhalten (Regler bleibt stehen)" if pv.playing else
                             "Laserbahn in Sendereihenfolge ablaufen lassen (vom Regler aus; "
                             "am Ende von vorn) – Ziehen am Regler hält an")
        for button, on in ((self.rapids, pv.show_rapids), (self.shade, pv.shade_power)):
            if button.isChecked() != on:
                button.blockSignals(True)
                button.setChecked(on)
                button.blockSignals(False)
        idx = self.speed.findData(pv.play_speed)
        if idx >= 0 and idx != self.speed.currentIndex():
            self.speed.blockSignals(True)
            self.speed.setCurrentIndex(idx)
            self.speed.blockSignals(False)

    def _filter_changed(self, _i: int) -> None:
        self.preview.set_filter(self.filter.currentData() or ALL)

    def _scrub(self, value: int) -> None:
        self.preview.set_limit(value)

    def _play_clicked(self, _checked: bool = False) -> None:
        self.preview.toggle_play()

    def _speed_changed(self, _i: int) -> None:
        f = self.speed.currentData()
        if f:
            self.preview.set_play_speed(f)
