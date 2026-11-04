"""Canvas hint for variable text: the value each object gets in the next job.

The canvas draws the *template* of a variable text (``Shape.text``, e.g.
„Nr. {n:3}“); LightBurn shows the evaluated text instead. This overlay puts
a small label under every variable text object with the value it will get
when the job is sent now – „→ Nr. 007“ – using the same evaluation as the
job (:func:`lumacut_job.vartext.preview_values`: series, reading order,
copies in a row, CSV row, „Nur Auswahl“ via ``source``). A template that
cannot be evaluated (missing CSV, unknown column …) gets a red „⚠ …“ label,
so the problem is visible before sending.

Runs on the canvas overlay hook (``editor.add_overlay``, no change to the
canvas code, never in export or G-code); recomputed shortly after document /
selection changes and every 30 s while a template shows date or time. The
labels scale with the zoom (heights in mm, like the objects).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QTransform

from . import vartext as vt

OVERLAY_KEY = "vartext_values"
DEBOUNCE_MS = 150
CLOCK_MS = 30_000
SETTINGS_KEY = "vartext/show_values"
MAX_CHARS = 48
LABEL_MIN_MM, LABEL_MAX_MM = 1.6, 5.0   # text height of a label
GAP_MM = 0.6
OK_COLOR = QColor("#9be37a")
ERROR_COLOR = QColor("#ff7b72")
BACKGROUND = QColor(24, 28, 34, 215)


def label_text(value: vt.PreviewValue) -> str:
    """One-line label: „→ value“ or „⚠ error“, newlines as ⏎, shortened."""
    if value.error:
        text = "⚠ " + value.error
    elif not value.text.strip():
        text = "→ (leer – wird nicht gelasert)"
    else:
        text = "→ " + value.text.replace("\r\n", "\n").replace("\n", " ⏎ ")
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS - 1] + "…"


def _text_path(text: str, height_mm: float) -> QPainterPath:
    font = QFont()
    font.setPointSizeF(48.0)
    raw = QPainterPath()
    raw.addText(QPointF(0, 0), font, text)
    box = raw.boundingRect()
    if box.height() <= 0:
        return QPainterPath()
    f = height_mm / box.height()
    return QTransform().scale(f, f).translate(-box.left(), -box.top()).map(raw)


class Label:
    """Pre-built label: background box and text outline in work-area mm."""

    def __init__(self, shape_id: str, value: vt.PreviewValue, anchor: QRectF,
                 work_h: float) -> None:
        self.shape_id = shape_id
        self.value = value
        self.text = label_text(value)
        h = max(LABEL_MIN_MM, min(LABEL_MAX_MM, anchor.height() * 0.35))
        path = _text_path(self.text, h)
        pad = h * 0.3
        w = path.boundingRect().width() + 2 * pad
        y = anchor.bottom() + GAP_MM
        if y + h + 2 * pad > work_h and anchor.top() - GAP_MM - h - 2 * pad >= 0:
            y = anchor.top() - GAP_MM - h - 2 * pad       # no room below: above the object
        self.box = QRectF(anchor.left(), y, w, h + 2 * pad)
        self.path = path.translated(anchor.left() + pad, y + pad)
        self.color = ERROR_COLOR if value.error else OK_COLOR


class VarTextValues(QObject):
    """Overlay with ``visible``/``opacity``/``paint`` for ``editor.add_overlay``.

    ``source``: callable returning the document the job is built from
    (default: the editor document; the Studio passes its „Nur Auswahl“
    aware job source)."""

    def __init__(self, editor, source=None, enabled: bool = True) -> None:
        super().__init__(editor)
        self.editor = editor
        self.source = source or (lambda: editor.document)
        self.visible = True
        self.opacity = 1.0
        self.enabled = bool(enabled)
        self.labels: list[Label] = []
        self.values: dict[str, vt.PreviewValue] = {}
        self._installed = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self.rebuild)
        self._clock = QTimer(self)
        self._clock.setInterval(CLOCK_MS)
        self._clock.timeout.connect(self.rebuild)
        for name in ("documentChanged", "selectionChanged"):
            signal = getattr(editor, name, None)
            if signal is not None:
                signal.connect(self.schedule)
        self.rebuild()

    def schedule(self, *_args) -> None:
        self._timer.start()

    def set_enabled(self, on: bool) -> None:
        self.enabled = bool(on)
        self.rebuild()

    def rebuild(self) -> None:
        from lumacut_canvas.workarea import WORK_HEIGHT_MM
        self._timer.stop()
        labels: list[Label] = []
        values: dict[str, vt.PreviewValue] = {}
        clock = False
        if self.enabled:
            try:
                doc = self.source()
            except ValueError:                 # „Nur Auswahl“ without a selection
                doc = None
            if doc is not None:
                values = vt.preview_values(doc)
                for s in doc.shapes:
                    v = values.get(s.id)
                    if v is None:
                        continue
                    b = s.bounds()
                    labels.append(Label(s.id, v, QRectF(b.x, b.y, b.w, b.h), WORK_HEIGHT_MM))
                    clock = clock or vt.uses_clock(s.text)
        self.values = values
        self.labels = labels
        if clock and not self._clock.isActive():
            self._clock.start()
        elif not clock:
            self._clock.stop()
        if labels and not self._installed:
            self.editor.add_overlay(OVERLAY_KEY, self, z=60)
            self._installed = True
        elif not labels and self._installed:
            self.editor.remove_overlay(OVERLAY_KEY)
            self._installed = False
        elif labels:
            self.editor.refresh_overlays()

    def label_for(self, shape_id: str) -> Label | None:
        return next((l for l in self.labels if l.shape_id == shape_id), None)

    def paint(self, painter: QPainter, work: QRectF) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        for label in self.labels:
            r = label.box.height() * 0.25
            painter.setBrush(BACKGROUND)
            painter.drawRoundedRect(label.box, r, r)
            painter.setBrush(label.color)
            painter.drawPath(label.path)
        painter.restore()


def load_enabled(settings) -> bool:
    if settings is None:
        return True
    v = settings.value(SETTINGS_KEY, True)
    return v not in (False, "false", "0", 0)


def save_enabled(settings, on: bool) -> None:
    if settings is not None:
        settings.setValue(SETTINGS_KEY, bool(on))


__all__ = ["Label", "OVERLAY_KEY", "VarTextValues", "label_text", "load_enabled",
           "save_enabled"]
