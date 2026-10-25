"""Load the Pi's MarlinLaserGuard to check generated G-code (skip if absent)."""
import importlib.util
from pathlib import Path

import pytest

_TRANSPORT = Path(__file__).resolve().parents[3] / "pi400" / "marlin" / "transport.py"


def pi_check(gcode: str) -> list[str]:
    if not _TRANSPORT.exists():
        pytest.skip("pi400 transport not in checkout")
    spec = importlib.util.spec_from_file_location("_lc_pi_transport", _TRANSPORT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    guard = mod.MarlinLaserGuard()
    return [guard.check(line, True) for line in gcode.splitlines()]
