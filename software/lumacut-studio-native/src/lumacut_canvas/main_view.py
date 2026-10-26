"""Aufgeräumte Hauptansicht: drei große Aktionen Material · Design · Start,
optionaler Kamera-Scan und alle erweiterten Optionen hinter „Mehr“.

Siehe docs/ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md (§1, §3, §5).

- **Material**: öffnet die Materialbibliothek; die schnelle Wahl (Material,
  Dicke) bleibt direkt darunter sichtbar (Gruppe „Material“, belegt vom
  Materials-Modul).
- **Design**: Menü zum Hinzufügen (Importieren, Text, Formen).
- **Start**: Ein-Klick-Auftrag ``window.one_click.start`` (Scan Probe,
  ``scanprobe.job_flow_qt.OneClickController``): Bestätigung → Referenzfahrt →
  Höhenmesh → Fokus → Lasern → Parken. Während des Ablaufs wird „Start“ zu
  „Abbrechen“. Siehe :data:`START_HOOK`.
- **Kamera-Scan**: optional, ruft ``ScanPanel.start_scan`` auf; kein Pflicht-
  Schritt im Auftrag. Das ist *der* Kamera-Scan-Knopf; der gleichnamige im
  Scan-Panel kann entfallen (Scan-Probe-Agent).
- **Mehr**: blendet Ablauf, Scan & Probe, Maschine (Verbinden, Joggen,
  Homing, Abtasten …), die Werkzeugleiste „Auftrag“ (Kerf/Haltestege/Anfahrt,
  Rahmen, Schätzung, Materialtest …) und die Ebenen-Feineinstellungen
  (Leistung, Geschwindigkeit, Füllung) ein. Standard: zu.

Alles nur über öffentliche Methoden/Signale der anderen Panels; dieses Modul
ändert keine Machine-/Scan-Dateien.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QGridLayout, QLabel, QMenu, QPushButton, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from . import theme

BIG_BUTTON_PX = 56
SMALL_BUTTON_PX = 48

#: HOOK: „Start“ ruft den Ein-Klick-Ablauf des Scan-Probe-Agents
#: (``window.one_click.start``, Anforderungen 2026-10-26 §1.1: Referenzfahrt
#: falls nötig → Höhenmesh immer → Fokus → Job → Parken; Bestätigung, Fehler-
#: und Abbruchmeldungen kommen vom Controller). Nur wenn der Controller fehlt
#: (Studio ohne scanprobe), fällt „Start“ auf ``START_FALLBACK`` zurück:
#: hochladen + ``MachinePanel.autorun_job`` (Pi ``op=autorun``, ein Punkt).
START_HOOK = "one_click.start"
START_FALLBACK = "machine_panel.autorun_job"
START_TEXT = "3  Start"
CANCEL_TEXT = "■  Abbrechen"

_BIG_QSS = f"""
QPushButton#MainAction {{
    min-height: {BIG_BUTTON_PX}px; font-size: 17px; font-weight: bold; text-align: left;
    padding: 6px 14px; border-radius: 10px; background: {theme.SURFACE_2};
    border: 1px solid {theme.BORDER};
}}
QPushButton#MainAction:hover {{ border-color: {theme.BORDER_HOVER}; }}
QPushButton#MainActionStart {{
    min-height: {BIG_BUTTON_PX}px; font-size: 18px; font-weight: bold; text-align: left;
    padding: 6px 14px; border-radius: 10px; border: none;
    background: {theme.ACCENT}; color: {theme.ACCENT_TEXT};
}}
QPushButton#MainActionStart:disabled {{ background: #2a4a43; color: #6f8a83; }}
QPushButton#SecondaryAction, QToolButton#MoreToggle {{
    min-height: {SMALL_BUTTON_PX}px; font-size: 15px; padding: 4px 12px; border-radius: 8px;
    background: {theme.SURFACE}; border: 1px solid {theme.BORDER};
}}
QToolButton#MoreToggle:checked {{ border-color: {theme.ACCENT}; }}
QLabel#MainHint {{ color: {theme.TEXT_DIM}; font-size: 13px; }}
"""


class MainActions(QWidget):
    """Kopf der rechten Spalte: Material, Design, Start, Kamera-Scan, Verbinden."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MainActions")
        self.setStyleSheet(_BIG_QSS)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        def big(text: str, tip: str, name: str = "MainAction") -> QPushButton:
            b = QPushButton(text)
            b.setObjectName(name)
            b.setToolTip(tip)
            b.setMinimumHeight(BIG_BUTTON_PX)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            lay.addWidget(b)
            return b

        self.material_button = big("1  Material", "Material und Dicke wählen – Leistung, Tempo und "
                                   "Durchgänge kommen aus der Materialbibliothek")
        self.design_button = big("2  Design", "Motiv hinzufügen: Datei importieren, Text oder Form zeichnen")
        self.start_button = big(START_TEXT, "Auftrag starten: Referenzfahrt, Höhenmesh, Fokus, "
                                "Lasern, Parken – alles automatisch", "MainActionStart")
        self.hint = QLabel("Material wählen, Motiv platzieren, Start drücken.")
        self.hint.setObjectName("MainHint")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

        row = QGridLayout()
        row.setSpacing(8)
        self.scan_button = QPushButton("Kamera-Scan")
        self.scan_button.setObjectName("SecondaryAction")
        self.scan_button.setMinimumHeight(SMALL_BUTTON_PX)
        self.scan_button.setToolTip("Optional: Arbeitsfläche mit der Kamera aufnehmen und als "
                                    "Hintergrund zum genauen Platzieren zeigen")
        self.connect_button = QPushButton("Verbinden")
        self.connect_button.setObjectName("SecondaryAction")
        self.connect_button.setMinimumHeight(SMALL_BUTTON_PX)
        self.connect_button.setToolTip("Mit der Maschine (Pi) verbinden – Adresse unter „Mehr › Maschine“")
        row.addWidget(self.scan_button, 0, 0)
        row.addWidget(self.connect_button, 0, 1)
        lay.addLayout(row)


