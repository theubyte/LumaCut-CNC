"""Eine Materialwahl wie in der Android-App (Anforderungen 2026-10-26 §9.1).

Die Hauptansicht hat genau *eine* Stelle, an der Material und Dicke gewählt
werden: eine große, touchfreundliche Liste „Material · Dicke“ mit Suche
(Muster: ``android/.../ui/MaterialScreen.kt`` und ``PiMaterials.grouped``).
Ein Tipp auf einen Eintrag setzt Leistung, Tempo, Durchgänge und Tiefen
*aller* Ebenen in einem Undo-Schritt – je Ebene mit der passenden
Operation (:func:`layer_operation`, wie ``EditorViewModel.selectMaterial``:
Gravieren → Gravur, Linie → Markieren, sonst Schneiden).

Datenquelle ist das Materials-Modul (``window.material_tools``): die
Materialdatenbank vom Pi (Abgleich beim Verbinden) mit lokalem Rückfall
(Cache bzw. mitgelieferte Datenbank) und die Einstellungs-Einträge/Presets
vom Pi. Gibt es für Material + Dicke + Operation einen Pi-Eintrag, gilt er;
sonst plant die Bibliothek (verknüpft, Dicke ändern plant neu).

Das Ebenen-Panel zeigt das Ergebnis nur noch an; Dicke/Tiefen von Hand und
der Materialwerte-Editor (Bibliotheksdialog) liegen unter „Mehr“.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from PySide6.QtCore import QObject, QSettings, QSize, Qt, Signal
from PySide6.QtWidgets import (QGroupBox, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QScroller, QSizePolicy, QVBoxLayout, QWidget)

from . import theme
from .commands import SetLayerAttrsCommand

ROW_PX = 56          # Listeneintrag (Finger)
SEARCH_PX = 44
LIST_MAX_PX = 260    # rechte Spalte bleibt auf kleinen Bildschirmen übersichtlich
SETTINGS_KEY = "material/choice"

PROCESS_LABELS = {"cut": "Schneiden", "engrave": "Gravieren", "mark": "Markieren"}

_QSS = f"""
QLineEdit#MaterialSearch {{ min-height: {SEARCH_PX}px; font-size: 15px; padding: 0 10px;
    border-radius: 8px; }}
QListWidget#MaterialList {{ font-size: 15px; border-radius: 8px; }}
QListWidget#MaterialList::item {{ padding: 6px 10px; border-bottom: 1px solid {theme.BORDER}; }}
QListWidget#MaterialList::item:selected {{ background: {theme.SURFACE_2};
    border-left: 4px solid {theme.ACCENT}; color: {theme.TEXT}; }}
