"""Driver for the real app window (see app/Automation.h). Only the standard library."""
import json
import os
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXE = Path(os.environ.get("LUMACUT_EXE") or ROOT / "build" / "LumaCutStudio.exe")
QT_BIN = os.environ.get("QT_BIN", r"C:\Qt\6.10.3\msvc2022_64\bin")


class App:
    def __init__(self, exe=None, port=9477, env=None, pi_url=None):
        e = dict(os.environ)
        e["LUMACUT_AUTOMATION_PORT"] = str(port)
        if QT_BIN and exe is None:
            e["PATH"] = QT_BIN + os.pathsep + e["PATH"]
        if pi_url:
            e["LUMACUT_PI_URL"] = pi_url
        e.update(env or {})
        self.proc = subprocess.Popen([str(exe or DEFAULT_EXE)], env=e)
        self.port = port
        self.sock = None
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"App beendet sich beim Start: {self.proc.returncode}")
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=30)
                break
            except OSError:
                time.sleep(0.1)
        if not self.sock:
            raise RuntimeError("Automation-Port nicht erreichbar")
        self.file = self.sock.makefile("rb")

    def call(self, cmd, **kw):
        kw["cmd"] = cmd
        self.sock.sendall((json.dumps(kw) + "\n").encode())
        r = json.loads(self.file.readline())
        if "error" in r:
            raise RuntimeError(f"{cmd} {kw}: {r['error']}")
        return r

    def click(self, name): return self.call("click", name=name)
    def find(self, name): return self.call("find", name=name)
    def get(self, name, prop): return self.call("get", name=name, prop=prop)["value"]
    def invoke(self, name, method, *args): return self.call("invoke", name=name, method=method, args=list(args)).get("value")
    def key(self, key, mods=0, text=""): return self.call("key", key=key, mods=mods, text=text)
    def text(self, text): return self.call("text", text=text)
    def shot(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return self.call("shot", path=str(Path(path).resolve()).replace("\\", "/"))
    def stats(self): return self.call("stats")
    def tree(self): return self.call("tree")["items"]

    def drag(self, x0, y0, x1, y1, steps=8):
        self.call("mouse", x=x0, y=y0, type="move")
        self.call("mouse", x=x0, y=y0, type="press")
        for i in range(1, steps + 1):
            self.call("mouse", x=x0 + (x1 - x0) * i / steps, y=y0 + (y1 - y0) * i / steps, type="move", down=True)
        self.call("mouse", x=x1, y=y1, type="release")

    def wait(self, fn, timeout=10, every=0.1):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                v = fn()
            except RuntimeError as e:      # the element is not there yet (views load asynchronously)
                if "not found" not in str(e):
                    raise
                v = None
            if v:
                return v
            time.sleep(every)
        raise TimeoutError(str(fn))

    def close(self):
        try:
            self.call("quit")
        except Exception:
            pass
        try:
            self.proc.wait(5)
        except Exception:
            self.proc.kill()
