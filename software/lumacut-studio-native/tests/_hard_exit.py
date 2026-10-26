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


def _kernel32():
    """kernel32 mit korrekten Signaturen (HANDLE ist 64 Bit – ohne restype
    würde ctypes das Pseudo-Handle von GetCurrentProcess auf int kürzen und
    TerminateProcess schlüge fehl)."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetCurrentProcess.argtypes = []
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k.TerminateProcess.restype = wintypes.BOOL
    return k


def hard_exit(status: int, platform: str | None = None) -> None:
    """Beendet den Prozess sofort mit ``status`` (pytests Exit-Code).

    Vorher werden stdout/stderr geleert und ``faulthandler`` abgeschaltet,
    damit ein Fehler im Abbau nicht als Absturz gemeldet wird.
    Unter Windows ``TerminateProcess``; scheitert das, kehrt die Funktion
    zurück und pytest beendet sich normal (``os._exit`` wäre dort genau der
    Absturz). Auf anderen Plattformen ``os._exit``.
    """
    status = int(status)
    platform = sys.platform if platform is None else platform
    _flush()
    try:
        faulthandler.disable()
    except Exception:       # pragma: no cover
        pass
    if platform == "win32":
        try:
            k = _kernel32()
            ok = k.TerminateProcess(k.GetCurrentProcess(), status & 0xFFFFFFFF)
            err = "TerminateProcess lieferte 0" if not ok else "kehrte zurück"
        except Exception as exc:
            err = repr(exc)
        sys.stderr.write("conftest: harter Exit unter Windows nicht möglich (%s), "
                         "normaler pytest-Exit\n" % err)
        _flush()
        return
    os._exit(status)


def _flush() -> None:
    for stream in (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__):
        try:
            if stream is not None:
                stream.flush()
        except Exception:   # pragma: no cover - closed/odd stream
            pass
