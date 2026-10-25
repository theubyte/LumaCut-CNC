#!/usr/bin/env python3
"""LumaCut Studio – native Windows desktop app (PySide6)."""

import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QLabel, QPushButton, QListWidget, QStackedWidget,
    QGroupBox, QFormLayout, QSpinBox, QDoubleSpinBox, QComboBox,
    QStatusBar, QToolBar, QFrame
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QFont, QPalette, QColor


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

        # Central splitter
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # Left: Layers
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("<b>Ebenen</b>"))
        self.layer_list = QListWidget()
        self.layer_list.addItem("Ebene 1 – Schneiden")
        self.layer_list.addItem("Ebene 2 – Gravieren")
        left_layout.addWidget(self.layer_list)
        add_layer = QPushButton("+ Ebene")
        left_layout.addWidget(add_layer)
        left_layout.addStretch()
        splitter.addWidget(left)

        # Center: Canvas placeholder
        center = QFrame()
        center.setStyleSheet("background: #0c1118; border: 1px solid #28303d;")
        center_layout = QVBoxLayout(center)
        canvas_label = QLabel("Arbeitsfläche 360 × 340 mm\n\nSafezone intern und unsichtbar\n\n(Canvas folgt)")
        canvas_label.setAlignment(Qt.AlignCenter)
        canvas_label.setStyleSheet("color: #93a1b5; font-size: 16px;")
        center_layout.addWidget(canvas_label)
        splitter.addWidget(center)

        # Right: Controls
        right = QWidget()
        right_layout = QVBoxLayout(right)

        # Design group
        design = QGroupBox("Design")
        design_form = QFormLayout(design)
        design_form.addRow("Material", QComboBox())
        right_layout.addWidget(design)

        # Scan & Probe
        scan = QGroupBox("Scan & Probe")
        scan_layout = QVBoxLayout(scan)
        scan_layout.addWidget(QLabel("Kopf-Kamera scannt bei fester Höhe.\nErkannte Bereiche werden automatisch geprobt."))
        btn_scan = QPushButton("Scan starten")
        btn_scan.setObjectName("primary")
        scan_layout.addWidget(btn_scan)
        btn_probe = QPushButton("Bereiche proben")
        scan_layout.addWidget(btn_probe)
        right_layout.addWidget(scan)

        # Machine
        machine = QGroupBox("Maschine")
        machine_layout = QVBoxLayout(machine)
        machine_layout.addWidget(QLabel("X: —   Y: —   Z: —"))
        machine_layout.addWidget(QLabel("Homed: —   Laser: Aus"))
        btn_home = QPushButton("Home")
        btn_park = QPushButton("Park")
        btn_focus = QPushButton("Fokus")
        machine_layout.addWidget(btn_home)
        machine_layout.addWidget(btn_park)
        machine_layout.addWidget(btn_focus)
        btn_estop = QPushButton("Not-Aus")
        btn_estop.setObjectName("danger")
        machine_layout.addWidget(btn_estop)
        right_layout.addWidget(machine)

        right_layout.addStretch()
        splitter.addWidget(right)

        splitter.setSizes([220, 800, 320])

        # Status bar
        status = QStatusBar()
        self.setStatusBar(status)
        status.showMessage("LumaCut Studio · Arbeitsfläche 360 × 340 mm · Safezone intern")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("LumaCut Studio")
    win = LumaCutStudio()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
