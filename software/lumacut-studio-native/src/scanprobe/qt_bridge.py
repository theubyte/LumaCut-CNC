"""Optionale PySide6-Anbindung: Workflow im Hintergrund-Thread.

Nur dieses Modul importiert Qt. Beispiel im Hauptfenster::

    from scanprobe.qt_bridge import ScanProbeWorker
    worker = ScanProbeWorker(workflow, scan_bounds=None, design_bounds=boxes)
    worker.progress.connect(lambda phase, done, total, msg, eta: ...)
    worker.tile_captured.connect(canvas.show_tile_preview)
    worker.finished_ok.connect(on_result)
    worker.failed.connect(show_error)
    worker.start()
    pause_btn.clicked.connect(worker.pause) ...
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from .control import Cancelled, Progress
from .workflow import ScanProbeWorkflow


class ScanProbeWorker(QThread):
    progress = Signal(str, int, int, str, float)       # phase, done, total, message, eta_s
    tile_captured = Signal(object, object)              # Tile, np.ndarray (entzerrt)
    finished_ok = Signal(object)                        # WorkflowResult
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, workflow: ScanProbeWorkflow, parent=None, **run_kwargs):
        super().__init__(parent)
        self.workflow = workflow
        self.run_kwargs = run_kwargs
        workflow.control.on_progress = self._on_progress

    def _on_progress(self, p: Progress) -> None:
        self.progress.emit(p.phase, p.done, p.total, p.message, float(p.eta_s or 0.0))
        if p.phase == "scan" and "image" in p.extra:
            self.tile_captured.emit(p.extra["tile"], p.extra["image"])

    def pause(self):
        self.workflow.control.pause()

    def resume(self):
        self.workflow.control.resume()

    def cancel(self):
        self.workflow.control.cancel()

    def run(self):  # noqa: D401 - QThread
        try:
            self.finished_ok.emit(self.workflow.run(**self.run_kwargs))
        except Cancelled:
            self.cancelled.emit()
        except Exception as exc:  # an die UI melden statt Thread sterben lassen
            self.failed.emit(f"{type(exc).__name__}: {exc}")
