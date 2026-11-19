"""Text direkt auf der Arbeitsfläche tippen (LightBurn: Text-Werkzeug klicken und lostippen,
Doppelklick auf einen Text bearbeitet ihn an Ort und Stelle; xTool: Text auf der Leinwand
bearbeiten).

Statt eines modalen Dialogs öffnet sich ein kleines Eingabefeld direkt unter dem Textobjekt
(bzw. an der Klickstelle des Text-Werkzeugs). Jede Eingabe zeigt sich sofort auf der
Arbeitsfläche – der Text wird mit seiner Schrift, Größe, Ausrichtung und seinem Satz neu
gesetzt, die Buchstaben behalten ihre Größe (:func:`text_ui.with_layout`).

Bedienung: Enter = neue Zeile, Strg+Enter oder ein Klick daneben = fertig, Esc = abbrechen
(alter Text bzw. kein neuer Text). Für Finger gibt es „✓“ und „✕“ (44 px im Touch-Modus).
Das Ergebnis ist genau ein Rückgängig-Schritt („Text einfügen“ bzw. „Text ändern“); wurde
nichts geändert oder alles gelöscht, entsteht keiner.

Die Vorschau läuft über den normalen Undo-Stapel (zusammengeführte
:class:`ReplaceShapeCommand`-Schritte); beim Beenden werden diese Zwischenschritte wieder
zurückgenommen und durch den einen sauberen Schritt ersetzt.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QKeyEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPlainTextEdit, QToolButton, QVBoxLayout

from .commands import AddShapesCommand
from .edit_commands import ReplaceShapeCommand
from .model import Geometry, Shape

TOUCH_PX = 44          # Mindestgröße für Finger (wie die übrigen Touch-Bedienelemente)
MIN_WIDTH_PX = 220
MAX_LINES_SHOWN = 8
GAP_PX = 6
PLACEHOLDER = "Text tippen – Enter: neue Zeile, Strg+Enter: fertig, Esc: abbrechen"


def _norm(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u2029", "\n")


class _Edit(QPlainTextEdit):
    """Eingabefeld: Strg+Enter beendet, Esc bricht ab, Fokusverlust beendet."""

    def __init__(self, owner: "InlineTextEditor", parent) -> None:
        super().__init__(parent)
        self.owner = owner
        self.setContextMenuPolicy(Qt.NoContextMenu)  # ein Popup würde das Feld schließen
        self.setTabChangesFocus(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.owner.cancel()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
            self.owner.commit()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        if event.reason() != Qt.ActiveWindowFocusReason:  # Fensterwechsel lässt das Feld offen
            self.owner.commit()


class InlineTextEditor(QObject):
    """Ein Eingabefeld auf der Arbeitsfläche für genau ein Textobjekt."""

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.ed = editor
        self.frame: QFrame | None = None
        self.edit: _Edit | None = None
        self.shape_id: str | None = None   # bearbeitetes (oder neu entstehendes) Objekt
        self.base: Shape | None = None     # Vorlage: altes Objekt bzw. neue Vorlage
        self.is_new = False
        self.original = ""
        self._start_index = 0              # Undo-Index beim Öffnen
        self._own_index: int | None = None  # Undo-Index nach unserer letzten Vorschau
        self._dirty = False                # Vorschau liegt unter einem fremden Schritt
        self._closing = False

    # --- Zustand --------------------------------------------------------------
    @property
    def active(self) -> bool:
        return self.frame is not None

    @property
    def doc(self):
        return self.ed.document

    def text(self) -> str:
        return _norm(self.edit.toPlainText()) if self.edit is not None else ""

    # --- Öffnen ---------------------------------------------------------------
    def edit_shape(self, shape_id: str) -> bool:
        """Vorhandenes Textobjekt an Ort und Stelle bearbeiten."""
        self.commit()
        if not self.doc.has_shape(shape_id) or self.doc.shape(shape_id).kind != "text":
            return False
        s = self.doc.shape(shape_id)
        self.shape_id, self.base, self.is_new, self.original = shape_id, s.copy(), False, s.text
        self._open(s.text, select_all=True)
        return True

    def new_text(self, pos: QPointF, height_mm: float) -> bool:
        """Neues Textobjekt an ``pos`` (obere linke Ecke) – entsteht mit dem ersten Zeichen."""
        self.commit()
        ed = self.ed
        family = ed.text_font_family
        bold = getattr(ed, "text_font_bold", False)
        italic = getattr(ed, "text_font_italic", False)
        from .shape_paths import text_aspect
        w = height_mm * text_aspect("A", family, bold, italic)
        self.base = Shape("text", Geometry(pos.x(), pos.y(), w, height_mm), self.doc.active_layer_id,  # type: ignore[arg-type]
                          text="A", font_family=family, font_bold=bold, font_italic=italic)
        self.shape_id, self.is_new, self.original = self.base.id, True, ""
        self._open("", select_all=False)
        return True

    def _open(self, text: str, select_all: bool) -> None:
        view = self.ed.view
        touch = bool(getattr(self.ed, "touch_mode", False))
        self.frame = QFrame(view.viewport())
        self.frame.setObjectName("inlineTextEditor")
        self.frame.setFrameShape(QFrame.StyledPanel)
        self.frame.setAutoFillBackground(True)
        lay = QHBoxLayout(self.frame)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(3)
        self.edit = _Edit(self, self.frame)
        self.edit.setPlaceholderText(PLACEHOLDER)
        font = QFont(self.base.font_family or self.edit.font().family())
        font.setBold(bool(self.base.font_bold))
        font.setItalic(bool(self.base.font_italic))
        font.setPixelSize(20 if touch else 15)
        self.edit.setFont(font)
        self.edit.setPlainText(text)
        if select_all:
            self.edit.selectAll()
        lay.addWidget(self.edit, 1)
        buttons = QVBoxLayout()
        buttons.setSpacing(3)
        self.ok_button = self._button("✓", "Fertig (Strg+Enter)", self.commit, touch)
        self.cancel_button = self._button("✕", "Abbrechen (Esc)", self.cancel, touch)
        buttons.addWidget(self.ok_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        lay.addLayout(buttons)
        self._start_index = self.ed.undo_stack.index()
        self._own_index = None
        self._dirty = False
        self.edit.textChanged.connect(self._preview)
        self._place()
        self.frame.show()
        self.frame.raise_()
        self.edit.setFocus(Qt.OtherFocusReason)
        view.viewChanged.connect(self._place)

    def _button(self, label: str, tip: str, slot, touch: bool) -> QToolButton:
        b = QToolButton(self.frame)
        b.setText(label)
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.NoFocus)  # Klick darauf soll das Feld nicht „verlassen“
        side = TOUCH_PX if touch else 24
        b.setFixedSize(side, side)
        b.clicked.connect(slot)
        return b

    # --- Lage auf dem Bildschirm ----------------------------------------------
    def _anchor_rect(self) -> QRectF:
        if self.doc.has_shape(self.shape_id):
            b = self.doc.shape(self.shape_id).bounds()
            return QRectF(b.x, b.y, b.w, b.h)
        g = self.base.geom                             # neuer Text vor dem ersten Zeichen
        return QRectF(g.x, g.y, 0.0, abs(g.h))

    def _place(self, *_) -> None:
        if self.frame is None:
            return
        view = self.ed.view
        vp = view.viewport()
        r = view.mapFromScene(self._anchor_rect()).boundingRect()
        touch = bool(getattr(self.ed, "touch_mode", False))
        fm = QFontMetricsF(self.edit.font())
        lines = max(1, min(MAX_LINES_SHOWN, self.text().count("\n") + 1))
        edit_h = int(lines * fm.lineSpacing() + 2 * self.edit.document().documentMargin() + 6)
        side = TOUCH_PX if touch else 24
        h = max(edit_h + 6, 2 * side + 9, TOUCH_PX if touch else 0)
        widest = max((fm.horizontalAdvance(t) for t in (self.text() or " ").split("\n")), default=0.0)
        w = int(max(MIN_WIDTH_PX, r.width(), widest + 40) + side + 10)
        w = max(120, min(w, vp.width() - 2 * GAP_PX))
        x = min(max(GAP_PX, r.left()), max(GAP_PX, vp.width() - w - GAP_PX))
        y = r.bottom() + GAP_PX
        if y + h > vp.height() - GAP_PX:               # kein Platz darunter: darüber
            y = r.top() - GAP_PX - h
        y = min(max(GAP_PX, y), max(GAP_PX, vp.height() - h - GAP_PX))
        self.frame.setGeometry(int(x), int(y), int(w), int(h))

    # --- Vorschau ---------------------------------------------------------------
    def _shape_for(self, text: str) -> Shape:
        from .text_ui import with_layout
        out = with_layout(self.base, text=text)
        out.id = self.shape_id
        return out

    def _preview(self) -> None:
        if self._closing or self.edit is None:
            return
        text = self.text()
        if text.strip():
            stack = self.ed.undo_stack
            mark = self._own_index if self._own_index is not None else self._start_index
            if stack.index() != mark:                  # fremder Schritt dazwischen: unsere
                self._start_index = stack.index()      # Vorschau darunter bleibt stehen
                self._dirty = self._own_index is not None or self._dirty
            if self.is_new and not self.doc.has_shape(self.shape_id):
                stack.push(AddShapesCommand(self.doc, [self._shape_for(text)], "Text einfügen"))
            elif self.doc.has_shape(self.shape_id):
                stack.push(ReplaceShapeCommand(self.doc, self._shape_for(text), "Text tippen",
                                               merge_key=f"inline-text:{self.shape_id}"))
            else:                                      # Objekt ist weg (z. B. gelöscht)
                self.cancel()
                return
            self._own_index = stack.index()
        self._place()

    def _drop_preview(self) -> bool:
        """Unsere Zwischenschritte zurücknehmen, solange sie oben auf dem Stapel liegen."""
        stack = self.ed.undo_stack
        if self._own_index is None:
            return not self._dirty
        if stack.index() == self._own_index:
            stack.setIndex(self._start_index)
            return not self._dirty
        return False

    # --- Beenden ----------------------------------------------------------------
    def commit(self) -> None:
        """Fertig: genau ein Undo-Schritt mit dem getippten Text (oder keiner)."""
        if self.frame is None or self._closing:
            return
        self._closing = True
        try:
            text = self.text()
            clean = self._drop_preview()
            changed = bool(text.strip()) and (self.is_new or text != self.original)
            if changed:
                final = self._shape_for(text)
                if not clean:                          # fremder Schritt dazwischen: auf Stand
                    if self.doc.has_shape(self.shape_id):
                        self.ed.undo_stack.push(ReplaceShapeCommand(self.doc, final, "Text ändern"))
                elif self.is_new:
                    self.ed.undo_stack.push(AddShapesCommand(self.doc, [final], "Text einfügen"))
                    self.ed.set_selection([final.id])
                elif self.doc.has_shape(self.shape_id):
                    self.ed.undo_stack.push(ReplaceShapeCommand(self.doc, final, "Text ändern"))
            elif not clean and self.doc.has_shape(self.shape_id):
                self._restore()
        finally:
            self._close()

    def cancel(self) -> None:
        """Abbrechen: alter Text bzw. kein neues Objekt."""
        if self.frame is None or self._closing:
            return
        self._closing = True
        try:
            if not self._drop_preview() and self.doc.has_shape(self.shape_id):
                self._restore()
        finally:
            self._close()

    def discard(self) -> None:
        """Feld schließen, ohne den Undo-Stapel anzufassen (Dokument wird ersetzt)."""
        if self.frame is not None and not self._closing:
            self._closing = True
            self._close()

    def _restore(self) -> None:
        if self.is_new:
            from .commands import DeleteShapesCommand
            self.ed.undo_stack.push(DeleteShapesCommand(self.doc, [self.shape_id]))
        else:
            self.ed.undo_stack.push(ReplaceShapeCommand(self.doc, self.base, "Text ändern"))

    def _close(self) -> None:
        frame = self.frame
        self.frame = None
        edit = self.edit
        self.edit = None
        try:
            self.ed.view.viewChanged.disconnect(self._place)
        except (RuntimeError, TypeError):
            pass
        if edit is not None:
            edit.blockSignals(True)
        if frame is not None:
            frame.hide()
            frame.deleteLater()
        self.shape_id = None
        self.base = None
        self._own_index = None
        self._closing = False
        self._dirty = False
        self.ed.view.setFocus(Qt.OtherFocusReason)
