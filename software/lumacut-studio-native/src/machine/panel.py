"""The "Maschine" panel: connection, live status, motion, job control.

Public integration points for the main window (and other panels):
    MachinePanel.connection_changed(state, text)  – for a toolbar badge
    MachinePanel.emergency_stop()                 – toolbar / shortcut
    MachinePanel.start_job()                      – toolbar "Start Job"
    MachinePanel.set_job_file(path)               – select a G-code file
    MachinePanel.send_gcode(name, text, start)    – export from the canvas
    MachinePanel.shutdown()                       – call from closeEvent
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QProgressBar,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from . import settings as settings_store
from .client import (JOB_SUFFIXES, JOG_STEPS, LumaCutClient, MachineStatus,
                     normalize_base_url)
from .worker import CommandRunner, ConnState, StatusPoller

# Colours match the app's dark theme (main.py).
OK = "#4cd4b0"
WARN = "#f0b429"
BAD = "#f36b73"
INFO = "#6cb4ff"
MUTED = "#93a1b5"

STATE_TEXT = {
    ConnState.DISCONNECTED: ("Nicht verbunden", MUTED),
    ConnState.CONNECTING: ("Verbinde …", INFO),
    ConnState.CONNECTED: ("Verbunden", OK),
    ConnState.ERROR: ("Fehler", BAD),
    ConnState.AUTH_FAILED: ("Schlüssel abgelehnt", BAD),
}

ESTOP_STYLE = ("QPushButton { background: #d7263d; color: white; font-weight: bold;"
               " font-size: 15px; border: 2px solid #ff9b96; border-radius: 8px;"
               " padding: 10px; } QPushButton:hover { background: #ef3349; }")


def badge(label: QLabel, text: str, colour: str) -> None:
    label.setText(text)
    label.setStyleSheet(
        "QLabel { color: %s; border: 1px solid %s; border-radius: 9px;"
        " padding: 2px 8px; font-weight: bold; }" % (colour, colour))


def _mm(value: float | None) -> str:
    return "—" if value is None else "%.2f" % value


class MachinePanel(QWidget):
    connection_changed = Signal(str, str)   # ConnState, display text

    def __init__(self, parent: QWidget | None = None, *,
                 store=None, confirm: Callable[[str, str], bool] | None = None):
        super().__init__(parent)
        self._store = store
        self._confirm = confirm or self._ask
        self._settings = settings_store.load(store)
        self._client: LumaCutClient | None = None
        self._poller: StatusPoller | None = None
        self._state = ConnState.DISCONNECTED
        self._status: MachineStatus | None = None
        self._job_path: Path | None = None
        self._uploaded: str = ""
        self._runner = CommandRunner(self)
        self._runner.started.connect(self._on_command_started)
        self._runner.finished.connect(self._on_command_finished)
        self._runner.failed.connect(self._on_command_failed)
        self._runner.busy_changed.connect(lambda _b: self._update_enabled())
        self._build()
        self._apply_state(ConnState.DISCONNECTED, "Nicht verbunden")
        if self._settings.auto_connect:
            self.connect_to_pi()

    # ------------------------------------------------------------ UI
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.estop_button = QPushButton("NOT-AUS (M112)")
        self.estop_button.setObjectName("estop")
        self.estop_button.setStyleSheet(ESTOP_STYLE)
        self.estop_button.setToolTip("Software-Notstopp M112 sofort auslösen. "
                                     "Ersetzt nicht den physischen Not-Aus.")
        self.estop_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.estop_button.clicked.connect(self.emergency_stop)
        root.addWidget(self.estop_button)

        # Connection
        conn = QGroupBox("Verbindung (Pi 400)")
        form = QFormLayout(conn)
        self.url_edit = QLineEdit(self._settings.base_url)
        self.url_edit.setPlaceholderText("http://lumacut.local:8080")
        form.addRow("Adresse", self.url_edit)
        self.key_edit = QLineEdit(self._settings.api_key)
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("X-LumaCut-Key (optional)")
        form.addRow("Schlüssel", self.key_edit)
        self.auto_check = QCheckBox("Beim Start verbinden")
        self.auto_check.setChecked(self._settings.auto_connect)
        form.addRow("", self.auto_check)
        row = QHBoxLayout()
        self.connect_button = QPushButton("Verbinden")
        self.connect_button.setObjectName("primary")
        self.connect_button.clicked.connect(self._toggle_connection)
        self.conn_badge = QLabel()
        row.addWidget(self.connect_button)
        row.addWidget(self.conn_badge)
        row.addStretch()
        form.addRow(row)
        root.addWidget(conn)

        # Status
        status = QGroupBox("Status")
        grid = QFormLayout(status)
        self.skr_label = QLabel("—")
        self.pos_label = QLabel("X: —   Y: —   Z: —")
        self.pos_label.setStyleSheet("font-family: monospace; font-size: 14px;")
        self.homed_label = QLabel("—")
        self.laser_label = QLabel("—")
        self.owner_label = QLabel("—")
        self.focus_label = QLabel("—")
        self.error_label = QLabel("—")
        self.error_label.setWordWrap(True)
        self.error_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        grid.addRow("SKR", self.skr_label)
        grid.addRow("Position", self.pos_label)
        grid.addRow("Homed", self.homed_label)
        grid.addRow("Laser", self.laser_label)
        grid.addRow("Steuerung", self.owner_label)
        grid.addRow("Werkstück/Fokus Z", self.focus_label)
        grid.addRow("Letzte Meldung", self.error_label)
        root.addWidget(status)

        # Motion
        motion = QGroupBox("Bewegung")
        mv = QVBoxLayout(motion)
        buttons = QGridLayout()
        self.home_button = QPushButton("Home")
        self.home_button.setToolTip("X/Y zuerst, dann Z, dann Z-Rückzug")
        self.park_button = QPushButton("Park")
        self.park_button.setToolTip("Laser aus, Z hoch, X0/Y0")
        self.focus_button = QPushButton("Fokus (G30)")
        self.focus_button.setToolTip("Werkstück unter der Laserposition abtasten; "
                                     "der Pi fährt vor dem ersten Schnitt auf Fokushöhe")
        self.reset_button = QPushButton("Notstopp quittieren")
        self.reset_button.setToolTip("Erst nach SKR-Reset / kurz stromlos")
        self.home_button.clicked.connect(self.home)
        self.park_button.clicked.connect(self.park)
        self.focus_button.clicked.connect(self.focus)
        self.reset_button.clicked.connect(self.reset_emergency)
        buttons.addWidget(self.home_button, 0, 0)
        buttons.addWidget(self.park_button, 0, 1)
        buttons.addWidget(self.focus_button, 1, 0)
        buttons.addWidget(self.reset_button, 1, 1)
        mv.addLayout(buttons)

        step_row = QHBoxLayout()
        step_row.addWidget(QLabel("Schritt"))
        self.step_combo = QComboBox()
        for step in JOG_STEPS:
            self.step_combo.addItem(("%g mm" % step).replace(".", ","), step)
        self.step_combo.setCurrentIndex(1)
        step_row.addWidget(self.step_combo)
        step_row.addStretch()
        mv.addLayout(step_row)
        jog = QGridLayout()
        self.jog_buttons: list[QPushButton] = []
        layout = [("Y", 1, 0, 1), ("X", -1, 1, 0), ("X", 1, 1, 2),
                  ("Y", -1, 2, 1), ("Z", 1, 0, 3), ("Z", -1, 2, 3)]
        for axis, direction, r, c in layout:
            b = QPushButton("%s %s" % (axis, "+" if direction > 0 else "−"))
            b.setProperty("axis", axis)
            b.setProperty("direction", direction)
            b.clicked.connect(lambda _=False, a=axis, d=direction: self.jog(a, d))
            jog.addWidget(b, r, c)
            self.jog_buttons.append(b)
        mv.addLayout(jog)
        root.addWidget(motion)

        # Job
        job = QGroupBox("Auftrag")
        jl = QVBoxLayout(job)
        file_row = QHBoxLayout()
        self.file_label = QLabel("Keine Datei")
        self.file_label.setStyleSheet("color: %s;" % MUTED)
        self.file_label.setWordWrap(True)
        self.choose_button = QPushButton("Datei …")
        self.choose_button.clicked.connect(self._choose_file)
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(self.choose_button)
        jl.addLayout(file_row)
        jb = QGridLayout()
        self.send_button = QPushButton("Senden")
        self.start_button = QPushButton("Starten")
        self.start_button.setObjectName("primary")
        self.autorun_button = QPushButton("Ein-Klick")
        self.autorun_button.setToolTip("Home → Abtasten unter Motivmitte → Fokus → Auftrag → Park")
        self.abort_button = QPushButton("Abbrechen")
        self.send_button.clicked.connect(self.send_job)
        self.start_button.clicked.connect(self.start_job)
        self.autorun_button.clicked.connect(self.autorun_job)
        self.abort_button.clicked.connect(self.abort_job)
        jb.addWidget(self.send_button, 0, 0)
        jb.addWidget(self.start_button, 0, 1)
        jb.addWidget(self.autorun_button, 1, 0)
        jb.addWidget(self.abort_button, 1, 1)
        jl.addLayout(jb)
        self.job_label = QLabel("Kein Auftrag")
        self.job_label.setWordWrap(True)
        self.job_progress = QProgressBar()
        self.job_progress.setRange(0, 1000)
        self.job_progress.setValue(0)
        self.job_progress.setFormat("—")
        jl.addWidget(self.job_label)
        jl.addWidget(self.job_progress)
        root.addWidget(job)
        root.addStretch()

        self._control_buttons = [self.home_button, self.park_button,
                                 self.focus_button, self.reset_button,
                                 *self.jog_buttons, self.send_button,
                                 self.start_button, self.autorun_button,
                                 self.abort_button]

    # ------------------------------------------------------ connection
    def _current_settings(self) -> settings_store.ConnectionSettings:
        return settings_store.ConnectionSettings(
            base_url=normalize_base_url(self.url_edit.text()),
            api_key=self.key_edit.text().strip(),
            poll_ms=self._settings.poll_ms,
            auto_connect=self.auto_check.isChecked())

    @Slot()
    def _toggle_connection(self) -> None:
        if self._poller is None:
            self.connect_to_pi()
        else:
            self.disconnect_from_pi()

    def connect_to_pi(self) -> None:
        self.disconnect_from_pi()
        try:
            new = self._current_settings()
        except ValueError as exc:
            self._apply_state(ConnState.ERROR, str(exc))
            return
        self._settings = new
        settings_store.save(new, self._store)
        self.url_edit.setText(new.base_url)
        self._client = LumaCutClient(new.base_url, new.api_key)
        self._poller = StatusPoller(self._client, new.poll_ms)
        self._poller.state_changed.connect(self._apply_state)
        self._poller.status_received.connect(self._apply_status)
        self._poller.start()

    def disconnect_from_pi(self) -> None:
        poller, self._poller = self._poller, None
        if poller is not None:
            poller.state_changed.disconnect(self._apply_state)
            poller.status_received.disconnect(self._apply_status)
            poller.stop()
            poller.deleteLater()
        self._status = None
        self._apply_state(ConnState.DISCONNECTED, "Getrennt")

    def shutdown(self) -> None:
        """Stop polling and wait briefly for running requests. Idempotent."""
        if getattr(self, "_shut_down", False):
            return
        self._shut_down = True
        self.disconnect_from_pi()
        self._runner.wait(2000)

    @property
    def connection_state(self) -> str:
        return self._state

    @Slot(str, str)
    def _apply_state(self, state: str, message: str) -> None:
        self._state = state
        text, colour = STATE_TEXT.get(state, (state, MUTED))
        badge(self.conn_badge, text, colour)
        self.connect_button.setText("Trennen" if self._poller else "Verbinden")
        self.url_edit.setEnabled(self._poller is None)
        self.key_edit.setEnabled(self._poller is None)
        if state in (ConnState.ERROR, ConnState.AUTH_FAILED):
            self._show_message(message, BAD)
        elif state == ConnState.DISCONNECTED:
            self._clear_status()
        self._update_enabled()
        self.connection_changed.emit(state, "%s · %s" % (text, message) if message else text)

    def _clear_status(self) -> None:
        self.skr_label.setText("—")
        self.skr_label.setStyleSheet("")
        self.pos_label.setText("X: —   Y: —   Z: —")
        for label in (self.homed_label, self.laser_label, self.owner_label,
                      self.focus_label):
            label.setText("—")
            label.setStyleSheet("")

    @Slot(object)
    def _apply_status(self, status: MachineStatus) -> None:
        self._status = status
        if status.emergency_latched:
            badge(self.skr_label, "NOTSTOPP VERRIEGELT", BAD)
        elif status.skr_connected:
            badge(self.skr_label, "USB OK · %s" % (status.state or "—"), OK)
        else:
            badge(self.skr_label, "SKR nicht verbunden", WARN)
        if status.position:
            x, y, z = status.position
            self.pos_label.setText("X: %7.2f   Y: %7.2f   Z: %6.2f" % (x, y, z))
        else:
            self.pos_label.setText("X: —   Y: —   Z: —")
        if status.homed:
            badge(self.homed_label, "Ja", OK)
        elif not status.homing_verified:
            badge(self.homed_label, "Nein · Mechanik nicht freigegeben", WARN)
        else:
            badge(self.homed_label, "Nein", WARN)
        if status.laser_armed:
            badge(self.laser_label, "AKTIV", BAD)
        else:
            badge(self.laser_label, "Aus" + (" · Lüfter nachlaufend"
                                             if status.laser_fan_on else ""), OK)
        free = status.owner in ("Frei", "")
        badge(self.owner_label, "Frei" if free else "Belegt: " + status.owner,
              OK if free else WARN)
        self.focus_label.setText("%s / %s mm" % (_mm(status.workpiece_surface_z),
                                                  _mm(status.laser_focus_z))
                                 if status.workpiece_surface_z is not None
                                 else "Nicht abgetastet")
        if status.fault:
            self._show_message(status.fault, BAD if status.emergency_latched else WARN)
        self._apply_job(status)
        self._update_enabled()

    def _apply_job(self, status: MachineStatus) -> None:
        job = status.job
        names = {"idle": "Bereit", "homing": "Referenzfahrt", "probing": "Abtasten",
                 "running": "Läuft", "complete": "Fertig", "aborted": "Abgebrochen",
                 "error": "Fehler"}
        text = names.get(job.state, job.state)
        if job.file:
            text += " · " + job.file
        if job.error:
            text += " · " + job.error
        colour = {"error": BAD, "aborted": WARN, "complete": OK}.get(
            job.state, INFO if job.active else MUTED)
        self.job_label.setText(text)
        self.job_label.setStyleSheet("color: %s;" % colour)
        progress = job.progress
        if progress is None:
            self.job_progress.setValue(0)
            self.job_progress.setFormat("—")
        else:
            self.job_progress.setValue(int(progress * 1000))
            self.job_progress.setFormat("%d / %d Zeilen (%.0f %%)" % (
                job.line, job.total, progress * 100))

    def _show_message(self, text: str, colour: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.error_label.setText("%s  %s" % (stamp, text))
        self.error_label.setStyleSheet("color: %s;" % colour)

    def _update_enabled(self) -> None:
        connected = self._state == ConnState.CONNECTED and self._client is not None
        idle = connected and not self._runner.busy
        s = self._status
        job_active = bool(s and s.job.active)
        for b in self._control_buttons:
            b.setEnabled(idle)
        if idle and s is not None:
            self.reset_button.setEnabled(s.emergency_latched)
            self.abort_button.setEnabled(job_active)
            for b in (self.home_button, self.park_button, self.focus_button,
                      self.start_button, self.autorun_button, *self.jog_buttons):
                b.setEnabled(not job_active and not s.emergency_latched)
            for b in (self.park_button, self.focus_button, *self.jog_buttons):
                b.setEnabled(b.isEnabled() and s.homed)
        if not self._job_path:
            self.send_button.setEnabled(False)
        if not self._uploaded:
            self.start_button.setEnabled(False)
            self.autorun_button.setEnabled(False)
        # The emergency stop is never disabled.
        self.estop_button.setEnabled(True)

    # ------------------------------------------------------- commands
    def _run(self, label: str, fn: Callable[[], str]) -> bool:
        if self._client is None or self._state != ConnState.CONNECTED:
            self._show_message("Nicht mit dem Pi verbunden", WARN)
            return False
        if not self._runner.run(label, fn):
            self._show_message("Es läuft noch ein Befehl", WARN)
            return False
        return True

    @Slot(str)
    def _on_command_started(self, label: str) -> None:
        self._show_message(label + " …", INFO)

    @Slot(str, str)
    def _on_command_finished(self, label: str, message: str) -> None:
        self._show_message("%s: %s" % (label, message), OK)
        if self._poller:
            self._poller.poll_now()

    @Slot(str, str, str)
    def _on_command_failed(self, label: str, kind: str, message: str) -> None:
        self._show_message("%s fehlgeschlagen: %s" % (label, message), BAD)
        if kind == ConnState.AUTH_FAILED:
            self._apply_state(ConnState.AUTH_FAILED, message)
        if self._poller:
            self._poller.poll_now()

    @Slot()
    def emergency_stop(self) -> None:
        """Always dispatched, even while another command is running."""
        client = self._client
        if client is None:
            try:
                s = self._current_settings()
                client = LumaCutClient(s.base_url, s.api_key)
            except ValueError as exc:
                self._show_message("NOT-AUS nicht gesendet: %s – physischen Not-Aus "
                                   "benutzen" % exc, BAD)
                return
        self._runner.run_urgent("NOT-AUS", client.emergency_stop)

    @Slot()
    def home(self) -> None:
        if self._client:
            self._run("Home", self._client.home)

    @Slot()
    def park(self) -> None:
        if self._client:
            self._run("Park", self._client.park)

    @Slot()
    def focus(self) -> None:
        if self._client:
            self._run("Fokus (G30)", self._client.focus)

    @Slot()
    def reset_emergency(self) -> None:
        if self._client:
            self._run("Notstopp quittieren", self._client.reset_emergency)

    def jog(self, axis: str, direction: int) -> None:
        if self._client is None:
            return
        step = float(self.step_combo.currentData())
        distance = step * (1 if direction > 0 else -1)
        client = self._client
        self._run("Jog %s %+g mm" % (axis, distance),
                  lambda: client.jog(axis, distance))

    # ------------------------------------------------------------ jobs
    @Slot()
    def _choose_file(self) -> None:
        pattern = "G-Code (%s)" % " ".join("*" + s for s in JOB_SUFFIXES)
        path, _ = QFileDialog.getOpenFileName(self, "G-Code wählen", "", pattern)
        if path:
            self.set_job_file(path)

    def set_job_file(self, path: str | Path) -> None:
        self._job_path = Path(path)
        self._uploaded = ""
        self.file_label.setText(self._job_path.name)
        self.file_label.setStyleSheet("")
        self._update_enabled()

    @Slot()
    def send_job(self) -> None:
        if self._client is None or self._job_path is None:
            return
        client, path = self._client, self._job_path

        def task() -> str:
            name, message = client.upload_job_file(path)
            self._uploaded = name
            return message
        self._run("Senden", task)

    def send_gcode(self, name: str, gcode: str, start: bool = False) -> None:
        """Upload generated G-code (e.g. from the canvas) and optionally start."""
        if self._client is None:
            self._show_message("Nicht mit dem Pi verbunden", WARN)
            return
        client = self._client

        def task() -> str:
            message = client.upload_job(name, gcode)
            self._uploaded = name
            if start:
                message = client.start_job(name)
            return message
        self.file_label.setText(name)
        self._run("Senden & Starten" if start else "Senden", task)

    @Slot()
    def start_job(self) -> None:
        if self._client is None or not self._uploaded:
            self._show_message("Zuerst einen Auftrag senden", WARN)
            return
        if not self._confirm("Auftrag starten",
                             "Auftrag %s starten? Bereich frei, Material eingelegt, "
                             "Schutzbrille?" % self._uploaded):
            return
        client, name = self._client, self._uploaded
        self._run("Start", lambda: client.start_job(name))

    @Slot()
    def autorun_job(self) -> None:
        if self._client is None or not self._uploaded:
            return
        if not self._confirm("Ein-Klick-Start",
                             "Maschine fährt Homing, tastet unter der Motivmitte ab "
                             "und lasert %s. Bereich frei und Material eingelegt?"
                             % self._uploaded):
            return
        client, name = self._client, self._uploaded
        self._run("Ein-Klick", lambda: client.autorun_job(name))

    @Slot()
    def abort_job(self) -> None:
        if self._client:
            self._run("Abbrechen", self._client.abort_job)

    def _ask(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text) == QMessageBox.Yes
