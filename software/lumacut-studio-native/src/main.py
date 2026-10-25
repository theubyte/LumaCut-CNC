#!/usr/bin/env python3
"""LumaCut Studio – native Windows desktop app (PySide6)."""

import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QLabel, QPushButton, QListWidget, QStackedWidget,
    QGroupBox, QFormLayout, QSpinBox, QDoubleSpinBox, QComboBox,
    QStatusBar, QToolBar, QFrame, QScrollArea
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
# --- end canvas integration ---
# --- scan integration (scan agent) ---
from scanprobe.panel import ScanPanel
# --- end scan integration ---
# --- job tools integration (review agent) ---
from lumacut_job.estimate import estimate_gcode
from lumacut_job.planner import optimized_document_gcode
from lumacut_job.qt_tools import install_job_tools
# --- end job tools integration ---
# --- materials integration (materials agent) ---
from lumacut_materials.dialog import install_materials
# --- end materials integration ---


class LumaCutStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LumaCut Studio")
        self.resize(1400, 900)
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
            QPushButton { background: #1a212b; border: 1px solid #28303d; padding: 8px 14px; border-radius: 6px; }
            QPushButton:hover { border-color: #526275; }
            QPushButton#primary { background: #4cd4b0; color: #09251f; font-weight: bold; border: none; }
            QPushButton#danger { background: #f36b73; color: white; border: none; }
            QGroupBox { border: 1px solid #28303d; border-radius: 8px; margin-top: 12px; padding-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QListWidget { background: #131820; border: 1px solid #28303d; }
            QStatusBar { background: #10141b; color: #93a1b5; }
        """)

    def _build_ui(self):
        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addWidget(QLabel("  LumaCut Studio   "))
        toolbar.addSeparator()
        self.status_label = QLabel("Nicht verbunden")
        toolbar.addWidget(self.status_label)
        toolbar.addWidget(QLabel("   "))
        start_btn = QPushButton("Start Job")
        start_btn.setObjectName("primary")
        toolbar.addWidget(start_btn)
        # --- machine integration (machine agent) ---
        # The machine panel owns connection, status and job control; the
        # toolbar only mirrors its state and offers an always-visible E-Stop.
        self.machine_panel = MachinePanel()
        self.machine_panel.connection_changed.connect(self._on_machine_state)
        start_btn.clicked.connect(self.machine_panel.start_job)
        toolbar.addWidget(QLabel("   "))
        estop_btn = QPushButton("NOT-AUS")
        estop_btn.setStyleSheet(ESTOP_STYLE)
        estop_btn.setToolTip("Software-Notstopp M112 (Pause/Untbr-Taste)")
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

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # --- canvas integration (canvas agent) ---
        # Left: Ebenen-Panel, Center: Canvas-Editor (Paket lumacut_canvas).
        self.canvas = CanvasEditor()
        self.layers_panel = LayersPanel(self.canvas.document, self.canvas.undo_stack)
        self.layers_panel.setMinimumWidth(295)
        splitter.addWidget(self.layers_panel)
        splitter.addWidget(self.canvas)
        send_btn = QPushButton("Design senden")
        send_btn.setToolTip("Sichtbare Ebenen als G-Code an den Pi übertragen (startet nicht)")
        send_btn.clicked.connect(self._send_canvas_job)
        start_action = next(a for a in toolbar.actions() if toolbar.widgetForAction(a) is start_btn)
        toolbar.insertWidget(start_action, send_btn)  # Ablauf: senden, dann starten
        toolbar.insertWidget(start_action, QLabel(" "))
        # --- end canvas integration ---

        # Right: Controls
        right = QWidget()
        right_layout = QVBoxLayout(right)

        # Design group
        design = QGroupBox("Design")
        design_form = QFormLayout(design)
        design_form.addRow("Material", QComboBox())
        right_layout.addWidget(design)

        # Scan & Probe
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
        # --- machine integration (machine agent) ---
        # The machine panel is tall; keep the right column scrollable.
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setWidget(right)
        splitter.addWidget(right_scroll)
        # --- end machine integration ---

        splitter.setSizes([220, 760, 380])
        # --- canvas integration (canvas agent) ---
        splitter.setSizes([290, 760, 380])
        splitter.setStretchFactor(1, 1)
        # --- end canvas integration ---

        # Status bar
        status = QStatusBar()
        self.setStatusBar(status)
        status.showMessage("LumaCut Studio · Arbeitsfläche 360 × 340 mm · Safezone intern")
        # --- canvas integration (canvas agent) ---
        status.showMessage("Arbeitsfläche 360 × 340 mm · Werkzeuge: V R E L T · Mittlere Maustaste/Leertaste = Verschieben")
        self.cursor_label = QLabel("X —  Y —")
        self.cursor_label.setMinimumWidth(190)
        status.addPermanentWidget(self.cursor_label)
        self.canvas.cursorMoved.connect(
            lambda x, y: self.cursor_label.setText(f"X {x:7.1f} mm   Y {y:7.1f} mm"))
        self.canvas.statusMessage.connect(lambda text: status.showMessage(text, 5000))
        # --- scan integration (scan agent) ---
        self.scan_panel.statusMessage.connect(lambda text: status.showMessage(text, 6000))
        # --- end scan integration ---
        self.canvas.fileChanged.connect(lambda t: self.setWindowTitle(f"{t} – LumaCut Studio"))
        self.setWindowTitle(f"{self.canvas.title()} – LumaCut Studio")
        # --- end canvas integration ---
        # --- job tools integration (review agent) ---
        install_job_tools(self)  # Zeit schätzen, Rahmen, Materialtest
        # --- end job tools integration ---
        # --- materials integration (materials agent) ---
        install_materials(self)  # Menü Material → Materialbibliothek
        # --- end materials integration ---


    # --- machine integration (machine agent) ---
    def _on_machine_state(self, state, text):
        colours = {"connected": "#4cd4b0", "connecting": "#6cb4ff",
                   "error": "#f36b73", "auth_failed": "#f36b73"}
        self.status_label.setText(text[:90])
        self.status_label.setStyleSheet("color: %s;" % colours.get(state, "#93a1b5"))

    def closeEvent(self, event):
        # --- canvas integration (canvas agent) ---
        if not self.canvas.confirm_discard():
            event.ignore()
            return
        # --- end canvas integration ---
        # --- scan integration (scan agent) ---
        self.scan_panel.shutdown()
        # --- end scan integration ---
        self.machine_panel.shutdown()
        super().closeEvent(event)
    # --- end machine integration ---

    # --- canvas integration (canvas agent) ---
    def _send_canvas_job(self):
        try:
            # job tools (review agent): inner shapes first, reduced travel
            gcode = optimized_document_gcode(self.canvas.document)
        except ValueError as exc:
            self.statusBar().showMessage(f"Senden nicht möglich: {exc}", 6000)
            return
        # --- scan integration (scan agent) ---
        gcode = self.scan_panel.prepare_job_gcode(gcode)  # unverändert ohne Fokuskorrektur
        if gcode is None:
            return
        # --- end scan integration ---
        stem = self.canvas.file_path.name.split(".")[0] if self.canvas.file_path else "canvas"
        self.machine_panel.send_gcode(f"{stem}.gcode", gcode, start=False)
        self.statusBar().showMessage(f"Gesendet: {stem}.gcode {estimate_gcode(gcode).summary()}", 10000)
    # --- end canvas integration ---


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("LumaCut")  # QSettings scope (machine settings)
    app.setApplicationName("LumaCut Studio")
    win = LumaCutStudio()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
