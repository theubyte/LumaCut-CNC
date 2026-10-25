"""Non-blocking machine I/O for the GUI.

* :class:`StatusPoller` polls GET /api/status on its own daemon thread.
  Requests never overlap and never run on the GUI thread.
* :class:`CommandRunner` executes actions on daemon threads, one normal
  command at a time. Motion requests on the Pi block until the SKR is done
  (home/probe/park up to minutes), so the emergency stop is always
  dispatched immediately on its own thread and connection and is never
  queued behind a running command.

Plain Python daemon threads are used on purpose: a request blocked for
minutes inside urllib can never hang or crash application exit (a QThread
or QThreadPool would be waited for, or destroyed while running). Results
reach the GUI through Qt signals, which Qt queues into the GUI thread.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

from .client import (STATUS_TIMEOUT_S, AuthFailed, LumaCutClient, MachineError,
                     ProtocolError, StatusTimeout)


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
    """Polls the Pi. Create, then call :meth:`start`; signals are queued.

    State rules:
      * success                      → CONNECTED
      * HTTP 401/403                 → AUTH_FAILED (immediately)
      * wrong/malformed answer       → ERROR (immediately)
      * refused / DNS / reset        → ERROR after ``FAILURE_TOLERANCE``
                                       consecutive failures while connected
      * timeout while connected      → stays CONNECTED (data becomes stale)
        while a command is running, else until ``TIMEOUT_GRACE_S`` without
        a good answer. The Pi's /api/status waits for machine.lock, which
        home/park/probe hold for the whole move.
    Errors back off up to ``MAX_BACKOFF_MS``.
    """

    status_received = Signal(object)          # MachineStatus
    state_changed = Signal(str, str)          # ConnState, message

    FAILURE_TOLERANCE = 2
    TIMEOUT_GRACE_S = 20.0
    MAX_BACKOFF_MS = 5000

    def __init__(self, client: LumaCutClient, interval_ms: int = 1000,
                 status_timeout_s: float = STATUS_TIMEOUT_S):
        super().__init__()
        self._client = client
        self._status_timeout = float(status_timeout_s)
        self._interval = max(250, int(interval_ms))
        self._failures = 0
        self._state = ConnState.DISCONNECTED
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._emit_lock = threading.RLock()
        self._stopped = True
        self._thread: threading.Thread | None = None
        self._command_running = False
        self.last_ok: float | None = None      # time.monotonic() of last success

    @property
    def state(self) -> str:
        return self._state

    def set_command_running(self, running: bool) -> None:
        """Tell the poller that a (possibly lock-holding) command is in flight."""
        self._command_running = bool(running)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stopped = False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="lumacut-status-poller")
        self._thread.start()

    def stop(self, wait_ms: int = 1000) -> None:
        """Stop polling. Never blocks longer than ``wait_ms``; idempotent.

        After stop() returns no further signal is emitted except the final
        DISCONNECTED (emitted here, in the caller's thread).
        """
        thread = self._thread
        if thread is None:
            return
        with self._emit_lock:
            already = self._stopped
            self._stopped = True
        self._stop.set()
        self._wake.set()
        thread.join(max(0, wait_ms) / 1000.0)   # daemon: may outlive this
        self._thread = None
        if not already:
            self._state = ConnState.DISCONNECTED
            self.state_changed.emit(ConnState.DISCONNECTED, "Getrennt")

    def poll_now(self) -> None:
        self._wake.set()

    # ---------------------------------------------------------- thread
    def _emit(self, signal, *args) -> None:
        with self._emit_lock:
            if self._stopped:
                return
            try:
                signal.emit(*args)
            except RuntimeError:     # QObject already deleted on shutdown
                self._stopped = True

    def _set_state(self, state: str, message: str = "") -> None:
        with self._emit_lock:
            if self._stopped:
                return
            self._state = state
        self._emit(self.state_changed, state, message)

    def _loop(self) -> None:
        self._failures = 0
        self._set_state(ConnState.CONNECTING, "Verbinde mit " + self._client.base_url)
        while not self._stop.is_set():
            self._poll_once()
            if self._failures == 0:
                delay = self._interval
            else:
                delay = min(self.MAX_BACKOFF_MS, self._interval * (1 + self._failures))
            self._wake.wait(delay / 1000.0)
            self._wake.clear()

    def _poll_once(self) -> None:
        try:
            status = self._client.status(timeout=self._status_timeout)
        except AuthFailed as exc:
            self._failures += 1
            self._set_state(ConnState.AUTH_FAILED, str(exc))
        except ProtocolError as exc:
            self._failures += 1
            self._set_state(ConnState.ERROR, str(exc))
        except StatusTimeout as exc:
            self._failures += 1
            age = (time.monotonic() - self.last_ok) if self.last_ok else None
            tolerated = (self._state == ConnState.CONNECTED and age is not None and
                         (self._command_running or age < self.TIMEOUT_GRACE_S))
            if not tolerated:
                self._set_state(ConnState.ERROR, str(exc))
        except MachineError as exc:
            self._failures += 1
            if (self._state != ConnState.CONNECTED or
                    self._failures >= self.FAILURE_TOLERANCE):
                self._set_state(ConnState.ERROR, str(exc))
        except Exception as exc:  # defensive: never kill the poll thread
            self._failures += 1
            self._set_state(ConnState.ERROR, "Unerwarteter Fehler: %s" % exc)
        else:
            self._failures = 0
            self.last_ok = time.monotonic()
            if self._state != ConnState.CONNECTED:
                self._set_state(ConnState.CONNECTED,
                                "Verbunden mit " + self._client.base_url)
            self._emit(self.status_received, status)


class _Signals(QObject):
    finished = Signal(str, str)        # label, message
    failed = Signal(str, str, str)     # label, ConnState-ish kind, message


class CommandRunner(QObject):
    """Runs one machine command at a time; the E-Stop bypasses the queue."""

    started = Signal(str)                 # label
    finished = Signal(str, str)           # label, message
    failed = Signal(str, str, str)        # label, kind, message
    busy_changed = Signal(bool)

    #: parallel E-Stop requests (repeated presses); M112 twice is harmless
    MAX_URGENT = 3

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._signals = _Signals()
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._running = 0
        self._label = ""
        self._threads: list[threading.Thread] = []
        self._urgent = threading.BoundedSemaphore(self.MAX_URGENT)

    @property
    def busy(self) -> bool:
        return self._running > 0

    @property
    def current(self) -> str:
        """Label of the running normal command ("" if idle)."""
        return self._label if self._running else ""

    def run(self, label: str, fn: Callable[[], str]) -> bool:
        """Start a normal command. Returns False if one is still running."""
        if self._running:
            return False
        self._running += 1
        self._label = label
        self.busy_changed.emit(True)
        self.started.emit(label)
        self._spawn(label, fn)
        return True

    def run_urgent(self, label: str, fn: Callable[[], str]) -> bool:
        """Emergency stop: dispatched immediately, independent of run()."""
        if not self._urgent.acquire(blocking=False):
            return False        # already MAX_URGENT E-Stops in flight
        self.started.emit(label)

        def guarded() -> str:
            try:
                return fn()
            finally:
                self._urgent.release()
        self._spawn("!" + label, guarded)
        return True

    def wait(self, ms: int = 5000) -> None:
        """Wait up to ``ms`` in total for running threads (never longer)."""
        deadline = time.monotonic() + ms / 1000.0
        for thread in list(self._threads):
            thread.join(max(0.0, deadline - time.monotonic()))

    def _spawn(self, label: str, fn: Callable[[], str]) -> None:
        self._threads = [t for t in self._threads if t.is_alive()]
        thread = threading.Thread(target=self._execute, args=(label, fn),
                                  daemon=True, name="lumacut-cmd " + label)
        self._threads.append(thread)
        thread.start()

    def _execute(self, label: str, fn: Callable[[], str]) -> None:
        try:
            message = fn()
        except MachineError as exc:
            self._send(self._signals.failed, label, classify(exc), str(exc))
        except ValueError as exc:
            self._send(self._signals.failed, label, "invalid", str(exc))
        except Exception as exc:
            self._send(self._signals.failed, label, ConnState.ERROR,
                       "Unerwarteter Fehler: %s" % exc)
        else:
            self._send(self._signals.finished, label, str(message or "Bestätigt"))

    @staticmethod
    def _send(signal, *args) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:    # receiver deleted during application exit
            pass

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
                self._label = ""
                self.busy_changed.emit(False)
