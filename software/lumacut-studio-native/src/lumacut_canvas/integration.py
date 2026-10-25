"""Helfer, mit denen ``main.py`` weitere Module (z. B. Scan & Probe) an das
Hauptfenster und den Canvas anschließt, ohne Canvas-Interna zu kennen::

    from lumacut_canvas.integration import add_dock_panel, make_action

    dock = add_dock_panel(window, ScanPanel(window.canvas), "Scan & Probe")
    act = make_action(window, "Bereich scannen", window.canvas.request_roi,
                      shortcut="Ctrl+Shift+B", icon="scan")
    window.canvas.add_toolbar_action(act, name="scan_roi")
    window.canvas.roiSelected.connect(lambda x, y, w, h: ...)  # mm

Docks bekommen einen stabilen ``objectName`` (für saveState/restoreState)
und lassen sich über ``dock.toggleViewAction()`` ein-/ausblenden.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import QDockWidget, QMainWindow, QWidget

from . import icons


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_") or "panel"


def add_dock_panel(window: QMainWindow, widget: QWidget, title: str,
                   area: Qt.DockWidgetArea = Qt.RightDockWidgetArea,
                   object_name: str | None = None, tabify_with: QDockWidget | None = None,
                   closable: bool = True) -> QDockWidget:
    """``widget`` als andockbares Panel in ``window`` einhängen und zurückgeben."""
    dock = QDockWidget(title, window)
    dock.setObjectName(object_name or f"dock_{_slug(title)}")
    dock.setWidget(widget)
    features = QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
    if closable:
        features |= QDockWidget.DockWidgetClosable
    dock.setFeatures(features)
    window.addDockWidget(area, dock)
    if tabify_with is not None:
        window.tabifyDockWidget(tabify_with, dock)
    return dock


def make_action(parent: QWidget, text: str, slot: Callable[..., object],
                shortcut: str | QKeySequence | None = None, icon: str | QIcon | None = None,
                checkable: bool = False, name: str | None = None) -> QAction:
    """QAction im Stil der Canvas-Aktionen (Tooltip mit Kürzel, optional Icon
    aus ``lumacut_canvas.icons`` oder ein QIcon – unbekannte Icon-Namen werden ignoriert)."""
    a = QAction(text, parent)
    if name:
        a.setObjectName(name)
    if isinstance(icon, QIcon):
        a.setIcon(icon)
    elif icon and icon in icons.available():
        a.setIcon(icons.icon(icon))
    if shortcut:
        seq = QKeySequence(shortcut)
        a.setShortcut(seq)
        a.setToolTip(f"{text}  ({seq.toString(QKeySequence.NativeText)})")
    else:
        a.setToolTip(text)
    a.setCheckable(checkable)
    a.triggered.connect(slot)
    return a
