"""Non-blocking machine I/O for the GUI.

* :class:`StatusPoller` lives in its own QThread and polls GET /api/status
  with a single-shot QTimer (no overlapping requests, no GUI blocking).
* :class:`CommandRunner` executes actions in a QThreadPool. Motion requests
  on the Pi block until the SKR is done (home/probe up to minutes), so the
  emergency stop is always dispatched on its own thread and never queued
  behind a running command.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import (QObject, QRunnable, QThread, QThreadPool, QTimer,
                            Signal, Slot)

from .client import (ApiError, AuthFailed, ConnectionFailed, LumaCutClient,
                     MachineError, MachineStatus, ProtocolError)


class ConnState:
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    AUTH_FAILED = "auth_failed"


def classify(exc: BaseException) -> str:
    if isinstance(exc, AuthFailed):
        return ConnState.AUTH_FAILED
    return ConnState.ERROR


class StatusPoller(QObject):
    """Polls the Pi. Create, then call :meth:`start`; signals are queued."""

    status_received = Signal(object)          # MachineStatus
    state_changed = Signal(str, str)          # ConnState, message
    _start_requested = Signal()
    _stop_requested = Signal()

    #: consecutive failures before CONNECTED drops to ERROR
    FAILURE_TOLERANCE = 2

    def __init__(self, client: LumaCutClient, interval_ms: int = 1000):
        super().__init__()
        self._client = client
        self._interval = max(250, int(interval_ms))
        self._failures = 0
        self._state = ConnState.DISCONNECTED
        self._timer: QTimer | None = None
        self._thread = QThread()
        self._thread.setObjectName("lumacut-status-poller")
        self.moveToThread(self._thread)
        self._start_requested.connect(self._on_start)
        self._stop_requested.connect(self._on_stop)

    @property
    def state(self) -> str:
        return self._state

    def start(self) -> None:
        self._thread.start()
        self._start_requested.emit()

    def stop(self, wait_ms: int = 5000) -> None:
        if not self._thread.isRunning():
            return
        self._stop_requested.emit()
        self._thread.quit()
        self._thread.wait(wait_ms)

    def poll_now(self) -> None:
        QTimer.singleShot(0, self, self._poll)

    def _set_state(self, state: str, message: str = "") -> None:
        if state != self._state or state != ConnState.CONNECTED:
            self._state = state
            self.state_changed.emit(state, message)

    @Slot()
    def _on_start(self) -> None:
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._poll)
        self._failures = 0
        self._set_state(ConnState.CONNECTING, "Verbinde mit " + self._client.base_url)
        self._poll()

    @Slot()
    def _on_stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._state = ConnState.DISCONNECTED
        self.state_changed.emit(ConnState.DISCONNECTED, "Getrennt")

    @Slot()
    def _poll(self) -> None:
        if self._timer is None:
            return
        try:
            status = self._client.status()
        except AuthFailed as exc:
            self._failures += 1
            self._set_state(ConnState.AUTH_FAILED, str(exc))
        except (ConnectionFailed, ApiError, ProtocolError, MachineError) as exc:
            self._failures += 1
            if (self._state != ConnState.CONNECTED or
                    self._failures >= self.FAILURE_TOLERANCE):
                self._set_state(ConnState.ERROR, str(exc))
        except Exception as exc:  # defensive: never kill the poll thread
            self._failures += 1
            self._set_state(ConnState.ERROR, "Unerwarteter Fehler: %s" % exc)
        else:
            self._failures = 0
            if self._state != ConnState.CONNECTED:
                self._state = ConnState.CONNECTED
                self.state_changed.emit(ConnState.CONNECTED,
                                        "Verbunden mit " + self._client.base_url)
            self.status_received.emit(status)
        if self._timer is not None:
            # Back off while the Pi is unreachable, poll fast when healthy.
            delay = self._interval if self._failures == 0 else min(
                5000, self._interval * (1 + self._failures))
            self._timer.start(delay)


class _Signals(QObject):
    finished = Signal(str, str)        # label, message
    failed = Signal(str, str, str)     # label, ConnState-ish kind, message


class _Task(QRunnable):
    def __init__(self, label: str, fn: Callable[[], str], signals: _Signals):
        super().__init__()
        self.label, self.fn, self.signals = label, fn, signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            message = self.fn()
        except MachineError as exc:
            self.signals.failed.emit(self.label, classify(exc), str(exc))
        except ValueError as exc:
            self.signals.failed.emit(self.label, "invalid", str(exc))
        except Exception as exc:
            self.signals.failed.emit(self.label, ConnState.ERROR,
                                     "Unerwarteter Fehler: %s" % exc)
        else:
            self.signals.finished.emit(self.label, str(message or "Bestätigt"))


class CommandRunner(QObject):
    """Runs one machine command at a time; E-Stop bypasses the queue."""

    started = Signal(str)                 # label
    finished = Signal(str, str)           # label, message
    failed = Signal(str, str, str)        # label, kind, message
    busy_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._estop_pool = QThreadPool(self)
        self._estop_pool.setMaxThreadCount(2)
        self._signals = _Signals()
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._running = 0

    @property
    def busy(self) -> bool:
        return self._running > 0

    def run(self, label: str, fn: Callable[[], str]) -> bool:
        """Queue a normal command. Returns False if one is still running."""
        if self._running:
            return False
        self._running += 1
        self.busy_changed.emit(True)
        self.started.emit(label)
        self._pool.start(_Task(label, fn, self._signals))
        return True

    def run_urgent(self, label: str, fn: Callable[[], str]) -> None:
        """Emergency stop: dispatched immediately on a separate pool."""
        self.started.emit(label)
        self._estop_pool.start(_Task("!" + label, fn, self._signals))

    def wait(self, ms: int = 5000) -> None:
        self._pool.waitForDone(ms)
        self._estop_pool.waitForDone(ms)

    @Slot(str, str)
    def _on_finished(self, label: str, message: str) -> None:
        self._done(label)
        self.finished.emit(label.lstrip("!"), message)

    @Slot(str, str, str)
    def _on_failed(self, label: str, kind: str, message: str) -> None:
        self._done(label)
        self.failed.emit(label.lstrip("!"), kind, message)

    def _done(self, label: str) -> None:
        if not label.startswith("!") and self._running:
            self._running -= 1
            if not self._running:
                self.busy_changed.emit(False)
