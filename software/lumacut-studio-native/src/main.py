#!/usr/bin/env python3
"""LumaCut Studio – native Windows desktop app (PySide6)."""

import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QLabel, QPushButton, QListWidget, QStackedWidget,
    QGroupBox, QFormLayout, QSpinBox, QDoubleSpinBox, QComboBox,
    QStatusBar, QToolBar, QFrame, QScrollArea, QToolButton
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QFont, QPalette, QColor, QKeySequence, QShortcut

# --- machine integration (machine agent) ---
from machine.panel import MachinePanel, ESTOP_STYLE
# --- end machine integration ---
# --- canvas integration (canvas agent) ---
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.gcode import document_to_gcode
from lumacut_canvas.layers_panel import LayersPanel
from lumacut_canvas.fit import install_screen_fit
# --- end canvas integration ---
# --- scan integration (scan agent) ---
from scanprobe.panel import ScanPanel
# --- end scan integration ---
# --- job tools integration (review agent) ---
from lumacut_job.estimate import estimate_gcode
from lumacut_job.planner import optimized_document_gcode
from lumacut_job.qt_tools import install_job_tools
from lumacut_job.help_qt import install_help
# --- end job tools integration ---
# --- materials integration (materials agent) ---
from lumacut_materials.dialog import install_materials
# --- end materials integration ---
# --- import integration (review agent) ---
from lumacut_import.qt import install_import
from lumacut_workflow.qt import install_workflow
from lumacut_session import install_autosave
# --- end import integration ---


class LumaCutStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LumaCut Studio")
        self.setMinimumSize(800, 560)
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1400, screen.width() - 20), min(900, screen.height() - 40))
        self._apply_dark_theme()
        self._build_ui()

    def _apply_dark_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(11, 14, 19))
        palette.setColor(QPalette.WindowText, QColor(237, 242, 247))
        palette.setColor(QPalette.Base, QColor(19, 24, 32))
        palette.setColor(QPalette.AlternateBase, QColor(26, 33, 43))
        palette.setColor(QPalette.Text, QColor(237, 242, 247))
        palette.setColor(QPalette.Button, QColor(26, 33, 43))
        palette.setColor(QPalette.ButtonText, QColor(237, 242, 247))
        palette.setColor(QPalette.Highlight, QColor(76, 212, 176))
        palette.setColor(QPalette.HighlightedText, QColor(9, 37, 31))
        self.setPalette(palette)
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #0b0e13; color: #edf2f7; }
            QPushButton {
                background: #1a212b; border: 1px solid #28303d;
                padding: 10px 16px; border-radius: 8px;
                min-height: 40px; font-size: 14px;
            }
            QPushButton:hover { border-color: #526275; }
            QPushButton#primary { background: #4cd4b0; color: #09251f; font-weight: bold; border: none; }
            QPushButton#danger { background: #f36b73; color: white; border: none; }
            QGroupBox { border: 1px solid #28303d; border-radius: 8px; margin-top: 10px; padding-top: 6px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QListWidget { background: #131820; border: 1px solid #28303d; font-size: 14px; }
            QListWidget::item { min-height: 42px; padding: 6px; }
            QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit {
                min-height: 38px; font-size: 14px; padding: 4px 8px;
            }
            QStatusBar { background: #10141b; color: #93a1b5; font-size: 13px; }
            QSplitter::handle { background: #28303d; width: 8px; }
            QSplitter::handle:hover { background: #526275; }
            QToolBar { spacing: 6px; }
            QScrollArea { border: none; }
            QToolButton { min-width: 36px; min-height: 36px; }
        """)

    def _build_ui(self):
        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(22, 22))
        self.addToolBar(toolbar)

        # Panel-Umschalter für Surface / kleine Bildschirme
        self.toggle_left = QToolButton()
        self.toggle_left.setText("Ebenen")
        self.toggle_left.setCheckable(True)
        self.toggle_left.setChecked(True)
        self.toggle_left.setToolTip("Linke Seitenleiste ein-/ausblenden")
        self.toggle_left.clicked.connect(self._toggle_left)
        toolbar.addWidget(self.toggle_left)

        self.toggle_right = QToolButton()
        self.toggle_right.setText("Steuerung")
        self.toggle_right.setCheckable(True)
        self.toggle_right.setChecked(True)
        self.toggle_right.setToolTip("Rechte Seitenleiste ein-/ausblenden")
        self.toggle_right.clicked.connect(self._toggle_right)
        toolbar.addWidget(self.toggle_right)

        toolbar.addSeparator()
        self.status_label = QLabel("Nicht verbunden")
        toolbar.addWidget(self.status_label)
        toolbar.addWidget(QLabel("  "))

        start_btn = QPushButton("Start Job")
        start_btn.setObjectName("primary")
        start_btn.setMinimumHeight(40)
        toolbar.addWidget(start_btn)

        # --- machine integration (machine agent) ---
        self.machine_panel = MachinePanel()
        self.machine_panel.connection_changed.connect(self._on_machine_state)
        start_btn.clicked.connect(self.machine_panel.start_job)
        toolbar.addWidget(QLabel("  "))
        estop_btn = QPushButton("NOT-AUS")
        estop_btn.setStyleSheet(ESTOP_STYLE + " min-height: 40px; font-size: 15px; font-weight: bold;")
        estop_btn.setToolTip("Software-Notstopp M112")
        estop_btn.clicked.connect(self.machine_panel.emergency_stop)
        toolbar.addWidget(estop_btn)
        QShortcut(QKeySequence(Qt.Key_Pause), self, self.machine_panel.emergency_stop,
                  context=Qt.ApplicationShortcut)
        # --- end machine integration ---

        # Central splitter
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(True)
        self.splitter.setHandleWidth(10)
        layout.addWidget(self.splitter)

        # --- canvas integration (canvas agent) ---
        self.canvas = CanvasEditor()
        self.layers_panel = LayersPanel(self.canvas.document, self.canvas.undo_stack)
        self.layers_panel.setMinimumWidth(160)
        self.splitter.addWidget(self.layers_panel)
        self.splitter.addWidget(self.canvas)

        send_btn = QPushButton("Design senden")
        send_btn.setToolTip("Sichtbare Ebenen als G-Code an den Pi übertragen (startet nicht)")
        send_btn.setMinimumHeight(40)
        send_btn.clicked.connect(self._send_canvas_job)
        start_action = next(a for a in toolbar.actions() if toolbar.widgetForAction(a) is start_btn)
        toolbar.insertWidget(start_action, send_btn)
        toolbar.insertWidget(start_action, QLabel(" "))
        # --- end canvas integration ---

        # Right: Controls (scrollable)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        design = QGroupBox("Design")
        design_form = QFormLayout(design)
        design_form.addRow("Material", QComboBox())
        right_layout.addWidget(design)

        # --- scan integration (scan agent) ---
        scan = QGroupBox("Scan & Probe")
        scan_layout = QVBoxLayout(scan)
        self.scan_panel = ScanPanel(
            self.canvas, client_provider=lambda: getattr(self.machine_panel, "_client", None))
        scan_layout.addWidget(self.scan_panel)
        right_layout.addWidget(scan)
        # --- end scan integration ---

        # --- machine integration (machine agent) ---
        machine = QGroupBox("Maschine")
        machine_layout = QVBoxLayout(machine)
        machine_layout.addWidget(self.machine_panel)
        right_layout.addWidget(machine)
        # --- end machine integration ---

        right_layout.addStretch()

        self.right_scroll = QScrollArea()
        self.right_scroll.setWidgetResizable(True)
        self.right_scroll.setFrameShape(QFrame.NoFrame)
        self.right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.right_scroll.setMinimumWidth(200)
        self.right_scroll.viewport().setAttribute(Qt.WA_AcceptTouchEvents, True)
        self.right_scroll.setWidget(right)
        self.splitter.addWidget(self.right_scroll)
        # --- end machine integration ---

        # Startgrößen anpassen
        total = max(800, self.width())
        left = min(240, int(total * 0.18))
        right_w = min(300, int(total * 0.24))
        center = total - left - right_w
        self.splitter.setSizes([left, max(280, center), right_w])
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setCollapsible(0, True)
        self.splitter.setCollapsible(2, True)

        # Status bar
        status = QStatusBar()
        self.setStatusBar(status)
        status.showMessage("Arbeitsfläche 360 × 340 mm · Werkzeuge: V R E L T · Mittlere Maustaste/Leertaste = Verschieben")
        self.cursor_label = QLabel("X —  Y —")
        self.cursor_label.setMinimumWidth(140)
        status.addPermanentWidget(self.cursor_label)
        self.canvas.cursorMoved.connect(
            lambda x, y: self.cursor_label.setText(f"X {x:6.1f}  Y {y:6.1f}"))
        self.canvas.statusMessage.connect(lambda text: status.showMessage(text, 5000))
        self.scan_panel.statusMessage.connect(lambda text: status.showMessage(text, 6000))
        self.canvas.fileChanged.connect(lambda t: self.setWindowTitle(f"{t} – LumaCut Studio"))
        self.setWindowTitle(f"{self.canvas.title()} – LumaCut Studio")

        # --- job tools integration (review agent) ---
        install_job_tools(self)
        # --- end job tools integration ---
        # --- materials integration (materials agent) ---
        install_materials(self)
        # --- end materials integration ---
        # --- import integration (review agent) ---
        install_import(self)
        # --- end import integration ---
        # --- workflow integration (review agent) ---
        install_workflow(self)
        # --- end workflow integration ---
        # --- autosave integration (review agent) ---
        install_autosave(self)
        # --- end autosave integration ---
        # --- canvas integration (canvas agent): small screens / touch ---
        install_screen_fit(self)  # Fenster in Bildschirm, Seitenleiste nicht abgeschnitten, Touch-Modus
        # --- end canvas integration ---
        # --- help integration (review agent): Hilfe › Tastenkürzel (F1), zuletzt ---
        install_help(self)
        # --- end help integration ---

    def _toggle_left(self):
        visible = self.toggle_left.isChecked()
        self.layers_panel.setVisible(visible)

    def _toggle_right(self):
        visible = self.toggle_right.isChecked()
        self.right_scroll.setVisible(visible)

    # --- machine integration (machine agent) ---
    def _on_machine_state(self, state, text):
        colours = {"connected": "#4cd4b0", "connecting": "#6cb4ff",
                   "error": "#f36b73", "auth_failed": "#f36b73"}
        self.status_label.setText(text[:80])
        self.status_label.setStyleSheet("color: %s;" % colours.get(state, "#93a1b5"))

    def closeEvent(self, event):
        if not self.canvas.confirm_discard():
            event.ignore()
            return
        self.scan_panel.shutdown()
        self.machine_panel.shutdown()
        super().closeEvent(event)
        self.autosave.shutdown()
    # --- end machine integration ---

    # --- canvas integration (canvas agent) ---
    def _send_canvas_job(self):
        try:
            gcode = optimized_document_gcode(self.canvas.document)
        except ValueError as exc:
            self.statusBar().showMessage(f"Senden nicht möglich: {exc}", 6000)
            return
        gcode = self.scan_panel.prepare_job_gcode(gcode)
        if gcode is None:
            return
        stem = self.canvas.file_path.name.split(".")[0] if self.canvas.file_path else "canvas"
        self.machine_panel.send_gcode(f"{stem}.gcode", gcode, start=False)
        self.statusBar().showMessage(f"Gesendet: {stem}.gcode {estimate_gcode(gcode).summary()}", 10000)
    # --- end canvas integration ---


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("LumaCut")
    app.setApplicationName("LumaCut Studio")
    app.setAttribute(Qt.AA_SynthesizeTouchForUnhandledMouseEvents, True)
    win = LumaCutStudio()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
