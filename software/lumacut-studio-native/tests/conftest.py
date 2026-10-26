"""Gemeinsame Test-Einrichtung: headless Qt und ``src`` im Importpfad."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Autosave der Tests nie in den echten AppData-Ordner (und keine Wiederherstellungs-Rückfrage)
import tempfile  # noqa: E402
os.environ.setdefault("LUMACUT_AUTOSAVE_DIR", tempfile.mkdtemp(prefix="lumacut-autosave-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _collect_qt_garbage():
    """Nach jedem Test im Hauptthread aufräumen.

    Qt-Objekte aus vorherigen Tests hängen oft in Referenzzyklen. Ohne
    explizites ``gc.collect()`` räumt Pythons zyklischer GC sie irgendwann auf –
    auch mitten in einem Worker-Thread (z. B. StatusPoller) –, und das Löschen
    von QObjects außerhalb des GUI-Threads führt zum Segfault.
    """
    yield
    import gc
    gc.collect()


_EXIT_STATUS = 0


def pytest_sessionfinish(session, exitstatus):
    global _EXIT_STATUS
    _EXIT_STATUS = int(exitstatus)


def pytest_unconfigure(config):
    """Prozess nach dem Testlauf hart beenden (gleicher Exit-Code).

    Die Tests lassen Fenster/Widgets zurück, die PySide6 sonst erst beim
    Interpreter-Ende in undefinierter Reihenfolge nach der QApplication
    zerstört – das stürzte unter Linux sporadisch mit Segfault (Exit 139) ab,
    obwohl alle Tests bestanden hatten. Ergebnis und Zusammenfassung sind zu
    diesem Zeitpunkt bereits ausgegeben.
    """
    if "PySide6.QtWidgets" not in sys.modules or os.environ.get("LUMACUT_TEST_NO_HARD_EXIT"):
        return
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_EXIT_STATUS)
