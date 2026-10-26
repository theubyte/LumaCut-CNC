#!/usr/bin/env python3
"""Eigenständige Demo des Canvas-Editors (ohne Maschinen-/Scan-Panels).

Start:  python src/canvas_demo.py
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDockWidget, QLabel, QMainWindow

from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.layers_panel import LayersPanel
from lumacut_canvas.theme import CANVAS_QSS
from lumacut_canvas.workarea import screen_to_user


class CanvasDemoWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.resize(1280, 820)
        self.setStyleSheet("QMainWindow, QWidget { background: #0b0e13; color: #edf2f7; }"
                           "QStatusBar { background: #10141b; color: #93a1b5; }"
                           "QDockWidget::title { background: #10141b; padding: 6px; }" + CANVAS_QSS)
        self.editor = CanvasEditor()
        self.setCentralWidget(self.editor)
        dock = QDockWidget("Ebenen", self)
        dock.setFeatures(QDockWidget.DockWidgetMovable)
        self.layers = LayersPanel(self.editor.document, self.editor.undo_stack)
        dock.setWidget(self.layers)
        dock.setMinimumWidth(290)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.pos_label = QLabel("X —  Y —")
        self.statusBar().addPermanentWidget(self.pos_label)
        self.editor.cursorMoved.connect(lambda x, y: self.pos_label.setText(
            "X {:7.1f} mm   Y {:7.1f} mm".format(*screen_to_user(x, y))))
        self.editor.statusMessage.connect(lambda t: self.statusBar().showMessage(t, 4000))
        self.editor.fileChanged.connect(lambda t: self.setWindowTitle(f"{t} – LumaCut Studio Canvas"))
        self.setWindowTitle(f"{self.editor.title()} – LumaCut Studio Canvas")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.editor.confirm_discard():
            event.accept()
        else:
            event.ignore()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("LumaCut Studio Canvas")
    win = CanvasDemoWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
