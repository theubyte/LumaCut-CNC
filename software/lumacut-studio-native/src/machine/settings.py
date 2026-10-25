"""Persisted connection settings for the Pi API (QSettings).

The API key is stored in the user's QSettings (Windows: registry under
HKCU\\Software\\LumaCut\\LumaCut Studio). It is never logged. The
environment variable ``LUMACUT_KEY`` overrides the stored key, which is
handy for shared/kiosk PCs where nothing should be persisted.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtCore import QSettings

from .client import DEFAULT_BASE_URL

ORGANIZATION = "LumaCut"
APPLICATION = "LumaCut Studio"
_URL = "machine/base_url"
_KEY = "machine/api_key"
_POLL = "machine/poll_ms"
_AUTO = "machine/auto_connect"


@dataclass
class ConnectionSettings:
    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    poll_ms: int = 1000
    auto_connect: bool = False

    def __repr__(self) -> str:
        return "ConnectionSettings(base_url=%r, api_key=%s, poll_ms=%d)" % (
            self.base_url, "***" if self.api_key else "''", self.poll_ms)


def _store(store: QSettings | None) -> QSettings:
    return store if store is not None else QSettings(ORGANIZATION, APPLICATION)


def load(store: QSettings | None = None) -> ConnectionSettings:
    s = _store(store)
    try:
        poll = int(s.value(_POLL, 1000))
    except (TypeError, ValueError):
        poll = 1000
    auto = s.value(_AUTO, False)
    return ConnectionSettings(
        base_url=str(s.value(_URL, DEFAULT_BASE_URL) or DEFAULT_BASE_URL),
        api_key=os.environ.get("LUMACUT_KEY") or str(s.value(_KEY, "") or ""),
        poll_ms=max(250, min(10000, poll)),
        auto_connect=auto in (True, "true", "1", 1),
    )


def save(settings: ConnectionSettings, store: QSettings | None = None) -> None:
    s = _store(store)
    s.setValue(_URL, settings.base_url)
    # Do not persist a key that only came from the environment.
    if settings.api_key != os.environ.get("LUMACUT_KEY"):
        s.setValue(_KEY, settings.api_key)
    s.setValue(_POLL, int(settings.poll_ms))
    s.setValue(_AUTO, bool(settings.auto_connect))
    s.sync()