QLabel#MaterialChosen {{ font-size: 15px; font-weight: bold; }}
QLabel#MaterialSource {{ color: {theme.TEXT_DIM}; font-size: 12px; }}
QLabel#MaterialSource[offline="true"] {{ color: #e8b04a; }}
"""


def fmt_mm(t: float) -> str:
    return f"{t:g}".replace(".", ",") + " mm"


@dataclass
class MaterialChoice:
    """Eine Kachel: Material + Dicke (Android ``MaterialGroup``)."""

    material_id: str
    name: str
    thickness_mm: float
    ops: tuple[str, ...] = ()                       # mögliche Bibliotheks-Operationen
    status: str = "ok"
    presets: dict[str, Any] = field(default_factory=dict)   # op → Pi-Eintrag/Preset

    @property
    def key(self) -> str:
        return f"{self.material_id}|{self.thickness_mm:g}"

    @property
    def title(self) -> str:
        return f"{self.name} · {fmt_mm(self.thickness_mm)}"

    @property
    def processes(self) -> list[str]:
        out = []
        ops = set(self.ops) | set(self.presets)
        if "cut" in ops:
            out.append(PROCESS_LABELS["cut"])
        if any(o.startswith("engrave") or o == "relief" for o in ops):
            out.append(PROCESS_LABELS["engrave"])
        return out


def material_choices(db: Any, presets: Iterable[Any] = (), query: str = "") -> list[MaterialChoice]:
    """Alle Kombinationen Material × Dicke, gefiltert nach Name oder Prozess.

    Lokale Bibliothek: je verträglichem Material seine Standarddicken. Pi-
    Einträge (Presets) ergänzen Dicken und legen Werte je Operation fest.
    """
    groups: dict[tuple[str, float], MaterialChoice] = {}
    for m in db.compatible():
        for t in m.thicknesses_mm:
            groups[(m.id, float(t))] = MaterialChoice(m.id, m.name_de, float(t),
                                                      tuple(m.operations()), m.status)
    for p in presets:
        if p.thickness_mm is None:
            continue
        k = (p.material_id, float(p.thickness_mm))
        g = groups.get(k)
        if g is None:
            try:
                m = db.material(p.material_id)
                if not m.compatible:
                    continue
                g = MaterialChoice(m.id, m.name_de, k[1], tuple(m.operations()), m.status)
            except Exception:      # Pi-Eintrag ohne Bibliotheksmaterial
                g = MaterialChoice(p.material_id, p.name, k[1])
            groups[k] = g
        g.presets.setdefault(p.op, p)
    q = query.strip().lower()
    out = [g for g in groups.values()
           if not q or q in g.name.lower() or any(q in s.lower() for s in g.processes)
           or q in fmt_mm(g.thickness_mm)]
    out.sort(key=lambda g: (g.name.lower(), g.thickness_mm))
    return out


def layer_operation(layer: Any, shapes: Iterable[Any], choice: MaterialChoice) -> str:
    """Operation für eine Ebene (Android: Gravieren/Linie → Gravur/Markieren,
    sonst Schneiden). Bilder und gefüllte Ebenen werden graviert."""
    name = (getattr(layer, "name", "") or "").lower()
    engrave = (any(getattr(s, "kind", "") == "image" for s in shapes)
               or getattr(layer, "fill_mode", "none") != "none"
               or any(w in name for w in ("grav", "bild", "foto", "linie", "mark", "engrav")))
    op = "engrave_surface" if engrave else "cut"
    avail = set(choice.ops) | set(choice.presets)
    if op not in avail:
        op = "engrave_surface" if "engrave_surface" in avail else (sorted(avail) or [op])[0]
    return op


def choice_layer_attrs(db: Any, choice: MaterialChoice, op: str, layer: Any) -> dict[str, Any]:
    """Ebenen-Attribute: Pi-Eintrag, falls vorhanden, sonst Bibliotheksplanung."""
    from lumacut_materials.link import plan_layer_attrs, preset_layer_attrs
    preset = choice.presets.get(op)
    if preset is not None:
        return preset_layer_attrs(db, preset, link=False, layer=layer)
    return plan_layer_attrs(db, choice.material_id, op, choice.thickness_mm, link=True, layer=layer)


def apply_choice(editor: Any, db: Any, choice: MaterialChoice) -> dict[str, str]:
    """Wahl auf alle Ebenen anwenden (ein Undo-Schritt). Ergebnis: Ebenen-ID → Operation."""
    doc = editor.document
    plans: list[tuple[str, str, dict]] = []
    for layer in doc.layers:
        op = layer_operation(layer, doc.shapes_in_layer(layer.id), choice)
        plans.append((layer.id, op, choice_layer_attrs(db, choice, op, layer)))
    stack = editor.undo_stack
    stack.beginMacro(f"Material: {choice.title}")
    try:
        for lid, _op, attrs in plans:
            stack.push(SetLayerAttrsCommand(doc, lid, attrs, f"Material: {choice.title}"))
    finally:
        stack.endMacro()
    return {lid: op for lid, op, _a in plans}


class MaterialPicker(QWidget):
    """Große Liste „Material · Dicke“ mit Suche, Quelle (Pi/lokal) und Auswahl."""

    chosen = Signal(str)   # key

    def __init__(self, window: Any, tools: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.window = window
        self.tools = tools
        self.setStyleSheet(_QSS)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.chosen_label = QLabel()
        self.chosen_label.setObjectName("MaterialChosen")
        self.chosen_label.setWordWrap(True)
        lay.addWidget(self.chosen_label)
        self.search = QLineEdit()
        self.search.setObjectName("MaterialSearch")
        self.search.setPlaceholderText("Material suchen (Name, Dicke, Schneiden …)")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(SEARCH_PX)
        self.search.textChanged.connect(lambda _t: self.reload())
        lay.addWidget(self.search)
        self.list = QListWidget()
        self.list.setObjectName("MaterialList")
        self.list.setMaximumHeight(LIST_MAX_PX)
        self.list.setMinimumHeight(3 * ROW_PX)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.list.setWordWrap(True)
        self.list.setAttribute(Qt.WA_AcceptTouchEvents, True)
        QScroller.grabGesture(self.list.viewport(), QScroller.TouchGesture)
        self.list.itemClicked.connect(self._item_clicked)
        self.list.itemActivated.connect(self._item_clicked)
        lay.addWidget(self.list)
        self.source = QLabel()
        self.source.setObjectName("MaterialSource")
        self.source.setWordWrap(True)
        lay.addWidget(self.source)
        self.choices: list[MaterialChoice] = []
        self.current_key: str = str(QSettings().value(SETTINGS_KEY, "") or "")
        self.last_ops: dict[str, str] = {}
        if hasattr(tools, "syncFinished"):
            tools.syncFinished.connect(lambda _r: self.reload())
        self.reload()

    # ------------------------------------------------------------ Daten
    @property
    def db(self) -> Any:
        return self.tools.db

    def presets(self) -> list[Any]:
        store = getattr(getattr(self.tools, "sync", None), "store", None)
        return list(getattr(store, "presets", []) or [])

    def choice(self, key: str) -> MaterialChoice | None:
        return next((c for c in material_choices(self.db, self.presets()) if c.key == key), None)

    def reload(self) -> None:
        self.choices = material_choices(self.db, self.presets(), self.search.text())
        self.list.blockSignals(True)
        self.list.clear()
        for c in self.choices:
            warn = "  ⚠" if c.status not in ("ok", "engrave_only") else ""
            item = QListWidgetItem(f"{c.title}{warn}\n{' · '.join(c.processes)}")
            item.setData(Qt.UserRole, c.key)
            item.setSizeHint(QSize(0, ROW_PX))
            if c.presets:
                item.setToolTip("Werte vom Pi: " + ", ".join(sorted(c.presets)))
            self.list.addItem(item)
            if c.key == self.current_key:
                item.setSelected(True)
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if not self.choices:
            self.list.addItem(QListWidgetItem("Kein Material gefunden"))
        self._show_source()
        self._show_chosen()

    def _show_source(self) -> None:
        sync = getattr(self.tools, "sync", None)
        text = sync.describe() if sync is not None and hasattr(sync, "describe") else ""
        online = sync is not None and (getattr(sync, "source", "") == "pi" or getattr(sync, "online", False))
        if not online:
            text = ("Kein Kontakt zum Pi – das ist die zuletzt gespeicherte bzw. mitgelieferte "
                    "Liste. Beim Verbinden wird sie aktualisiert.")
        self.source.setText(text)
        self.source.setProperty("offline", "false" if online else "true")
        self.source.style().unpolish(self.source)
        self.source.style().polish(self.source)

    def _show_chosen(self) -> None:
        c = self.choice(self.current_key) if self.current_key else None
        self.chosen_label.setText(f"Gewählt: {c.title}" if c else
                                  "Material und Dicke antippen – Leistung, Tempo und Durchgänge "
                                  "setzt die App danach selbst.")

    # ------------------------------------------------------------ Wählen
    def _item_clicked(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.UserRole)
        if key:
            self.select(key)

    def select(self, key: str) -> bool:
        c = self.choice(key)
        editor = getattr(self.window, "canvas", None)
        if c is None or editor is None:
            return False
        try:
            self.last_ops = apply_choice(editor, self.db, c)
        except Exception as exc:   # MaterialError, ValueError aus der Planung
            self._status(f"Material nicht anwendbar: {exc}")
            return False
        self.current_key = key
        QSettings().setValue(SETTINGS_KEY, key)
        self._show_chosen()
        procs = sorted({_op_label(o) for o in self.last_ops.values()})
        self._status(f"„{c.title}“ gewählt: {', '.join(procs)} – Werte auf alle Ebenen gesetzt")
        self.chosen.emit(key)
        return True

    def focus(self) -> None:
        """„1 Material“: Liste in den sichtbaren Bereich holen, Suche fokussieren."""
        sc = getattr(self.window, "right_scroll", None)
        if sc is not None:
            sc.ensureWidgetVisible(self, 0, 0)
        self.search.setFocus(Qt.OtherFocusReason)

    def _status(self, text: str) -> None:
        sb = getattr(self.window, "statusBar", None)
        if callable(sb):
            sb().showMessage(text, 8000)


def _op_label(op: str) -> str:
    if op == "cut":
        return "Schneiden"
    return "Gravieren"


class MaterialEditorEntry(QObject):
    """„Mehr › Materialwerte“: Bibliotheksdialog als Editor, Testzelle, Pi-Abgleich.

    Das Menü „Material“ der Menüleiste entfällt (keine zweite Materialwahl);
    die Kürzel (Strg+Umschalt+M) bleiben am Fenster.
    """

    def __init__(self, window: Any, tools: Any) -> None:
        super().__init__(window)
        self.box = QGroupBox("Materialwerte bearbeiten")
        lay = QVBoxLayout(self.box)
        hint = QLabel("Werte prüfen, eigene Presets anlegen, Testzelle übernehmen. "
                      "Gewählt wird das Material oben unter „1 Material“.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.buttons: list[QPushButton] = []
        acts = [a for a in (getattr(tools, "action", None), getattr(tools, "test_action", None),
                            getattr(tools, "pi_action", None)) if a is not None]
        for a in acts:
            b = QPushButton(a.text())
            b.setMinimumHeight(44)
            b.setToolTip(a.toolTip())
            b.setEnabled(a.isEnabled())
            a.changed.connect(lambda b=b, a=a: b.setEnabled(a.isEnabled()))
            b.clicked.connect(lambda _=False, a=a: a.trigger())
            lay.addWidget(b)
            self.buttons.append(b)
        self.editor_button = self.buttons[0] if self.buttons else None
        menu = getattr(tools, "menu", None)
        if menu is not None and hasattr(window, "menuBar"):
            window.addActions(acts)               # Kürzel wirken weiter
            window.menuBar().removeAction(menu.menuAction())
        more = getattr(window, "more_panel", None)
        if more is not None and more.layout() is not None:
            more.layout().insertWidget(1, self.box)


def install_material_picker(window: Any) -> MaterialPicker | None:
    """Nach ``install_materials`` und vor ``install_main_view`` aufrufen."""
    tools = getattr(window, "material_tools", None)
    group = getattr(window, "material_group", None)
    if tools is None or group is None:
        return None
    picker = MaterialPicker(window, tools, group)
    lay = group.layout() or QVBoxLayout(group)
    lay.addWidget(picker)
    window.material_picker = picker
    window.material_editor = MaterialEditorEntry(window, tools)
    lp = getattr(window, "layers_panel", None)
    if lp is not None and hasattr(lp, "set_material_choice_external"):
        lp.set_material_choice_external(True)
    return picker
