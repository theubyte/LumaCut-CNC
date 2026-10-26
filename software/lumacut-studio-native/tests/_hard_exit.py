"""Harter Prozess-Exit nach dem Testlauf (von ``conftest.py`` genutzt).

Warum überhaupt hart beenden (Commit 93c7cd0): Die Tests lassen Qt-Fenster
und -Widgets zurück, die PySide6 sonst erst beim Interpreter-Ende in
undefinierter Reihenfolge nach der QApplication zerstört; das stürzte unter
Linux sporadisch mit Segfault (Exit 139) ab, obwohl alle Tests bestanden.

Warum nicht überall ``os._exit``: Unter Windows ruft ``os._exit`` über die
CRT ``ExitProcess`` auf. Dabei laufen die DLL_PROCESS_DETACH-Routinen der
Qt-DLLs, und genau dort trat in der CI eine Access-Violation auf, die
pytests aktiver ``faulthandler`` als „Windows fatal exception: access
violation“ meldete und die den Schritt trotz grüner Tests scheitern ließ.
``TerminateProcess`` beendet den Prozess sofort mit dem angegebenen
Exit-Code, ohne DLL-Abbau.
"""
from __future__ import annotations

import faulthandler
import os
import sys


def hard_exit(status: int, platform: str | None = None) -> None:
    """Beendet den Prozess sofort mit ``status`` (pytests Exit-Code).

    Vorher werden stdout/stderr geleert und ``faulthandler`` abgeschaltet,
    damit ein Fehler im Abbau nicht als Absturz gemeldet wird. Unter Windows
    ``TerminateProcess``, sonst (und falls das scheitert) ``os._exit``.
    """
    status = int(status)
    platform = sys.platform if platform is None else platform
    for stream in (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__):
        try:
            if stream is not None:
                stream.flush()
        except Exception:   # pragma: no cover - closed/odd stream
            pass
    try:
        faulthandler.disable()
    except Exception:       # pragma: no cover
        pass
    if platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.TerminateProcess(kernel32.GetCurrentProcess(), status & 0xFFFFFFFF)
        except Exception:   # pragma: no cover - fall back below
            pass
    os._exit(status)
