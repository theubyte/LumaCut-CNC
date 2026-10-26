"""The "Maschine" panel: connection, live status, motion, job control.

Public integration points for the main window (and other panels):
    MachinePanel.connection_changed(state, text)  – for a toolbar badge
    MachinePanel.emergency_stop()                 – toolbar / shortcut
    MachinePanel.start_job()                      – toolbar "Start Job"
    MachinePanel.set_job_file(path)               – select a G-code file
    MachinePanel.send_gcode(name, text, start)    – export from the canvas
    MachinePanel.frame_gcode(text, mode)          – laser-off outline (op=frame)
    MachinePanel.set_frame_provider(fn)           – mode -> frame G-code for the button
    MachinePanel.frame_available_changed(bool)    – frame shortcuts enabled state
    MachinePanel.set_user_origin(x, y)            – user origin from the camera scan
    MachinePanel.set_job_origin(origin, anchor)   – preset the start origin (#16)
    MachinePanel.shutdown()                       – call from closeEvent
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QProgressBar,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from . import settings as settings_store
from .client import (ANCHORS, FRAME_MODES, JOB_SUFFIXES, JOG_STEPS, ORIGIN_MODES,
                     TRANSIENT_OWNERS, ApiError, LumaCutClient,
                     MachineStatus, normalize_base_url)
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

#: Status older than this is shown as stale and motion controls are locked.
STALE_AFTER_S = 3.0
ESTOP_LABEL = "NOT-AUS"
FRAME_LABELS = {"box": "Rechteck", "hull": "Gummiband"}
ORIGIN_LABELS = {"absolute": "Absolut", "current": "Aktuelle Position",
                 "user": "Benutzer-Ursprung"}
ANCHOR_LABELS = {"tl": "Oben links", "tr": "Oben rechts", "bl": "Unten links",
                 "br": "Unten rechts", "center": "Mitte"}
OLD_PI_ORIGIN = "Pi-Dienst zu alt: nur absolute Aufträge – Pi aktualisieren"

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
    frame_available_changed = Signal(bool)  # a frame run may be requested now
    status_changed = Signal(object)         # MachineStatus after each poll (workflow panel)
    command_finished = Signal(str, bool)    # label, success (workflow panel)

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
        self._status_at: float | None = None     # monotonic time of last status
        self._stale = False
        self._job_path: Path | None = None
        self._uploaded: str = ""
        # Bumped by every upload and file choice: a late worker result of
        # an older upload must not mark a file as ready to start.
        self._upload_gen = 0
        # Label of an operation another module (scan/probe) runs with this
        # panel's client outside the CommandRunner ("" = none).
        self._external = ""
        self._frame_provider: Callable[[str], str] | None = None
        self._frame_available = False
        self._last_frame_state = ""
        self._runner = CommandRunner(self)
        self._runner.started.connect(self._on_command_started)
        self._runner.finished.connect(self._on_command_finished)
        self._runner.failed.connect(self._on_command_failed)
        self._runner.busy_changed.connect(self._on_busy_changed)
        self._build()
        # Stale-data watchdog runs in the GUI thread, so it still fires when
        # the poll thread is stuck in a request.
        self._stale_timer = QTimer(self)
        self._stale_timer.setInterval(500)
        self._stale_timer.timeout.connect(self._check_stale)
        self._stale_timer.start()
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
        self.estop_label = QLabel("")
        self.estop_label.setWordWrap(True)
        self.estop_label.setVisible(False)
        root.addWidget(self.estop_label)

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
        frame_row = QHBoxLayout()
        self.frame_button = QPushButton("Rahmen")
        self.frame_button.setToolTip(
            "Umriss des Designs mit ausgeschaltetem Laser abfahren (Strg+Umschalt+F / "
            "Alt+Umschalt+F). Der gesendete Auftrag bleibt geladen.")
        self.frame_button.clicked.connect(lambda _=False: self.frame())
        self.frame_mode_combo = QComboBox()
        for mode in FRAME_MODES:
            self.frame_mode_combo.addItem(FRAME_LABELS[mode], mode)
        self.frame_mode_combo.setToolTip("Rechteck = Begrenzungsrahmen, "
                                         "Gummiband = konvexe Hülle")
        frame_row.addWidget(self.frame_button, 1)
        frame_row.addWidget(self.frame_mode_combo)
        jl.addLayout(frame_row)
        # Job origin (#16): where the motif runs. Absolute = as drawn.
        self.origin_combo = QComboBox()
        for mode in ORIGIN_MODES:
            self.origin_combo.addItem(ORIGIN_LABELS[mode], mode)
        self.origin_combo.setToolTip(
            "Absolut = wie gezeichnet; Aktuelle Position = Bezugspunkt auf den Kopf; "
            "Benutzer-Ursprung = Bezugspunkt auf den gespeicherten Ursprung")
        self.anchor_combo = QComboBox()
        for anchor in ANCHORS:
            self.anchor_combo.addItem(ANCHOR_LABELS[anchor], anchor)
        self.anchor_combo.setToolTip("Welcher Punkt des Motivs auf dem Ursprung liegt")
        self.origin_set_button = QPushButton("Ursprung = Kopf")
        self.origin_set_button.setToolTip("Aktuelle Kopfposition als Benutzer-Ursprung "
                                          "auf dem Pi speichern")
        self.origin_set_button.clicked.connect(lambda _=False: self.set_user_origin())
        # Stacked (not side by side): the sidebar must fit 1024-px screens.
        for w in (self.origin_combo, self.anchor_combo, self.origin_set_button):
            jl.addWidget(w)
        self.origin_label = QLabel("")
        self.origin_label.setWordWrap(True)
        self.origin_label.setStyleSheet("color: %s;" % MUTED)
        jl.addWidget(self.origin_label)
        self.origin_combo.currentIndexChanged.connect(lambda _=0: self._update_enabled())
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
                                 self.abort_button, self.frame_button,
                                 self.origin_set_button]

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
        self._poller.state_changed.connect(self._on_poller_state)
        self._poller.status_received.connect(self._on_poller_status)
        self._poller.set_command_running(self._runner.busy or bool(self._external))
        self._poller.start()

    def disconnect_from_pi(self) -> None:
        poller, self._poller = self._poller, None
        if poller is not None:
            poller.state_changed.disconnect(self._on_poller_state)
            poller.status_received.disconnect(self._on_poller_status)
            poller.stop(wait_ms=200)    # daemon thread; never blocks the GUI long
            poller.deleteLater()
        self._status = None
        self._status_at = None
        self._stale = False
        self._apply_state(ConnState.DISCONNECTED, "Getrennt")

    def shutdown(self) -> None:
        """Stop polling and wait briefly for running requests. Idempotent."""
        if getattr(self, "_shut_down", False):
            return
        self._shut_down = True
        self._stale_timer.stop()
        self.disconnect_from_pi()
        # Commands run on daemon threads: wait briefly so a just-sent E-Stop
        # gets its answer, but never hang application exit on a long Home.
        self._runner.wait(1000)

    @property
    def connection_state(self) -> str:
        return self._state

    @property
    def last_status(self) -> MachineStatus | None:
        """Most recent status from the Pi (None when disconnected)."""
        return self._status if self._state == ConnState.CONNECTED else None

    @property
    def client(self) -> LumaCutClient | None:
        """Client of the current connection (None when disconnected). It is
        stateless and thread-safe; use set_external_operation() while
        driving the machine with it outside this panel."""
        return self._client

    def set_external_operation(self, label: str) -> None:
        """Another module (e.g. scan/probe) moves the machine with
        ``client``: lock the motion buttons and tolerate slow status like
        during an own command. ``""`` ends it. E-Stop stays usable."""
        self._external = label or ""
        if self._poller is not None:
            self._poller.set_command_running(self._runner.busy or bool(self._external))
        self._update_enabled()

    @property
    def command_running(self) -> str:
        """Label of the command currently running ("" if none)."""
        return self._runner.current or ""

    @property
    def stale(self) -> bool:
        """True while connected but the last status is older than STALE_AFTER_S."""
        return self._stale

    @Slot(str, str)
    def _on_poller_state(self, state: str, message: str) -> None:
        if self.sender() is self._poller:   # ignore queued signals of old pollers
            self._apply_state(state, message)

    @Slot(object)
    def _on_poller_status(self, status: MachineStatus) -> None:
        if self.sender() is self._poller:
            self._apply_status(status)

    @Slot(bool)
    def _on_busy_changed(self, busy: bool) -> None:
        if self._poller is not None:
            self._poller.set_command_running(busy or bool(self._external))
        self._update_enabled()

    @Slot()
    def _check_stale(self) -> None:
        age = (None if self._status_at is None else
               time.monotonic() - self._status_at)
        stale = (self._state == ConnState.CONNECTED and
                 (age is None or age > STALE_AFTER_S))
        if stale:
            busy = self._runner.current or self._external
            text = ("Pi beschäftigt (%s)" % busy) if busy else "Keine Statusdaten"
            if age is not None:
                text += " · Status %.0f s alt" % age
            badge(self.conn_badge, text, WARN)
            self.pos_label.setStyleSheet(
                "font-family: monospace; font-size: 14px; color: %s;" % MUTED)
        if stale != self._stale:
            self._stale = stale
            if not stale:
                if self._state == ConnState.CONNECTED:
                    badge(self.conn_badge, *STATE_TEXT[ConnState.CONNECTED])
                self.pos_label.setStyleSheet("font-family: monospace; font-size: 14px;")
            self._update_enabled()

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
        self._status_at = time.monotonic()
        self.status_changed.emit(status)
        if self._stale:
            self._check_stale()
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
        if status.laser_armed is None:
            badge(self.laser_label, "Unbekannt", WARN)
        elif status.laser_armed:
            badge(self.laser_label, "AKTIV", BAD)
        else:
            badge(self.laser_label, "Aus" + (" · Lüfter nachlaufend"
                                             if status.laser_fan_on else ""), OK)
        free = status.owner in TRANSIENT_OWNERS
        owner_text = "Frei" if free else "Belegt: " + status.owner
        if status.pi_busy:
            # Pi answered from its snapshot while a move holds the lock.
            owner_text += " · Pi fährt"
        badge(self.owner_label, owner_text, OK if free else WARN)
        self.focus_label.setText("%s / %s mm" % (_mm(status.workpiece_surface_z),
                                                  _mm(status.laser_focus_z))
                                 if status.workpiece_surface_z is not None
                                 else "Nicht abgetastet")
        if status.fault:
            self._show_message(status.fault, BAD if status.emergency_latched else WARN)
        self._apply_job(status)
        self._update_enabled()

    def _apply_job(self, status: MachineStatus) -> None:
        self._note_frame_result(status)
        if status.framing:
            frame = status.frame
            text = "Rahmenfahrt läuft (%s) · Laser aus" % FRAME_LABELS.get(
                frame.mode, frame.mode or "Rahmen")
            if self._uploaded:
                text += " · %s bleibt geladen" % self._uploaded
            self.job_label.setText(text)
            self.job_label.setStyleSheet("color: %s;" % INFO)
            if frame.total > 0:
                self.job_progress.setValue(int(1000 * min(1.0, frame.line / frame.total)))
                self.job_progress.setFormat("Rahmen %d / %d" % (frame.line, frame.total))
            else:
                self.job_progress.setValue(0)
                self.job_progress.setFormat("Rahmen …")
            return
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

    def _note_frame_result(self, status: MachineStatus) -> None:
        state = status.frame.state
        if self._last_frame_state == "running" and state != "running":
            if state == "complete":
                self._show_message("Rahmenfahrt fertig – Auftrag unverändert, "
                                   "Starten ohne erneutes Senden möglich", OK)
            elif state == "aborted":
                self._show_message("Rahmenfahrt abgebrochen (Laser aus)", WARN)
            elif state == "error":
                self._show_message("Rahmenfahrt fehlgeschlagen: " +
                                   (status.frame.error or "ohne Begründung"), BAD)
        self._last_frame_state = state

    def _show_message(self, text: str, colour: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.error_label.setText("%s  %s" % (stamp, text))
        self.error_label.setStyleSheet("color: %s;" % colour)

    def _update_enabled(self) -> None:
        connected = (self._state == ConnState.CONNECTED and self._client is not None
                     and not self._stale)
        idle = connected and not self._runner.busy and not self._external
        s = self._status
        job_active = bool(s and s.job.active)
        framing = bool(s and s.framing)
        # LightBurn or another client holds the Pi: motion would be refused.
        foreign = bool(s and s.foreign_owner)
        for b in self._control_buttons:
            b.setEnabled(idle)
        if idle and s is not None:
            self.reset_button.setEnabled(s.emergency_latched)
            self.abort_button.setEnabled(job_active or framing)
            for b in (self.home_button, self.park_button, self.focus_button,
                      self.start_button, self.autorun_button, self.frame_button,
                      *self.jog_buttons):
                b.setEnabled(not job_active and not framing and not foreign
                             and not s.emergency_latched)
            for b in (self.park_button, self.focus_button, self.frame_button,
                      *self.jog_buttons):
                b.setEnabled(b.isEnabled() and s.homed)
        elif s is None:
            self.frame_button.setEnabled(False)
        elif (self._stale and self._state == ConnState.CONNECTED and
              self._client is not None and not self._runner.busy and
              not self._external and (job_active or framing)):
            # During a frame the Pi holds machine.lock for each edge (M400),
            # so status can go stale. Aborting only stops, so keep it usable.
            self.abort_button.setEnabled(True)
        frame_ok = self.frame_button.isEnabled()
        if frame_ok != self._frame_available:
            self._frame_available = frame_ok
            self.frame_available_changed.emit(frame_ok)
        if self._frame_provider is None:
            self.frame_button.setEnabled(False)
        if not self._job_path:
            self.send_button.setEnabled(False)
        if not self._uploaded:
            self.start_button.setEnabled(False)
            self.autorun_button.setEnabled(False)
        self._update_origin(s)
        # The emergency stop is never disabled.
        self.estop_button.setEnabled(True)

    def _update_origin(self, s: MachineStatus | None) -> None:
        supported = s is not None and s.origin.supported
        self.origin_combo.setEnabled(supported)
        self.anchor_combo.setEnabled(supported and self.origin_combo.currentData() != "absolute")
        if not supported:
            self.origin_set_button.setEnabled(False)
            self.origin_label.setText("" if s is None else OLD_PI_ORIGIN)
            return
        self.origin_set_button.setEnabled(
            self.origin_set_button.isEnabled() and s.homed and not s.job.active
            and not s.framing and not s.foreign_owner and not s.emergency_latched)
        user = s.origin.user
        text = "Benutzer-Ursprung: %s" % (
            "nicht gesetzt" if user is None else "X%.1f Y%.1f" % user)
        p = s.origin.placement
        if p and p.get("file"):
            text += " · platziert: %s (%s, %s)" % (
                p["file"], ORIGIN_LABELS.get(p.get("origin"), p.get("origin")),
                ANCHOR_LABELS.get(p.get("anchor"), p.get("anchor")))
        self.origin_label.setText(text)

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
        if label == ESTOP_LABEL:
            self._estop_feedback("NOT-AUS gesendet – warte auf Bestätigung …", WARN)

    def _estop_feedback(self, text: str, colour: str) -> None:
        self.estop_label.setText("%s  %s" % (time.strftime("%H:%M:%S"), text))
        self.estop_label.setStyleSheet("QLabel { color: %s; font-weight: bold; }" % colour)
        self.estop_label.setVisible(True)

    @Slot(str, str)
    def _on_command_finished(self, label: str, message: str) -> None:
        self._show_message("%s: %s" % (label, message), OK)
        if label == ESTOP_LABEL:
            self._estop_feedback("NOT-AUS bestätigt: " + message, OK)
        if self._poller:
            self._poller.poll_now()
        self.command_finished.emit(label, True)

    @Slot(str, str, str)
    def _on_command_failed(self, label: str, kind: str, message: str) -> None:
        self._show_message("%s fehlgeschlagen: %s" % (label, message), BAD)
        self.command_finished.emit(label, False)
        if label == ESTOP_LABEL:
            hint = "" if "physischen Not-Aus" in message else " – physischen Not-Aus benutzen!"
            self._estop_feedback("NOT-AUS NICHT bestätigt: " + message + hint, BAD)
        if kind == ConnState.AUTH_FAILED:
            self._apply_state(ConnState.AUTH_FAILED, message)
        if self._poller:
            self._poller.poll_now()

    @Slot()
    def emergency_stop(self) -> None:
        """Always dispatched at once: while another command runs, while the
        status poll is stalled, and also when not connected (then the
        address and key from the fields are used)."""
        client = self._client
        if client is None:
            try:
                s = self._current_settings()
                client = LumaCutClient(s.base_url, s.api_key)
            except ValueError as exc:
                text = "NOT-AUS nicht gesendet: %s – physischen Not-Aus benutzen!" % exc
                self._show_message(text, BAD)
                self._estop_feedback(text, BAD)
                return
        if not self._runner.run_urgent(ESTOP_LABEL, client.emergency_stop):
            self._estop_feedback("NOT-AUS wird bereits gesendet …", WARN)
        if self._poller:
            self._poller.poll_now()

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
        """Release the Pi's M112 latch. The Pi only accepts it once the SKR
        answers again (reset button or brief power cycle); the machine is
        then unhomed and must be referenced again."""
        if not self._client:
            return
        if not self._confirm("Notstopp quittieren",
                             "Ursache beseitigt und SKR neu gestartet (Reset-Taste "
                             "oder 24 V/USB kurz getrennt)? Danach muss neu "
                             "referenziert werden."):
            return
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
        self._upload_gen += 1
        self._uploaded = ""
        self.file_label.setText(self._job_path.name)
        self.file_label.setStyleSheet("")
        self._update_enabled()

    @Slot()
    def send_job(self) -> None:
        if self._client is None or self._job_path is None:
            return
        client, path = self._client, self._job_path

        def task(gen: int) -> str:
            name, message = client.upload_job_file(path)
            self._mark_uploaded(gen, name)
            return message
        self._run_upload("Senden", task)

    def send_gcode(self, name: str, gcode: str, start: bool = False) -> None:
        """Upload generated G-code (e.g. from the canvas) and optionally start."""
        if self._client is None:
            self._show_message("Nicht mit dem Pi verbunden", WARN)
            return
        client = self._client

        def task(gen: int) -> str:
            message = client.upload_job(name, gcode)
            if not self._mark_uploaded(gen, name):
                return message + " (inzwischen anderer Auftrag gewählt)"
            if start:
                message = client.start_job(name)
            return message
        if self._run_upload("Senden & Starten" if start else "Senden", task):
            self.file_label.setText(name)

    def _run_upload(self, label: str, task: Callable[[int], str]) -> bool:
        """Dispatch an upload. Until it succeeds nothing counts as sent, so
        Start can never run the previous job after a failed or newer
        upload (same file name included: the Pi would still hold the old
        content)."""
        previous, previous_gen = self._uploaded, self._upload_gen
        self._upload_gen = gen = previous_gen + 1
        self._uploaded = ""
        if self._run(label, lambda: task(gen)):
            self._update_enabled()
            return True
        self._uploaded, self._upload_gen = previous, previous_gen
        return False

    def _mark_uploaded(self, gen: int, name: str) -> bool:
        """Worker thread: record a finished upload unless a newer upload or
        file choice superseded it. Returns True if recorded."""
        if gen != self._upload_gen:
            return False
        self._uploaded = name
        return True

    # ---------------------------------------------------------- frame
    @property
    def frame_available(self) -> bool:
        """Connected, fresh status, homed, idle, no job/frame running."""
        return self._frame_available

    def set_frame_provider(self, provider: Callable[[str], str] | None) -> None:
        """``provider(mode)`` returns the frame G-code of the current design
        (or raises ValueError); used by the "Rahmen" button."""
        self._frame_provider = provider
        self._update_enabled()

    def frame(self, mode: str | None = None) -> bool:
        """Button: build the frame for the chosen mode, confirm, run it."""
        mode = mode or self.frame_mode_combo.currentData() or "box"
        if self._frame_provider is None:
            self._show_message("Rahmen: kein Design verfügbar", WARN)
            return False
        try:
            gcode = self._frame_provider(mode)
        except ValueError as exc:
            self._show_message("Rahmen nicht möglich: %s" % exc, WARN)
            return False
        if not self._confirm("Rahmen",
                             "Umriss (%s) mit ausgeschaltetem Laser abfahren? Bereich "
                             "frei? Der gesendete Auftrag bleibt geladen."
                             % FRAME_LABELS.get(mode, mode)):
            return False
        return self.frame_gcode(gcode, mode)

    def frame_gcode(self, gcode: str, mode: str = "box") -> bool:
        """Run a laser-off outline on the Pi (op=frame) without uploading:
        the job that was sent before stays loaded and can be started next.
        Returns True if the request was dispatched."""
        if self._client is None or self._state != ConnState.CONNECTED:
            self._show_message("Nicht mit dem Pi verbunden", WARN)
            return False
        s = self._status
        if s is not None and (s.job.active or s.framing):
            self._show_message("Rahmen erst, wenn %s beendet ist" % (
                "die Rahmenfahrt" if s.framing else "der Auftrag"), WARN)
            return False
        if s is not None and s.emergency_latched:
            self._show_message("Rahmen gesperrt: Notstopp zuerst quittieren", WARN)
            return False
        if s is not None and not s.homed:
            self._show_message("Vor dem Rahmen referenzieren (Home)", WARN)
            return False
        client = self._client
        origin, anchor = self.job_origin()
        if origin == "absolute":
            return self._run("Rahmen (%s)" % FRAME_LABELS.get(mode, mode),
                             lambda: client.frame(gcode, mode))
        if not self._origin_ready():
            return False
        if not self._uploaded:
            self._show_message("Rahmen am Ursprung: zuerst den Auftrag senden "
                               "(der Pi verschiebt den Rahmen wie den Auftrag)", WARN)
            return False
        name = self._uploaded

        def task() -> str:
            self._ensure_placement(client, name, origin, anchor)
            return client.frame(gcode, mode, placement=True, name=name)
        return self._run("Rahmen (%s, %s)" % (FRAME_LABELS.get(mode, mode),
                                             ORIGIN_LABELS[origin]), task)

    # ------------------------------------------------------- origin (#16)
    def job_origin(self) -> tuple[str, str]:
        """(origin, anchor) chosen for start/frame; absolute on an older Pi."""
        s = self._status
        if s is None or not s.origin.supported:
            return "absolute", "tl"
        return (self.origin_combo.currentData() or "absolute",
                self.anchor_combo.currentData() or "tl")

    def set_job_origin(self, origin: str, anchor: str = "tl") -> None:
        """Preset the origin choice (e.g. after a camera scan)."""
        if origin not in ORIGIN_MODES or anchor not in ANCHORS:
            raise ValueError("Ursprung/Bezugspunkt unbekannt")
        self.origin_combo.setCurrentIndex(self.origin_combo.findData(origin))
        self.anchor_combo.setCurrentIndex(self.anchor_combo.findData(anchor))
        self._update_enabled()

    def _origin_ready(self) -> bool:
        s = self._status
        if s is None or not s.origin.supported:
            # Never send origin fields to an older Pi: it would ignore them
            # and run the job absolute.
            self._show_message(OLD_PI_ORIGIN, WARN)
            return False
        return True

    def _ensure_placement(self, client: LumaCutClient, name: str, origin: str,
                          anchor: str) -> None:
        """Worker thread: let the Pi place the job unless it already holds
        exactly this placement (the frame must not shift a "current" one)."""
        s = self._status
        if s is None or not s.origin.placed(name, origin, anchor):
            client.place_job(name, origin, anchor)

    def _placed_call(self, client: LumaCutClient, name: str, origin: str,
                     anchor: str, call: Callable[[], str]) -> str:
        self._ensure_placement(client, name, origin, anchor)
        try:
            return call()
        except ApiError as exc:
            # The Pi dropped the placement meanwhile (jog/home/new upload).
            if "neu platzieren" not in str(exc):
                raise
            client.place_job(name, origin, anchor)
            return call()

    def set_user_origin(self, x: float | None = None, y: float | None = None) -> bool:
        """Store the user origin on the Pi: head XY, or a machine point (mm,
        e.g. the camera scan). The Pi checks homed state and the safe zone."""
        if self._client is None or self._state != ConnState.CONNECTED:
            self._show_message("Nicht mit dem Pi verbunden", WARN)
            return False
        if not self._origin_ready():
            return False
        client = self._client
        return self._run("Ursprung setzen", lambda: client.set_user_origin(x, y))

    @Slot()
    def start_job(self) -> None:
        if self._client is None or not self._uploaded:
            self._show_message("Zuerst einen Auftrag senden", WARN)
            return
        origin, anchor = self.job_origin()
        if origin != "absolute" and not self._origin_ready():
            return
        where = "" if origin == "absolute" else " am Ursprung „%s“ (%s)" % (
            ORIGIN_LABELS[origin], ANCHOR_LABELS[anchor])
        if not self._confirm("Auftrag starten",
                             "Auftrag %s%s starten? Bereich frei, Material eingelegt, "
                             "Schutzbrille?" % (self._uploaded, where)):
            return
        client, name = self._client, self._uploaded
        if origin == "absolute":
            self._run("Start", lambda: client.start_job(name))
            return
        self._run("Start", lambda: self._placed_call(
            client, name, origin, anchor, lambda: client.start_job(name, placement=True)))

    @Slot()
    def autorun_job(self) -> None:
        if self._client is None or not self._uploaded:
            return
        origin, anchor = self.job_origin()
        if origin != "absolute" and not self._origin_ready():
            return
        if not self._confirm("Ein-Klick-Start",
                             "Maschine fährt Homing, tastet unter der Motivmitte ab "
                             "und lasert %s. Bereich frei und Material eingelegt?"
                             % self._uploaded):
            return
        client, name = self._client, self._uploaded
        if origin == "absolute":
            self._run("Ein-Klick", lambda: client.autorun_job(name))
            return
        # Placed before the run homes, so "current" keeps the head position.
        self._run("Ein-Klick", lambda: self._placed_call(
            client, name, origin, anchor, lambda: client.autorun_job(name, placement=True)))

    def active_operation(self) -> str:
        """What the machine is doing that closing the app would not stop
        ("" if nothing): a running command, a Pi job or a frame run."""
        s = self._status if self._state == ConnState.CONNECTED else None
        if s is not None and s.framing:
            return "Rahmenfahrt"
        if s is not None and s.job.active:
            return "Auftrag " + (s.job.file or "")
        current = self._runner.current
        if current and current != ESTOP_LABEL:
            return current
        return self._external

    def confirm_close(self) -> bool:
        """Ask before closing while the Pi works. Closing never stops the
        machine; the dialog says so and points to NOT-AUS / Abbrechen."""
        active = self.active_operation().strip()
        if not active:
            return True
        return self._confirm(
            "LumaCut Studio schließen",
            "%s läuft noch auf dem Pi. Schließen stoppt die Maschine NICHT – "
            "sie arbeitet ohne Überwachung weiter. Vorher „Abbrechen“ oder "
            "NOT-AUS benutzen. Trotzdem schließen?" % active)

    @Slot()
    def abort_job(self) -> None:
        if self._client:
            self._run("Abbrechen", self._client.abort_job)

    def _ask(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text) == QMessageBox.Yes
