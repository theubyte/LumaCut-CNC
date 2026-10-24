"""Password-gated high-privilege Pi configuration.

No password or session signing secret is exposed through the web client.
Bootstrap password is the operator-requested 'lumaservice', hashed on the
device on first run and replaceable from the authenticated service UI.
"""
from __future__ import annotations
import json
import os
import secrets
import threading
import time
from pathlib import Path
from werkzeug.security import check_password_hash, generate_password_hash


class ServiceAuth:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "service-auth.json"
        self._lock = threading.RLock()
        self._failures = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({
                "password_hash": generate_password_hash("lumaservice"),
                "session_secret": secrets.token_urlsafe(48),
            }, exclusive=True)
        self._data = json.loads(self.path.read_text(encoding="utf-8"))
        if not self._data.get("password_hash") or not self._data.get("session_secret"):
            raise RuntimeError("Ungültige service-auth.json; Servicebetrieb verweigert")

    def _write(self, data, exclusive=False):
        if exclusive:
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                return
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream)
            return
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
        os.replace(tmp, self.path)

    @property
    def signing_secret(self):
        return self._data["session_secret"]

    def authenticate(self, password: str, client: str) -> bool:
        # Five incorrect guesses within five minutes suspend new attempts.
        with self._lock:
            now = time.monotonic()
            failures = [t for t in self._failures.get(client, []) if now - t < 300]
            if len(failures) >= 5:
                raise PermissionError("Serviceanmeldung vorübergehend gesperrt")
            ok = check_password_hash(self._data["password_hash"], password)
            if ok:
                self._failures.pop(client, None)
            else:
                failures.append(now)
                self._failures[client] = failures
            return ok

    def change_password(self, old: str, new: str, client: str):
        if not self.authenticate(old, client):
            raise PermissionError("Bisheriges Servicepasswort falsch")
        if len(new) < 12 or len(new) > 128:
            raise ValueError("Neues Servicepasswort: 12 bis 128 Zeichen")
        with self._lock:
            updated = dict(self._data)
            updated["password_hash"] = generate_password_hash(new)
            updated["session_secret"] = secrets.token_urlsafe(48)
            self._write(updated)
            self._data = updated
