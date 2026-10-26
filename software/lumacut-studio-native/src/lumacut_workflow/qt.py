"""Panel „Ablauf“: geführter Workflow über die vorhandenen Panels.

Der Adapter liest die Fakten aus MachinePanel (Pi-Status), ScanPanel
(Scan/Markierung/Höhenmesh) und dem Canvas und löst die vorhandenen
Aktionen aus – keine eigene Maschinenlogik, keine eigenen Sicherheitsprüfungen
(die bleiben in MachinePanel/ScanPanel/Pi). Jeder Schritt zeigt seinen Status
(erledigt/bereit/gesperrt/übersprungen/läuft) und kann übersprungen werden.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from .steps import (BLOCKED, DONE, READY, RUNNING, SKIPPED, STEPS, StepState, WorkflowFacts,
                    WorkflowMarks, current_step, evaluate, step_def, summary)

ICONS = {DONE: "✔", READY: "▶", BLOCKED: "⛔", SKIPPED: "↷", RUNNING: "⏳"}
COLOURS = {DONE: "#4cd4b0", READY: "#6cb4ff", BLOCKED: "#93a1b5", SKIPPED: "#93a1b5",
           RUNNING: "#f0b54a"}


class WindowWorkflowAdapter(QObject):
    """Verbindet den Ablauf mit dem Hauptfenster (machine_panel, scan_panel, canvas)."""

    changed = Signal()
    message = Signal(str)

    def __init__(self, window: Any, confirm: Optional[Callable[[str, str], bool]] = None):
        super().__init__(window)
        self.win = window
        self.confirm = confirm or self._ask
        self.marks = WorkflowMarks()
        self._last_frame = ""
        self._last_job = ""
        mp, sp, ed = window.machine_panel, window.scan_panel, window.canvas
        mp.status_changed.connect(self._on_status)
        mp.connection_changed.connect(lambda *_: self.changed.emit())
        mp.command_finished.connect(self._on_command)
        sp.busyChanged.connect(lambda *_: self.changed.emit())
        sp.resultReady.connect(lambda *_: self.changed.emit())
        sp.objects_list.itemChanged.connect(lambda *_: self.changed.emit())
        sp.design_only.toggled.connect(lambda *_: self.changed.emit())
        if hasattr(sp, "areasChanged"):
            sp.areasChanged.connect(lambda *_: self.changed.emit())
        sp.mode_combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        ed.documentChanged.connect(self._on_document)

    # ------------------------------------------------------------ Fakten
    def facts(self) -> WorkflowFacts:
        mp, sp = self.win.machine_panel, self.win.scan_panel
        st = mp.last_status
        connected = st is not None and not mp.stale
        running_cmd = mp.command_running
        activity = ""
        if st is not None and st.framing:
            activity = "frame"
        elif st is not None and st.job.active:
            activity = "job"
        elif running_cmd:
            activity = "command"
        try:
            areas = len(sp.probe_areas()[0])
        except Exception:  # noqa: BLE001 - Bereichsvorschlag darf den Ablauf nicht stören
            areas = 0
        from scanprobe.panel import MODE_SIM
        return WorkflowFacts(
            connected=connected,
            homed=bool(st and st.homed),
            emergency=bool(st and st.emergency_latched),
            machine_busy=bool(st and st.busy) or bool(running_cmd),
            machine_activity=activity,
            job_state=st.job.state if st else "idle",
            frame_state=st.frame.state if st else "idle",
            surface_z=st.workpiece_surface_z if st else None,
            design_empty=self._design_empty(),
            simulation=sp.mode == MODE_SIM,
            scan_busy=sp.busy,
            scan_kind=getattr(sp, "_kind", "") if sp.busy else "",
            has_mosaic=sp.mosaic is not None,
            marked_areas=areas,
            has_maps=sp.maps is not None and bool(getattr(sp.maps, "maps", None)),
        )

    def _design_empty(self) -> bool:
        doc = self.win.canvas.document
        visible = {l.id for l in doc.layers if l.visible}
        return not any(s.layer_id in visible for s in doc.shapes)

    # --------------------------------------------------------- Ereignisse
    def _on_status(self, status) -> None:
        # „erledigt“ nur bei einem Übergang running → complete (nicht für alte Läufe)
        if self._last_frame == "running" and status.frame.state == "complete":
            self.marks.mark_done("frame")
        if self._last_job in ("homing", "probing", "running") and status.job.state == "complete":
            self.marks.mark_done("job")
            self.marks.invalidate(["park"])
        self._last_frame, self._last_job = status.frame.state, status.job.state
        self.changed.emit()

    def _on_command(self, label: str, ok: bool) -> None:
        if ok and label == "Park":
            self.marks.mark_done("park")
        self.changed.emit()

    def _on_document(self, *_args) -> None:
        # Design geändert → Rahmen/Auftrag gelten nicht mehr
        self.marks.invalidate(["frame", "job"])
        self.changed.emit()

    # ------------------------------------------------------------ Aktionen
    def run(self, key: str) -> bool:
        mp, sp = self.win.machine_panel, self.win.scan_panel
        if key == "home":
            mp.home()
        elif key == "scan":
            return bool(sp.start_scan())
        elif key == "mark":
            if hasattr(sp, "start_marking") and sp.start_marking():
                self.message.emit("Bereich auf dem Canvas aufziehen: umschlossene Werkstücke werden "
                                  "angehakt, sonst wird der Bereich selbst geprobt (Esc bricht ab).")
                return True
            sp.objects_list.setFocus()
            self.message.emit("Werkstücke in der Liste „Erkannte Werkstücke“ anhaken "
                              "oder das Design auf dem Werkstück platzieren.")
            return False
        elif key == "probe":
            return bool(sp.start_probe())
        elif key == "focus":
            mp.focus()
        elif key == "frame":
            return bool(mp.frame())
        elif key == "job":
            return self._send_and_start()
        elif key == "park":
            mp.park()
        else:
            raise KeyError(key)
        self.changed.emit()
        return bool(mp.command_running)

    def _send_and_start(self) -> bool:
        """Wie „Design senden“ + „Start Job“ in einem Schritt (mit Rückfrage)."""
        from lumacut_job.planner import optimized_document_gcode
        from lumacut_job.estimate import estimate_gcode
        tools = getattr(self.win, "job_tools", None)
        try:
            gcode, note = (tools.job_gcode() if tools is not None
                           else (optimized_document_gcode(self.win.canvas.document), ""))
        except ValueError as exc:
            self.message.emit(f"Auftrag nicht möglich: {exc}")
            return False
        gcode = self.win.scan_panel.prepare_job_gcode(gcode)
        if gcode is None:
            return False
        path = self.win.canvas.file_path
        stem = path.name.split(".")[0] if path else "canvas"
        if not self.confirm("Auftrag starten",
                            f"{stem}.gcode senden und starten ({estimate_gcode(gcode).summary()})? "
                            "Bereich frei, Material eingelegt, Schutzbrille?"
                            + (f"\n\nHinweis: {note}" if note else "")):
            return False
        self.win.machine_panel.send_gcode(f"{stem}.gcode", gcode, start=True)
        self.changed.emit()
        return True

    def _ask(self, title: str, text: str) -> bool:
        return QMessageBox.question(self.win, title, text) == QMessageBox.StandardButton.Yes


class WorkflowPanel(QWidget):
    """Liste der Schritte mit Status + Ausführen/Überspringen/Zurücksetzen."""

    statusMessage = Signal(str)  # noqa: N815

    def __init__(self, adapter: Any, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.adapter = adapter
        self.states: list[StepState] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        lay.addWidget(self.summary_label)
        self.list = QListWidget()
        self.list.setMaximumHeight(190)
        self.list.currentRowChanged.connect(lambda *_: self._update_buttons())
        self.list.itemDoubleClicked.connect(lambda *_: self.run_selected())
        lay.addWidget(self.list)
        self.reason_label = QLabel("")
        self.reason_label.setWordWrap(True)
        self.reason_label.setStyleSheet("color: #93a1b5;")
        lay.addWidget(self.reason_label)
        row = QHBoxLayout()
        self.run_button = QPushButton("Ausführen")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.run_selected)
        self.skip_button = QPushButton("Überspringen")
        self.skip_button.clicked.connect(self.toggle_skip)
        self.reset_button = QPushButton("Neu beginnen")
        self.reset_button.setToolTip("Übersprungene/erledigte Markierungen zurücksetzen")
        self.reset_button.clicked.connect(self.reset)
        for b in (self.run_button, self.skip_button, self.reset_button):
            row.addWidget(b)
        lay.addLayout(row)
        for sd in STEPS:
            item = QListWidgetItem(sd.title)
            item.setData(Qt.ItemDataRole.UserRole, sd.key)
            item.setToolTip(sd.hint)
            self.list.addItem(item)
        if hasattr(adapter, "changed"):
            adapter.changed.connect(self.refresh)
        if hasattr(adapter, "message"):
            adapter.message.connect(self._notify)
        self._follow_current = True
        self.refresh()

    # ------------------------------------------------------------ Zustand
    def state(self, key: str) -> StepState:
        return next(s for s in self.states if s.key == key)

    def selected_key(self) -> str:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    def select(self, key: str) -> None:
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == key:
                self._follow_current = False
                self.list.setCurrentRow(i)
                return
        raise KeyError(key)

    def refresh(self) -> None:
        self.states = evaluate(self.adapter.facts(), self.adapter.marks)
        for i, st in enumerate(self.states):
            item = self.list.item(i)
            text = f"{ICONS[st.status]}  {i + 1}. {st.title} – {st.label}"
            item.setText(text)
            item.setForeground(QColor(COLOURS[st.status]))
        self.summary_label.setText(summary(self.states))
        cur = current_step(self.states)
        if self._follow_current or self.list.currentRow() < 0:
            row = STEPS.index(step_def(cur.key)) if cur else len(STEPS) - 1
            self.list.blockSignals(True)
            self.list.setCurrentRow(row)
            self.list.blockSignals(False)
        self._update_buttons()

    def _update_buttons(self) -> None:
        key = self.selected_key()
        if not key or not self.states:
            return
        st = self.state(key)
        sd = step_def(key)
        self.reason_label.setText(st.reason or sd.hint)
        self.run_button.setEnabled(st.status in (READY, DONE))
        self.run_button.setText("Markieren" if key == "mark" else
                                ("Wiederholen" if st.status == DONE else "Ausführen"))
        self.skip_button.setEnabled(sd.skippable and st.status != RUNNING)
        self.skip_button.setText("Nicht überspringen" if st.status == SKIPPED else "Überspringen")

    def _notify(self, text: str) -> None:
        self.reason_label.setText(text)
        self.statusMessage.emit(text)

    # ------------------------------------------------------------ Aktionen
    def run_selected(self) -> bool:
        key = self.selected_key()
        if not key:
            return False
        st = self.state(key)
        if st.status not in (READY, DONE):
            self._notify(f"{st.title}: {st.reason or st.label}")
            return False
        self._follow_current = True
        ok = self.adapter.run(key)
        self.refresh()
        return ok

    def toggle_skip(self) -> None:
        key = self.selected_key()
        if not key:
            return
        marks = self.adapter.marks
        if key in marks.skipped:
            marks.unskip(key)
        else:
            try:
                marks.skip(key)
            except ValueError as exc:
                self._notify(str(exc))
                return
        self._follow_current = True
        self.refresh()

    def reset(self) -> None:
        self.adapter.marks.reset()
        self._follow_current = True
        self.refresh()


def install_workflow(window: Any, confirm: Optional[Callable[[str, str], bool]] = None) -> WorkflowPanel:
    """Gruppe „Ablauf“ oben in die rechte Spalte des Hauptfensters einfügen."""
    adapter = WindowWorkflowAdapter(window, confirm)
    panel = WorkflowPanel(adapter)
    group = QGroupBox("Ablauf")
    QVBoxLayout(group).addWidget(panel)
    scan_group = window.scan_panel.parentWidget()
    column = scan_group.parentWidget() if scan_group is not None else None
    if column is not None and column.layout() is not None:
        column.layout().insertWidget(0, group)
    status = window.statusBar() if hasattr(window, "statusBar") else None
    if status is not None:
        panel.statusMessage.connect(lambda t: status.showMessage(t, 6000))
    # Sicherheitsnetz: falls ein Zustand ohne Signal wechselt (z. B. Pi-Timeout)
    timer = QTimer(panel)
    timer.setInterval(1000)
    timer.timeout.connect(panel.refresh)
    timer.start()
    window.workflow_panel = panel
    window.workflow_adapter = adapter
    return panel
