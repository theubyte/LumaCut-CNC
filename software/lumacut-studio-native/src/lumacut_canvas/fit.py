"""Kleine Bildschirme und Touch: Scroll-Hilfen und Fenster-Anpassung.

* :class:`HScrollStrip` – waagerecht scrollbare Leiste (z. B. Eigenschaftsleiste),
  deren Höhe dem Inhalt folgt; nichts wird abgeschnitten.
* :func:`enable_touch_scroll` – Finger-Scrollen (kinetisch) in einer QScrollArea.
* :func:`install_screen_fit` – vom Hauptfenster aufgerufen (main.py, markierter
  Canvas-Block): Standardgröße aus der verfügbaren Bildschirmfläche, rechte
  Seitenleiste breit genug für ihren Inhalt und senkrecht scrollbar, Touch-Modus
  auf kleinen/Touch-Bildschirmen standardmäßig an.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtWidgets import (QAbstractScrollArea, QApplication, QFrame, QScrollArea,
                               QScroller, QSizePolicy, QStyle, QWidget)

from . import touch

# Logische Bildschirmgröße (nach Windows-Skalierung), ab der der Bildschirm als
# klein gilt: Surface Pro 2736×1824 bei 200 % = 1368×912, 1280×720 usw.
SMALL_SCREEN_W = 1500
SMALL_SCREEN_H = 950
SIDEBAR_MAX_FRACTION = 0.42  # rechte Seitenleiste höchstens so viel der Fensterbreite
LAYERS_MAX_FRACTION = 0.26   # Ebenen-Panel (links)
SIDEBAR_HARD_MIN = 180       # px; darunter klappt der Splitter die Leiste ein


def is_small_screen(screen=None) -> bool:
    screen = screen or QApplication.primaryScreen()
    if screen is None:
        return False
    g = screen.availableGeometry()
    return g.width() < SMALL_SCREEN_W or g.height() < SMALL_SCREEN_H


def enable_touch_scroll(area: QAbstractScrollArea) -> None:
    """Mit dem Finger ziehen = scrollen (Maus und Stift bleiben unverändert)."""
    QScroller.grabGesture(area.viewport(), QScroller.TouchGesture)


class HScrollStrip(QScrollArea):
    """Waagerecht scrollbare Leiste: so hoch wie ihr Inhalt (plus Bildlaufleiste,
    falls der Inhalt breiter ist als der Platz), schmal im Minimum."""

    def __init__(self, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(f"{content.objectName() or 'Strip'}Scroll")
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setWidget(content)
        content.installEventFilter(self)
        self._overflow = False
        enable_touch_scroll(self)

    def _needs_scroll(self) -> bool:
        w = self.widget()
        return bool(w) and w.minimumSizeHint().width() > self.viewport().width()

    def _height(self) -> int:
        w = self.widget()
        h = w.sizeHint().height() if w else 0
        if self._overflow:
            h += self.horizontalScrollBar().sizeHint().height()
        return h

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        w = self.widget()
        return QSize(w.sizeHint().width() if w else 0, self._height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(80, self._height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync()

    def _sync(self) -> None:
        over = self._needs_scroll()
        if over != self._overflow:
            self._overflow = over
            self.updateGeometry()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if obj is self.widget() and event.type() == QEvent.LayoutRequest:
            QTimer.singleShot(0, self._sync)
        return super().eventFilter(obj, event)


def sidebar_needed_width(area: QScrollArea) -> int:
    """Breite, bei der der Inhalt einer senkrecht scrollenden Seitenleiste nicht
    abgeschnitten wird (Inhalt + senkrechte Bildlaufleiste + Rahmen)."""
    content = area.widget()
    if content is None:
        return area.minimumWidth()
    bar = area.style().pixelMetric(QStyle.PM_ScrollBarExtent, None, area)
    return content.minimumSizeHint().width() + bar + 2 * area.frameWidth() + 2


class _ScreenFit(QObject):
    """Hält die rechte Seitenleiste breit genug und das Fenster auf dem Bildschirm."""

    def __init__(self, win) -> None:
        super().__init__(win)
        self.win = win
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.fit_panels)
        win.installEventFilter(self)
        # Inhalt der Seitenleisten kann später wachsen (Panels füllen sich,
        # Schrift/DPI unter Windows) – dann erneut anpassen.
        for name in ("right_scroll", "layers_panel"):
            area = self._area(getattr(win, name, None))
            if area is not None and area.widget() is not None:
                area.widget().installEventFilter(self)

    @staticmethod
    def _area(panel):
        area = panel if isinstance(panel, QScrollArea) else getattr(panel, "scroll", None)
        return area if isinstance(area, QScrollArea) else None

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        t = event.type()
        if (obj is self.win and t in (QEvent.Show, QEvent.Resize)) or t == QEvent.LayoutRequest:
            self._timer.start()
        return False

    def fit_panels(self) -> None:
        """Seitenleisten so breit, dass ihr Inhalt nicht abgeschnitten wird
        (höchstens ein Anteil der Fensterbreite); den Platz gibt der Canvas ab."""
        win = self.win
        splitter = getattr(win, "splitter", None)
        canvas = getattr(win, "canvas", None)
        if splitter is None:
            return
        sizes = splitter.sizes()
        centre = splitter.indexOf(canvas) if canvas is not None else -1
        changed = False
        for name, fraction in (("right_scroll", SIDEBAR_MAX_FRACTION), ("layers_panel", LAYERS_MAX_FRACTION)):
            panel = getattr(win, name, None)
            if panel is None:
                continue
            area = self._area(panel)
            if area is None:
                continue
            want = min(sidebar_needed_width(area), sidebar_cap(win.width(), fraction))
            # Hartes Minimum klein halten (das Fenster darf nie breiter als der
            # Bildschirm erzwungen werden); in sehr schmalen Fenstern scrollt die
            # Leiste dann notfalls waagerecht, statt Felder abzuschneiden.
            panel.setMinimumWidth(min(want, SIDEBAR_HARD_MIN))
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            i = splitter.indexOf(panel)
            if i < 0 or sizes[i] == 0 or sizes[i] >= want:
                continue  # eingeklappt/ausgeblendet oder schon breit genug
            if centre >= 0:
                sizes[centre] = max(0, sizes[centre] - (want - sizes[i]))
            sizes[i] = want
            changed = True
        if changed:
            splitter.setSizes(sizes)


def sidebar_cap(window_width: int, fraction: float = SIDEBAR_MAX_FRACTION) -> int:
    """Höchstbreite einer Seitenleiste; breiterer Inhalt scrollt waagerecht."""
    return max(160, int(window_width * fraction))


def default_window_size(screen=None) -> QSize:
    """Startgröße innerhalb der verfügbaren Fläche (Taskleiste und Titelzeile abgezogen)."""
    screen = screen or QApplication.primaryScreen()
    if screen is None:
        return QSize(1400, 900)
    g = screen.availableGeometry()
    return QSize(max(640, min(1400, g.width() - 16)), max(480, min(900, g.height() - 48)))


def install_screen_fit(win) -> None:
    """Hauptfenster an kleine Bildschirme und Touch anpassen (siehe Modul-Doku)."""
    screen = QApplication.primaryScreen()
    if screen is not None:
        g = screen.availableGeometry()
        # Mindestgröße darf nie größer sein als der Bildschirm.
        win.setMinimumSize(min(win.minimumWidth(), g.width() - 16),
                           min(win.minimumHeight(), g.height() - 48))
        size = default_window_size(screen)
        win.resize(size)
        win.move(g.left() + max(0, (g.width() - size.width()) // 2),
                 g.top() + max(0, (g.height() - size.height() - 32) // 2))

    right = getattr(win, "right_scroll", None)
    if isinstance(right, QScrollArea):
        enable_touch_scroll(right)

    canvas = getattr(win, "canvas", None)
    panel = getattr(win, "layers_panel", None)
    if canvas is not None:
        if touch.load_setting(canvas._settings) is None and is_small_screen(screen):
            canvas.set_touch_mode(True, persist=False)  # große Griffe; Wahl bleibt änderbar
        if panel is not None and hasattr(panel, "set_touch_mode"):
            panel.set_touch_mode(canvas.touch_mode)
            canvas.touchModeChanged.connect(panel.set_touch_mode)

    win._screen_fit = _ScreenFit(win)
    win._screen_fit.fit_panels()
