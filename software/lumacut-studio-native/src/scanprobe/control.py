"""Pause / Fortsetzen / Abbrechen und Fortschrittsmeldungen.

Thread-sicher: die UI ruft ``pause()``, ``resume()``, ``cancel()`` aus dem
GUI-Thread, der Worker ruft ``checkpoint()`` zwischen zwei Maschinenschritten.
Ein Abbruch passiert dadurch nie mitten in einer Bewegung oder einem G30.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Callable, Optional


class Cancelled(Exception):
    """Der Nutzer hat abgebrochen."""


@dataclass
class Progress:
    phase: str               # "scan", "stitch", "detect", "probe", "verify"
    done: int
    total: int
    message: str = ""
    eta_s: Optional[float] = None
    extra: dict = field(default_factory=dict)

    @property
    def fraction(self) -> float:
        return 1.0 if self.total <= 0 else min(1.0, self.done / self.total)


ProgressCallback = Callable[[Progress], None]


class RunControl:
    def __init__(self, on_progress: Optional[ProgressCallback] = None):
        self._run = threading.Event()
        self._run.set()
        self._cancel = threading.Event()
        self.on_progress = on_progress

    # --- UI-Seite -----------------------------------------------------
    def pause(self) -> None:
        self._run.clear()

    def resume(self) -> None:
        self._run.set()

    def cancel(self) -> None:
        self._cancel.set()
        self._run.set()  # wartenden Worker aufwecken

    @property
    def paused(self) -> bool:
        return not self._run.is_set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # --- Worker-Seite -------------------------------------------------
    def checkpoint(self, poll_s: float = 0.05) -> None:
        """Blockiert während Pause, wirft ``Cancelled`` bei Abbruch."""
        while not self._run.wait(poll_s):
            pass
        if self._cancel.is_set():
            raise Cancelled()

    def report(self, progress: Progress) -> None:
        if self.on_progress is not None:
            self.on_progress(progress)


class EtaEstimator:
    """Mischt geplante Zeit mit gemessener Zeit pro Schritt."""

    def __init__(self, total: int, planned_s_per_step: float):
        self.total = total
        self.planned = planned_s_per_step
        self.start = time.monotonic()
        self.paused_s = 0.0

    def eta(self, done: int) -> float:
        remaining = max(0, self.total - done)
        if done <= 0:
            return remaining * self.planned
        measured = (time.monotonic() - self.start) / done
        w = min(1.0, done / 5)  # nach 5 Schritten zählt nur die Messung
        return remaining * (w * measured + (1 - w) * self.planned)
