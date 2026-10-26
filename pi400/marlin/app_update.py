"""Android app updates served by the Pi.

The Android CI publishes every signed build as a GitHub release with two
assets: ``LumaCut-Android.apk`` and ``LumaCut-Android.json``
(``{"version_code", "version_name", "sha256", "size", "commit"}``). The Pi
fetches the newest one (at start, every few hours, on request), checks size
and SHA-256 and keeps exactly one APK on disk. Tablets in the Wi-Fi ask the
Pi (``GET /api/app/android``) and download the APK from it; Android itself
refuses an APK that is not signed with the installed app's key.

Never touches the machine: network and disk only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

LOG = logging.getLogger("lumacut.app_update")

REPO = os.environ.get("LUMACUT_APP_REPO", "theubyte/LumaCut-CNC")
APK_ASSET = "LumaCut-Android.apk"
META_ASSET = "LumaCut-Android.json"
MAX_APK_BYTES = 100 * 1024 * 1024
CHECK_INTERVAL_S = 6 * 3600


class AppUpdates:
    def __init__(self, data_dir: Path, repo: str = REPO, opener=None):
        self.dir = Path(data_dir) / "app"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.repo = repo
        self.apk = self.dir / "android.apk"
        self.meta_file = self.dir / "android.json"
        self.lock = threading.Lock()
        self.checked_at: str | None = None
        self.error: str | None = None
        # Injected in tests; urllib otherwise.
        self._open = opener or (lambda url, timeout: urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "LumaCut-Pi",
                                                 "Accept": "application/vnd.github+json"}), timeout=timeout))

    # ---------- stored version ----------

    def meta(self) -> dict | None:
        try:
            m = json.loads(self.meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not self.apk.is_file() or self.apk.stat().st_size != m.get("size"):
            return None
        return m

    def status(self) -> dict:
        m = self.meta() or {}
        return {"available": bool(m), "version_code": m.get("version_code"),
                "version_name": m.get("version_name"), "sha256": m.get("sha256"),
                "size": m.get("size"), "checked_at": self.checked_at, "error": self.error}

    # ---------- fetching from GitHub ----------

    def _get(self, url: str, timeout: float = 30) -> bytes:
        with self._open(url, timeout) as r:
            return r.read()

    def check(self) -> dict:
        """Downloads a newer APK from the latest release; returns status()."""
        with self.lock:
            try:
                self._check_locked()
                self.error = None
            except Exception as exc:
                self.error = str(exc)[:200]
                LOG.warning("App update check failed: %s", exc)
            self.checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return self.status()

    def _check_locked(self):
        try:
            release = json.loads(self._get("https://api.github.com/repos/%s/releases/latest" % self.repo))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise RuntimeError("Auf GitHub ist noch keine signierte App-Version veröffentlicht") from exc
            raise
        assets = {a.get("name"): a.get("browser_download_url") for a in release.get("assets", [])}
        if APK_ASSET not in assets or META_ASSET not in assets:
            raise RuntimeError("Neuestes Release enthält keine LumaCut-Android-APK")
        new = json.loads(self._get(assets[META_ASSET]))
        code, size, digest = int(new["version_code"]), int(new["size"]), str(new["sha256"]).lower()
        if not 0 < size <= MAX_APK_BYTES or len(digest) != 64:
            raise RuntimeError("Release-Angaben unplausibel")
        current = self.meta()
        if current and int(current.get("version_code", 0)) >= code:
            return                                           # already the newest
        data = self._get(assets[APK_ASSET], timeout=300)
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError("Heruntergeladene APK stimmt nicht mit der Prüfsumme überein")
        tmp = self.apk.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, self.apk)
        meta = {"version_code": code, "version_name": str(new.get("version_name") or code),
                "sha256": digest, "size": size, "commit": new.get("commit")}
        tmp = self.meta_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta), encoding="utf-8")
        os.replace(tmp, self.meta_file)
        LOG.info("Android app %s (%d) bereit", meta["version_name"], code)

    def run_forever(self, running, busy=lambda: False, interval: float = CHECK_INTERVAL_S):
        """Background loop: check soon after start, then every ``interval`` s (not during jobs)."""
        next_at = time.monotonic() + 30
        while running():
            time.sleep(5)
            if time.monotonic() < next_at or busy():
                continue
            self.check()
            next_at = time.monotonic() + interval
