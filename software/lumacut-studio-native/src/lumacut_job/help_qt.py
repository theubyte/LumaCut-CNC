"""Menü „Hilfe“: Tastenkürzel-Übersicht (F1).

Die Liste wird beim Öffnen aus allen ``QAction``/``QShortcut`` des Fensters
gesammelt – neue Kürzel anderer Module erscheinen also automatisch.
"""

from __future__ import annotations

from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView, QLineEdit, QMenu, QTableWidget,
                               QTableWidgetItem, QToolBar, QVBoxLayout)

# Bedienung ohne QAction (Maus/Touch/feste Tasten), immer mit aufgeführt.
FIXED_ENTRIES = (
    ("Not-Halt (M112)", "Pause", "Maschine"),
    ("Zoomen", "Mausrad / Zwei-Finger-Pinch", "Canvas"),
    ("Ansicht verschieben", "Mittlere Maustaste / Leertaste + Ziehen", "Canvas"),
    ("Auswahl verschieben (1 mm)", "Pfeiltasten (mit Umschalt 10 mm)", "Canvas"),
    ("Polygon abschließen / letzten Punkt / abbrechen", "Eingabe / Rücktaste / Esc", "Canvas"),
)


def _clean(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&").strip()


def _area_name(obj_name: str) -> str:
    low = obj_name.lower()
    for key, label in (("canvas", "Canvas"), ("editor", "Canvas"), ("job", "Auftrag"),
                       ("material", "Material"), ("import", "Datei"), ("scan", "Scan & Probe"),
                       ("machine", "Maschine"), ("workflow", "Ablauf")):
        if key in low:
            return label
    return "Allgemein"


def _area(action, window) -> str:
    """Bereich: Menü/Werkzeugleiste, in der die Aktion steckt, sonst ihr Eltern-Widget."""
    for obj in action.associatedObjects():
        title = ""
        if isinstance(obj, QMenu):
            title = obj.title()
        elif isinstance(obj, QToolBar):
            title = obj.windowTitle()
        if title:
            return _clean(title)
    p = action.parent()
    if p is not None and p is not window:
        return _area_name(p.objectName() or type(p).__name__)
    return "Allgemein"


def collect_shortcuts(window) -> list[tuple[str, str, str]]:
    """(Aktion, Kürzel, Bereich) aller Kürzel im Fenster, sortiert und ohne Dubletten."""
    rows: dict[tuple[str, str], str] = {}
    for a in window.findChildren(QAction):
        seqs = []
        for seq in a.shortcuts():
            text = seq.toString(QKeySequence.NativeText)
            if text and text not in seqs:
                seqs.append(text)
        if not seqs or not a.text():
            continue
        rows.setdefault((_clean(a.text()), " / ".join(seqs)), _area(a, window))
    fixed_keys = {k for _, k, _ in FIXED_ENTRIES}
    for s in window.findChildren(QShortcut):
        keys = s.key().toString(QKeySequence.NativeText)
        if keys and keys not in fixed_keys and not any(k == keys for (_, k) in rows):
            rows.setdefault((s.whatsThis() or "Kürzel", keys), "Allgemein")
    for name, keys, area in FIXED_ENTRIES:
        if not any(n == name for (n, _) in rows):
            rows[(name, keys)] = area
    return sorted(((n, k, a) for (n, k), a in rows.items()), key=lambda r: (r[2], r[0].lower()))


class ShortcutDialog(QDialog):
    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tastenkürzel")
        self.resize(560, 520)
        lay = QVBoxLayout(self)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Suchen …")
        self.filter.setClearButtonEnabled(True)
        lay.addWidget(self.filter)
        self.table = QTableWidget(len(rows), 3)
        self.table.setHorizontalHeaderLabels(["Aktion", "Kürzel", "Bereich"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(text))
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        lay.addWidget(self.table)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.filter.textChanged.connect(self.apply_filter)

    def apply_filter(self, text: str) -> int:
        t = text.strip().lower()
        shown = 0
        for r in range(self.table.rowCount()):
            hit = not t or any(t in self.table.item(r, c).text().lower() for c in range(3))
            self.table.setRowHidden(r, not hit)
            shown += hit
        return shown


class HelpMenu:
    def __init__(self, window):
        self.window = window
        self.menu = window.menuBar().addMenu("&Hilfe")
        self.shortcuts_action = QAction("Tastenkürzel …", window)
        self.shortcuts_action.setShortcut(QKeySequence("F1"))
        self.shortcuts_action.triggered.connect(lambda _=False: self.show_shortcuts())
        self.menu.addAction(self.shortcuts_action)
        window.addAction(self.shortcuts_action)

    def show_shortcuts(self, modal: bool = True) -> ShortcutDialog:
        dlg = ShortcutDialog(collect_shortcuts(self.window), self.window)
        if modal:
            dlg.exec()
        return dlg


def install_help(window) -> HelpMenu:
    """Menü „Hilfe“ anhängen (zuletzt aufrufen, damit es rechts steht)."""
    h = HelpMenu(window)
    window.help_menu = h
    return h
