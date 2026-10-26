"""Dunkles Farbschema und QSS für den Canvas-Editor.

Farben passen zum bestehenden Studio (main.py, design.css): Hintergrund
#0b0e13, Akzent #4cd4b0. Die Regeln sind über objectName auf den Editor
beschränkt, damit andere Panels (Maschine, Scan) ihr Aussehen behalten.
"""

from __future__ import annotations

BG = "#0b0e13"
PANEL = "#10141b"
SURFACE = "#131820"
SURFACE_2 = "#1a212b"
BORDER = "#28303d"
BORDER_HOVER = "#526275"
TEXT = "#edf2f7"
TEXT_DIM = "#93a1b5"
ACCENT = "#4cd4b0"
ACCENT_TEXT = "#09251f"
DANGER = "#f36b73"

# Canvas-Farben
CANVAS_OUTSIDE = "#080b10"
CANVAS_WORK = "#111720"
GRID_MINOR = "#18202b"
GRID_MAJOR = "#243041"
WORK_BORDER = "#3a4a5e"
SELECTION = ACCENT

CANVAS_QSS = f"""
#CanvasEditor, #LayersPanel {{ background: {BG}; }}
#CanvasEditor QToolBar {{ background: {PANEL}; border: none; spacing: 2px; padding: 4px; }}
#CanvasEditor QToolBar#ToolStrip {{ border-right: 1px solid {BORDER}; padding: 6px 4px; }}
/* Werkzeugleiste immer ≥ 44 × 44 px (Inhalt 34 + 2 × 4 Innenabstand + 2 × 1 Rand), mit Abstand */
#CanvasEditor QToolBar#ToolStrip {{ spacing: 4px; }}
#CanvasEditor QToolBar#ToolStrip QToolButton {{ min-width: 34px; min-height: 34px; padding: 4px; }}
#CanvasEditor QToolBar#ActionBar {{ border-bottom: 1px solid {BORDER}; }}
#CanvasEditor QToolButton {{
    background: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 5px; color: {TEXT};
}}
#CanvasEditor QToolButton:hover {{ background: {SURFACE_2}; border-color: {BORDER}; }}
#CanvasEditor QToolButton:checked {{ background: #173a33; border-color: {ACCENT}; }}
#CanvasEditor QToolButton:disabled {{ color: #4a5566; }}
#PropertyBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
#PathPreviewBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
#PropertyBar QLabel {{ color: {TEXT_DIM}; padding: 0 2px 0 8px; }}
#PropertyBar QLabel#PropTitle {{ color: {TEXT}; font-weight: 600; padding-left: 4px; }}
#CanvasEditor QDoubleSpinBox, #CanvasEditor QLineEdit, #CanvasEditor QComboBox,
#LayersPanel QDoubleSpinBox, #LayersPanel QSpinBox, #LayersPanel QLineEdit {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 5px;
    padding: 3px 6px; color: {TEXT}; selection-background-color: {ACCENT};
    selection-color: {ACCENT_TEXT}; min-height: 20px;
}}
#CanvasEditor QDoubleSpinBox:focus, #CanvasEditor QLineEdit:focus,
#LayersPanel QDoubleSpinBox:focus, #LayersPanel QSpinBox:focus, #LayersPanel QLineEdit:focus {{
    border-color: {ACCENT};
}}
#CanvasEditor QDoubleSpinBox:disabled, #CanvasEditor QLineEdit:disabled,
#CanvasEditor QComboBox:disabled {{ color: #4a5566; }}
#CanvasEditor QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER}; }}
#Ruler {{ background: {PANEL}; }}
CanvasView {{ border: none; background: {CANVAS_OUTSIDE}; }}
#PropertyBarScroll, #LayersScroll, #PathPreviewBarScroll {{ background: transparent; border: none; }}
#LayersContent {{ background: {BG}; }}
#PropertyBarScroll QScrollBar:horizontal, #LayersScroll QScrollBar:horizontal {{
    background: {PANEL}; height: 10px; margin: 0; border: none;
}}
#LayersScroll QScrollBar:vertical {{ background: {PANEL}; width: 10px; margin: 0; border: none; }}
#PropertyBarScroll QScrollBar::handle:horizontal, #LayersScroll QScrollBar::handle:horizontal {{
    background: {BORDER_HOVER}; min-width: 40px; border-radius: 4px; margin: 2px;
}}
#LayersScroll QScrollBar::handle:vertical {{
    background: {BORDER_HOVER}; min-height: 40px; border-radius: 4px; margin: 2px;
}}
#PropertyBarScroll QScrollBar::add-line, #PropertyBarScroll QScrollBar::sub-line,
#LayersScroll QScrollBar::add-line, #LayersScroll QScrollBar::sub-line {{ width: 0; height: 0; }}
#PropertyBarScroll QScrollBar::add-page, #PropertyBarScroll QScrollBar::sub-page,
#LayersScroll QScrollBar::add-page, #LayersScroll QScrollBar::sub-page {{ background: none; }}

#LayersPanel QLabel#SectionTitle {{ color: {TEXT}; font-weight: 600; font-size: 13px; padding: 2px 0; }}
#LayersPanel QLabel#Hint {{ color: {TEXT_DIM}; font-size: 11px; }}
#LayersPanel QListWidget {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; outline: none; padding: 2px;
}}
#LayersPanel QListWidget::item {{ border-radius: 5px; margin: 1px; }}
#LayersPanel QListWidget::item:selected {{ background: #173a33; }}
#LayersPanel QListWidget::item:hover:!selected {{ background: {SURFACE_2}; }}
#LayersPanel QLabel#LayerName {{ color: {TEXT}; font-weight: 600; background: transparent; }}
#LayersPanel QLabel#LayerSummary {{ color: {TEXT_DIM}; font-size: 11px; background: transparent; }}
#LayersPanel QWidget#LayerRow {{ background: transparent; }}
#LayersPanel QToolButton {{
    background: transparent; border: 1px solid transparent; border-radius: 5px; padding: 3px;
}}
#LayersPanel QToolButton:hover {{ background: {SURFACE_2}; border-color: {BORDER}; }}
#LayersPanel QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px;
}}
#LayersPanel QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {TEXT}; }}
#LayersPanel QPushButton#ColorButton {{ border: 1px solid {BORDER}; border-radius: 5px; min-height: 20px; max-height: 20px; padding: 2px; }}
#LayersPanel QComboBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 5px;
    padding: 3px 6px; color: {TEXT}; min-height: 20px;
}}
#LayersPanel QComboBox:focus {{ border-color: {ACCENT}; }}
#LayersPanel QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {BORDER}; color: {TEXT};
    selection-background-color: #173a33;
}}
#LayersPanel QGroupBox QLabel {{ color: {TEXT_DIM}; background: transparent; }}
#LayersPanel QLabel#PassBadge {{
    border-radius: 4px; padding: 1px 6px; font-size: 11px; font-weight: 600;
}}
#LayersPanel QLabel#PassBadge[auto="true"] {{ background: #173a33; color: {ACCENT}; }}
#LayersPanel QLabel#PassBadge[auto="false"] {{ background: #3a2f17; color: #f2c46d; }}
#LayersPanel QLabel#PassPlan {{ color: {TEXT_DIM}; font-size: 11px; }}
#LayersPanel QLabel#PassPlan[warn="true"] {{ color: {DANGER}; }}
#LayersPanel QPushButton#AutoPasses {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 5px; color: {TEXT};
    padding: 2px 8px;
}}
#LayersPanel QPushButton#AutoPasses:hover {{ border-color: {ACCENT}; }}
#LayersPanel QPushButton#AutoPasses:disabled {{ color: #4a5566; }}

/* --- Touch-Modus (dynamische Eigenschaft touch="true", siehe touch.py) --- */
#CanvasEditor[touch="true"] QToolBar {{ spacing: 6px; padding: 6px; }}
#CanvasEditor[touch="true"] QToolBar#ToolStrip {{ padding: 8px 6px; }}
#CanvasEditor[touch="true"] QToolButton {{ min-width: 40px; min-height: 40px; padding: 7px; border-radius: 8px; }}
#CanvasEditor[touch="true"] QToolBar#ToolStrip {{ spacing: 6px; }}
#CanvasEditor[touch="true"] QToolBar#ToolStrip QToolButton {{ min-width: 40px; min-height: 40px; padding: 7px; }}
#CanvasEditor[touch="true"] #PropertyBarScroll QScrollBar:horizontal {{ height: 16px; }}
#LayersPanel[touch="true"] #LayersScroll QScrollBar:vertical {{ width: 16px; }}
#LayersPanel[touch="true"] #LayersScroll QScrollBar:horizontal {{ height: 16px; }}
#CanvasEditor[touch="true"] QDoubleSpinBox, #CanvasEditor[touch="true"] QLineEdit,
#CanvasEditor[touch="true"] QComboBox {{ min-height: 34px; }}
#LayersPanel[touch="true"] QToolButton {{ min-width: 36px; min-height: 36px; padding: 4px; }}
#LayersPanel[touch="true"] QDoubleSpinBox, #LayersPanel[touch="true"] QSpinBox,
#LayersPanel[touch="true"] QLineEdit, #LayersPanel[touch="true"] QComboBox {{ min-height: 34px; }}
#LayersPanel[touch="true"] QPushButton#ColorButton {{ min-height: 34px; max-height: 34px; }}
#LayersPanel[touch="true"] QPushButton#AutoPasses {{ min-height: 34px; padding: 2px 12px; }}
"""
