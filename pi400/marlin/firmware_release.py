"""Firmware updates from GitHub, flashed by the Pi on the owner's button press.

A release of the own firmware (docs/FIRMWARE_EIGEN.md) is a GitHub release
``lumacut-fw-<run>`` (never marked "latest": that one is the Android app) with
``LumaCut-Firmware.json`` and the image::

    {"number": 12, "commit": "...",
     "boards": {"skr":  {"asset": "LumaCut-Firmware-SKR.bin",  "build": "Oct 31 2026 16:54:31",
                         "sha256": "...", "size": 123}}}

Old ``marlin-<run>`` releases and a Marlin release.json still on the Pi's disk
are ignored, and validate_image() refuses a Marlin image anyway.

The Pi fetches the newest one (at start, every few hours, on request), checks
size, SHA-256 and the image itself (validate_image) and keeps the image on disk. ``offer()`` compares the build stamp with the
one the connected board reports in M115; flashing stays a button press in the
web UI (owner present). Never touches the machine: network and disk only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from .app_update import CHECK_INTERVAL_S, REPO

LOG = logging.getLogger("lumacut.firmware_release")

META_ASSET = "LumaCut-Firmware.json"
TAG_PREFIX = "lumacut-fw-"
MAX_IMAGE_BYTES = 2 * 1024 * 1024
BOARDS = {"skr": "skr.bin"}
BOARD_NAMES = {"skr": "SKR Mini MZ"}
# M115 MACHINE_TYPE of our own build; Marlin builds ("LumaCut CNC Marlin"), the
# Grbl bridge ("LumaCut CNC Atomstack-Grbl") and foreign firmwares get no offer.
MACHINE_TYPES = {"LumaCut CNC": "skr"}
_MACHINE_RE = re.compile(r"MACHINE_TYPE:(LumaCut CNC)(?=\s*$)")
_BUILD_RE = re.compile(r"\(((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [ \d]\d \d{4} \d\d:\d\d:\d\d)\)")


def board_of(identity: str) -> str | None:
    m = _MACHINE_RE.search(identity or "")
    return MACHINE_TYPES.get(m.group(1)) if m else None


def running_build(identity: str) -> str | None:
    m = _BUILD_RE.search(identity or "")
    return m.group(1) if m else None


def _when(build: str | None) -> datetime | None:
    try:
        return datetime.strptime(" ".join((build or "").split()), "%b %d %Y %H:%M:%S")
    except ValueError:
        return None


def validate(board: str, data: bytes) -> dict:
    """The same checks as a manual upload; raises FirmwareImageError."""
    from .firmware_flash import validate_image
    return validate_image(data)


class FirmwareReleases:
    def __init__(self, data_dir: Path, repo: str = REPO, opener=None):
        self.dir = Path(data_dir) / "firmware"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.repo = repo
        self.meta_file = self.dir / "release.json"
        self.lock = threading.Lock()
        self.checked_at: str | None = None
        self.error: str | None = None
        self._open = opener or (lambda url, timeout: urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "LumaCut-Pi",
                                                 "Accept": "application/vnd.github+json"}), timeout=timeout))

    # ---------- stored release ----------

    def meta(self) -> dict | None:
        try:
            meta = json.loads(self.meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        # A release.json from the Marlin releases has no tag: not ours any more.
        return meta if str(meta.get("tag", "")).startswith(TAG_PREFIX) else None

    def image(self, board: str) -> bytes | None:
        """Stored image for ``board``, only if it still matches the release."""
        entry = ((self.meta() or {}).get("boards") or {}).get(board)
        path = self.dir / BOARDS[board]
        try:
            data = path.read_bytes()
        except OSError:
            return None
        if not entry or len(data) != entry.get("size") or hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            return None
        return data

    def offer(self, identity: str) -> dict:
        """What the web UI shows for the connected board."""
        m = self.meta() or {}
        board = board_of(identity)
        running = running_build(identity)
        entry = (m.get("boards") or {}).get(board) if board else None
        # Polled with every status: size only here, the hash at install time.
        path = self.dir / BOARDS[board] if board else None
        stored = bool(entry and path.is_file() and path.stat().st_size == entry.get("size"))
        newer = bool(stored and _when(entry.get("build")) and
                     (_when(running) is None or _when(entry["build"]) > _when(running)))
        return {"number": m.get("number"), "commit": m.get("commit"),
                "board": board, "board_name": BOARD_NAMES.get(board),
                "running_build": running, "release_build": entry.get("build") if entry else None,
                "update_available": newer, "checked_at": self.checked_at, "error": self.error}

    # ---------- fetching from GitHub ----------

    def _get(self, url: str, timeout: float = 30) -> bytes:
        with self._open(url, timeout) as r:
            return r.read()

    def check(self) -> dict:
        """Downloads the newest firmware release; returns meta() or {}."""
        with self.lock:
            try:
                self._check_locked()
                self.error = None
            except Exception as exc:
                self.error = str(exc)[:200]
                LOG.warning("Firmware update check failed: %s", exc)
            self.checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return self.meta() or {}

    def _check_locked(self):
        releases = json.loads(self._get("https://api.github.com/repos/%s/releases?per_page=30" % self.repo))
        release = next((r for r in releases if str(r.get("tag_name", "")).startswith(TAG_PREFIX)
                        and not r.get("draft") and not r.get("prerelease")), None)
        if release is None:
            raise RuntimeError("Auf GitHub ist noch keine Firmware veröffentlicht")
        assets = {a.get("name"): a.get("browser_download_url") for a in release.get("assets", [])}
        if META_ASSET not in assets:
            raise RuntimeError("Firmware-Release ohne %s" % META_ASSET)
        new = json.loads(self._get(assets[META_ASSET]))
        number = int(new["number"])
        current = self.meta()
        if current and int(current.get("number", 0)) >= number and \
                all(self.image(b) is not None for b in current.get("boards", {}) if b in BOARDS):
            return                                           # already the newest
        boards = {}
        for board, entry in (new.get("boards") or {}).items():
            if board not in BOARDS:
                continue
            size, digest = int(entry["size"]), str(entry["sha256"]).lower()
            if not 0 < size <= MAX_IMAGE_BYTES or len(digest) != 64 or entry.get("asset") not in assets:
                raise RuntimeError("Firmware-Release-Angaben unplausibel (%s)" % board)
            data = self._get(assets[entry["asset"]], timeout=120)
            if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                raise RuntimeError("Firmware %s stimmt nicht mit der Prüfsumme überein" % board)
            info = validate(board, data)
            if info.get("build") != entry.get("build"):
                raise RuntimeError("Firmware %s: Build-Stempel passt nicht zum Release" % board)
            tmp = self.dir / (BOARDS[board] + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, self.dir / BOARDS[board])
            boards[board] = {"build": entry["build"], "sha256": digest, "size": size}
        if not boards:
            raise RuntimeError("Firmware-Release enthält kein Board-Image")
        meta = {"tag": release["tag_name"], "number": number, "commit": new.get("commit"), "boards": boards}
        tmp = self.meta_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta), encoding="utf-8")
        os.replace(tmp, self.meta_file)
        LOG.info("Firmware-Release %d bereit (%s)", number, ", ".join(sorted(boards)))

    def run_forever(self, running, busy=lambda: False, interval: float = CHECK_INTERVAL_S):
        """Background loop: check soon after start, then every ``interval`` s (not during jobs)."""
        next_at = time.monotonic() + 45
        while running():
            time.sleep(5)
            if time.monotonic() < next_at or busy():
                continue
            self.check()
            next_at = time.monotonic() + interval
