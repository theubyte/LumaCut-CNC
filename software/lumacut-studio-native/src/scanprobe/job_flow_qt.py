"""Qt-Anbindung des Ein-Klick-Auftrags (:mod:`scanprobe.job_flow`).

Startet :class:`~scanprobe.job_flow.OneClickJob` in einem Hintergrund-Thread,
zeigt Fortschritt/Pause/Abbrechen im Scan-&-Probe-Panel und sperrt solange die
Fahrknöpfe des Machine-Panels (``set_external_operation``).

Der Start-Knopf der Hauptansicht ruft ``window.one_click.start`` auf
(Canvas, 285d8b0); zusätzlich unter „Mehr …“ → „Ein-Klick-Auftrag starten“.

Ursprung ≠ „Absolut“ geht nur mit einem Pi, der ``autorun_mesh`` meldet: dann
platziert ``machine_panel.autorun_task`` den Auftrag und der Pi tastet am
platzierten Ort ab. Eine Kamera-Kalibrierung braucht der Auftrag nicht.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QMessageBox, QPushButton

from .job_flow import ClientMachinePort, FlowResult, OneClickJob

CONFIRM_TEXT = ("Auftrag starten?\n\nAblauf: Referenzfahrt (falls nötig) → Höhenmesh "
                "messen → Fokus → Lasern → Parken.\n\nArbeitsbereich frei, Material "
                "eingelegt, Schutzbrille auf?")


class _NoWorkflow:
    """Platzhalter, wenn sich kein Mess-Workflow bauen ließ. Stört nur, wenn
    Studio selbst proben muss (Pi ohne ``autorun_mesh``)."""

    def __init__(self, why: str):
        self.why = why
        self.control = None
        self.settings = None

    def _fail(self, *_a, **_k):
        raise RuntimeError(f"Taster/Maschine für das Proben nicht bereit: {self.why}")

    try_reuse = plan_probe = probe_areas = _fail


class _PlacedAutorunPort:
    """Wie der normale Port, aber ``autorun`` platziert vorher am gewählten
    Ursprung (``machine_panel.autorun_task``, Machine-Agent)."""

    def __init__(self, port, task: Callable[[], str]):
        self._port = port
        self._task = task

    def __getattr__(self, item):
        return getattr(self._port, item)

    def autorun(self, name: str) -> str:
        return self._task()


class OneClickRunner(QThread):
    """Führt ``job.run(...)`` aus; Ereignisse kommen per Signal in den GUI-Thread."""

    event = Signal(dict)
    done = Signal(object)

    def __init__(self, job: OneClickJob, gcode: str, name: str, *, objects=(),
                 mosaic=None, saved_maps=None, parent=None):
        super().__init__(parent)
        self.job = job
        self.args = (gcode, name)
        self.kw = dict(objects=objects, mosaic=mosaic, saved_maps=saved_maps)
        job.on_event = self.event.emit

    def run(self) -> None:  # noqa: D401 - QThread
        try:
            res = self.job.run(*self.args, **self.kw)
        except Exception as exc:  # noqa: BLE001 - nie still im Thread sterben
            res = FlowResult(state="fehler", job_name=self.args[1], error_code="job_failed",
                             error=f"Interner Fehler: {exc}")
        self.done.emit(res)

    # Pause/Abbrechen für ScanPanel.attach_external_run
    def pause(self) -> None:
        self.job.pause()

    def resume(self) -> None:
        self.job.resume()

    def cancel(self) -> None:
        self.job.cancel()


class OneClickController(QObject):
    """Hält die Teile zusammen: Machine-Panel, Scan-Panel, JobTools, Statusleiste."""

    finished = Signal(object)  # FlowResult

    def __init__(self, win: Any, *, ask: bool = True,
                 port_factory: Callable[[Any], Any] = ClientMachinePort,
                 workflow_factory: Optional[Callable[[], Any]] = None,
                 job_kwargs: Optional[dict] = None):
        super().__init__(win if isinstance(win, QObject) else None)
        self.win = win
        self.ask = ask
        self.port_factory = port_factory
        self.workflow_factory = workflow_factory
        self.job_kwargs = dict(job_kwargs or {})
        self.runner: Optional[OneClickRunner] = None
        self.last_result: Optional[FlowResult] = None
        self.last_message = ""

    @property
    def busy(self) -> bool:
        return self.runner is not None

    # ------------------------------------------------------------ helpers
    def _message(self, text: str, ms: int = 10000) -> None:
        self.last_message = text
        bar = getattr(self.win, "statusBar", None)
        if callable(bar):
            try:
                bar().showMessage(text, ms)
            except Exception:  # noqa: BLE001 - nur Anzeige
                pass

    def _refuse(self, text: str) -> bool:
        self._message("Ein-Klick-Auftrag: " + text)
        if self.ask:
            QMessageBox.warning(self.win if hasattr(self.win, "window") else None,
                                "Auftrag nicht möglich", text)
        return False

    def _job_name(self) -> str:
        canvas = getattr(self.win, "canvas", None)
        path = getattr(canvas, "file_path", None)
        stem = path.name.split(".")[0] if path else "canvas"
        return f"{stem}.gcode"

    def _workflow(self, panel) -> Any:
        if self.workflow_factory is not None:
            return self.workflow_factory()
        try:
            from .panel import MODE_PI, MODE_SIM
            if not panel._mode_chosen and panel.mode == MODE_SIM and panel._client() is not None:
                panel.set_mode(MODE_PI)   # gleiche Regel wie „Kamera-Scan“
            return panel._ensure_workflow(False)
        except Exception as exc:  # noqa: BLE001 - erst nötig, wenn Studio probt
            return _NoWorkflow(str(exc))

    @staticmethod
    def _pi_places_with_mesh(mp) -> bool:
        """Pi meldet ``autorun_mesh`` und das Machine-Panel kann platziert starten."""
        from .job_flow import pi_runs_mesh
        return hasattr(mp, "autorun_task") and pi_runs_mesh(getattr(mp, "_status", None))

    # ------------------------------------------------------------ start
    def start(self) -> bool:
        if self.busy:
            return self._refuse("Es läuft bereits ein Ein-Klick-Auftrag.")
        mp = self.win.machine_panel
        panel = self.win.scan_panel
        client = getattr(mp, "client", None)
        if client is None:
            return self._refuse("Nicht mit dem Pi verbunden.")
        if panel.busy:
            return self._refuse("Scan/Probing läuft noch – erst abwarten oder abbrechen.")
        origin, _anchor = mp.job_origin()
        placed = origin != "absolute"
        if placed and not self._pi_places_with_mesh(mp):
            # Studio misst das Höhenmesh in Maschinen-mm; eine Pi-Platzierung würde
            # den Auftrag dagegen verschieben. Ein Pi mit ``autorun_mesh`` tastet
            # erst nach dem Platzieren ab – dann geht jeder Ursprung.
            return self._refuse("Ursprung „%s“ geht nur, wenn der Pi selbst abtastet "
                                "(Pi-Software mit „autorun_mesh“ aktualisieren). Bis dahin "
                                "Ursprung „Absolut“ wählen (Motiv so lasern, wie es im "
                                "Canvas liegt)." % origin)
        tools = getattr(self.win, "job_tools", None)
        try:
            if tools is None:
                raise ValueError("Kein Auftrag (JobTools fehlen)")
            gcode, _note = tools.job_gcode()
        except ValueError as exc:
            return self._refuse(str(exc))
        if self.ask and QMessageBox.question(
                None, "Auftrag starten", CONFIRM_TEXT) != QMessageBox.StandardButton.Yes:
            return False
        name = self._job_name()
        port = self.port_factory(client)
        kwargs = dict(self.job_kwargs)
        if placed:
            try:
                task = mp.autorun_task(name)   # GUI-Thread: liest Ursprung/Bezugspunkt
            except RuntimeError as exc:
                return self._refuse(str(exc))
            port = _PlacedAutorunPort(port, task)
            kwargs["use_pi_mesh"] = True      # nur der Pi kann platziert abtasten
        job = OneClickJob(port, self._workflow(panel) if not placed else _NoWorkflow(
            "Pi tastet selbst ab"), **kwargs)
        maps = panel.maps if getattr(panel, "has_maps", False) else None
        self.runner = OneClickRunner(job, gcode, name,
                                     objects=panel.checked_objects(), mosaic=panel.mosaic,
                                     saved_maps=maps, parent=self)
        self.runner.event.connect(self._on_event)
        self.runner.done.connect(self._on_done)
        mp.set_external_operation("Ein-Klick-Auftrag")
        panel.attach_external_run(self.runner, "Ein-Klick-Auftrag läuft …")
        self.runner.start()
        return True

    def pause(self) -> None:
        if self.runner is not None:
            self.runner.pause()

    def resume(self) -> None:
        if self.runner is not None:
            self.runner.resume()

    def cancel(self) -> None:
        if self.runner is not None:
            self.runner.cancel()

    def wait(self, ms: int = 60000) -> bool:
        """Für Tests: auf das Ende warten (verarbeitet Qt-Ereignisse)."""
        from PySide6.QtCore import QCoreApplication, QDeadlineTimer
        deadline = QDeadlineTimer(ms)
        while self.runner is not None and not deadline.hasExpired():
            QCoreApplication.processEvents()
            QThread.msleep(5)
        QCoreApplication.processEvents()
        return self.runner is None

    # ------------------------------------------------------------ events
    def _on_event(self, ev: dict) -> None:
        self.win.scan_panel.show_job_event(ev)
        text = f"{ev.get('label', '')}: {ev.get('message', '')}".strip(": ")
        self._message(text, 15000)

    def _on_done(self, res: FlowResult) -> None:
        runner, self.runner = self.runner, None
        if runner is not None:
            runner.wait(2000)
            runner.deleteLater()
        self.last_result = res
        self.win.machine_panel.set_external_operation("")
        panel = self.win.scan_panel
        panel.detach_external_run()
        if res.maps is not None and not res.reused_mesh:
            panel.set_maps(res.maps)   # für den nächsten Auftrag wiederverwendbar
        if res.ok:
            text = "Auftrag fertig, Kopf geparkt"
            if res.notes:
                text += f" ({len(res.notes)} Hinweis(e))"
        elif res.state == "abgebrochen":
            text = "Auftrag abgebrochen"
        else:
            text = f"Auftrag fehlgeschlagen: {res.error}"
        self._message(text, 20000)
        if self.ask and res.state == "fehler":
            QMessageBox.critical(None, "Auftrag fehlgeschlagen", res.error)
        self.finished.emit(res)

    def shutdown(self, ms: int = 5000) -> None:
        """Beim Schließen: vor dem Lasern abbrechen, einen laufenden Auftrag auf
        dem Pi aber **nicht** abbrechen (nur nicht mehr beobachten)."""
        if self.runner is not None:
            self.runner.job.detach()
            self.runner.wait(ms)


def install_one_click(win: Any, **kw) -> OneClickController:
    """Controller anlegen und unter „Mehr …“ im Scan-&-Probe-Panel einhängen."""
    ctrl = OneClickController(win, **kw)
    panel = win.scan_panel
    btn = QPushButton("Ein-Klick-Auftrag starten")
    btn.setToolTip("Referenzfahrt → Höhenmesh → Fokus → Lasern → Parken "
                   "(Start-Knopf der Werkzeugleiste: Machine-Agent)")
    btn.clicked.connect(ctrl.start)
    panel.advanced.layout().addWidget(btn)
    panel.one_click_button = btn
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(ctrl.shutdown)
    return ctrl