class MoreToggle(QToolButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MoreToggle")
        self.setStyleSheet(_BIG_QSS)
        self.setCheckable(True)
        self.setMinimumHeight(SMALL_BUTTON_PX)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.setToolTip("Erweiterte Optionen: Ablauf, Kamera & Abtasten, Maschine, Schnittoptionen "
                        "(Kerf, Haltestege, Anfahrt), Füllung und Ebenen-Feineinstellungen")
        self.toggled.connect(self._label)
        self._label(False)

    def _label(self, on: bool) -> None:
        self.setText("Mehr ▾" if on else "Mehr ▸")


class OneClickStart(QObject):
    """Start-Knopf → ``window.one_click`` (Ein-Klick-Auftrag, siehe START_HOOK).

    Zustände: bereit → (Bestätigung im Controller) → läuft (Knopf = Abbrechen)
    → fertig / abgebrochen / Fehler (Meldung in der Statusleiste, Fehlerdialog
    vom Controller) → bereit.
    """

    message = Signal(str)
    running_changed = Signal(bool)

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window
        self.pending: str | None = None
        mp = getattr(window, "machine_panel", None)
        if mp is not None and hasattr(mp, "command_finished"):
            mp.command_finished.connect(self._finished)
        ctrl = self.controller
        if ctrl is not None and hasattr(ctrl, "finished"):
            ctrl.finished.connect(self._flow_done)

    @property
    def controller(self) -> Any:
        return getattr(self.window, "one_click", None)

    @property
    def running(self) -> bool:
        ctrl = self.controller
        return bool(ctrl is not None and getattr(ctrl, "busy", False))

    def clicked(self) -> bool:
        """Start, oder während des Ablaufs: Abbrechen."""
        if self.running:
            return self.cancel()
        return self.start()

    def cancel(self) -> bool:
        ctrl = self.controller
        if ctrl is None or not self.running:
            return False
        ctrl.cancel()
        self.message.emit("Abbruch angefordert – der Kopf wird sicher angehalten und geparkt.")
        return True

    def start(self) -> bool:
        w = self.window
        mp = getattr(w, "machine_panel", None)
        if mp is None or getattr(mp, "connection_state", "") != "connected":
            self.message.emit("Nicht mit der Maschine verbunden – „Verbinden“ drücken "
                              "(Adresse unter „Mehr › Maschine“).")
            return False
        if self.pending is not None or getattr(mp, "command_running", "") or self.running:
            self.message.emit("Die Maschine ist noch beschäftigt – bitte kurz warten.")
            return False
        ctrl = self.controller
        if ctrl is not None:
            ok = bool(ctrl.start())  # Bestätigung, Prüfungen, Fehlermeldung: Controller
            if ok:
                self.running_changed.emit(True)
            elif getattr(ctrl, "last_message", ""):
                self.message.emit(ctrl.last_message)
            return ok
        job = w._build_canvas_job()
        if job is None:
            return False
        name, gcode, _note = job
        self.pending = name
        mp.send_gcode(name, gcode, start=False)
        if self.pending is not None and getattr(mp, "command_running", "") != "Senden":
            # Nicht losgeschickt (z. B. Befehl läuft) oder schon fertig und gemeldet.
            self.pending = None
            return False
        self.message.emit(f"Übertrage {name} …")
        return True

    def _finished(self, label: str, ok: bool) -> None:
        if self.pending is None or label != "Senden":
            return
        name, self.pending = self.pending, None
        if not ok:
            self.message.emit(f"Übertragen von {name} fehlgeschlagen – siehe „Mehr › Maschine“.")
            return
        self._run_machine()

    def _run_machine(self) -> None:
        # Nur ohne Ein-Klick-Controller (START_FALLBACK): Pi op=autorun.
        self.window.machine_panel.autorun_job()

    def _flow_done(self, res: Any) -> None:
        self.running_changed.emit(False)
        ctrl = self.controller
        text = getattr(ctrl, "last_message", "")
        if text:
            self.message.emit(text)


class MainView(QObject):
    """Verdrahtet :class:`MainActions` und „Mehr“ mit den Panels des Fensters."""

    def __init__(self, window: Any, actions: MainActions, more_toggle: MoreToggle,
                 more_panel: QWidget) -> None:
        super().__init__(window)
        self.window = window
        self.actions = actions
        self.more_toggle = more_toggle
        self.more_panel = more_panel
        self.starter = OneClickStart(window)
        self.starter.message.connect(self._status)

        actions.material_button.clicked.connect(self.open_material)
        self.design_menu = self._build_design_menu()
        actions.design_button.clicked.connect(self._show_design_menu)
        actions.start_button.clicked.connect(self.starter.clicked)
        self.starter.running_changed.connect(self._sync_start)
        actions.scan_button.clicked.connect(self.camera_scan)
        actions.connect_button.clicked.connect(self.connect_machine)
        mp = getattr(window, "machine_panel", None)
        if mp is not None and hasattr(mp, "connection_changed"):
            mp.connection_changed.connect(lambda state, _t: self._sync_connection(state))
            self._sync_connection(getattr(mp, "connection_state", ""))

        # Werkzeugleiste „Auftrag“ (Review-Agent): erweitert → hinter „Mehr“.
        # Ihre Aktionen bleiben über das Menü „Auftrag“ und Tastenkürzel erreichbar.
        jt = getattr(window, "job_tools", None)
        self.job_toolbar = getattr(jt, "toolbar", None)
        if self.job_toolbar is not None:
            acts = [a for a in self.job_toolbar.actions() if not a.isSeparator()]
            window.addActions(acts)  # Kürzel wirken auch bei versteckter Leiste
            menu = window.menuBar().addMenu("&Auftrag")
            menu.addActions(acts)
            self.job_menu = menu
        more_toggle.toggled.connect(self.set_more)
        self.set_more(False)

    # ------------------------------------------------------------ Mehr
    def set_more(self, on: bool) -> None:
        if self.more_toggle.isChecked() != on:
            self.more_toggle.setChecked(on)  # ruft set_more erneut
            return
        self.more_panel.setVisible(on)
        if self.job_toolbar is not None:
            self.job_toolbar.setVisible(on)
        lp = getattr(self.window, "layers_panel", None)
        if lp is not None and hasattr(lp, "set_advanced_visible"):
            lp.set_advanced_visible(on)

    @property
    def more_open(self) -> bool:
        return self.more_toggle.isChecked()

    # ------------------------------------------------------------ Aktionen
    def open_material(self) -> None:
        tools = getattr(self.window, "material_tools", None)
        if tools is not None:
            tools.open()
        else:
            self._status("Materialbibliothek nicht verfügbar")

    def _build_design_menu(self) -> QMenu:
        menu = QMenu(self.actions.design_button)
        imp = getattr(getattr(self.window, "import_tools", None), "import_action", None)
        if imp is not None:
            menu.addAction(imp)
            menu.addSeparator()
        ed = self.window.canvas
        from .tools import Tool
        for t in (Tool.TEXT, Tool.RECT, Tool.ELLIPSE, Tool.POLYGON, Tool.FREEHAND, Tool.LINE):
            a = ed.actions_by_name.get(f"tool_{t.value}")
            if a is not None:
                menu.addAction(a)
        return menu

    def _show_design_menu(self) -> None:
        b = self.actions.design_button
        self.design_menu.popup(b.mapToGlobal(b.rect().bottomLeft()))

    def camera_scan(self) -> bool:
        """Optionaler Kamera-Scan (ScanPanel.start_scan); ändert den Auftrag nicht."""
        sp = getattr(self.window, "scan_panel", None)
        if sp is None or not hasattr(sp, "start_scan"):
            self._status("Kamera-Scan nicht verfügbar")
            return False
        ok = bool(sp.start_scan())
        self._status("Kamera-Scan läuft …" if ok else
                     "Kamera-Scan nicht möglich – " + (getattr(sp, "last_error", "") or "siehe „Mehr › Scan“"))
        return ok

    def connect_machine(self) -> None:
        mp = getattr(self.window, "machine_panel", None)
        if mp is not None:
            mp.connect_to_pi()

    def _sync_start(self, running: bool) -> None:
        b = self.actions.start_button
        b.setText(CANCEL_TEXT if running else START_TEXT)
        b.setToolTip("Laufenden Auftrag abbrechen (Kopf wird geparkt)" if running else
                     "Auftrag starten: Referenzfahrt, Höhenmesh, Fokus, Lasern, Parken – "
                     "alles automatisch")

    def _sync_connection(self, state: str) -> None:
        self.actions.connect_button.setVisible(state != "connected")

    def _status(self, text: str) -> None:
        sb = self.window.statusBar() if hasattr(self.window, "statusBar") else None
        if sb is not None:
            sb.showMessage(text, 8000)


def install_main_view(window: Any) -> MainView:
    """Nach allen anderen ``install_*`` (Materials, Import, Job-Tools) aufrufen."""
    view = MainView(window, window.main_actions, window.more_toggle, window.more_panel)
    window.main_view = view
    return view
