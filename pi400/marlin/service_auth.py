"""Password for the web service menu (laser 24 V by hand, manual shot).

Only a salted PBKDF2 hash is stored on the Pi; the owner sets the password
himself on first use in the web interface. A wrong password waits a second
and slow checks run one at a time, so it cannot be guessed quickly from the
LAN, also not with many requests at once.

The page sends the password with every slider move and every 1.5 s while the
beam is on. A full PBKDF2 for each would load the Pi and delay "laser off", so
a correct password is remembered for VERIFIED_S: not the password itself, only
an HMAC of it under a random key that lives in this process and dies with it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from pathlib import Path

from .storage import atomic_write

ITERATIONS = 200_000
MIN_LENGTH = 4
VERIFIED_S = 60.0


class ServiceAuth:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self._guess_lock = threading.Lock()
        self._key = os.urandom(32)
        self._verified: tuple[bytes, float] | None = None   # (HMAC tag, valid until)

    def _load(self):
        """The stored record, None if no password was ever set.

        A damaged file is NOT "no password": anyone in the LAN could then set a
        new one. The menu stays locked until the owner deletes the file.
        """
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise PermissionError("Service-Passwort-Datei nicht lesbar: %s" % exc) from exc
        try:
            stored = json.loads(raw)
            salt = bytes.fromhex(stored["salt"])
            iterations = int(stored["iterations"])
            digest = stored["hash"]
            if not salt or iterations < 1 or not isinstance(digest, str) or not digest.isascii():
                raise ValueError("unvollständig")
        except (ValueError, KeyError, TypeError) as exc:
            raise PermissionError("Service-Passwort-Datei beschädigt – Menü bleibt gesperrt. "
                                  "Zum Neusetzen auf dem Pi löschen: %s" % self.path) from exc
        return {"salt": salt, "iterations": iterations, "hash": digest}

    @staticmethod
    def _hash(password: str, salt: bytes, iterations: int) -> str:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()

    def is_set(self) -> bool:
        """True also for a damaged file (read with every status: one file check)."""
        return self.path.exists()

    def _tag(self, password: str, stored: dict) -> bytes:
        # The stored hash is part of it: a changed password file ends the shortcut.
        message = stored["salt"] + stored["hash"].encode("ascii") + password.encode("utf-8")
        return hmac.new(self._key, message, hashlib.sha256).digest()

    def check(self, password: str):
        stored = self._load()
        if stored is None:
            raise PermissionError("Service-Passwort noch nicht festgelegt")
        password = password or ""
        tag = self._tag(password, stored)
        verified = self._verified
        if verified and time.monotonic() < verified[1] and hmac.compare_digest(tag, verified[0]):
            return
        with self._guess_lock:
            digest = self._hash(password, stored["salt"], stored["iterations"])
            if not hmac.compare_digest(digest, stored["hash"]):
                time.sleep(1.0)
                raise PermissionError("Service-Passwort falsch")
        self._verified = (tag, time.monotonic() + VERIFIED_S)

    def set(self, new: str, old: str | None = None):
        if not isinstance(new, str) or len(new) < MIN_LENGTH:
            raise ValueError("Service-Passwort: mindestens %d Zeichen" % MIN_LENGTH)
        with self.lock:
            if self.is_set():
                self.check(old or "")
            salt = os.urandom(16)
            data = {"salt": salt.hex(), "iterations": ITERATIONS,
                    "hash": self._hash(new, salt, ITERATIONS)}
            atomic_write(self.path, json.dumps(data), mode=0o600)
            self._verified = None
