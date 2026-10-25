"""Gemeinsame Test-Einrichtung: headless Qt und ``src`` im Importpfad."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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
