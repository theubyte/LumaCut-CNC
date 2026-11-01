"""Password for the web service menu (laser 24 V by hand, manual shot).

Only a salted PBKDF2 hash is stored on the Pi; the owner sets the password
himself on first use in the web interface. A wrong password waits a second
so it cannot be guessed quickly from the LAN.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from pathlib import Path

ITERATIONS = 200_000
MIN_LENGTH = 4


class ServiceAuth:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def _load(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    @staticmethod
    def _hash(password: str, salt: bytes, iterations: int) -> str:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()

    def is_set(self) -> bool:
        return self._load() is not None

    def check(self, password: str):
        stored = self._load()
        if stored is None:
            raise PermissionError("Service-Passwort noch nicht festgelegt")
        digest = self._hash(password or "", bytes.fromhex(stored["salt"]), int(stored["iterations"]))
        if not hmac.compare_digest(digest, stored["hash"]):
            time.sleep(1.0)
            raise PermissionError("Service-Passwort falsch")

    def set(self, new: str, old: str | None = None):
        if not isinstance(new, str) or len(new) < MIN_LENGTH:
            raise ValueError("Service-Passwort: mindestens %d Zeichen" % MIN_LENGTH)
        with self.lock:
            if self.is_set():
                self.check(old or "")
            salt = os.urandom(16)
            data = {"salt": salt.hex(), "iterations": ITERATIONS,
                    "hash": self._hash(new, salt, ITERATIONS)}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
