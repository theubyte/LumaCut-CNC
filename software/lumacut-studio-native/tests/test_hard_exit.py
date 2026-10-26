"""conftest beendet pytest hart – unter Windows per TerminateProcess."""
from __future__ import annotations

import faulthandler
import subprocess
import sys
import types
from pathlib import Path

import pytest

import _hard_exit


class _Exited(BaseException):
    pass


@pytest.fixture
def calls(monkeypatch):
    log = {"os_exit": [], "terminate": [], "faulthandler_enabled": []}

    def fake_os_exit(code):
        log["faulthandler_enabled"].append(faulthandler.is_enabled())
        log["os_exit"].append(code)
        raise _Exited

    class Kernel32:
        def GetCurrentProcess(self):
            return "HANDLE"

        def TerminateProcess(self, handle, code):
            log["faulthandler_enabled"].append(faulthandler.is_enabled())
            log["terminate"].append((handle, code))
            raise _Exited       # the real call never returns

    fake_ctypes = types.SimpleNamespace(windll=types.SimpleNamespace(kernel32=Kernel32()))
    monkeypatch.setattr(_hard_exit.os, "_exit", fake_os_exit)
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)
    was_enabled = faulthandler.is_enabled()
    faulthandler.enable()
    yield log
    if was_enabled:
        faulthandler.enable()
    else:
        faulthandler.disable()


@pytest.mark.parametrize("status", [0, 1, 5])
def test_windows_uses_terminate_process_with_status(calls, status):
    with pytest.raises(_Exited):
        _hard_exit.hard_exit(status, platform="win32")
    assert calls["terminate"] == [("HANDLE", status)]
    assert calls["os_exit"] == []
    assert calls["faulthandler_enabled"] == [False]


def test_windows_falls_back_to_os_exit_if_terminate_fails(calls, monkeypatch):
    def broken():
        raise OSError("kein kernel32")
    sys.modules["ctypes"].windll.kernel32.GetCurrentProcess = broken
    with pytest.raises(_Exited):
        _hard_exit.hard_exit(1, platform="win32")
    assert calls["os_exit"] == [1]


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_other_platforms_use_os_exit(calls, platform):
    with pytest.raises(_Exited):
        _hard_exit.hard_exit(1, platform=platform)
    assert calls["terminate"] == []
    assert calls["os_exit"] == [1]
    assert calls["faulthandler_enabled"] == [False]


def test_enum_exit_status_is_passed_as_int(calls):
    with pytest.raises(_Exited):
        _hard_exit.hard_exit(pytest.ExitCode.TESTS_FAILED, platform="win32")
    assert calls["terminate"] == [("HANDLE", 1)]


def test_real_process_exit_code_and_output_are_kept(tmp_path):
    """Echter Kindprozess: Ausgabe kommt vollständig an, Code bleibt erhalten."""
    here = Path(__file__).resolve().parent
    script = ("import sys; sys.path.insert(0, %r); import faulthandler; "
              "faulthandler.enable(); from _hard_exit import hard_exit; "
              "print('vor dem Exit', end=''); hard_exit(3)" % str(here))
    run = subprocess.run([sys.executable, "-c", script], capture_output=True,
                         text=True, timeout=60)
    assert run.returncode == 3
    assert run.stdout == "vor dem Exit"
    assert "fatal" not in run.stderr.lower()
